"""
metrics.py
──────────
Workforce intelligence core metrics, employee-day facts aggregation,
approval cycle diagnostics, and multi-dimensional breakdown analysis.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from workforce_intelligence.policy_config import (
    APPROVAL_STATE_MAP,
    ATTENDANCE_EXCEPTION_MAP,
)


def normalize_approval_state(status: Any) -> str:
    """Normalize raw Approval Status into canonical approval state."""
    if status is None or pd.isna(status):
        return "UNKNOWN"
    st = str(status).strip().lower()
    return APPROVAL_STATE_MAP.get(st, "UNKNOWN")


def build_employee_day_facts(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construct the Employee-Day analytical fact layer.
    Collapses multiple intra-day events into a single employee-day record.

    Calculates:
    - Daily presence indicators (present, leave, wfh, absent, missing swipes, etc.)
    - Attendance exception determination (absent, missing swipe, regularized)
    - Eligibility flag (pure week-off / holiday = ineligible; active work events = eligible)
    - Daily quantity totals and data-quality warnings
    """
    if len(df) == 0:
        cols = [
            "Employee Number", "Employee Name", "Business Unit", "Department",
            "Sub Department", "Location", "Reporting Manager", "Date",
            "record_count", "daily_total_quantity",
            "has_present", "has_leave", "has_wfh", "has_absent",
            "has_missing_swipe", "has_regularization", "has_week_off", "has_holiday",
            "is_attendance_exception", "attendance_exception_types",
            "is_eligible_attendance_day", "dq_daily_quantity_exceeds_one"
        ]
        return pd.DataFrame(columns=cols)

    # Filter rows with valid Employee Number and Date
    valid_mask = df["Employee Number"].notna() & df["Date"].notna()
    work_df = df[valid_mask].copy()

    if len(work_df) == 0:
        return pd.DataFrame()

    # Normalization helper for categories
    work_df["_cat"] = work_df["attendance_category"].astype(str).str.strip() if "attendance_category" in work_df.columns else ""

    records = []
    for (emp, dt), group in work_df.groupby(["Employee Number", "Date"], sort=False):
        first_row = group.iloc[0]

        cats = set(group["_cat"])
        status_vals = set(group["Status"].dropna().astype(str).str.upper()) if "Status" in group.columns else set()

        has_pres = "Present" in cats or "P" in status_vals or "WOW" in status_vals or "WOH" in status_vals
        has_lv = "Leave" in cats or any(s in ("CL", "SL", "PL", "EL", "ML", "CLSL", "L") for s in status_vals)
        has_wfh = "Work From Home" in cats or "WFH" in status_vals
        has_abs = "Absent" in cats or "A" in status_vals or "AB" in status_vals
        has_ms = "Missing Swipes" in cats or any("MS" in s for s in status_vals)
        has_reg = "Attendance Regularized" in cats or any("(R)" in s or s in ("AR", "PR") for s in status_vals)
        has_wo = "Week Off" in cats or "WO" in status_vals or "W/O" in status_vals
        has_hol = "Holiday" in cats or "H" in status_vals or "PH" in status_vals
        has_od = "On Duty" in cats or "OD" in status_vals

        # Exception classification
        exception_types = []
        if has_abs:
            exception_types.append("ABSENT")
        if has_ms:
            exception_types.append("MISSING_SWIPE")
        if has_reg:
            exception_types.append("ATTENDANCE_REGULARIZED")

        is_exception = len(exception_types) > 0
        exception_type_str = ", ".join(exception_types) if exception_types else "NONE"

        # Eligibility determination:
        # Pure week off / holiday -> NOT eligible
        # Any active event (present, leave, wfh, absent, missing swipes, regularization, on duty) -> ELIGIBLE
        active_events = has_pres or has_lv or has_wfh or has_abs or has_ms or has_reg or has_od
        is_eligible = bool(active_events)

        # Quantity and DQ flags
        quantities = group["Quantity"].dropna() if "Quantity" in group.columns else pd.Series([], dtype=float)
        qty_sum = round(float(quantities.sum()), 4) if not quantities.empty else None

        has_qty_exceed = bool(
            (group["dq_daily_quantity_exceeds_one"].any() if "dq_daily_quantity_exceeds_one" in group.columns else False)
            or (qty_sum is not None and qty_sum > 1.000001)
        )
        has_missing_emp = bool(group["dq_missing_employee"].any() if "dq_missing_employee" in group.columns else False)
        has_missing_date = bool(group["dq_missing_date"].any() if "dq_missing_date" in group.columns else False)
        has_invalid_date = bool(group["dq_invalid_date"].any() if "dq_invalid_date" in group.columns else False)

        has_warning = bool(
            (group["dq_exact_duplicate"].any() if "dq_exact_duplicate" in group.columns else False)
            or (group["dq_missing_quantity"].any() if "dq_missing_quantity" in group.columns else False)
            or (group["dq_unknown_attendance"].any() if "dq_unknown_attendance" in group.columns else False)
        )

        # Determine employee-day data quality status & evaluability
        is_critical = has_qty_exceed or has_missing_emp or has_missing_date or has_invalid_date
        if is_critical:
            quality_status = "CRITICAL"
            is_evaluable = False
            exclusion_reasons = []
            if has_qty_exceed:
                exclusion_reasons.append("DAILY_QUANTITY_EXCEEDS_ONE")
            if has_missing_emp:
                exclusion_reasons.append("MISSING_EMPLOYEE")
            if has_missing_date:
                exclusion_reasons.append("MISSING_DATE")
            if has_invalid_date:
                exclusion_reasons.append("INVALID_DATE")
            exclusion_reason_str = ", ".join(exclusion_reasons) if exclusion_reasons else "CRITICAL_DATA_QUALITY"
        elif has_warning:
            quality_status = "WARNING"
            is_evaluable = True
            exclusion_reason_str = "NONE"
        else:
            quality_status = "VALID"
            is_evaluable = True
            exclusion_reason_str = "NONE"

        records.append({
            "Employee Number": emp,
            "Employee Name": first_row.get("Employee Name"),
            "Business Unit": first_row.get("Business Unit"),
            "Department": first_row.get("Department"),
            "Sub Department": first_row.get("Sub Department"),
            "Location": first_row.get("Location"),
            "Reporting Manager": first_row.get("Reporting Manager"),
            "Date": dt,
            "record_count": len(group),
            "daily_total_quantity": qty_sum,
            "has_present": has_pres,
            "has_leave": has_lv,
            "has_wfh": has_wfh,
            "has_absent": has_abs,
            "has_missing_swipe": has_ms,
            "has_regularization": has_reg,
            "has_week_off": has_wo,
            "has_holiday": has_hol,
            "is_attendance_exception": is_exception,
            "attendance_exception_types": exception_type_str,
            "is_eligible_attendance_day": is_eligible,
            "dq_daily_quantity_exceeds_one": has_qty_exceed,
            "employee_day_quality_status": quality_status,
            "is_metric_evaluable": is_evaluable,
            "metric_exclusion_reason": exclusion_reason_str,
        })

    return pd.DataFrame(records)


def _safe_rate(numerator: int, denominator: int) -> Optional[float]:
    """Calculate percentage rate safely, returning None when denominator is 0."""
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def _make_metric_contract(total_applicable: int, excluded_dq: int, numerator: int) -> Dict[str, Any]:
    """Helper to produce consistent metric dictionary contract."""
    evaluable = total_applicable - excluded_dq
    return {
        "total_applicable": total_applicable,
        "evaluable": evaluable,
        "excluded_data_quality": excluded_dq,
        "data_quality_uncertain_count": excluded_dq,
        "numerator": numerator,
        "denominator": evaluable,
        "rate": _safe_rate(numerator, evaluable),
    }


def calculate_core_metrics(
    evaluated_df: pd.DataFrame,
    evaluated_requests: Optional[List[Dict[str, Any]]] = None,
    employee_day_facts: Optional[pd.DataFrame] = None,
    analysis_as_of_date: Optional[Union[date, datetime]] = None,
) -> Dict[str, Any]:
    """
    Compute structured, transparent compliance metrics and operational indicators.
    All rates return explicit numerator, denominator, evaluable, and rate fields.
    Critical data-quality issues are excluded from leadership denominators.
    """
    if employee_day_facts is None:
        employee_day_facts = build_employee_day_facts(evaluated_df)

    # Reconstructed leave requests DataFrame
    req_df = pd.DataFrame(evaluated_requests) if evaluated_requests else pd.DataFrame()

    # 1. Post-Policy Leave Application Compliance
    post_leave_tot = 0
    post_leave_dq = 0
    post_leave_num = 0

    pl_post_tot = 0
    pl_post_dq = 0
    pl_post_num = 0

    non_pl_post_tot = 0
    non_pl_post_dq = 0
    non_pl_post_num = 0

    # 2. Pre-Policy Leave Benchmark
    pre_leave_tot = 0
    pre_leave_dq = 0
    pre_leave_num = 0

    if not req_df.empty:
        # Post-policy requests
        post_reqs = req_df[req_df["policy_period"] == "POST_POLICY"]
        post_leave_tot = len(post_reqs)
        post_leave_dq = int((post_reqs["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
        post_leave_num = int((post_reqs["policy_compliant"] == True).sum())

        # PL Post-policy
        pl_post_reqs = post_reqs[post_reqs["is_pl"] == True]
        pl_post_tot = len(pl_post_reqs)
        pl_post_dq = int((pl_post_reqs["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
        pl_post_num = int((pl_post_reqs["policy_compliant"] == True).sum())

        # Non-PL Post-policy
        non_pl_post_reqs = post_reqs[post_reqs["is_pl"] == False]
        non_pl_post_tot = len(non_pl_post_reqs)
        non_pl_post_dq = int((non_pl_post_reqs["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
        non_pl_post_num = int((non_pl_post_reqs["policy_compliant"] == True).sum())

        # Pre-policy benchmark requests
        pre_reqs = req_df[req_df["policy_period"] == "PRE_POLICY"]
        pre_leave_tot = len(pre_reqs)
        pre_leave_dq = int((pre_reqs["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
        pre_leave_num = int((pre_reqs["benchmark_compliant"] == True).sum())

    # 3. WFH Application Compliance (evaluated at row/event level)
    wfh_rows = evaluated_df[evaluated_df["policy_event_type"] == "WFH"].copy()

    # Post-policy WFH
    post_wfh = wfh_rows[wfh_rows["policy_period"] == "POST_POLICY"]
    post_wfh_tot = len(post_wfh)
    post_wfh_dq = int((post_wfh["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
    post_wfh_num = int((post_wfh["policy_compliant"] == True).sum())

    # Pre-policy WFH benchmark
    pre_wfh = wfh_rows[wfh_rows["policy_period"] == "PRE_POLICY"]
    pre_wfh_tot = len(pre_wfh)
    pre_wfh_dq = int((pre_wfh["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
    pre_wfh_num = int((pre_wfh["benchmark_compliant"] == True).sum())

    # 4. Attendance Exception Rate (Governed vs. Raw)
    eligible_days_raw = int(employee_day_facts["is_eligible_attendance_day"].sum()) if not employee_day_facts.empty else 0
    evaluable_mask = (
        (employee_day_facts["is_eligible_attendance_day"] == True) & (employee_day_facts["is_metric_evaluable"] == True)
    ) if not employee_day_facts.empty else pd.Series(dtype=bool)
    evaluable_days = int(evaluable_mask.sum()) if not employee_day_facts.empty else 0
    dq_excluded_days = eligible_days_raw - evaluable_days

    # Governed attendance exception days: only evaluable eligible days with an exception
    gov_exception_mask = evaluable_mask & (employee_day_facts["is_attendance_exception"] == True)
    gov_exception_days = int(gov_exception_mask.sum()) if not employee_day_facts.empty else 0

    # Raw attendance exception days: all eligible days with an exception
    raw_exception_mask = (
        (employee_day_facts["is_eligible_attendance_day"] == True) & (employee_day_facts["is_attendance_exception"] == True)
    ) if not employee_day_facts.empty else pd.Series(dtype=bool)
    raw_exception_days = int(raw_exception_mask.sum()) if not employee_day_facts.empty else 0

    # 5. Approval Cycle Diagnostics
    df_eval = evaluated_df.copy()
    df_eval["approval_state"] = df_eval["Approval Status"].apply(normalize_approval_state) if "Approval Status" in df_eval.columns else "UNKNOWN"

    # Reference date for pending age
    if analysis_as_of_date is None:
        if "Date" in df_eval.columns and not df_eval["Date"].dropna().empty:
            analysis_as_of_date = pd.to_datetime(df_eval["Date"]).dropna().max().date()
        else:
            analysis_as_of_date = date.today()
    elif isinstance(analysis_as_of_date, datetime):
        analysis_as_of_date = analysis_as_of_date.date()

    # Approved Turnaround
    approved_records = df_eval[df_eval["approval_state"] == "APPROVED"]
    valid_turnarounds = approved_records["approval_turnaround_days"].dropna().astype(float) if "approval_turnaround_days" in approved_records.columns else pd.Series([], dtype=float)

    avg_turnaround: Optional[float] = round(float(valid_turnarounds.mean()), 2) if not valid_turnarounds.empty else None
    med_turnaround: Optional[float] = round(float(valid_turnarounds.median()), 2) if not valid_turnarounds.empty else None
    approval_count = len(valid_turnarounds)

    # Pending Approvals
    pending_records = df_eval[df_eval["approval_state"] == "PENDING"]
    pending_count = len(pending_records)
    pending_ages = []

    if pending_count > 0 and "Applied On" in pending_records.columns:
        for _, r in pending_records.iterrows():
            app_on = r.get("Applied On")
            if pd.notna(app_on):
                app_date = pd.to_datetime(app_on).date()
                age = (analysis_as_of_date - app_date).days
                if age >= 0:
                    pending_ages.append(age)

    avg_pending_age: Optional[float] = round(float(np.mean(pending_ages)), 2) if pending_ages else None
    max_pending_age: Optional[int] = int(np.max(pending_ages)) if pending_ages else None

    # 6. Data Quality Uncertain Policy Records
    dq_uncertain_records = int((df_eval["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum())
    dq_uncertain_requests = int((req_df["compliance_status"] == "DATA_QUALITY_UNCERTAIN").sum()) if not req_df.empty else 0

    return {
        # Post-Policy Leave Application Compliance
        "overall_leave_application_compliance": _make_metric_contract(
            total_applicable=post_leave_tot,
            excluded_dq=post_leave_dq,
            numerator=post_leave_num,
        ),
        "pl_application_compliance": _make_metric_contract(
            total_applicable=pl_post_tot,
            excluded_dq=pl_post_dq,
            numerator=pl_post_num,
        ),
        "non_pl_application_compliance": _make_metric_contract(
            total_applicable=non_pl_post_tot,
            excluded_dq=non_pl_post_dq,
            numerator=non_pl_post_num,
        ),

        # Pre-Policy Leave Benchmark
        "pre_policy_leave_benchmark": _make_metric_contract(
            total_applicable=pre_leave_tot,
            excluded_dq=pre_leave_dq,
            numerator=pre_leave_num,
        ),

        # WFH Application Compliance
        "wfh_application_compliance": _make_metric_contract(
            total_applicable=post_wfh_tot,
            excluded_dq=post_wfh_dq,
            numerator=post_wfh_num,
        ),
        "pre_policy_wfh_benchmark": _make_metric_contract(
            total_applicable=pre_wfh_tot,
            excluded_dq=pre_wfh_dq,
            numerator=pre_wfh_num,
        ),

        # Governed Attendance Exception Rate (Primary Leadership KPI)
        "attendance_exception_rate": {
            "total_applicable": eligible_days_raw,
            "eligible_employee_days_raw": eligible_days_raw,
            "evaluable": evaluable_days,
            "evaluable_employee_days": evaluable_days,
            "excluded_data_quality": dq_excluded_days,
            "data_quality_excluded_employee_days": dq_excluded_days,
            "numerator": gov_exception_days,
            "attendance_exception_days": gov_exception_days,
            "denominator": evaluable_days,
            "eligible_employee_days": evaluable_days,  # backward compatibility alias
            "rate": _safe_rate(gov_exception_days, evaluable_days),
            # Diagnostic raw metrics
            "raw_attendance_exception_days": raw_exception_days,
            "raw_attendance_exception_rate": _safe_rate(raw_exception_days, eligible_days_raw),
        },

        # Approval Cycle Diagnostics
        "approval_turnaround": {
            "approval_count": approval_count,
            "average_approval_turnaround_days": avg_turnaround,
            "median_approval_turnaround_days": med_turnaround,
            "pending_approval_count": pending_count,
            "average_pending_approval_age_days": avg_pending_age,
            "max_pending_approval_age_days": max_pending_age,
        },

        # Data Quality Uncertainty Summary
        "data_quality_uncertainty": {
            "uncertain_policy_rows": dq_uncertain_records,
            "uncertain_leave_requests": dq_uncertain_requests,
            "data_quality_excluded_employee_days": dq_excluded_days,
        },
    }


def calculate_compliance_breakdown(
    evaluated_df: pd.DataFrame,
    group_by: List[str],
    policy_period_filter: Optional[str] = None,
) -> pd.DataFrame:
    """
    Calculate compliance metric breakdowns along specified dimensions
    (e.g., Business Unit, Department, Location, Reporting Manager).
    """
    df = evaluated_df.copy()
    if policy_period_filter:
        df = df[df["policy_period"] == policy_period_filter]

    valid_group_cols = [c for c in group_by if c in df.columns]
    if not valid_group_cols:
        raise ValueError(f"None of the specified grouping columns {group_by} exist in the DataFrame.")

    # Only include leave and WFH rows for application compliance
    app_df = df[df["policy_event_type"].isin(["PL", "NON_PL_LEAVE", "WFH"])].copy()

    records = []
    for group_vals, grp in app_df.groupby(valid_group_cols, sort=False):
        if not isinstance(group_vals, tuple):
            group_vals = (group_vals,)

        grp_dict = {col: val for col, val in zip(valid_group_cols, group_vals)}

        # Evaluable records (excluding DATA_QUALITY_UNCERTAIN)
        total_app = len(grp)
        evaluable = grp[grp["compliance_status"] != "DATA_QUALITY_UNCERTAIN"]
        total_eval = len(evaluable)
        excluded_dq = total_app - total_eval

        # Check pre vs post compliance
        comp_count = int(
            (evaluable["policy_compliant"] == True).sum()
            if "POST_POLICY" in evaluable["policy_period"].values
            else (evaluable["benchmark_compliant"] == True).sum()
        )

        grp_dict["total_applicable"] = total_app
        grp_dict["evaluable_count"] = total_eval
        grp_dict["excluded_data_quality"] = excluded_dq
        grp_dict["compliant_count"] = comp_count
        grp_dict["compliance_rate"] = _safe_rate(comp_count, total_eval)

        records.append(grp_dict)

    return pd.DataFrame(records)
