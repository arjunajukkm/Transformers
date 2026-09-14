"""
analysis_service.py
───────────────────
In-memory analytical session manager and dashboard data preparation service.
Connects the FastAPI backend to the workforce_intelligence analytical engine.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd

from workforce_intelligence import (
    DataQualityReport,
    build_employee_day_facts,
    calculate_core_metrics,
    calculate_time_series_trends,
    evaluate_policy,
    get_trend_metric_catalogue,
    load_workforce_data,
)
from workforce_intelligence.policy_config import POLICY_EFFECTIVE_DATE, POLICY_EFFECTIVE_DATE_STR


def _serialize_value(val: Any) -> Any:
    """Recursively convert numpy types, timestamps, and NaN to JSON serializable objects."""
    if val is None:
        return None
    if isinstance(val, (list, tuple, set)):
        return [_serialize_value(item) for item in val]
    if isinstance(val, (np.ndarray, pd.Series)):
        return [_serialize_value(x) for x in val.tolist()]
    if isinstance(val, dict):
        return {str(k): _serialize_value(v) for k, v in val.items()}
    if isinstance(val, (pd.Timestamp, datetime, date)):
        return val.isoformat()
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.floating, float)):
        return None if np.isnan(val) else float(val)
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    return val


def format_display_period(d_min: Optional[date], d_max: Optional[date]) -> str:
    """Return clean human-readable date display according to Stage 3.1 specification."""
    if not d_min or not d_max:
        return "No active date range"
    if d_min == d_max:
        return d_min.strftime("%d %B %Y")
    if d_min.year == d_max.year:
        if d_min.month == d_max.month:
            # Check if it covers full month
            import calendar
            _, last_day = calendar.monthrange(d_min.year, d_min.month)
            if d_min.day == 1 and d_max.day == last_day:
                return d_min.strftime("%B %Y")
            return f"{d_min.day}–{d_max.day} {d_min.strftime('%B %Y')}"
        return f"{d_min.strftime('%B')}–{d_max.strftime('%B %Y')}"
    return f"{d_min.strftime('%B %Y')}–{d_max.strftime('%B %Y')}"


class AnalysisSession:
    """Holds active analysis state in application memory."""

    def __init__(self):
        self.filename: Optional[str] = None
        self.cleaned_df: Optional[pd.DataFrame] = None
        self.evaluated_df: Optional[pd.DataFrame] = None
        self.leave_requests: Optional[List[Dict[str, Any]]] = None
        self.employee_day_facts: Optional[pd.DataFrame] = None
        self.quality_report: Optional[DataQualityReport] = None
        self.upload_timestamp: Optional[datetime] = None

    @property
    def is_loaded(self) -> bool:
        return self.evaluated_df is not None and not self.evaluated_df.empty

    def load_dataset(
        self,
        file_path: Union[str, Path, Sequence[Union[str, Path]]],
        filename: str,
        file_names: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest, evaluate, and store workforce dataset (single or multi-file)."""
        cleaned_df, report = load_workforce_data(file_path, file_names=file_names)
        eval_df, eval_reqs = evaluate_policy(cleaned_df)
        facts = build_employee_day_facts(eval_df)

        self.filename = filename
        self.cleaned_df = cleaned_df
        self.evaluated_df = eval_df
        self.leave_requests = eval_reqs
        self.employee_day_facts = facts
        self.quality_report = report
        self.upload_timestamp = datetime.now()

        return self.get_summary()

    def get_available_filters(self) -> Dict[str, List[str]]:
        """Return unique filter values for active dataset."""
        if not self.is_loaded or self.evaluated_df is None:
            return {
                "business_unit": [],
                "department": [],
                "sub_department": [],
                "location": [],
                "reporting_manager": [],
            }

        df = self.evaluated_df

        def _get_unique(col: str) -> List[str]:
            if col in df.columns:
                vals = df[col].dropna().astype(str).str.strip().unique().tolist()
                return sorted([v for v in vals if v and v.lower() != "nan"])
            return []

        return {
            "business_unit": _get_unique("Business Unit"),
            "department": _get_unique("Department"),
            "sub_department": _get_unique("Sub Department"),
            "location": _get_unique("Location"),
            "reporting_manager": _get_unique("Reporting Manager"),
        }

    def get_summary(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate structured dashboard payload, optionally filtered."""
        if not self.is_loaded or self.evaluated_df is None or self.quality_report is None:
            return {
                "loaded": False,
                "message": "No workforce dataset loaded",
            }

        df = self.evaluated_df.copy()
        facts = self.employee_day_facts.copy() if self.employee_day_facts is not None else pd.DataFrame()
        reqs = list(self.leave_requests) if self.leave_requests is not None else []

        # Apply dimension filters if provided
        active_filters = {}
        if filters:
            for k, col in [
                ("business_unit", "Business Unit"),
                ("department", "Department"),
                ("sub_department", "Sub Department"),
                ("location", "Location"),
                ("reporting_manager", "Reporting Manager"),
            ]:
                val = filters.get(k)
                if val:
                    val_str = str(val).strip()
                    if col in df.columns:
                        df = df[df[col].astype(str).str.strip() == val_str]
                    if not facts.empty and col in facts.columns:
                        facts = facts[facts[col].astype(str).str.strip() == val_str]
                    active_filters[k] = val_str

            # Filter leave requests by matching employee numbers
            active_emps = set(df["Employee Number"].dropna())
            reqs = [r for r in reqs if r.get("employee_number") in active_emps]

        # Recalculate metrics on filtered data
        metrics = calculate_core_metrics(
            evaluated_df=df,
            evaluated_requests=reqs,
            employee_day_facts=facts,
        )

        # Standardize approval turnaround aliases
        if "approval_turnaround" in metrics:
            appr = metrics["approval_turnaround"]
            if "average_pending_approval_age_days" in appr:
                appr["avg_pending_age_days"] = appr["average_pending_approval_age_days"]
            if "average_approval_turnaround_days" in appr:
                appr["mean_approval_turnaround_days"] = appr["average_approval_turnaround_days"]

        # 1. Dataset metadata
        unique_emps = int(df["Employee Number"].nunique()) if "Employee Number" in df.columns else 0
        d_min: Optional[date] = None
        d_max: Optional[date] = None
        date_min_str: Optional[str] = None
        date_max_str: Optional[str] = None
        if "Date" in df.columns and not df["Date"].dropna().empty:
            d_min = df["Date"].dropna().min().date()
            d_max = df["Date"].dropna().max().date()
            date_min_str = d_min.strftime("%Y-%m-%d")
            date_max_str = d_max.strftime("%Y-%m-%d")

        display_period = format_display_period(d_min, d_max)

        # Period classification: PRE_POLICY if entire data is before 2026-10-01
        is_all_pre = True
        if d_max is not None:
            if d_max >= POLICY_EFFECTIVE_DATE:
                is_all_pre = False

        policy_period = "PRE_POLICY" if is_all_pre else "POST_POLICY"

        # 2. Quality summary
        qr = self.quality_report
        crit_count = sum(1 for f in qr.quality_findings if f.get("severity") == "CRITICAL")
        warn_count = sum(1 for f in qr.quality_findings if f.get("severity") == "WARNING")
        info_count = sum(1 for f in qr.quality_findings if f.get("severity") == "INFO")

        att_metric = metrics["attendance_exception_rate"]
        excluded_days = att_metric["data_quality_excluded_employee_days"]

        normalized_findings = []
        for f in qr.quality_findings:
            f_copy = dict(f)
            if "category" not in f_copy and "code" in f_copy:
                f_copy["category"] = f_copy["code"]
            if "code" not in f_copy and "category" in f_copy:
                f_copy["code"] = f_copy["category"]
            normalized_findings.append(f_copy)

        quality_payload = {
            "core_completeness": qr.core_data_completeness_percentage,
            "full_completeness": qr.full_data_completeness_percentage,
            "exact_duplicate_rows": qr.exact_duplicate_rows,
            "cross_file_exact_duplicate_rows": qr.cross_file_exact_duplicate_rows,
            "duplicate_rows_excluded_from_analysis": qr.duplicate_rows_excluded_from_analysis,
            "critical_findings": crit_count,
            "warning_findings": warn_count,
            "info_findings": info_count,
            "excluded_employee_days": excluded_days,
            "findings": normalized_findings,
            "missing_optional_columns": qr.missing_expected_optional_columns,
            "source_files": qr.source_files,
        }

        # 3. Monthly Trend points
        trend_points: List[Dict[str, Any]] = []
        if "Date" in df.columns and not df["Date"].dropna().empty:
            df["_month_label"] = df["Date"].dt.strftime("%b %Y")
            for m_label, grp in df.groupby("_month_label", sort=False):
                grp_facts = facts[facts["Date"].isin(grp["Date"])] if not facts.empty else pd.DataFrame()
                grp_metrics = calculate_core_metrics(grp, employee_day_facts=grp_facts)
                trend_points.append({
                    "month": m_label,
                    "attendance_exception_rate": grp_metrics["attendance_exception_rate"]["rate"],
                    "leave_compliance_rate": (
                        grp_metrics["overall_leave_application_compliance"]["rate"]
                        if policy_period == "POST_POLICY"
                        else grp_metrics["pre_policy_leave_benchmark"]["rate"]
                    ),
                    "wfh_compliance_rate": (
                        grp_metrics["wfh_application_compliance"]["rate"]
                        if policy_period == "POST_POLICY"
                        else grp_metrics["pre_policy_wfh_benchmark"]["rate"]
                    ),
                    "approval_turnaround_days": grp_metrics["approval_turnaround"]["median_approval_turnaround_days"],
                })

        # 4. Deterministic Executive Key Observations
        observations: List[Dict[str, str]] = []
        gov_exc_days = att_metric["attendance_exception_days"]
        eval_days = att_metric["evaluable_employee_days"]
        att_rate = att_metric["rate"]

        if eval_days > 0 and att_rate is not None:
            observations.append({
                "type": "attendance",
                "text": f"{gov_exc_days} of {eval_days} evaluable attendance days ({att_rate:.1f}%) contain an attendance exception.",
            })

        if excluded_days > 0:
            observations.append({
                "type": "data_quality",
                "text": f"{excluded_days} employee-day was excluded from leadership attendance KPIs due to critical source-data quantity errors.",
            })

        # Month name for observation
        month_label = d_min.strftime("%B") if d_min else "Period"

        # Leave & WFH Benchmark / Compliance observation
        if policy_period == "PRE_POLICY":
            lv_bench = metrics["pre_policy_leave_benchmark"]["rate"]
            lv_eval_count = metrics["pre_policy_leave_benchmark"]["denominator"]
            lv_str = f"{lv_bench:.1f}%" if lv_bench is not None else "N/A"
            req_text = f"across {lv_eval_count} evaluable request" if lv_eval_count == 1 else f"across {lv_eval_count} evaluable requests"
            observations.append({
                "type": "policy",
                "text": f"{month_label} leave application compliance was {lv_str} {req_text}. The revised policy becomes effective from 1 October 2026.",
            })
        else:
            lv_comp = metrics["overall_leave_application_compliance"]["rate"]
            lv_str = f"{lv_comp:.1f}%" if lv_comp is not None else "N/A"
            eval_req_count = metrics["overall_leave_application_compliance"]["denominator"]
            req_text = f"across {eval_req_count} evaluable request" if eval_req_count == 1 else f"across {eval_req_count} evaluable requests"
            observations.append({
                "type": "policy",
                "text": f"{month_label} leave application compliance was {lv_str} {req_text}.",
            })

        # Approvals observation
        appr = metrics["approval_turnaround"]
        appr_count = appr["approval_count"]
        med_appr = appr["median_approval_turnaround_days"]
        pend_count = appr["pending_approval_count"]
        if appr_count > 0:
            pend_txt = f" with {pend_count} pending request(s)" if pend_count > 0 else ""
            observations.append({
                "type": "approval",
                "text": f"Median approval turnaround is {med_appr:.1f} days across {appr_count} approved requests{pend_txt}.",
            })

        payload = {
            "loaded": True,
            "filename": self.filename,
            "upload_timestamp": self.upload_timestamp.isoformat() if self.upload_timestamp else None,
            "dataset": {
                "rows": len(df),
                "total_source_rows": len(self.cleaned_df) if self.cleaned_df is not None else len(df),
                "unique_employees": unique_emps,
                "date_min": date_min_str,
                "date_max": date_max_str,
                "display_period": display_period,
                "policy_period": policy_period,
                "policy_effective_date": POLICY_EFFECTIVE_DATE_STR,
            },
            "quality": quality_payload,
            "metrics": metrics,
            "trends": trend_points,
            "observations": observations,
            "filters": self.get_available_filters(),
            "active_filters": active_filters,
        }

        return _serialize_value(payload)

    def get_trends(
        self,
        metric: str = "attendance_exception_rate",
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate time series and trends payload for a selected metric."""
        if not self.is_loaded or self.evaluated_df is None:
            return {
                "loaded": False,
                "message": "No workforce dataset loaded",
            }

        df = self.evaluated_df.copy()
        facts = self.employee_day_facts.copy() if self.employee_day_facts is not None else pd.DataFrame()
        reqs = list(self.leave_requests) if self.leave_requests is not None else []

        active_filters = {}
        if filters:
            for k, col in [
                ("business_unit", "Business Unit"),
                ("department", "Department"),
                ("sub_department", "Sub Department"),
                ("location", "Location"),
                ("reporting_manager", "Reporting Manager"),
            ]:
                val = filters.get(k)
                if val:
                    val_str = str(val).strip()
                    if col in df.columns:
                        df = df[df[col].astype(str).str.strip() == val_str]
                    if not facts.empty and col in facts.columns:
                        facts = facts[facts[col].astype(str).str.strip() == val_str]
                    active_filters[k] = val_str

            active_emps = set(df["Employee Number"].dropna())
            reqs = [r for r in reqs if r.get("employee_number") in active_emps]

        trend_res = calculate_time_series_trends(
            evaluated_df=df,
            evaluated_requests=reqs,
            employee_day_facts=facts,
            metric_id=metric,
        )

        payload = {
            "loaded": True,
            "filename": self.filename,
            "active_filters": active_filters,
            "available_filters": self.get_available_filters(),
            **trend_res,
        }
        return _serialize_value(payload)

    def get_trend_metrics(self) -> Dict[str, Any]:
        """Return grouped trend metrics catalogue."""
        return _serialize_value(get_trend_metric_catalogue())


# Global analysis session singleton
SESSION = AnalysisSession()
