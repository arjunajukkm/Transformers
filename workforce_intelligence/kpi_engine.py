"""
workforce_intelligence/kpi_engine.py
──────────────────────────────────────
High-performance analytical calculation engine for Transformers 2.0 Workforce Intelligence Dashboard.

Implements confirmed business rules and analytical specifications:
1. WFH Allowance: 3 days per employee per calendar month. Resets on 1st of each month.
   Excess = max(0, monthly_wfh - 3). Preserves half-days. Identifies partially observed months.
2. Punch Deviations: In-time and out-time compared against Business Unit benchmarks.
   Descriptive deviation flag for > 60 minutes difference (strictly > 60, exact 60 not flagged).
   Handles overnight shifts (+1440 min) and date-specific BU attribution for transfers.
3. Repeated Attendance Exceptions: Parameterized threshold (default: 3 qualifying days).
   Single employee-day with multiple flags counts as 1 qualifying exception day.
4. Executive Overview: 9 primary KPIs (EMP HC, Attendance Days, Present, OD, Leave, WFH,
   Holiday, Week Off, Attendance Exceptions) with strict additive quantity-weighted composition.
5. Leave & WFH Intelligence: Request reconstruction, confirmed vs inferred separation,
   applicant ownership, signed lead times (+/0/-), approval ownership on completed approvals,
   and approval turnaround.
6. Working Hours & Swipes: Swipe completeness categories, duration distribution bands
   reconciling strictly to complete swipes, and average punch metrics.

Pure backend analytics only. UI-independent, thread-safe, and read-only on shared DataFrames.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import numpy as np
import pandas as pd

from workforce_intelligence.normalization import (
    normalize_attendance_category,
    normalize_employee_number,
    normalize_quantity,
    normalize_text,
    parse_time_to_minutes as norm_parse_time,
)
import time_series_analysis as tsa


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions: Time, Duration & Date
# ─────────────────────────────────────────────────────────────────────────────

def minutes_to_time_str(mins: Optional[Union[float, int]], use_12hr: bool = True) -> str:
    """Convert minutes from midnight to a 12-hour or 24-hour time string."""
    if mins is None or pd.isna(mins) or math.isnan(mins):
        return "-"
    total_mins = int(round(mins)) % 1440
    hours = total_mins // 60
    minutes = total_mins % 60
    if use_12hr:
        period = "AM" if hours < 12 else "PM"
        disp_h = hours % 12
        if disp_h == 0:
            disp_h = 12
        return f"{disp_h:02d}:{minutes:02d} {period}"
    return f"{hours:02d}:{minutes:02d}"


def hours_to_duration_str(hrs: Optional[Union[float, int]]) -> str:
    """Convert decimal hours to duration string format (e.g. '8h 35m')."""
    if hrs is None or pd.isna(hrs) or math.isnan(hrs) or hrs <= 0:
        return "-"
    total_mins = int(round(hrs * 60))
    h = total_mins // 60
    m = total_mins % 60
    return f"{h}h {m:02d}m"


def ensure_clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure normalized helper columns exist on the DataFrame without mutating original.
    Returns df if already normalized, or a normalized copy.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame()
    if "_emp_num" in df.columns and "_bu" in df.columns and "_att_type" in df.columns:
        return df

    from storage.snapshot_service import normalize_dataset_dataframe
    return normalize_dataset_dataframe(df)


# ─────────────────────────────────────────────────────────────────────────────
# Part 1A: Monthly WFH Allowance Engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EmployeeMonthWFH:
    """Allowance tracking record for a single employee in a single calendar month."""
    employee_id: str
    employee_name: str
    business_unit: str
    department: str
    calendar_month: str  # Format: "YYYY-MM"
    eligible_wfh_days: float
    allowed_days: float  # Confirmed: 3.0
    excess_days: float   # max(0, eligible - allowed)
    is_exceeding: bool
    is_partially_observed: bool
    record_ids: List[str] = field(default_factory=list)
    wfh_days_in_scope: Optional[float] = None


def compute_wfh_allowance_monthly(
    df: pd.DataFrame,
    allowance_days: float = 3.0,
    scope_date_range: Optional[Tuple[date, date]] = None,
    full_dataset_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Compute WFH allowance metrics strictly by calendar month.
    Allowance resets on the 1st of each calendar month.
    Excess = max(0, eligible_monthly_wfh_days - allowance_days).

    Preserves half-day WFH quantities.
    Identifies partially observed calendar months.
    When a date filter or BU filter is applied, allowance calculations evaluate the
    complete available employee-month data, ensuring monthly excess is not artificially
    zeroed out by date slicing.
    """
    if df is None or len(df) == 0:
        return {
            "total_wfh_days": 0.0,
            "employees_taking_wfh": 0,
            "employees_exceeding_allowance": 0,
            "total_additional_wfh_days": 0.0,
            "wfh_allowance_threshold": allowance_days,
            "employee_month_breakdown": [],
            "exceeding_employee_ids": set(),
            "monthly_summary": {},
            "partially_observed_months": [],
        }

    work_df = ensure_clean_dataframe(df)
    eval_df = ensure_clean_dataframe(full_dataset_df) if full_dataset_df is not None and len(full_dataset_df) > 0 else work_df

    # Extract calendar month string (YYYY-MM) from _date
    def _extract_cal_month(d_val) -> str:
        if isinstance(d_val, (date, datetime)):
            return f"{d_val.year:04d}-{d_val.month:02d}"
        if isinstance(d_val, str) and len(d_val) >= 7:
            parsed = tsa.parse_date_value(d_val)
            if parsed:
                return f"{parsed.year:04d}-{parsed.month:02d}"
        return "Unknown"

    # Filter to WFH records on complete evaluation dataset
    is_wfh_eval = (
        eval_df["_att_type"].str.contains("work from home", case=False, na=False) |
        (eval_df["_att_type"].str.lower() == "wfh") |
        eval_df["_status"].str.lower().isin(["wfh", "work from home"])
    )
    eval_wfh_df = eval_df[is_wfh_eval].copy()

    if len(eval_wfh_df) == 0:
        return {
            "total_wfh_days": 0.0,
            "employees_taking_wfh": 0,
            "employees_exceeding_allowance": 0,
            "total_additional_wfh_days": 0.0,
            "wfh_allowance_threshold": allowance_days,
            "employee_month_breakdown": [],
            "exceeding_employee_ids": set(),
            "monthly_summary": {},
            "partially_observed_months": [],
        }

    # Extract clean quantities (preserving 0.5 fractions)
    qty_series = eval_wfh_df["_qty"] if "_qty" in eval_wfh_df.columns else (
        eval_wfh_df["Quantity"] if "Quantity" in eval_wfh_df.columns else pd.Series(1.0, index=eval_wfh_df.index)
    )
    clean_qtys = [normalize_quantity(q) if pd.notna(q) else 1.0 for q in qty_series]
    eval_wfh_df["_clean_qty"] = [1.0 if q is None or q <= 0 else q for q in clean_qtys]
    eval_wfh_df["_cal_month"] = [_extract_cal_month(d) for d in eval_wfh_df["_date"]]

    # Detect dataset date bounds per month to check partial observation
    all_dates = [d for d in eval_df["_date"] if isinstance(d, (date, datetime))]
    month_min_max: Dict[str, Tuple[int, int]] = {}
    if all_dates:
        for d in all_dates:
            m_key = f"{d.year:04d}-{d.month:02d}"
            if m_key not in month_min_max:
                month_min_max[m_key] = (d.day, d.day)
            else:
                month_min_max[m_key] = (
                    min(month_min_max[m_key][0], d.day),
                    max(month_min_max[m_key][1], d.day),
                )

    # Determine in-scope calendar months
    all_months_in_eval = set(eval_wfh_df["_cal_month"].dropna()) - {"Unknown", ""}
    if scope_date_range and len(scope_date_range) == 2 and scope_date_range[0] and scope_date_range[1]:
        start_d, end_d = scope_date_range
        import calendar
        in_scope_months = set()
        for m_str in all_months_in_eval:
            try:
                yr, mo = map(int, m_str.split("-"))
                m_start = date(yr, mo, 1)
                _, last_d = calendar.monthrange(yr, mo)
                m_end = date(yr, mo, last_d)
                if m_start <= end_d and m_end >= start_d:
                    in_scope_months.add(m_str)
            except Exception:
                in_scope_months.add(m_str)
    else:
        in_scope_months = all_months_in_eval

    # Identify scoped employees from active DataFrame
    scoped_emps = set(work_df["_emp_num"].dropna().unique()) - {"", "nan"}
    if not scoped_emps:
        scoped_emps = set(eval_wfh_df["_emp_num"].dropna().unique()) - {"", "nan"}

    emp_meta = eval_df.drop_duplicates(subset=["_emp_num"]).set_index("_emp_num")
    emp_names = emp_meta["_emp_name"].to_dict() if "_emp_name" in emp_meta.columns else {}
    emp_bus = emp_meta["_bu"].to_dict() if "_bu" in emp_meta.columns else {}
    emp_depts = emp_meta["_dept"].to_dict() if "_dept" in emp_meta.columns else {}

    breakdown_list: List[Dict[str, Any]] = []
    exceeding_emp_ids: Set[str] = set()
    total_excess_days = 0.0
    monthly_agg: Dict[str, Dict[str, Any]] = {}
    total_wfh_in_scope_days = 0.0
    distinct_wfh_emps: Set[str] = set()

    for cal_month in sorted(in_scope_months):
        m_rows = eval_wfh_df[eval_wfh_df["_cal_month"] == cal_month]
        if len(m_rows) == 0:
            continue

        for emp_id, grp in m_rows.groupby("_emp_num"):
            emp_str = str(emp_id).strip()
            if not emp_str or emp_str in ("nan", "None", ""):
                continue
            if emp_str not in scoped_emps:
                continue

            # Complete month WFH total for this employee across organization
            eligible_days = float(grp["_clean_qty"].sum())
            excess = max(0.0, eligible_days - allowance_days)
            is_exceeding = excess > 0.0

            # Calculate WFH days within the scope_date_range if provided
            if scope_date_range and len(scope_date_range) == 2 and scope_date_range[0] and scope_date_range[1]:
                start_d, end_d = scope_date_range
                s_mask = grp["_date"].apply(lambda d: start_d <= d <= end_d if isinstance(d, (date, datetime)) else False)
                wfh_in_scope = float(grp.loc[s_mask, "_clean_qty"].sum())
                scoped_rec_ids = grp.loc[s_mask, "record_id"].tolist() if "record_id" in grp.columns else []
            else:
                wfh_in_scope = eligible_days
                scoped_rec_ids = grp["record_id"].tolist() if "record_id" in grp.columns else []

            # If employee has WFH in scope (or full month without date filter)
            if wfh_in_scope > 0 or (scope_date_range is None and eligible_days > 0):
                distinct_wfh_emps.add(emp_str)
                total_wfh_in_scope_days += wfh_in_scope

            if is_exceeding:
                exceeding_emp_ids.add(emp_str)
                total_excess_days += excess

            # Determine partial observation: if available dataset does not start on day 1 or end on month-end
            is_partially_obs = False
            if cal_month in month_min_max:
                min_d, max_d = month_min_max[cal_month]
                try:
                    yr, mo = map(int, cal_month.split("-"))
                    import calendar
                    _, days_in_mo = calendar.monthrange(yr, mo)
                    if min_d > 1 or max_d < days_in_mo:
                        is_partially_obs = True
                except Exception:
                    pass

            # Business unit attribution (using latest BU in this month in case of transfer)
            bu_val = str(emp_bus.get(emp_str, "General"))
            if "_bu" in grp.columns:
                bu_list = [b for b in grp["_bu"].dropna().unique() if b not in ("", "nan", "None")]
                if bu_list:
                    bu_val = bu_list[-1]

            em_record = EmployeeMonthWFH(
                employee_id=emp_str,
                employee_name=str(emp_names.get(emp_str, emp_str)),
                business_unit=bu_val,
                department=str(emp_depts.get(emp_str, "General")),
                calendar_month=cal_month,
                eligible_wfh_days=round(eligible_days, 1),
                allowed_days=allowance_days,
                excess_days=round(excess, 1),
                is_exceeding=is_exceeding,
                is_partially_observed=is_partially_obs,
                record_ids=scoped_rec_ids,
                wfh_days_in_scope=round(wfh_in_scope, 1),
            )
            breakdown_list.append(asdict(em_record))

            # Monthly summary aggregate
            if cal_month not in monthly_agg:
                monthly_agg[cal_month] = {
                    "total_wfh_days": 0.0,
                    "wfh_days_in_scope": 0.0,
                    "employees_taking_wfh": set(),
                    "employees_exceeding": set(),
                    "excess_days": 0.0,
                    "is_partially_observed": is_partially_obs,
                }
            monthly_agg[cal_month]["total_wfh_days"] += eligible_days
            monthly_agg[cal_month]["wfh_days_in_scope"] += wfh_in_scope
            if wfh_in_scope > 0 or (scope_date_range is None and eligible_days > 0):
                monthly_agg[cal_month]["employees_taking_wfh"].add(emp_str)
            if is_exceeding:
                monthly_agg[cal_month]["employees_exceeding"].add(emp_str)
                monthly_agg[cal_month]["excess_days"] += excess

    # Format monthly summary
    final_monthly_summary = {}
    for m_k, m_v in monthly_agg.items():
        final_monthly_summary[m_k] = {
            "total_wfh_days": round(m_v["total_wfh_days"], 1),
            "wfh_days_in_scope": round(m_v["wfh_days_in_scope"], 1),
            "employees_taking_wfh": len(m_v["employees_taking_wfh"]),
            "employees_exceeding": len(m_v["employees_exceeding"]),
            "excess_days": round(m_v["excess_days"], 1),
            "is_partially_observed": m_v["is_partially_observed"],
        }

    partially_observed_months = [m for m, v in final_monthly_summary.items() if v["is_partially_observed"]]

    return {
        "total_wfh_days": round(total_wfh_in_scope_days, 1),
        "employees_taking_wfh": len(distinct_wfh_emps),
        "employees_exceeding_allowance": len(exceeding_emp_ids),
        "total_additional_wfh_days": round(total_excess_days, 1),
        "wfh_allowance_threshold": allowance_days,
        "employee_month_breakdown": breakdown_list,
        "exceeding_employee_ids": exceeding_emp_ids,
        "monthly_summary": final_monthly_summary,
        "partially_observed_months": partially_observed_months,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part 1B: Business Unit Punch Deviation Engine (> 60 Minutes)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EmployeePunchDeviation:
    """Punch deviation profile for an employee against their Business Unit baseline."""
    employee_id: str
    employee_name: str
    business_unit: str
    observation_count: int
    avg_in_mins: Optional[float]
    avg_out_mins: Optional[float]
    bu_avg_in_mins: Optional[float]
    bu_avg_out_mins: Optional[float]
    in_deviation_mins: Optional[float]   # Employee - BU
    out_deviation_mins: Optional[float]  # Employee - BU
    is_late_arrival: bool    # in_deviation_mins > 60.0
    is_early_departure: bool # out_deviation_mins < -60.0
    comparison_status: str = "EVALUATED"
    notes: str = "Descriptive workforce pattern, not a confirmed attendance-policy violation."


def compute_punch_deviations_bu(
    df: pd.DataFrame,
    threshold_mins: float = 60.0,
) -> Dict[str, Any]:
    """
    Compare each employee against the average punch times of their relevant Business Unit.
    Confirmed descriptive deviation threshold: MORE THAN 60 MINUTES (> 60.0 min).
    Exact 60.0 minutes difference is NOT flagged.

    Handles:
    - Date-specific Business Unit attribution for employee transfers.
    - Overnight shifts (+1440 min when out < in).
    - Shift cohort comparability: non-comparable shifts (>4h circular discrepancy) are marked N/A.
    - Missing punches are never treated as midnight.
    - Results represent descriptive workforce patterns, not policy violations.
    """
    if df is None or len(df) == 0:
        return {
            "bu_benchmarks": {},
            "employee_deviations": [],
            "late_arrival_employees_count": 0,
            "early_departure_employees_count": 0,
            "deviation_threshold_mins": threshold_mins,
        }

    work_df = ensure_clean_dataframe(df)

    # Filter to physical attendance records
    is_physical = (
        work_df["_att_type"].str.contains("present|missing swipes", case=False, na=False) |
        work_df["_status"].str.lower().isin(["p", "p(ms)", "ms", "present"])
    )
    phys_df = work_df[is_physical].copy()

    if len(phys_df) == 0 or "_in_mins" not in phys_df.columns:
        return {
            "bu_benchmarks": {},
            "employee_deviations": [],
            "late_arrival_employees_count": 0,
            "early_departure_employees_count": 0,
            "deviation_threshold_mins": threshold_mins,
        }

    # Handle cross-midnight overnight shifts: if out < in, add 1440 min
    in_m = phys_df["_in_mins"].copy()
    out_m = phys_df["_out_mins"].copy()
    adjusted_out = []
    for i_val, o_val in zip(in_m, out_m):
        if pd.notna(i_val) and pd.notna(o_val):
            if o_val < i_val:
                adjusted_out.append(o_val + 1440.0)
            else:
                adjusted_out.append(float(o_val))
        elif pd.notna(o_val):
            adjusted_out.append(float(o_val))
        else:
            adjusted_out.append(np.nan)
    phys_df["_adj_out_mins"] = adjusted_out

    # Step 1: Calculate Business Unit benchmarks
    bu_in_avg: Dict[str, float] = {}
    bu_out_avg: Dict[str, float] = {}
    bu_counts: Dict[str, int] = {}

    for bu_name, grp in phys_df.groupby("_bu"):
        if not bu_name or bu_name in ("nan", "None", ""):
            continue
        valid_in = grp["_in_mins"].dropna()
        valid_out = grp["_adj_out_mins"].dropna()

        if len(valid_in) > 0:
            bu_in_avg[bu_name] = float(valid_in.mean())
        if len(valid_out) > 0:
            bu_out_avg[bu_name] = float(valid_out.mean())
        bu_counts[bu_name] = len(grp)

    # Step 2: Calculate Employee Averages per BU (honoring transfers across BUs)
    emp_meta = phys_df.drop_duplicates(subset=["_emp_num"]).set_index("_emp_num")
    emp_names = emp_meta["_emp_name"].to_dict() if "_emp_name" in emp_meta.columns else {}

    employee_devs: List[Dict[str, Any]] = []
    late_arrival_emps: Set[str] = set()
    early_departure_emps: Set[str] = set()

    for (emp_id, bu_name), grp in phys_df.groupby(["_emp_num", "_bu"]):
        if not emp_id or emp_id in ("nan", "None", ""):
            continue
        emp_str = str(emp_id).strip()
        obs_count = len(grp)

        valid_in = grp["_in_mins"].dropna()
        valid_out = grp["_adj_out_mins"].dropna()

        emp_in_mean = float(valid_in.mean()) if len(valid_in) > 0 else None
        emp_out_mean = float(valid_out.mean()) if len(valid_out) > 0 else None

        bu_in_benchmark = bu_in_avg.get(bu_name)
        bu_out_benchmark = bu_out_avg.get(bu_name)

        # In-Time Deviation: Employee Average In - BU Average In
        in_dev = None
        is_late = False
        out_dev = None
        is_early = False
        comparison_status = "EVALUATED"

        if emp_in_mean is not None and bu_in_benchmark is not None:
            # Check shift cohort comparability on circular 24h clock (1440 min)
            clock_diff = abs(emp_in_mean - bu_in_benchmark)
            circular_shift_diff = min(clock_diff, 1440.0 - clock_diff)

            if circular_shift_diff > 240.0:
                comparison_status = "N/A: Non-comparable shift schedule (overnight/different shift cohort)"
            else:
                in_dev = round(emp_in_mean - bu_in_benchmark, 1)
                # Confirmed rule: strictly > 60.0 (exact 60.0 is NOT flagged)
                if in_dev > threshold_mins:
                    is_late = True
                    late_arrival_emps.add(emp_str)

        if comparison_status == "EVALUATED" and emp_out_mean is not None and bu_out_benchmark is not None:
            out_dev = round(emp_out_mean - bu_out_benchmark, 1)
            # Confirmed rule: strictly < -60.0 (exact -60.0 is NOT flagged)
            if out_dev < -threshold_mins:
                is_early = True
                early_departure_emps.add(emp_str)

        dev_record = EmployeePunchDeviation(
            employee_id=emp_str,
            employee_name=str(emp_names.get(emp_str, emp_str)),
            business_unit=bu_name,
            observation_count=obs_count,
            avg_in_mins=round(emp_in_mean, 1) if emp_in_mean is not None else None,
            avg_out_mins=round(emp_out_mean, 1) if emp_out_mean is not None else None,
            bu_avg_in_mins=round(bu_in_benchmark, 1) if bu_in_benchmark is not None else None,
            bu_avg_out_mins=round(bu_out_benchmark, 1) if bu_out_benchmark is not None else None,
            in_deviation_mins=in_dev,
            out_deviation_mins=out_dev,
            is_late_arrival=is_late,
            is_early_departure=is_early,
            comparison_status=comparison_status,
            notes="Descriptive workforce pattern, not a confirmed attendance-policy violation.",
        )
        employee_devs.append(asdict(dev_record))

    bu_benchmark_dict = {}
    for bu_k in bu_counts.keys():
        bu_benchmark_dict[bu_k] = {
            "record_count": bu_counts[bu_k],
            "avg_in_mins": round(bu_in_avg.get(bu_k, 0.0), 1) if bu_k in bu_in_avg else None,
            "avg_out_mins": round(bu_out_avg.get(bu_k, 0.0), 1) if bu_k in bu_out_avg else None,
            "avg_in_time_str": minutes_to_time_str(bu_in_avg.get(bu_k)),
            "avg_out_time_str": minutes_to_time_str(bu_out_avg.get(bu_k)),
            "avg_in_str": minutes_to_time_str(bu_in_avg.get(bu_k)),
            "avg_out_str": minutes_to_time_str(bu_out_avg.get(bu_k)),
        }

    return {
        "bu_benchmarks": bu_benchmark_dict,
        "employee_deviations": employee_devs,
        "late_arrival_employees_count": len(late_arrival_emps),
        "early_departure_employees_count": len(early_departure_emps),
        "deviation_threshold_mins": threshold_mins,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part 1C: Repeated Attendance Exceptions (Adjustable Threshold)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RepeatExceptionDossier:
    """Exception tracking record for an employee with attendance non-compliance."""
    employee_id: str
    employee_name: str
    business_unit: str
    department: str
    reporting_manager: str
    qualifying_exception_days: int
    threshold: int
    meets_threshold: bool
    exception_dates: List[str] = field(default_factory=list)
    exception_types: List[str] = field(default_factory=list)
    source_record_ids: List[str] = field(default_factory=list)


def compute_repeated_exceptions(
    df: pd.DataFrame,
    threshold: int = 3,
) -> Dict[str, Any]:
    """
    Compute repeated attendance non-compliance with a configurable threshold parameter.
    Initial default threshold: 3 qualifying employee-day occurrences.

    Rule: Multiple exception flags on the same employee-day count as ONE qualifying exception day.
    """
    if df is None or len(df) == 0:
        return {
            "threshold": threshold,
            "total_repeat_employees": 0,
            "repeat_employee_pct": 0.0,
            "dossiers": [],
            "repeat_employee_ids": set(),
        }

    work_df = ensure_clean_dataframe(df)

    is_reg = (
        work_df["_att_type"].str.contains("regulariz", case=False, na=False) |
        work_df["_status"].str.contains(r'\(r\)|ar|pr', case=False, regex=True, na=False)
    )
    is_ms = (
        work_df["_att_type"].str.contains("missing swipes", case=False, na=False) |
        work_df["_status"].str.lower().isin(["ms", "p(ms)"])
    )
    is_ab = (
        work_df["_att_type"].str.contains("absent", case=False, na=False) |
        work_df["_status"].str.lower().isin(["ab", "absent", "a"])
    )

    is_excp = is_reg | is_ms | is_ab
    excp_df = work_df[is_excp].copy()

    unique_employees = len(set(work_df["_emp_num"].unique()) - {"", "nan"})
    if unique_employees == 0:
        return {
            "threshold": threshold,
            "total_repeat_employees": 0,
            "repeat_employee_pct": 0.0,
            "dossiers": [],
            "repeat_employee_ids": set(),
        }

    emp_meta = work_df.drop_duplicates(subset=["_emp_num"]).set_index("_emp_num")
    emp_names = emp_meta["_emp_name"].to_dict() if "_emp_name" in emp_meta.columns else {}
    emp_bus = emp_meta["_bu"].to_dict() if "_bu" in emp_meta.columns else {}
    emp_depts = emp_meta["_dept"].to_dict() if "_dept" in emp_meta.columns else {}
    emp_rms = emp_meta["_rm"].to_dict() if "_rm" in emp_meta.columns else {}

    dossiers: List[Dict[str, Any]] = []
    repeat_emp_ids: Set[str] = set()

    all_emps = set(work_df["_emp_num"].unique()) - {"", "nan"}
    for emp_id in sorted(all_emps):
        emp_str = str(emp_id).strip()
        e_rows = excp_df[excp_df["_emp_num"] == emp_id]

        if len(e_rows) == 0:
            qualifying_dates: Set[Any] = set()
            excp_types_seen: Set[str] = set()
            rec_ids: List[str] = []
        else:
            qualifying_dates = set(e_rows["_date"].dropna())
            excp_types_seen = set()
            for _, r in e_rows.iterrows():
                st = str(r.get("_status", "")).lower()
                at = str(r.get("_att_type", "")).lower()
                if "reg" in at or re.search(r'\(r\)|ar|pr', st):
                    excp_types_seen.add("Regularization")
                if "missing" in at or st in ("ms", "p(ms)"):
                    excp_types_seen.add("Missing Swipe")
                if "absent" in at or st in ("ab", "absent", "a"):
                    excp_types_seen.add("Absent")
        date_strs = [d.isoformat() if isinstance(d, (date, datetime)) else str(d) for d in sorted(qualifying_dates, key=lambda x: str(x))]
        if "record_id" in e_rows.columns:
            rec_ids = [str(x) for x in e_rows["record_id"].tolist()]
        elif "Record ID" in e_rows.columns:
            rec_ids = [str(x) for x in e_rows["Record ID"].tolist()]
        else:
            rec_ids = [f"{emp_str}_{d}" for d in date_strs]

        q_count = len(qualifying_dates)
        meets = q_count >= threshold
        if meets:
            repeat_emp_ids.add(emp_str)

        dossier = RepeatExceptionDossier(
            employee_id=emp_str,
            employee_name=str(emp_names.get(emp_str, emp_str)),
            business_unit=str(emp_bus.get(emp_str, "General")),
            department=str(emp_depts.get(emp_str, "General")),
            reporting_manager=str(emp_rms.get(emp_str, "Unknown")),
            qualifying_exception_days=q_count,
            threshold=threshold,
            meets_threshold=meets,
            exception_dates=date_strs,
            exception_types=sorted(excp_types_seen),
            source_record_ids=rec_ids,
        )
        dossiers.append(asdict(dossier))

    total_repeat = len(repeat_emp_ids)
    repeat_pct = round((total_repeat / unique_employees) * 100.0, 1) if unique_employees > 0 else 0.0

    return {
        "threshold": threshold,
        "total_repeat_employees": total_repeat,
        "repeat_employee_pct": repeat_pct,
        "dossiers": dossiers,
        "repeat_employee_ids": repeat_emp_ids,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: Comprehensive Workforce Intelligence KPI Engine
# ─────────────────────────────────────────────────────────────────────────────

def compute_workforce_intelligence_bundle(
    df: pd.DataFrame,
    canonical_data: Optional[Any] = None,
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
    Compute comprehensive KPI bundle across all five dashboard sections.
    Integrates CanonicalWorkforceData requests and facts when available.
    """
    if df is None or len(df) == 0:
        return _empty_bundle(exception_threshold, wfh_allowance)

    work_df = ensure_clean_dataframe(df)
    filtered = work_df.copy()

    # Apply global filters
    if business_unit and business_unit not in ("All", "All Business Units", ""):
        filtered = filtered[filtered["_bu"].str.lower() == business_unit.strip().lower()]

    if department and department not in ("All", "All Departments", ""):
        filtered = filtered[filtered["_dept"].str.lower() == department.strip().lower()]

    if manager and manager not in ("All", "All Managers", "All Reporting Managers", ""):
        filtered = filtered[filtered["_rm"].str.lower() == manager.strip().lower()]

    if employee and employee not in ("All", "All Employees", ""):
        emp_clean = employee.strip().lower()
        filtered = filtered[
            (filtered["_emp_num"].str.lower() == emp_clean) |
            (filtered["_emp_name"].str.lower() == emp_clean)
        ]

    if date_range and len(date_range) == 2:
        start_d, end_d = date_range
        if start_d and end_d and "_date" in filtered.columns:
            filtered = filtered[filtered["_date"].apply(lambda d: start_d <= d <= end_d if isinstance(d, (date, datetime)) else False)]

    total_records = len(filtered)
    if total_records == 0:
        return _empty_bundle(exception_threshold, wfh_allowance)

    # 1. Extract clean quantities (continuous weights, preserving 0.5)
    qty_series = filtered["_qty"] if "_qty" in filtered.columns else (
        filtered["Quantity"] if "Quantity" in filtered.columns else pd.Series(1.0, index=filtered.index)
    )
    clean_qtys = [normalize_quantity(q) if pd.notna(q) else 1.0 for q in qty_series]
    clean_qtys = [1.0 if q is None or q <= 0 else q for q in clean_qtys]
    filtered["_clean_qty"] = clean_qtys

    unique_employees = len(set(filtered["_emp_num"].unique()) - {"", "nan"})
    recorded_employee_days = len(filtered.drop_duplicates(subset=["_emp_num", "_date"])) if "_date" in filtered.columns else total_records

    # ─────────────────────────────────────────────────────────────────────────
    # Section 1: Executive Overview & Attendance Composition
    # ─────────────────────────────────────────────────────────────────────────
    is_wfh = (
        filtered["_att_type"].str.contains("work from home", case=False, na=False) |
        (filtered["_att_type"].str.lower() == "wfh") |
        filtered["_status"].str.lower().isin(["wfh", "work from home"])
    )
    is_leave = (
        filtered["_att_type"].str.contains("leave", case=False, na=False) |
        filtered["_status"].str.lower().isin(["cl", "sl", "pl", "el", "co", "leave", "l"])
    ) & (~is_wfh)
    is_od = (
        filtered["_att_type"].str.contains("on duty|duty", case=False, na=False) |
        filtered["_status"].str.lower().isin(["od", "on duty"])
    ) & (~is_wfh) & (~is_leave)
    is_hol = (
        filtered["_att_type"].str.contains("holiday", case=False, na=False) |
        filtered["_status"].str.lower().isin(["h", "ho", "holiday"])
    ) & (~is_wfh) & (~is_leave) & (~is_od)
    is_wo = (
        filtered["_att_type"].str.contains("week off|weekly off|off", case=False, na=False) |
        filtered["_status"].str.lower().isin(["wo", "w/o", "off", "week off"])
    ) & (~is_wfh) & (~is_leave) & (~is_od) & (~is_hol)
    is_ms = (
        filtered["_att_type"].str.contains("missing swipes", case=False, na=False) |
        filtered["_status"].str.lower().isin(["ms", "p(ms)"])
    )
    is_ab = (
        filtered["_att_type"].str.contains("absent", case=False, na=False) |
        filtered["_status"].str.lower().isin(["ab", "absent", "a"])
    ) & (~is_leave) & (~is_wfh) & (~is_od) & (~is_hol) & (~is_wo)
    is_pres = (
        filtered["_att_type"].str.contains("present", case=False, na=False) |
        filtered["_status"].str.lower().isin(["p", "present"])
    ) & (~is_ms) & (~is_leave) & (~is_wfh) & (~is_od) & (~is_hol) & (~is_wo) & (~is_ab)

    is_classified = (is_pres | is_ms | is_od | is_leave | is_wfh | is_hol | is_wo | is_ab)
    is_unclassified = ~is_classified

    q_pres = float(filtered.loc[is_pres, "_clean_qty"].sum())
    q_ms = float(filtered.loc[is_ms, "_clean_qty"].sum())
    q_total_present = q_pres + q_ms
    q_od = float(filtered.loc[is_od, "_clean_qty"].sum())
    q_leave = float(filtered.loc[is_leave, "_clean_qty"].sum())
    q_wfh = float(filtered.loc[is_wfh, "_clean_qty"].sum())
    q_hol = float(filtered.loc[is_hol, "_clean_qty"].sum())
    q_wo = float(filtered.loc[is_wo, "_clean_qty"].sum())
    q_absent = float(filtered.loc[is_ab, "_clean_qty"].sum())
    q_unclassified = float(filtered.loc[is_unclassified, "_clean_qty"].sum())
    unclassified_records_count = int(sum(is_unclassified))

    q_classified_denom = q_total_present + q_od + q_leave + q_wfh + q_hol + q_wo + q_absent
    total_quantity_recorded = q_classified_denom + q_unclassified
    attendance_composition_denom = total_quantity_recorded if total_quantity_recorded > 0 else float(recorded_employee_days)

    pct_pres = round((q_total_present / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_od = round((q_od / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_leave = round((q_leave / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_wfh = round((q_wfh / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_hol = round((q_hol / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_wo = round((q_wo / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_absent = round((q_absent / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0
    pct_unclassified = round((q_unclassified / attendance_composition_denom) * 100.0, 1) if attendance_composition_denom > 0 else 0.0

    is_reg = (
        filtered["_att_type"].str.contains("regulariz", case=False, na=False) |
        filtered["_status"].str.contains(r'\(r\)|ar|pr', case=False, regex=True, na=False)
    )
    is_exception_row = is_ms | is_reg | is_ab
    excp_days_count = len(filtered[is_exception_row].drop_duplicates(subset=["_emp_num", "_date"])) if "_date" in filtered.columns else int(sum(is_exception_row))
    excp_rate_pct = round((excp_days_count / recorded_employee_days) * 100.0, 1) if recorded_employee_days > 0 else 0.0
    excp_affected_emps = len(set(filtered.loc[is_exception_row, "_emp_num"].unique()) - {"", "nan"})

    # ─────────────────────────────────────────────────────────────────────────
    # Section 2: Leave Intelligence
    # ─────────────────────────────────────────────────────────────────────────
    leave_df = filtered[is_leave].copy()
    leave_emps = len(set(leave_df["_emp_num"].unique()) - {"", "nan"})
    leave_emp_penetration_pct = round((leave_emps / unique_employees) * 100.0, 1) if unique_employees > 0 else 0.0

    leave_requests_count = len(leave_df)
    confirmed_leave_requests = 0
    inferred_leave_requests = 0

    if canonical_data and hasattr(canonical_data, "requests"):
        scope_emp_ids = set(filtered["_emp_num"].unique())
        c_leaves = [
            r for r in canonical_data.requests
            if r.request_type == "LEAVE" and r.employee_id in scope_emp_ids
        ]
        if c_leaves:
            leave_requests_count = len(c_leaves)
            confirmed_leave_requests = sum(1 for r in c_leaves if not r.is_inferred)
            inferred_leave_requests = sum(1 for r in c_leaves if r.is_inferred)
    if confirmed_leave_requests == 0 and inferred_leave_requests == 0:
        confirmed_leave_requests = leave_requests_count

    valid_leave_app = leave_df[leave_df["_date"].notna() & leave_df["_applied_on"].notna()].copy()
    leave_prior_cnt = 0
    leave_same_day_cnt = 0
    leave_retro_cnt = 0
    leave_lead_times: List[float] = []

    if len(valid_leave_app) > 0:
        for dt, app in zip(valid_leave_app["_date"], valid_leave_app["_applied_on"]):
            if isinstance(dt, (date, datetime)) and isinstance(app, (date, datetime)):
                lead_days = float((dt - app).days)
                leave_lead_times.append(lead_days)
                if lead_days > 0:
                    leave_prior_cnt += 1
                elif lead_days == 0:
                    leave_same_day_cnt += 1
                else:
                    leave_retro_cnt += 1

    valid_leave_app_count = len(leave_lead_times)
    leave_prior_pct = round((leave_prior_cnt / valid_leave_app_count) * 100.0, 1) if valid_leave_app_count > 0 else 0.0
    leave_same_day_pct = round((leave_same_day_cnt / valid_leave_app_count) * 100.0, 1) if valid_leave_app_count > 0 else 0.0
    leave_retro_pct = round((leave_retro_cnt / valid_leave_app_count) * 100.0, 1) if valid_leave_app_count > 0 else 0.0

    avg_leave_lead_time = round(float(np.mean(leave_lead_times)), 1) if leave_lead_times else 0.0
    median_leave_lead_time = round(float(np.median(leave_lead_times)), 1) if leave_lead_times else 0.0

    leave_applied_by_emp = int(sum(leave_df["_applied_by"].str.lower() == "employee"))
    leave_applied_by_admin = int(sum(leave_df["_applied_by"].str.lower() == "admin"))
    tot_leave_applied_actor = len(leave_df)
    pct_leave_emp_actor = round((leave_applied_by_emp / tot_leave_applied_actor) * 100.0, 1) if tot_leave_applied_actor > 0 else 0.0
    pct_leave_admin_actor = round((leave_applied_by_admin / tot_leave_applied_actor) * 100.0, 1) if tot_leave_applied_actor > 0 else 0.0

    valid_leave_appr = leave_df[leave_df["_applied_on"].notna() & leave_df["_approved_on"].notna()].copy()
    leave_approval_days: List[float] = []
    if len(valid_leave_appr) > 0:
        for appr, appl in zip(valid_leave_appr["_approved_on"], valid_leave_appr["_applied_on"]):
            if isinstance(appr, (date, datetime)) and isinstance(appl, (date, datetime)):
                t_days = float((appr - appl).days)
                if t_days >= 0:
                    leave_approval_days.append(t_days)

    avg_leave_turnaround = round(float(np.mean(leave_approval_days)), 1) if leave_approval_days else 0.0
    median_leave_turnaround = round(float(np.median(leave_approval_days)), 1) if leave_approval_days else 0.0

    leave_completed_approvals = len(valid_leave_appr)
    leave_appr_mgr = int(sum(valid_leave_appr["_approved_by"].str.lower() == "manager"))
    leave_appr_admin = int(sum(valid_leave_appr["_approved_by"].str.lower() == "admin"))
    leave_appr_other = max(0, leave_completed_approvals - leave_appr_mgr - leave_appr_admin)

    leave_pct_mgr = round((leave_appr_mgr / leave_completed_approvals) * 100.0, 1) if leave_completed_approvals > 0 else 0.0
    leave_pct_admin = round((leave_appr_admin / leave_completed_approvals) * 100.0, 1) if leave_completed_approvals > 0 else 0.0
    leave_pct_other = round((leave_appr_other / leave_completed_approvals) * 100.0, 1) if leave_completed_approvals > 0 else 0.0

    leave_pending_count = max(0, len(leave_df) - leave_completed_approvals)

    # ─────────────────────────────────────────────────────────────────────────
    # Section 3: WFH Intelligence (Monthly Reset Model)
    # ─────────────────────────────────────────────────────────────────────────
    wfh_monthly_bundle = compute_wfh_allowance_monthly(
        filtered,
        allowance_days=wfh_allowance,
        scope_date_range=date_range,
        full_dataset_df=work_df,
    )

    wfh_df = filtered[is_wfh].copy()
    wfh_requests_count = len(wfh_df)
    confirmed_wfh_requests = 0
    inferred_wfh_requests = 0

    if canonical_data and hasattr(canonical_data, "requests"):
        scope_emp_ids = set(filtered["_emp_num"].unique())
        c_wfh = [
            r for r in canonical_data.requests
            if r.request_type == "WFH" and r.employee_id in scope_emp_ids
        ]
        if c_wfh:
            wfh_requests_count = len(c_wfh)
            confirmed_wfh_requests = sum(1 for r in c_wfh if not r.is_inferred)
            inferred_wfh_requests = sum(1 for r in c_wfh if r.is_inferred)
    if confirmed_wfh_requests == 0 and inferred_wfh_requests == 0:
        confirmed_wfh_requests = wfh_requests_count

    valid_wfh_app = wfh_df[wfh_df["_date"].notna() & wfh_df["_applied_on"].notna()].copy()
    wfh_prior_cnt = 0
    wfh_same_day_cnt = 0
    wfh_retro_cnt = 0
    wfh_lead_times: List[float] = []

    if len(valid_wfh_app) > 0:
        for dt, app in zip(valid_wfh_app["_date"], valid_wfh_app["_applied_on"]):
            if isinstance(dt, (date, datetime)) and isinstance(app, (date, datetime)):
                lead_days = float((dt - app).days)
                wfh_lead_times.append(lead_days)
                if lead_days > 0:
                    wfh_prior_cnt += 1
                elif lead_days == 0:
                    wfh_same_day_cnt += 1
                else:
                    wfh_retro_cnt += 1

    valid_wfh_app_count = len(wfh_lead_times)
    wfh_prior_pct = round((wfh_prior_cnt / valid_wfh_app_count) * 100.0, 1) if valid_wfh_app_count > 0 else 0.0
    wfh_same_day_pct = round((wfh_same_day_cnt / valid_wfh_app_count) * 100.0, 1) if valid_wfh_app_count > 0 else 0.0
    wfh_retro_pct = round((wfh_retro_cnt / valid_wfh_app_count) * 100.0, 1) if valid_wfh_app_count > 0 else 0.0

    avg_wfh_lead_time = round(float(np.mean(wfh_lead_times)), 1) if wfh_lead_times else 0.0
    median_wfh_lead_time = round(float(np.median(wfh_lead_times)), 1) if wfh_lead_times else 0.0

    wfh_applied_by_emp = int(sum(wfh_df["_applied_by"].str.lower() == "employee"))
    wfh_applied_by_admin = int(sum(wfh_df["_applied_by"].str.lower() == "admin"))
    tot_wfh_applied_actor = len(wfh_df)
    pct_wfh_emp_actor = round((wfh_applied_by_emp / tot_wfh_applied_actor) * 100.0, 1) if tot_wfh_applied_actor > 0 else 0.0
    pct_wfh_admin_actor = round((wfh_applied_by_admin / tot_wfh_applied_actor) * 100.0, 1) if tot_wfh_applied_actor > 0 else 0.0

    valid_wfh_appr = wfh_df[wfh_df["_applied_on"].notna() & wfh_df["_approved_on"].notna()].copy()
    wfh_approval_days: List[float] = []
    if len(valid_wfh_appr) > 0:
        for appr, appl in zip(valid_wfh_appr["_approved_on"], valid_wfh_appr["_applied_on"]):
            if isinstance(appr, (date, datetime)) and isinstance(appl, (date, datetime)):
                t_days = float((appr - appl).days)
                if t_days >= 0:
                    wfh_approval_days.append(t_days)

    avg_wfh_turnaround = round(float(np.mean(wfh_approval_days)), 1) if wfh_approval_days else 0.0
    median_wfh_turnaround = round(float(np.median(wfh_approval_days)), 1) if wfh_approval_days else 0.0

    wfh_completed_approvals = len(valid_wfh_appr)
    wfh_appr_mgr = int(sum(valid_wfh_appr["_approved_by"].str.lower() == "manager"))
    wfh_appr_admin = int(sum(valid_wfh_appr["_approved_by"].str.lower() == "admin"))
    wfh_pct_mgr = round((wfh_appr_mgr / wfh_completed_approvals) * 100.0, 1) if wfh_completed_approvals > 0 else 0.0
    wfh_pct_admin = round((wfh_appr_admin / wfh_completed_approvals) * 100.0, 1) if wfh_completed_approvals > 0 else 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Section 4: Working Hours & Swipe Intelligence
    # ─────────────────────────────────────────────────────────────────────────
    is_pres_ms = is_pres | is_ms
    pres_ms_df = filtered[is_pres_ms].copy()
    total_physical_days = len(pres_ms_df)

    has_in = pres_ms_df["_in_mins"].notna()
    has_out = pres_ms_df["_out_mins"].notna()

    complete_swipes_mask = has_in & has_out
    missing_in_mask = (~has_in) & has_out
    missing_out_mask = has_in & (~has_out)
    both_missing_mask = (~has_in) & (~has_out)

    complete_swipes_cnt = int(sum(complete_swipes_mask))
    missing_in_cnt = int(sum(missing_in_mask))
    missing_out_cnt = int(sum(missing_out_mask))
    both_missing_cnt = int(sum(both_missing_mask))

    complete_swipes_pct = round((complete_swipes_cnt / total_physical_days) * 100.0, 1) if total_physical_days > 0 else 0.0
    missing_in_pct = round((missing_in_cnt / total_physical_days) * 100.0, 1) if total_physical_days > 0 else 0.0
    missing_out_pct = round((missing_out_cnt / total_physical_days) * 100.0, 1) if total_physical_days > 0 else 0.0
    both_missing_pct = round((both_missing_cnt / total_physical_days) * 100.0, 1) if total_physical_days > 0 else 0.0

    valid_in = pres_ms_df.loc[has_in, "_in_mins"]
    avg_in_mins = float(valid_in.mean()) if len(valid_in) > 0 else None

    complete_df = pres_ms_df[complete_swipes_mask].copy()
    adj_out_mins = []
    work_durations = []
    for i_m, o_m in zip(complete_df["_in_mins"], complete_df["_out_mins"]):
        if o_m < i_m:
            o_adj = o_m + 1440.0
        else:
            o_adj = float(o_m)
        adj_out_mins.append(o_adj)
        dur = (o_adj - i_m) / 60.0
        work_durations.append(dur)
    complete_df["_adj_out_mins"] = adj_out_mins
    complete_df["_calc_work_hrs"] = work_durations

    avg_out_mins = float(complete_df["_adj_out_mins"].mean()) if len(complete_df) > 0 else (
        float(pres_ms_df.loc[has_out, "_out_mins"].mean()) if sum(has_out) > 0 else None
    )
    avg_work_hrs = float(complete_df["_calc_work_hrs"].mean()) if len(complete_df) > 0 else None

    # Working duration bands strictly summing to complete_swipes_cnt
    dur_band_under_4h = int(sum(complete_df["_calc_work_hrs"] < 4.0)) if len(complete_df) > 0 else 0
    dur_band_4_8h = int(sum((complete_df["_calc_work_hrs"] >= 4.0) & (complete_df["_calc_work_hrs"] < 8.0))) if len(complete_df) > 0 else 0
    dur_band_8_10h = int(sum((complete_df["_calc_work_hrs"] >= 8.0) & (complete_df["_calc_work_hrs"] <= 10.0))) if len(complete_df) > 0 else 0
    dur_band_over_10h = int(sum(complete_df["_calc_work_hrs"] > 10.0)) if len(complete_df) > 0 else 0

    pct_band_under_4h = round((dur_band_under_4h / complete_swipes_cnt) * 100.0, 1) if complete_swipes_cnt > 0 else 0.0
    pct_band_4_8h = round((dur_band_4_8h / complete_swipes_cnt) * 100.0, 1) if complete_swipes_cnt > 0 else 0.0
    pct_band_8_10h = round((dur_band_8_10h / complete_swipes_cnt) * 100.0, 1) if complete_swipes_cnt > 0 else 0.0
    pct_band_over_10h = round((dur_band_over_10h / complete_swipes_cnt) * 100.0, 1) if complete_swipes_cnt > 0 else 0.0

    deviations_bundle = compute_punch_deviations_bu(
        filtered,
        threshold_mins=late_departure_threshold_mins,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Section 5: Repeated Attendance Exceptions Engine
    # ─────────────────────────────────────────────────────────────────────────
    repeated_excp_bundle = compute_repeated_exceptions(
        filtered,
        threshold=exception_threshold,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Legacy Metric Compatibility Bundle (Preserves exact keys for tests)
    # ─────────────────────────────────────────────────────────────────────────
    legacy_bundle = tsa.compute_time_series_metrics(filtered)

    result = {
        "total_records": total_records,
        "unique_employees": unique_employees,
        "recorded_employee_days": recorded_employee_days,
        "attendance_composition_denominator": round(attendance_composition_denom, 1),
        "classified_attendance_denominator": round(q_classified_denom, 1),
        "unclassified_records_count": unclassified_records_count,

        # Section 1: Executive Overview (9 Primary KPIs)
        "kpi_1_emp_hc": unique_employees,
        "kpi_2_attendance_days": recorded_employee_days,
        "kpi_3_present_days": round(q_total_present, 1),
        "kpi_3_present_pct": pct_pres,
        "kpi_4_od_days": round(q_od, 1),
        "kpi_4_od_pct": pct_od,
        "kpi_5_leave_days": round(q_leave, 1),
        "kpi_5_leave_pct": pct_leave,
        "kpi_6_wfh_days": round(q_wfh, 1),
        "kpi_6_wfh_pct": pct_wfh,
        "kpi_7_holiday_days": round(q_hol, 1),
        "kpi_7_holiday_pct": pct_hol,
        "kpi_8_week_off_days": round(q_wo, 1),
        "kpi_8_week_off_pct": pct_wo,
        "kpi_absent_days": round(q_absent, 1),
        "kpi_absent_pct": pct_absent,
        "kpi_unclassified_days": round(q_unclassified, 1),
        "kpi_unclassified_pct": pct_unclassified,
        "unclassified_record_ids": filtered.loc[is_unclassified, "record_id"].astype(str).tolist() if "record_id" in filtered.columns else [],
        "kpi_9_attendance_exceptions_days": excp_days_count,
        "kpi_9_attendance_exceptions_rate_pct": excp_rate_pct,
        "kpi_9_attendance_exceptions_affected_emps": excp_affected_emps,

        # Section 2: Leave Intelligence
        "total_leave_days": round(q_leave, 1),
        "employees_taking_leave": leave_emps,
        "leave_penetration_pct": leave_emp_penetration_pct,
        "total_leave_requests": leave_requests_count,
        "confirmed_leave_requests": confirmed_leave_requests,
        "inferred_leave_requests": inferred_leave_requests,
        "leave_applied_by_emp_cnt": leave_applied_by_emp,
        "leave_applied_by_emp_pct": pct_leave_emp_actor,
        "leave_applied_by_admin_cnt": leave_applied_by_admin,
        "leave_applied_by_admin_pct": pct_leave_admin_actor,
        "leave_prior_cnt": leave_prior_cnt,
        "leave_prior_pct": leave_prior_pct,
        "leave_same_day_cnt": leave_same_day_cnt,
        "leave_same_day_pct": leave_same_day_pct,
        "leave_retro_cnt": leave_retro_cnt,
        "leave_retro_pct": leave_retro_pct,
        "leave_avg_lead_time_days": avg_leave_lead_time,
        "leave_median_lead_time_days": median_leave_lead_time,
        "leave_completed_approvals": leave_completed_approvals,
        "leave_pending_approvals": leave_pending_count,
        "leave_approved_by_mgr_cnt": leave_appr_mgr,
        "leave_approved_by_mgr_pct": leave_pct_mgr,
        "leave_approved_by_admin_cnt": leave_appr_admin,
        "leave_approved_by_admin_pct": leave_pct_admin,
        "leave_approved_by_other_cnt": leave_appr_other,
        "leave_approved_by_other_pct": leave_pct_other,
        "leave_avg_approval_turnaround_days": avg_leave_turnaround,
        "leave_median_approval_turnaround_days": median_leave_turnaround,

        # Section 3: WFH Intelligence
        "total_wfh_days": wfh_monthly_bundle["total_wfh_days"],
        "employees_taking_wfh": wfh_monthly_bundle["employees_taking_wfh"],
        "total_wfh_requests": wfh_requests_count,
        "confirmed_wfh_requests": confirmed_wfh_requests,
        "inferred_wfh_requests": inferred_wfh_requests,
        "wfh_applied_by_emp_cnt": wfh_applied_by_emp,
        "wfh_applied_by_emp_pct": pct_wfh_emp_actor,
        "wfh_applied_by_admin_cnt": wfh_applied_by_admin,
        "wfh_applied_by_admin_pct": pct_wfh_admin_actor,
        "wfh_prior_cnt": wfh_prior_cnt,
        "wfh_prior_pct": wfh_prior_pct,
        "wfh_same_day_cnt": wfh_same_day_cnt,
        "wfh_same_day_pct": wfh_same_day_pct,
        "wfh_retro_cnt": wfh_retro_cnt,
        "wfh_retro_pct": wfh_retro_pct,
        "wfh_avg_lead_time_days": avg_wfh_lead_time,
        "wfh_median_lead_time_days": median_wfh_lead_time,
        "wfh_completed_approvals": wfh_completed_approvals,
        "wfh_approved_by_mgr_cnt": wfh_appr_mgr,
        "wfh_approved_by_mgr_pct": wfh_pct_mgr,
        "wfh_approved_by_admin_cnt": wfh_appr_admin,
        "wfh_approved_by_admin_pct": wfh_pct_admin,
        "wfh_avg_approval_turnaround_days": avg_wfh_turnaround,
        "wfh_median_approval_turnaround_days": median_wfh_turnaround,
        "wfh_employees_exceeding_allowance": wfh_monthly_bundle["employees_exceeding_allowance"],
        "wfh_total_additional_days": wfh_monthly_bundle["total_additional_wfh_days"],
        "wfh_monthly_summary": wfh_monthly_bundle["monthly_summary"],
        "wfh_employee_month_breakdown": wfh_monthly_bundle["employee_month_breakdown"],
        "wfh_partially_observed_months": wfh_monthly_bundle["partially_observed_months"],

        # Section 4: Working Hours & Swipe Intelligence
        "total_physical_days": total_physical_days,
        "complete_swipe_records": complete_swipes_cnt,
        "complete_swipe_pct": complete_swipes_pct,
        "missing_in_punch_count": missing_in_cnt,
        "missing_in_punch_pct": missing_in_pct,
        "missing_out_punch_count": missing_out_cnt,
        "missing_out_punch_pct": missing_out_pct,
        "both_punches_missing_count": both_missing_cnt,
        "both_punches_missing_pct": both_missing_pct,
        "avg_in_time": minutes_to_time_str(avg_in_mins, use_12hr=True),
        "avg_out_time": minutes_to_time_str(avg_out_mins, use_12hr=True),
        "avg_working_hours": hours_to_duration_str(avg_work_hrs),
        "avg_working_hours_decimal": round(avg_work_hrs, 2) if avg_work_hrs else 0.0,
        "duration_under_4h_count": dur_band_under_4h,
        "duration_under_4h_pct": pct_band_under_4h,
        "duration_4_8h_count": dur_band_4_8h,
        "duration_4_8h_pct": pct_band_4_8h,
        "duration_8_10h_count": dur_band_8_10h,
        "duration_8_10h_pct": pct_band_8_10h,
        "duration_over_10h_count": dur_band_over_10h,
        "duration_over_10h_pct": pct_band_over_10h,
        "bu_benchmarks": deviations_bundle["bu_benchmarks"],
        "employee_punch_deviations": deviations_bundle["employee_deviations"],
        "late_arrival_employees_count": deviations_bundle["late_arrival_employees_count"],
        "early_departure_employees_count": deviations_bundle["early_departure_employees_count"],

        # Section 5: Repeated Attendance Exceptions
        "repeated_exception_threshold": exception_threshold,
        "repeated_exception_employees_count": repeated_excp_bundle["total_repeat_employees"],
        "repeated_exception_rate_pct": repeated_excp_bundle["repeat_employee_pct"],
        "repeated_exception_dossiers": repeated_excp_bundle["dossiers"],
    }

    # Overlay all legacy keys
    for k_leg, v_leg in legacy_bundle.items():
        if k_leg not in result:
            result[k_leg] = v_leg

    return result


def _empty_bundle(threshold: int = 3, allowance: float = 3.0) -> Dict[str, Any]:
    """Return empty metrics dictionary when dataset has no matching rows."""
    empty_legacy = tsa._empty_metrics()
    res = {
        "total_records": 0,
        "unique_employees": 0,
        "recorded_employee_days": 0,
        "attendance_composition_denominator": 0.0,
        "classified_attendance_denominator": 0.0,
        "unclassified_records_count": 0,
        "kpi_1_emp_hc": 0,
        "kpi_2_attendance_days": 0,
        "kpi_3_present_days": 0.0,
        "kpi_3_present_pct": 0.0,
        "kpi_4_od_days": 0.0,
        "kpi_4_od_pct": 0.0,
        "kpi_5_leave_days": 0.0,
        "kpi_5_leave_pct": 0.0,
        "kpi_6_wfh_days": 0.0,
        "kpi_6_wfh_pct": 0.0,
        "kpi_7_holiday_days": 0.0,
        "kpi_7_holiday_pct": 0.0,
        "kpi_8_week_off_days": 0.0,
        "kpi_8_week_off_pct": 0.0,
        "kpi_absent_days": 0.0,
        "kpi_absent_pct": 0.0,
        "kpi_unclassified_days": 0.0,
        "kpi_unclassified_pct": 0.0,
        "unclassified_record_ids": [],
        "kpi_9_attendance_exceptions_days": 0,
        "kpi_9_attendance_exceptions_rate_pct": 0.0,
        "kpi_9_attendance_exceptions_affected_emps": 0,
        "total_leave_days": 0.0,
        "employees_taking_leave": 0,
        "leave_penetration_pct": 0.0,
        "total_leave_requests": 0,
        "confirmed_leave_requests": 0,
        "inferred_leave_requests": 0,
        "leave_applied_by_emp_cnt": 0,
        "leave_applied_by_emp_pct": 0.0,
        "leave_applied_by_admin_cnt": 0,
        "leave_applied_by_admin_pct": 0.0,
        "leave_prior_cnt": 0,
        "leave_prior_pct": 0.0,
        "leave_same_day_cnt": 0,
        "leave_same_day_pct": 0.0,
        "leave_retro_cnt": 0,
        "leave_retro_pct": 0.0,
        "leave_avg_lead_time_days": 0.0,
        "leave_median_lead_time_days": 0.0,
        "leave_completed_approvals": 0,
        "leave_pending_approvals": 0,
        "leave_approved_by_mgr_cnt": 0,
        "leave_approved_by_mgr_pct": 0.0,
        "leave_approved_by_admin_cnt": 0,
        "leave_approved_by_admin_pct": 0.0,
        "leave_approved_by_other_cnt": 0,
        "leave_approved_by_other_pct": 0.0,
        "leave_avg_approval_turnaround_days": 0.0,
        "leave_median_approval_turnaround_days": 0.0,
        "total_wfh_days": 0.0,
        "employees_taking_wfh": 0,
        "total_wfh_requests": 0,
        "confirmed_wfh_requests": 0,
        "inferred_wfh_requests": 0,
        "wfh_applied_by_emp_cnt": 0,
        "wfh_applied_by_emp_pct": 0.0,
        "wfh_applied_by_admin_cnt": 0,
        "wfh_applied_by_admin_pct": 0.0,
        "wfh_prior_cnt": 0,
        "wfh_prior_pct": 0.0,
        "wfh_same_day_cnt": 0,
        "wfh_same_day_pct": 0.0,
        "wfh_retro_cnt": 0,
        "wfh_retro_pct": 0.0,
        "wfh_avg_lead_time_days": 0.0,
        "wfh_median_lead_time_days": 0.0,
        "wfh_completed_approvals": 0,
        "wfh_approved_by_mgr_cnt": 0,
        "wfh_approved_by_mgr_pct": 0.0,
        "wfh_approved_by_admin_cnt": 0,
        "wfh_approved_by_admin_pct": 0.0,
        "wfh_avg_approval_turnaround_days": 0.0,
        "wfh_median_approval_turnaround_days": 0.0,
        "wfh_employees_exceeding_allowance": 0,
        "wfh_total_additional_days": 0.0,
        "wfh_monthly_summary": {},
        "wfh_employee_month_breakdown": [],
        "wfh_partially_observed_months": [],
        "total_physical_days": 0,
        "complete_swipe_records": 0,
        "complete_swipe_pct": 0.0,
        "missing_in_punch_count": 0,
        "missing_in_punch_pct": 0.0,
        "missing_out_punch_count": 0,
        "missing_out_punch_pct": 0.0,
        "both_punches_missing_count": 0,
        "both_punches_missing_pct": 0.0,
        "avg_in_time": "-",
        "avg_out_time": "-",
        "avg_working_hours": "-",
        "avg_working_hours_decimal": 0.0,
        "duration_under_4h_count": 0,
        "duration_under_4h_pct": 0.0,
        "duration_4_8h_count": 0,
        "duration_4_8h_pct": 0.0,
        "duration_8_10h_count": 0,
        "duration_8_10h_pct": 0.0,
        "duration_over_10h_count": 0,
        "duration_over_10h_pct": 0.0,
        "bu_benchmarks": {},
        "employee_punch_deviations": [],
        "late_arrival_employees_count": 0,
        "early_departure_employees_count": 0,
        "repeated_exception_threshold": threshold,
        "repeated_exception_employees_count": 0,
        "repeated_exception_rate_pct": 0.0,
        "repeated_exception_dossiers": [],
    }
    for k, v in empty_legacy.items():
        if k not in res:
            res[k] = v
    return res
