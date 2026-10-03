"""
workforce_intelligence/snapshot_bridge.py
────────────────────────────────────────
Thread-safe analytical bridge connecting AnalyticalSnapshot to the
Workforce Intelligence KPI calculation engine.

Provides the decoupled, UI-independent analytical service interface:
- Retrieves active snapshot and canonical foundation without reloading data.
- Bounded LRU cache (default 128 items) for on-demand filtered requests.
- Automatic cache invalidation when the active dataset is replaced.
- Supports background execution without UI or disk blocking.
- Provides benchmarking tools for initial computation vs. cached retrieval.
"""

from collections import OrderedDict
from dataclasses import asdict
from datetime import date, datetime
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from storage.cache_manager import (
    AnalyticalSnapshot,
    CacheManager,
    snapshot_cache,
    _defensive_copy_dict,
)
from storage.snapshot_service import (
    TimeSeriesSnapshotService,
    snapshot_service as default_snapshot_service,
)
from workforce_intelligence.kpi_engine import (
    EmployeeMonthWFH,
    EmployeePunchDeviation,
    RepeatExceptionDossier,
    _empty_bundle,
    compute_punch_deviations_bu,
    compute_repeated_exceptions,
    compute_wfh_allowance_monthly,
    compute_workforce_intelligence_bundle,
    ensure_clean_dataframe,
    get_effective_bu,
)
from workforce_intelligence.patterns import (
    detect_patterns,
    PatternResult,
    PatternSummary,
)
from workforce_intelligence.policy import evaluate_policy
from workforce_intelligence.trends import (
    TREND_METRICS,
    TrendMetricDefinition,
    calculate_time_series_trends,
    format_metric_value,
    get_materiality_threshold,
    POLICY_EFFECTIVE_DATE_STR,
)
import time_series_analysis as tsa


def _norm_str(val: Optional[str]) -> Optional[str]:
    """Normalize filter strings to None if empty or 'All'."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("all", "all business units", "all departments", "all managers", "all reporting managers", "all employees", "none", "nan"):
        return None
    return s.lower()


def _norm_emp(val: Optional[str]) -> Optional[str]:
    """Normalize employee filter string to stable employee ID prefix if format is 'EMP001 — Name'."""
    s = _norm_str(val)
    if s is None:
        return None
    if " — " in s:
        return s.split(" — ")[0].strip()
def _filter_workforce_df(
    df: pd.DataFrame,
    business_unit: Optional[str] = None,
    department: Optional[str] = None,
    manager: Optional[str] = None,
    employee: Optional[str] = None,
    date_range: Optional[Tuple[date, date]] = None,
) -> pd.DataFrame:
    filtered = df.copy()
    if filtered.empty:
        return filtered

    # 1. Business Unit
    if business_unit and str(business_unit).strip() not in ("All", "All Business Units", "", "None", "nan"):
        bu_clean = str(business_unit).strip().lower()
        if bu_clean in ("unknown", "unknown / unassigned", "unassigned"):
            filtered = filtered[
                filtered["_eff_bu"].astype(str).str.strip().str.lower().isin(("unknown / unassigned", "unknown", "unassigned", "", "nan", "none"))
            ]
        else:
            filtered = filtered[
                (filtered["_eff_bu"].astype(str).str.strip().str.lower() == bu_clean) |
                (filtered["_bu"].astype(str).str.strip().str.lower() == bu_clean)
            ]

    # 2. Department
    if department and str(department).strip() not in ("All", "All Departments", "", "None", "nan"):
        dept_clean = str(department).strip().lower()
        if dept_clean in ("unknown", "unknown / unassigned", "unassigned"):
            filtered = filtered[
                filtered["_dept"].isna() |
                filtered["_dept"].astype(str).str.strip().str.lower().isin(("unknown / unassigned", "unknown", "unassigned", "", "nan", "none"))
            ]
        else:
            filtered = filtered[filtered["_dept"].astype(str).str.strip().str.lower() == dept_clean]

    # 3. Manager
    if manager and str(manager).strip() not in ("All", "All Managers", "All Reporting Managers", "", "None", "nan"):
        mgr_clean = str(manager).strip().lower()
        if mgr_clean in ("unknown", "unknown / unassigned", "unassigned"):
            filtered = filtered[
                filtered["_rm"].isna() |
                filtered["_rm"].astype(str).str.strip().str.lower().isin(("unknown / unassigned", "unknown", "unassigned", "", "nan", "none"))
            ]
        else:
            filtered = filtered[filtered["_rm"].astype(str).str.strip().str.lower() == mgr_clean]

    # 4. Employee
    if employee and str(employee).strip() not in ("All", "All Employees", "", "None", "nan"):
        emp_raw = str(employee).strip()
        if " — " in emp_raw:
            emp_id_key = emp_raw.split(" — ")[0].strip().lower()
        elif " - " in emp_raw:
            emp_id_key = emp_raw.split(" - ")[0].strip().lower()
        else:
            emp_id_key = emp_raw.lower()

        filtered = filtered[
            (filtered["_emp_num"].astype(str).str.strip().str.lower() == emp_id_key) |
            (filtered["_emp_name"].astype(str).str.strip().str.lower() == emp_raw.lower())
        ]

    # 5. Date Range
    if date_range and len(date_range) == 2:
        raw_start, raw_end = date_range
        if raw_start is not None and raw_end is not None:
            start_d = raw_start.date() if isinstance(raw_start, datetime) else raw_start
            end_d = raw_end.date() if isinstance(raw_end, datetime) else raw_end
            if isinstance(start_d, date) and isinstance(end_d, date):
                if start_d > end_d:
                    return filtered.iloc[0:0].copy()
                if "_date" in filtered.columns:
                    def _in_range(d_val):
                        if d_val is None or pd.isna(d_val):
                            return False
                        if isinstance(d_val, datetime):
                            d_val = d_val.date()
                        elif isinstance(d_val, str) and d_val not in ("", "nan", "None"):
                            try:
                                d_val = tsa.parse_date_value(d_val)
                            except Exception:
                                return False
                        if isinstance(d_val, date):
                            return start_d <= d_val <= end_d
                        return False
                    filtered = filtered[filtered["_date"].apply(_in_range)]

    return filtered


def _empty_trend_bundle(metric_id: str = "attendance_exception_rate", benchmark_type: str = "ORGANIZATION") -> Dict[str, Any]:
    metric_def = TREND_METRICS.get(metric_id, TREND_METRICS["attendance_exception_rate"])
    return {
        "metric_id": metric_id,
        "metric_def": metric_def.to_dict(),
        "benchmark_type": benchmark_type,
        "benchmark_label": "Organisation",
        "date_range_display": "No dataset loaded",
        "policy_effective_date": POLICY_EFFECTIVE_DATE_STR,
        "time_series": [],
        "org_time_series": [],
        "benchmark_time_series": [],
        "historical_baseline_value": None,
        "historical_baseline_formatted": "—",
        "current_period": None,
        "current_period_display": None,
        "trend_pulse": [
            {"title": "Current Value", "value": "—", "sub": "Selected Metric Value", "note": "Awaiting dataset ingestion", "color": None},
            {"title": "MoM Change", "value": "—", "sub": "vs last month", "note": "Month-over-month trajectory", "color": None},
            {"title": "3-Month Trend", "value": "—", "sub": "Trajectory", "note": "Trailing directional pattern", "color": None},
            {"title": "Benchmark Gap", "value": "—", "sub": f"vs {benchmark_type.lower()}", "note": "Performance vs target baseline", "color": None},
            {"title": "Data Confidence", "value": "—", "sub": "Awaiting Data", "note": "0 observations recorded", "color": None},
        ],
        "pulse": {
            "current_value": None,
            "current_value_formatted": "—",
            "previous_value": None,
            "previous_value_formatted": "—",
            "mom_change": None,
            "mom_change_formatted": "—",
            "mom_change_pp": None,
            "trend_direction": "INSUFFICIENT_DATA",
            "streak_direction": None,
            "streak_months": 0,
            "gap_vs_benchmark": None,
            "gap_vs_benchmark_formatted": "—",
            "benchmark_label": "Organisation",
            "volume_status": "LOW",
            "confidence_label": "Awaiting Data",
            "valid_observations": 0,
        },
        "chart": {
            "points": [],
            "metric_id": metric_id,
            "metric_name": metric_def.label,
            "format": metric_def.format,
            "direction": metric_def.direction,
            "reference_range": None,
        },
        "heatmap": {
            "months": [],
            "rows": [],
            "lower_is_better": metric_def.direction == "lower_is_better",
        },
        "bu_heatmap": {
            "months": [],
            "rows": [],
            "lower_is_better": metric_def.direction == "lower_is_better",
        },
        "what_changed": {
            "has_change": False,
            "has_movement": False,
            "title": "What Changed?",
            "headline": "No dataset loaded. Ingest data to evaluate workforce trends.",
            "summary": "No dataset loaded. Ingest data to evaluate workforce trends.",
            "total_change_str": "—",
            "direction": "neutral",
            "drivers": [],
        },
        "patterns": [],
        "benchmark_table": {
            "columns": [
                ("bu", "Business Unit", 160, "w"),
                ("curr", "Current", 80, "w"),
                ("avg3m", "3M Average", 80, "w"),
                ("org", "Organisation", 80, "w"),
                ("hist", "Historical", 80, "w"),
                ("gap", "Gap", 75, "w"),
                ("trend", "Trend", 95, "w"),
                ("volume", "Volume", 90, "w"),
            ],
            "rows": [],
            "total": {},
            "total_row": {},
        },
        "scope_description": "Awaiting Dataset Ingestion",
        "observations": ["No workforce dataset loaded. Ingest a performance file to analyze trends."],
    }


class WorkforceIntelligenceBridge:
    """
    Decoupled analytical service interface for Transformers 2.0 Workforce Intelligence.
    Interacts with TimeSeriesSnapshotService and AnalyticalSnapshot.
    Maintains a thread-safe, bounded LRU cache for workforce KPI requests.
    """

    def __init__(
        self,
        snapshot_service: Optional[TimeSeriesSnapshotService] = None,
        max_cache_size: int = 256,
    ):
        self._service = snapshot_service or default_snapshot_service
        self._max_cache_size = max_cache_size
        self._cache: OrderedDict[Tuple[Any, ...], Dict[str, Any]] = OrderedDict()
        self._last_dataset_id: Optional[str] = None
        self._lock = threading.RLock()

    def _sync_dataset_state(self, snap: Optional[AnalyticalSnapshot]) -> None:
        """Invalidate cached results if the active dataset has changed or been purged."""
        current_id = snap.dataset_id if snap and snap.is_valid() else None
        if current_id != self._last_dataset_id:
            with self._lock:
                self._cache.clear()
                self._last_dataset_id = current_id

    def get_workforce_metrics(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        exception_threshold: int = 3,
        wfh_allowance: float = 3.0,
        late_departure_threshold_mins: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Retrieve comprehensive Workforce Intelligence KPI bundle.
        Uses cached results if available for identical filter parameters.
        Otherwise computes from the active snapshot's shared fact DataFrame.
        """
        snap = self._service.get_active_snapshot()
        if not snap or not snap.is_valid():
            return _empty_bundle(exception_threshold, wfh_allowance)

        self._sync_dataset_state(snap)

        bu_key = _norm_str(business_unit)
        dept_key = _norm_str(department)
        mgr_key = _norm_str(manager)
        emp_key = _norm_emp(employee)
        dr_key = (date_range[0], date_range[1]) if date_range and len(date_range) == 2 else None

        cache_key = (
            bu_key,
            dept_key,
            mgr_key,
            emp_key,
            dr_key,
            int(exception_threshold),
            float(wfh_allowance),
            float(late_departure_threshold_mins),
        )

        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return _defensive_copy_dict(self._cache[cache_key])

        # Compute new bundle using the shared DataFrame (read-only contract)
        foundation = getattr(snap, "workforce_foundation", None)
        bundle = compute_workforce_intelligence_bundle(
            df=snap.fact_df,
            canonical_data=foundation,
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            exception_threshold=exception_threshold,
            wfh_allowance=wfh_allowance,
            late_departure_threshold_mins=late_departure_threshold_mins,
        )

        with self._lock:
            self._cache[cache_key] = bundle
            if len(self._cache) > self._max_cache_size:
                self._cache.popitem(last=False)

        return _defensive_copy_dict(bundle)

    def get_wfh_allowance_audit(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        wfh_allowance: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Retrieve WFH allowance audit records and summary.
        Reuses cached workforce bundle if available.
        """
        bundle = self.get_workforce_metrics(
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            wfh_allowance=wfh_allowance,
        )
        return {
            "summary": bundle.get("wfh_monthly_summary", {}),
            "breakdown": bundle.get("wfh_employee_month_breakdown", []),
            "partially_observed_months": bundle.get("wfh_partially_observed_months", []),
            "total_additional_wfh_days": bundle.get("wfh_total_additional_days", 0.0),
            "employees_exceeding_allowance": bundle.get("wfh_employees_exceeding_allowance", 0),
        }

    def get_punch_deviations(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        deviation_threshold_mins: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Retrieve Business Unit benchmark deviations for employees.
        """
        bundle = self.get_workforce_metrics(
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            late_departure_threshold_mins=deviation_threshold_mins,
        )
        return {
            "bu_benchmarks": bundle.get("bu_benchmarks", {}),
            "deviations": bundle.get("employee_punch_deviations", []),
            "late_arrival_count": bundle.get("late_arrival_employees_count", 0),
            "early_departure_count": bundle.get("early_departure_employees_count", 0),
        }

    def get_repeated_exceptions(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        threshold: int = 3,
    ) -> Dict[str, Any]:
        """
        Retrieve repeated attendance exception dossiers.
        """
        bundle = self.get_workforce_metrics(
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            exception_threshold=threshold,
        )
        return {
            "threshold": bundle.get("repeated_exception_threshold", threshold),
            "affected_employees_count": bundle.get("repeated_exception_employees_count", 0),
            "affected_rate_pct": bundle.get("repeated_exception_rate_pct", 0.0),
            "dossiers": bundle.get("repeated_exception_dossiers", []),
        }

    def get_trend_intelligence(
        self,
        metric_id: str = "attendance_exception_rate",
        benchmark_type: str = "ORGANIZATION",
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        analysis_as_of_date: Optional[Union[date, datetime]] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve complete deterministic Workforce Trend Intelligence bundle:
        - Time series trajectories for the active filter scope.
        - Organisation, Historical, and Peer Benchmarks.
        - 5 Trend Pulse cards.
        - Business Unit Heatmap matrix.
        - What Changed? Driver decomposition.
        - Top 3-5 Emerging Patterns from patterns.py.
        - Benchmark comparison table.
        """
        snap = self._service.get_active_snapshot()
        if not snap or not snap.is_valid():
            return _empty_trend_bundle(metric_id, benchmark_type)

        self._sync_dataset_state(snap)

        if metric_id not in TREND_METRICS:
            metric_id = "attendance_exception_rate"
        metric_def = TREND_METRICS[metric_id]

        bench_mode = str(benchmark_type or "ORGANIZATION").strip().upper()
        if "HIST" in bench_mode:
            bench_mode = "HISTORICAL"
            bench_label = "Historical Baseline"
        elif "PEER" in bench_mode:
            bench_mode = "PEER"
            bench_label = "Peer Business Unit"
        else:
            bench_mode = "ORGANIZATION"
            bench_label = "Organisation"

        bu_key = _norm_str(business_unit)
        dept_key = _norm_str(department)
        mgr_key = _norm_str(manager)
        emp_key = _norm_emp(employee)
        dr_key = (date_range[0], date_range[1]) if date_range and len(date_range) == 2 else None

        cache_key = (
            "TREND_INTEL_V2",
            metric_id,
            bench_mode,
            bu_key,
            dept_key,
            mgr_key,
            emp_key,
            dr_key,
        )

        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return _defensive_copy_dict(self._cache[cache_key])

        raw_df = snap.fact_df
        if raw_df is None or len(raw_df) == 0:
            return _empty_trend_bundle(metric_id, bench_mode)

        org_df = ensure_clean_dataframe(raw_df)
        org_eval_df, org_eval_reqs = evaluate_policy(org_df)

        # 1. Scoped Dataset
        scoped_df = _filter_workforce_df(
            org_df,
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
        )
        if scoped_df.empty:
            scoped_eval_df, scoped_eval_reqs = org_eval_df.iloc[0:0].copy(), []
        else:
            scoped_eval_df, scoped_eval_reqs = evaluate_policy(scoped_df)

        # 2. Main Scoped Trend & Org Trend
        scope_trend = calculate_time_series_trends(
            scoped_eval_df,
            scoped_eval_reqs,
            metric_id=metric_id,
            analysis_as_of_date=analysis_as_of_date,
        )
        org_trend = calculate_time_series_trends(
            org_eval_df,
            org_eval_reqs,
            metric_id=metric_id,
            analysis_as_of_date=analysis_as_of_date,
        )

        org_series = org_trend.get("time_series", [])
        scope_series = scope_trend.get("time_series", [])

        # 3. All Distinct Business Units across Dataset
        if "_eff_bu" in org_df.columns:
            bu_col = org_df["_eff_bu"]
        else:
            bu_col = org_df["_bu"]
        raw_bus = [str(b).strip() for b in bu_col.dropna().unique() if str(b).strip() not in ("", "nan", "None")]
        all_bus = sorted(list(set(raw_bus)))

        # 4. Precompute BU-level time series for heatmap and peer benchmarks
        bu_trends: Dict[str, Dict[str, Any]] = {}
        for bu_name in all_bus:
            bu_df = _filter_workforce_df(org_df, business_unit=bu_name)
            if not bu_df.empty:
                bu_eval_df, bu_eval_reqs = evaluate_policy(bu_df)
                bu_trends[bu_name] = calculate_time_series_trends(
                    bu_eval_df,
                    bu_eval_reqs,
                    metric_id=metric_id,
                    analysis_as_of_date=analysis_as_of_date,
                )
            else:
                bu_trends[bu_name] = {"time_series": []}

        # 5. Peer Benchmark & Historical Baseline Series
        periods = [p["period"] for p in org_series]
        peer_points: List[Dict[str, Any]] = []
        hist_points: List[Dict[str, Any]] = []

        # Scope values mapped by period
        scope_pt_map = {p["period"]: p for p in scope_series}
        org_pt_map = {p["period"]: p for p in org_series}

        # Calculate Peer Benchmark per period (median of peer BUs)
        for p_idx, period_str in enumerate(periods):
            p_display = org_pt_map[period_str]["period_display"]
            peer_vals = []
            for bu_name, bu_tr in bu_trends.items():
                bu_pts = {pt["period"]: pt for pt in bu_tr.get("time_series", [])}
                if period_str in bu_pts:
                    pt_val = bu_pts[period_str].get("value")
                    ev_cnt = bu_pts[period_str].get("evaluable", 0) or bu_pts[period_str].get("valid_observation_count", 0)
                    if pt_val is not None and ev_cnt is not None and ev_cnt >= 5:
                        peer_vals.append(pt_val)
                    elif pt_val is not None:
                        peer_vals.append(pt_val)

            peer_val = round(float(np.median(peer_vals)), 2) if peer_vals else org_pt_map[period_str].get("value")
            peer_points.append({
                "period": period_str,
                "period_display": p_display,
                "value": peer_val,
                "formatted_value": format_metric_value(peer_val, metric_def.format),
            })

            # Historical baseline for scope (trailing 3-month median of preceding months)
            prior_vals = []
            for prev_idx in range(max(0, p_idx - 3), p_idx):
                prev_period = periods[prev_idx]
                if prev_period in scope_pt_map and scope_pt_map[prev_period].get("value") is not None:
                    prior_vals.append(scope_pt_map[prev_period]["value"])
            if prior_vals:
                hist_val = round(float(np.median(prior_vals)), 2)
            else:
                hist_val = scope_pt_map.get(period_str, {}).get("value")
            
            hist_points.append({
                "period": period_str,
                "period_display": p_display,
                "value": hist_val,
                "formatted_value": format_metric_value(hist_val, metric_def.format),
            })

        # Historical baseline overall (median of all previous months in scope)
        all_prior_scope_vals = [p["value"] for p in scope_series[:-1] if p.get("value") is not None]
        if all_prior_scope_vals:
            hist_baseline_val = round(float(np.median(all_prior_scope_vals)), 2)
        elif scope_series and scope_series[-1].get("value") is not None:
            hist_baseline_val = scope_series[-1]["value"]
        else:
            hist_baseline_val = None
        hist_baseline_fmt = format_metric_value(hist_baseline_val, metric_def.format) if hist_baseline_val is not None else "—"

        # 6. Active Benchmark Series & Current Value
        if bench_mode == "ORGANIZATION":
            benchmark_series = org_series
            current_bench_val = org_trend.get("current_value")
            current_bench_fmt = org_trend.get("current_value_formatted", "—")
        elif bench_mode == "HISTORICAL":
            benchmark_series = hist_points
            current_bench_val = hist_baseline_val
            current_bench_fmt = hist_baseline_fmt
        else:  # "PEER"
            benchmark_series = peer_points
            current_bench_val = peer_points[-1]["value"] if peer_points else None
            current_bench_fmt = peer_points[-1]["formatted_value"] if peer_points else "—"

        # 7. Gap vs Benchmark Calculation
        curr_val = scope_trend.get("current_value")
        if curr_val is not None and current_bench_val is not None:
            gap_val = round(curr_val - current_bench_val, 2)
            sign_str = "+" if gap_val > 0 else ""
            if metric_def.format == "percentage":
                gap_fmt = f"{sign_str}{gap_val:.1f} pp"
            elif metric_def.format == "days":
                gap_fmt = f"{sign_str}{gap_val:.1f} d"
            elif metric_def.format in ("duration", "time"):
                gap_fmt = f"{sign_str}{gap_val:.0f}m"
            else:
                gap_fmt = f"{sign_str}{gap_val:.1f}"
        else:
            gap_val = None
            gap_fmt = "—"

        # 8. MoM Change Formatted
        mom_change = scope_trend.get("mom_change")
        if mom_change is not None:
            sign_str = "+" if mom_change > 0 else ""
            if metric_def.format == "percentage":
                mom_change_fmt = f"{sign_str}{mom_change:.1f} pp"
            elif metric_def.format == "days":
                mom_change_fmt = f"{sign_str}{mom_change:.1f} d"
            elif metric_def.format in ("duration", "time"):
                mom_change_fmt = f"{sign_str}{mom_change:.0f}m"
            else:
                mom_change_fmt = f"{sign_str}{mom_change:.1f}"
        else:
            mom_change_fmt = "Baseline (First Month)"

        valid_obs = 0
        if scope_series:
            latest_scope_pt = scope_series[-1]
            valid_obs = latest_scope_pt.get("evaluable", 0) or latest_scope_pt.get("valid_observation_count", 0) or latest_scope_pt.get("total_applicable", 0) or 0
        vol_status = scope_trend.get("volume_status") or ("HIGH" if valid_obs >= 50 else ("MODERATE" if valid_obs >= 10 else "LOW"))
        conf_label = f"{vol_status.capitalize()} confidence · {valid_obs:,} observations" if valid_obs > 0 else "Low confidence · 0 observations"

        # 9. Chart Combined Points
        chart_points = []
        bench_pt_map = {p["period"]: p for p in benchmark_series}
        hist_pt_map = {p["period"]: p for p in hist_points}

        all_chart_vals = []
        for period_str in periods:
            sc_p = scope_pt_map.get(period_str, {})
            bn_p = bench_pt_map.get(period_str, {})
            hs_p = hist_pt_map.get(period_str, {})

            v_act = sc_p.get("value")
            v_bn = bn_p.get("value")
            v_hs = hs_p.get("value")

            if v_act is not None:
                all_chart_vals.append(v_act)
            if v_bn is not None:
                all_chart_vals.append(v_bn)

            p_dt = pd.to_datetime(period_str, errors="coerce")
            pol_dt = pd.to_datetime(POLICY_EFFECTIVE_DATE_STR, errors="coerce")
            is_post_pol = bool(pd.notna(p_dt) and pd.notna(pol_dt) and p_dt.date() >= pol_dt.date())
            is_low_vol = bool(sc_p.get("volume_status") == "LOW")

            chart_points.append({
                "period": period_str,
                "period_display": org_pt_map[period_str]["period_display"],
                "actual": v_act,
                "actual_formatted": sc_p.get("formatted_value") or "—",
                "benchmark": v_bn,
                "benchmark_formatted": bn_p.get("formatted_value") or "—",
                "historical": v_hs,
                "historical_formatted": hs_p.get("formatted_value") or "—",
                "is_low_volume": is_low_vol,
                "is_regression": False,
                "is_post_policy": is_post_pol,
                "evaluable": sc_p.get("evaluable") or sc_p.get("valid_observation_count") or 0,
            })

        # Mark regression on chart if detected
        if scope_trend.get("regression_detected") and len(chart_points) >= 1:
            chart_points[-1]["is_regression"] = True

        # Reference Range
        if all_chart_vals:
            ref_min = max(0.0, float(np.percentile(all_chart_vals, 10)))
            ref_max = float(np.percentile(all_chart_vals, 90))
            ref_range = (round(ref_min, 1), round(ref_max, 1))
        else:
            ref_range = None

        # 10. Business Unit Trend Heatmap & Benchmark Table Rows
        heatmap_months = [org_pt_map[p]["period_display"] for p in periods]
        heatmap_rows = []
        table_rows = []

        org_curr_val = org_trend.get("current_value")
        org_curr_fmt = org_trend.get("current_value_formatted", "—")
        org_valid_pts = [p["value"] for p in org_series if p.get("value") is not None]
        org_3m_avg_val = round(float(np.mean(org_valid_pts[-3:])), 2) if org_valid_pts else org_curr_val
        org_3m_avg_fmt = format_metric_value(org_3m_avg_val, metric_def.format) if org_3m_avg_val is not None else "—"

        for bu_name in all_bus:
            b_tr = bu_trends.get(bu_name, {})
            b_series = b_tr.get("time_series", [])
            b_pt_map = {p["period"]: p for p in b_series}

            b_curr_val = b_tr.get("current_value")
            b_curr_fmt = b_tr.get("current_value_formatted", "—")
            b_valid_pts = [p["value"] for p in b_series if p.get("value") is not None]
            b_3m_avg = round(float(np.mean(b_valid_pts[-3:])), 2) if b_valid_pts else b_curr_val
            b_3m_avg_fmt = format_metric_value(b_3m_avg, metric_def.format) if b_3m_avg is not None else "—"

            b_hist_pts = b_valid_pts[:-1] if len(b_valid_pts) >= 2 else b_valid_pts
            b_hist_val = round(float(np.median(b_hist_pts)), 2) if b_hist_pts else None
            b_hist_fmt = format_metric_value(b_hist_val, metric_def.format) if b_hist_val is not None else "—"

            if b_curr_val is not None and org_curr_val is not None:
                b_gap_val = round(b_curr_val - org_curr_val, 2)
                sign_str = "+" if b_gap_val > 0 else ""
                unit_str = " pp" if metric_def.format == "percentage" else (" d" if metric_def.format == "days" else "")
                b_gap_fmt = f"{sign_str}{b_gap_val:.1f}{unit_str}"
            else:
                b_gap_val = None
                b_gap_fmt = "—"

            b_vol_count = 0
            if b_series:
                b_vol_count = b_series[-1].get("evaluable", 0) or b_series[-1].get("valid_observation_count", 0) or 0
            b_vol_st = b_tr.get("volume_status") or ("High" if b_vol_count >= 50 else ("Moderate" if b_vol_count >= 10 else "Low"))

            b_trend_dir = b_tr.get("trend_direction", "INSUFFICIENT_DATA")

            # Monthly deltas for heatmap
            m_vals = []
            m_deltas = []
            for period_str in periods:
                b_p = b_pt_map.get(period_str, {})
                o_p = org_pt_map.get(period_str, {})
                bv = b_p.get("value")
                ov = o_p.get("value")
                m_vals.append({
                    "period": period_str,
                    "value": bv,
                    "formatted_value": b_p.get("formatted_value") or "—",
                })
                if bv is not None and ov is not None:
                    d_val = round(bv - ov, 2)
                    sign_s = "+" if d_val > 0 else ""
                    u_s = " pp" if metric_def.format == "percentage" else ""
                    d_fmt = f"{sign_s}{d_val:.1f}{u_s}"
                else:
                    d_val = None
                    d_fmt = "—"
                m_deltas.append({
                    "period": period_str,
                    "delta": d_val,
                    "formatted_delta": d_fmt,
                    "bu_value": bv,
                    "org_value": ov,
                })

            heatmap_rows.append({
                "business_unit": bu_name,
                "current_value": b_curr_val,
                "current_formatted": b_curr_fmt,
                "trend_direction": b_trend_dir,
                "monthly_values": m_vals,
                "monthly_deltas": m_deltas,
            })

            table_rows.append({
                "business_unit": bu_name,
                "current": b_curr_fmt,
                "current_val": b_curr_val,
                "three_month_avg": b_3m_avg_fmt,
                "org_benchmark": org_curr_fmt,
                "historical": b_hist_fmt,
                "gap": b_gap_fmt,
                "gap_val": b_gap_val,
                "trend": b_trend_dir.replace("_", " ").title(),
                "volume": f"{b_vol_count:,} ({b_vol_st.capitalize()})",
                "evaluable": b_vol_count,
            })

        # Organization-Wide Total Row for Table
        org_vol_cnt = 0
        if org_series:
            org_vol_cnt = org_series[-1].get("evaluable", 0) or org_series[-1].get("valid_observation_count", 0) or 0
        org_vol_st = org_trend.get("volume_status") or ("High" if org_vol_cnt >= 50 else "Moderate")

        org_total_row = {
            "business_unit": "Total (Organisation-Wide)",
            "current": org_curr_fmt,
            "current_val": org_curr_val,
            "three_month_avg": org_3m_avg_fmt,
            "org_benchmark": org_curr_fmt,
            "historical": hist_baseline_fmt,
            "gap": "—",
            "gap_val": 0.0,
            "trend": org_trend.get("trend_direction", "STABLE").replace("_", " ").title(),
            "volume": f"{org_vol_cnt:,} ({org_vol_st.capitalize()})",
            "evaluable": org_vol_cnt,
        }

        # 11. What Changed? (Deterministic Driver Attribution)
        if len(scope_series) >= 2 and scope_series[-1].get("value") is not None and scope_series[-2].get("value") is not None:
            latest_p = scope_series[-1]
            prev_p = scope_series[-2]
            tot_delta = round(latest_p["value"] - prev_p["value"], 2)
            dir_w = "increased" if tot_delta > 0 else ("decreased" if tot_delta < 0 else "remained stable")
            u_txt = " percentage points" if metric_def.format == "percentage" else (" days" if metric_def.format == "days" else " units")
            sign_s = "+" if tot_delta > 0 else ""
            what_summary = f"{metric_def.label} {dir_w} by {abs(tot_delta):.1f}{u_txt} in {latest_p['period_display']} (from {prev_p['formatted_value']} to {latest_p['formatted_value']})."
            tot_chg_str = f"{sign_s}{tot_delta:.1f} {'pp' if metric_def.format == 'percentage' else ''}"

            # Calculate BU contributors
            drivers = []
            bu_deltas = []
            tot_eval_curr = latest_p.get("evaluable") or latest_p.get("valid_observation_count") or 1

            for bu_name in all_bus:
                b_tr = bu_trends.get(bu_name, {})
                b_pts = {pt["period"]: pt for pt in b_tr.get("time_series", [])}
                if latest_p["period"] in b_pts and prev_p["period"] in b_pts:
                    bv_curr = b_pts[latest_p["period"]].get("value")
                    bv_prev = b_pts[prev_p["period"]].get("value")
                    bu_ev = b_pts[latest_p["period"]].get("evaluable") or b_pts[latest_p["period"]].get("valid_observation_count") or 0
                    if bv_curr is not None and bv_prev is not None:
                        d_bu = round(bv_curr - bv_prev, 2)
                        weight = bu_ev / max(1, tot_eval_curr)
                        contrib = round(d_bu * weight, 2)
                        bu_deltas.append((bu_name, d_bu, contrib))

            bu_deltas.sort(key=lambda x: abs(x[2]), reverse=True)

            top_bus = bu_deltas[:3]
            for bu_name, d_bu, contrib in top_bus:
                if abs(d_bu) >= 0.05:
                    sign_b = "+" if d_bu > 0 else ""
                    is_adv = bool((d_bu > 0 and metric_def.direction == "lower_is_better") or (d_bu < 0 and metric_def.direction == "higher_is_better"))
                    fmt_d = f"{sign_b}{d_bu:.1f} {'pp' if metric_def.format == 'percentage' else ''}"
                    drivers.append({
                        "driver": bu_name,
                        "name": bu_name,
                        "delta": d_bu,
                        "delta_str": fmt_d,
                        "formatted_delta": fmt_d,
                        "contribution_str": f"{sign_b}{contrib:.1f} pp contribution" if metric_def.format == "percentage" else "",
                        "is_adverse": is_adv,
                        "type": "BU",
                    })

            if len(bu_deltas) > 3:
                other_contrib = sum(x[2] for x in bu_deltas[3:])
                if abs(other_contrib) >= 0.05:
                    sign_o = "+" if other_contrib > 0 else ""
                    fmt_o = f"{sign_o}{other_contrib:.1f} {'pp' if metric_def.format == 'percentage' else ''}"
                    drivers.append({
                        "driver": "Other Business Units",
                        "name": "Other Business Units",
                        "delta": other_contrib,
                        "delta_str": fmt_o,
                        "formatted_delta": fmt_o,
                        "contribution_str": f"{sign_o}{other_contrib:.1f} pp net",
                        "is_adverse": bool(other_contrib > 0 if metric_def.direction == "lower_is_better" else other_contrib < 0),
                        "type": "BU",
                    })

            what_changed_data = {
                "has_change": True,
                "has_movement": True,
                "title": "What Changed?",
                "headline": what_summary,
                "summary": what_summary,
                "metric_name": metric_def.label,
                "total_change_str": tot_chg_str,
                "direction": dir_w,
                "drivers": drivers,
            }
        else:
            single_lbl = scope_series[0]["period_display"] if scope_series else "Current period"
            single_val = scope_series[0]["formatted_value"] if scope_series else "—"
            what_changed_data = {
                "has_change": False,
                "has_movement": False,
                "title": "What Changed?",
                "headline": f"Baseline established for {single_lbl} ({single_val}). Additional monthly history will reveal movement drivers.",
                "summary": f"Baseline established for {single_lbl} ({single_val}). Additional monthly history will reveal movement drivers.",
                "metric_name": metric_def.label,
                "total_change_str": "Baseline",
                "direction": "neutral",
                "drivers": [],
            }

        # 12. Emerging Patterns (Top 3-5)
        try:
            _, pattern_results = detect_patterns(scoped_eval_df, scoped_eval_reqs)
        except Exception:
            pattern_results = []

        pattern_items = []
        for p in pattern_results[:5]:
            p_title = getattr(p, "pattern_title", getattr(p, "pattern_name", getattr(p, "pattern_type", "Governance Pattern")))
            p_desc = getattr(p, "description", getattr(p, "why_detected", "Recurring behavioral or process pattern observed."))
            p_why = getattr(p, "why_detected", p_desc)
            p_scope = getattr(p, "entity_name", getattr(p, "entity_id", "Organisation"))
            e_type = getattr(p, "entity_type", "EMPLOYEE")
            if hasattr(e_type, "replace"):
                scope_str = f"{e_type.replace('_', ' ').title()}: {p_scope}"
            else:
                scope_str = f"Scope: {p_scope}"
            pers = str(getattr(p, "persistence", "Single Period")).replace("_", " ").title()
            ev_cnt = getattr(p, "event_count", len(getattr(p, "evidence_items", [])))
            d_mo = getattr(p, "distinct_months", 1)

            pattern_items.append({
                "id": getattr(p, "pattern_id", "pat_item"),
                "name": p_title,
                "pattern_name": p_title,
                "pattern_title": p_title,
                "category": getattr(p, "pattern_category", "Attendance"),
                "badge": getattr(p, "severity", "ATTENTION"),
                "severity": getattr(p, "severity", "ATTENTION"),
                "strength": getattr(p, "strength", "MEDIUM"),
                "explanation": p_desc,
                "scope": scope_str,
                "persistence": pers,
                "volume": f"{ev_cnt} events ({d_mo} mo)",
                "why_detected": p_why,
                "score": getattr(p, "pattern_score", 50.0),
            })

        trend_pulse = [
            {
                "title": "Current Value",
                "value": scope_trend.get("current_value_formatted", "—"),
                "sub": metric_def.label,
                "note": f"Latest period: {scope_trend.get('current_period_display', 'Current')}",
                "color": None,
            },
            {
                "title": "MoM Change",
                "value": mom_change_fmt,
                "sub": "vs last month" if mom_change is not None else "Baseline",
                "note": f"Previous: {scope_trend.get('previous_value_formatted', '—')}",
                "color": "#F43F5E" if (mom_change and mom_change > 0 and metric_def.direction == "lower_is_better") else ("#10B981" if mom_change and mom_change < 0 and metric_def.direction == "lower_is_better" else None),
            },
            {
                "title": "3-Month Trend",
                "value": scope_trend.get("trend_direction", "INSUFFICIENT_DATA").replace("_", " ").title(),
                "sub": f"{scope_trend.get('streak_months', 0)}-mo {scope_trend.get('streak_direction', '').lower()} streak" if scope_trend.get('streak_months') else "Trajectory",
                "note": "Based on 3-month trailing movement",
                "color": "#10B981" if "impr" in str(scope_trend.get("trend_direction", "")).lower() else ("#F43F5E" if "detr" in str(scope_trend.get("trend_direction", "")).lower() or "regress" in str(scope_trend.get("trend_direction", "")).lower() else None),
            },
            {
                "title": "Benchmark Gap",
                "value": gap_fmt,
                "sub": f"vs {bench_label} ({current_bench_fmt})",
                "note": f"Benchmark: {bench_label}",
                "color": "#F43F5E" if (gap_val and gap_val > 0 and metric_def.direction == "lower_is_better") else ("#10B981" if gap_val and gap_val < 0 and metric_def.direction == "lower_is_better" else None),
            },
            {
                "title": "Data Confidence",
                "value": f"{vol_status.capitalize()} Confidence",
                "sub": f"{valid_obs:,} observations",
                "note": f"Evaluated across {len(periods)} months",
                "color": "#10B981" if vol_status == "HIGH" else ("#F59E0B" if vol_status == "MODERATE" else None),
            },
        ]

        # Scope description
        parts = []
        if business_unit:
            parts.append(f"BU: {business_unit}")
        if department:
            parts.append(f"Dept: {department}")
        if manager:
            parts.append(f"Mgr: {manager}")
        if employee:
            parts.append(f"Emp: {employee}")
        if date_range:
            parts.append(f"{date_range[0]} to {date_range[1]}")
        scope_description = " • ".join(parts) if parts else "Complete Active Population"

        bundle = {
            "metric_id": metric_id,
            "metric_name": metric_def.label,
            "metric_def": metric_def.to_dict(),
            "benchmark_type": bench_mode,
            "benchmark_label": bench_label,
            "scope_description": scope_description,
            "date_range_display": scope_trend.get("date_range_display", "No data"),
            "policy_effective_date": POLICY_EFFECTIVE_DATE_STR,
            "time_series": scope_series,
            "org_time_series": org_series,
            "benchmark_time_series": benchmark_series,
            "historical_baseline_value": hist_baseline_val,
            "historical_baseline_formatted": hist_baseline_fmt,
            "current_period": scope_trend.get("current_period"),
            "current_period_display": scope_trend.get("current_period_display"),
            "trend_pulse": trend_pulse,
            "pulse": {
                "current_value": curr_val,
                "current_value_formatted": scope_trend.get("current_value_formatted", "—"),
                "previous_value": scope_trend.get("previous_value"),
                "previous_value_formatted": scope_trend.get("previous_value_formatted", "—"),
                "mom_change": mom_change,
                "mom_change_formatted": mom_change_fmt,
                "mom_change_pp": scope_trend.get("mom_change_pp"),
                "trend_direction": scope_trend.get("trend_direction", "INSUFFICIENT_DATA"),
                "streak_direction": scope_trend.get("streak_direction"),
                "streak_months": scope_trend.get("streak_months", 0),
                "gap_vs_benchmark": gap_val,
                "gap_vs_benchmark_formatted": gap_fmt,
                "benchmark_label": bench_label,
                "volume_status": vol_status,
                "confidence_label": conf_label,
                "valid_observations": valid_obs,
            },
            "chart": {
                "points": chart_points,
                "metric_id": metric_id,
                "metric_name": metric_def.label,
                "unit": metric_def.unit if hasattr(metric_def, "unit") else "%",
                "format": metric_def.format,
                "direction": metric_def.direction,
                "lower_is_better": metric_def.direction == "lower_is_better",
                "reference_range": ref_range,
                "policy_effective_date": POLICY_EFFECTIVE_DATE_STR,
            },
            "heatmap": {
                "months": heatmap_months,
                "rows": heatmap_rows,
                "lower_is_better": metric_def.direction == "lower_is_better",
            },
            "bu_heatmap": {
                "months": heatmap_months,
                "rows": heatmap_rows,
                "lower_is_better": metric_def.direction == "lower_is_better",
            },
            "what_changed": what_changed_data,
            "patterns": pattern_items,
            "benchmark_table": {
                "columns": [
                    ("bu", "Business Unit", 160, "w"),
                    ("curr", "Current", 80, "w"),
                    ("avg3m", "3M Average", 80, "w"),
                    ("org", "Organisation", 80, "w"),
                    ("hist", "Historical", 80, "w"),
                    ("gap", "Gap", 75, "w"),
                    ("trend", "Trend", 95, "w"),
                    ("volume", "Volume", 90, "w"),
                ],
                "rows": table_rows,
                "total": org_total_row,
                "total_row": org_total_row,
            },
            "observations": scope_trend.get("observations", []),
        }

        with self._lock:
            self._cache[cache_key] = bundle
            if len(self._cache) > self._max_cache_size:
                self._cache.popitem(last=False)

        return _defensive_copy_dict(bundle)

    def get_filter_cache_stats(self) -> Dict[str, Any]:
        """Return counts and metadata for the internal LRU cache."""
        snap = self._service.get_active_snapshot()
        self._sync_dataset_state(snap)
        with self._lock:
            return {
                "cached_bundles": len(self._cache),
                "max_cache_size": self._max_cache_size,
                "active_dataset_id": self._last_dataset_id,
            }

    def clear_cache(self) -> None:
        """Purge all cached analytical bundles."""
        with self._lock:
            self._cache.clear()

    def benchmark_performance(
        self,
        iterations: int = 5,
    ) -> Dict[str, float]:
        """
        Benchmark initial preparation vs. cached retrieval time.
        Returns average timings in milliseconds.
        """
        snap = self._service.get_active_snapshot()
        if not snap or not snap.is_valid():
            return {"initial_ms": 0.0, "cached_ms": 0.0}

        self.clear_cache()

        # 1. Measure initial calculation time
        t0 = time.perf_counter()
        _ = self.get_workforce_metrics()
        initial_ms = (time.perf_counter() - t0) * 1000.0

        # 2. Measure cached retrieval time over N iterations
        cached_times = []
        for _ in range(iterations):
            t_start = time.perf_counter()
            _ = self.get_workforce_metrics()
            cached_times.append((time.perf_counter() - t_start) * 1000.0)

        avg_cached_ms = sum(cached_times) / len(cached_times) if cached_times else 0.0

        return {
            "initial_ms": round(initial_ms, 2),
            "cached_ms": round(avg_cached_ms, 4),
        }


# Global singleton bridge instance
workforce_bridge = WorkforceIntelligenceBridge()
