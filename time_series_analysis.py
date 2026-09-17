"""
time_series_analysis.py
───────────────────────
Comprehensive analytics engine for Workforce Time Series Analysis.
Calculates compliance rates, exception metrics, swipe statistics,
working hours, and multi-level drilldowns (Business Unit, Department, RM, Employee).
"""

from datetime import date, datetime, time
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from openpyxl.styles import Font, PatternFill, Border


# ════════════════════════════════════════════════════════════════
# Column Aliases
# ════════════════════════════════════════════════════════════════

ALIASES = {
    "employee_number": ["employee number", "emp no", "emp number", "employee id", "emp id", "staff id"],
    "employee_name": ["employee name", "emp name", "name", "employee"],
    "business_unit": ["business unit", "bu", "division"],
    "department": ["department", "dept"],
    "sub_department": ["sub department", "sub dept"],
    "reporting_manager": ["reporting manager", "rm", "manager", "reports to"],
    "date": ["date", "attendance date", "event date"],
    "month": ["month", "attendance month"],
    "in_time": ["in time", "intime", "in", "punch in", "first in"],
    "out_time": ["out time", "outtime", "out", "punch out", "last out"],
    "attendance_type": ["attendance type", "attendancetype", "type", "attendance_type"],
    "status": ["status", "attendance status"],
    "leave_name": ["leave name", "leave type", "leavename"],
    "quantity": ["quantity", "qty", "duration", "total days"],
    "applied_by": ["applied by", "requester", "applicant", "applied_by"],
    "applied_on": ["applied on", "application date", "applied date", "applied_on"],
    "approved_by": ["approved by", "approver", "action taken by", "approved_by"],
    "approved_on": ["approved on", "approval date", "approved date", "approved_on"],
    "approval_status": ["approval status", "request status", "approval_status"],
    "total_hours": ["total hours", "total hrs", "hours", "work hours", "duration_hours"],
}


def find_column(df: pd.DataFrame, canonical_key: str) -> Optional[str]:
    """Find the matching column name in DataFrame using canonical aliases."""
    candidates = ALIASES.get(canonical_key.lower(), [])
    col_map = {str(c).strip().lower(): c for c in df.columns}

    # Direct match
    for cand in candidates:
        if cand in col_map:
            return col_map[cand]

    # Alphanumeric match
    alnum_map = {re.sub(r'[^a-z0-9]', '', str(c).lower()): c for c in df.columns}
    for cand in candidates:
        clean = re.sub(r'[^a-z0-9]', '', cand.lower())
        if clean in alnum_map:
            return alnum_map[clean]

    return None


# ════════════════════════════════════════════════════════════════
# Parsing & Normalization Helpers
# ════════════════════════════════════════════════════════════════

def parse_time_to_minutes(val: Any) -> Optional[float]:
    """Convert time value (str '09:30', '9:30 AM', datetime.time, or Timestamp) to minutes from midnight."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s.upper() in ("NA", "N/A", "#N/A", "NAN", "-", ""):
        return None

    if isinstance(val, time):
        return val.hour * 60 + val.minute + val.second / 60.0

    if isinstance(val, (datetime, pd.Timestamp)):
        return val.hour * 60 + val.minute + val.second / 60.0

    # Try common string formats
    # Check 12-hr with AM/PM
    m12 = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)$', s, re.IGNORECASE)
    if m12:
        h, m = int(m12.group(1)), int(m12.group(2))
        ampm = m12.group(4).upper()
        if ampm == "PM" and h < 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return h * 60 + m

    # Check 24-hr HH:MM or HH:MM:SS
    m24 = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', s)
    if m24:
        h, m = int(m24.group(1)), int(m24.group(2))
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m

    # Try pandas to_datetime fallback
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.notna(dt):
            return dt.hour * 60 + dt.minute + dt.second / 60.0
    except Exception:
        pass

    return None


def minutes_to_time_str(mins: Optional[float], use_12hr: bool = True) -> str:
    """Format minutes from midnight back to time string (e.g. '09:42 AM' or '09:42')."""
    if mins is None or np.isnan(mins):
        return "-"
    total_mins = int(round(mins)) % 1440
    h = total_mins // 60
    m = total_mins % 60

    if use_12hr:
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12:02d}:{m:02d} {ampm}"
    else:
        return f"{h:02d}:{m:02d}"


def hours_to_duration_str(hrs: Optional[float]) -> str:
    """Format decimal hours to 'Xh Ym' (e.g. '8h 35m') or '-'."""
    if hrs is None or np.isnan(hrs) or hrs <= 0:
        return "-"
    total_mins = int(round(hrs * 60))
    h = total_mins // 60
    m = total_mins % 60
    return f"{h}h {m:02d}m"


def parse_date_value(val: Any) -> Optional[date]:
    """Parse date from string, Timestamp, or date."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.upper() in ("NA", "N/A", "#N/A", "NAN", "-", ""):
        return None
    try:
        if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', s):
            dt = pd.to_datetime(s, errors="coerce")
        else:
            dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.notna(dt):
            return dt.date()
    except Exception:
        pass
    return None


# ════════════════════════════════════════════════════════════════
# Data Ingestion and Normalization
# ════════════════════════════════════════════════════════════════

def load_time_series_dataset(file_path: Union[str, Path]) -> pd.DataFrame:
    """
    Read .xlsx, .xls, or .csv dataset while preserving literal 'NA'.
    Normalizes canonical columns and pre-parses dates and minutes.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    ext = p.suffix.lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(p, keep_default_na=False)
    elif ext == ".csv":
        df = pd.read_csv(p, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Expected .xlsx, .xls, or .csv.")

    # Canonical mapping
    canon_cols = {}
    for canon in ALIASES.keys():
        matched = find_column(df, canon)
        if matched:
            canon_cols[canon] = matched

    # Ensure essential attributes exist
    work_df = df.copy()

    # Create normalized helper columns
    # 1. Date & Month
    if "date" in canon_cols:
        work_df["_date"] = work_df[canon_cols["date"]].apply(parse_date_value)
    else:
        work_df["_date"] = None

    if "month" in canon_cols:
        work_df["_month_raw"] = work_df[canon_cols["month"]].astype(str).str.strip()
    elif "date" in canon_cols:
        work_df["_month_raw"] = work_df["_date"].apply(lambda d: d.strftime("%b %Y") if d else "Unknown")
    else:
        work_df["_month_raw"] = "All"

    # Format Month cleanly (e.g. 'Sep 2026')
    def _clean_month(m_val, d_val):
        if m_val and m_val not in ("nan", "None", "", "NA", "NaT"):
            parsed = parse_date_value(m_val)
            if parsed:
                return parsed.strftime("%b %Y")
            if re.match(r'^[A-Za-z]{3}\s*\d{4}', m_val):
                return m_val
        if d_val:
            return d_val.strftime("%b %Y")
        return "Unknown"

    work_df["_month_clean"] = [
        _clean_month(m, d) for m, d in zip(work_df["_month_raw"], work_df["_date"])
    ]

    # 2. Business Unit, Department, RM, Employee
    work_df["_bu"] = work_df[canon_cols["business_unit"]].astype(str).str.strip() if "business_unit" in canon_cols else "General"
    work_df["_dept"] = work_df[canon_cols["department"]].astype(str).str.strip() if "department" in canon_cols else "General"
    work_df["_rm"] = work_df[canon_cols["reporting_manager"]].astype(str).str.strip() if "reporting_manager" in canon_cols else "Unknown"
    work_df["_emp_num"] = work_df[canon_cols["employee_number"]].astype(str).str.strip() if "employee_number" in canon_cols else ""
    work_df["_emp_name"] = work_df[canon_cols["employee_name"]].astype(str).str.strip() if "employee_name" in canon_cols else work_df["_emp_num"]

    # Clean float string representation (e.g. 'FIN101.0' -> 'FIN101')
    work_df["_emp_num"] = work_df["_emp_num"].apply(lambda s: s[:-2] if s.endswith(".0") else s)

    # 3. Attendance Type & Status
    work_df["_att_type"] = work_df[canon_cols["attendance_type"]].astype(str).str.strip() if "attendance_type" in canon_cols else ""
    work_df["_status"] = work_df[canon_cols["status"]].astype(str).str.strip() if "status" in canon_cols else ""
    work_df["_leave_name"] = work_df[canon_cols["leave_name"]].astype(str).str.strip() if "leave_name" in canon_cols else ""

    # 4. Swipes and Working Hours
    work_df["_in_mins"] = work_df[canon_cols["in_time"]].apply(parse_time_to_minutes) if "in_time" in canon_cols else None
    work_df["_out_mins"] = work_df[canon_cols["out_time"]].apply(parse_time_to_minutes) if "out_time" in canon_cols else None

    # Calculate hours difference between Out and In
    def _calc_work_hrs(in_m, out_m, att_t):
        if in_m is None or out_m is None or pd.isna(in_m) or pd.isna(out_m):
            return np.nan
        # "only consider if the Attendance Type is Present and Missing Swipes"
        att_norm = str(att_t).lower()
        if not ("present" in att_norm or "missing swipes" in att_norm or att_norm in ("p", "p(ms)", "ms")):
            return np.nan

        diff_mins = out_m - in_m
        if diff_mins < 0:
            diff_mins += 1440  # handle cross-midnight
        return diff_mins / 60.0

    work_df["_work_hours"] = [
        _calc_work_hrs(i, o, a) for i, o, a in zip(work_df["_in_mins"], work_df["_out_mins"], work_df["_att_type"])
    ]

    # 5. Applied and Approved dates and roles
    work_df["_applied_on"] = work_df[canon_cols["applied_on"]].apply(parse_date_value) if "applied_on" in canon_cols else None
    work_df["_approved_on"] = work_df[canon_cols["approved_on"]].apply(parse_date_value) if "approved_on" in canon_cols else None
    work_df["_applied_by"] = work_df[canon_cols["applied_by"]].astype(str).str.strip() if "applied_by" in canon_cols else ""
    work_df["_approved_by"] = work_df[canon_cols["approved_by"]].astype(str).str.strip() if "approved_by" in canon_cols else ""

    return work_df


# ════════════════════════════════════════════════════════════════
# Core Metrics Engine
# ════════════════════════════════════════════════════════════════

def compute_time_series_metrics(df: pd.DataFrame,
                                business_unit: Optional[str] = None,
                                department: Optional[str] = None,
                                month: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute the 8 primary Time Series Analysis metrics with optional filters.
    """
    filtered = df.copy()

    # Apply filters
    if business_unit and business_unit not in ("All", "All Business Units", ""):
        filtered = filtered[filtered["_bu"].str.lower() == business_unit.strip().lower()]
    if department and department not in ("All", "All Departments", ""):
        filtered = filtered[filtered["_dept"].str.lower() == department.strip().lower()]
    if month and month not in ("All", "All Months", ""):
        filtered = filtered[filtered["_month_clean"].str.lower() == month.strip().lower()]

    total_records = len(filtered)
    unique_employees = filtered["_emp_num"].nunique() if total_records > 0 else 0

    if total_records == 0:
        return _empty_metrics()

    # -------------------------------------------------------------
    # 1. Leave Application Compliance Rate
    # AVG days by which when leave from the leave availed date is applied
    # and % of leave applied by Employee vs Admin
    # -------------------------------------------------------------
    is_leave = (
        filtered["_att_type"].str.contains("leave", case=False, na=False) |
        (filtered["_leave_name"].notna() & ~filtered["_leave_name"].isin(["", "-", "NA", "None"]))
    )
    leave_df = filtered[is_leave].copy()
    valid_leave_app = leave_df[leave_df["_date"].notna() & leave_df["_applied_on"].notna()].copy()

    if len(valid_leave_app) > 0:
        # Days from application to leave availed date:
        # (Date - Applied On) measures advance lead time (e.g. +3 days before leave date).
        # Positive = applied in advance; Negative = applied retrospectively/late.
        days_diff = [(dt - app).days for dt, app in zip(valid_leave_app["_date"], valid_leave_app["_applied_on"])]
        avg_leave_apply_days = float(np.mean(days_diff))
    else:
        avg_leave_apply_days = 0.0

    total_leaves_applied = len(leave_df)
    applied_by_emp_cnt = sum(leave_df["_applied_by"].str.lower() == "employee")
    applied_by_admin_cnt = sum(leave_df["_applied_by"].str.lower() == "admin")

    pct_leave_emp = (applied_by_emp_cnt / total_leaves_applied * 100.0) if total_leaves_applied > 0 else 0.0
    pct_leave_admin = (applied_by_admin_cnt / total_leaves_applied * 100.0) if total_leaves_applied > 0 else 0.0

    # -------------------------------------------------------------
    # 2. Manager Approval Compliance Rate
    # AVG days by which the leave and WFH is approved, and % approval Manager vs Admin
    # -------------------------------------------------------------
    is_wfh = (
        filtered["_att_type"].str.contains("work from home", case=False, na=False) |
        (filtered["_att_type"].str.lower() == "wfh")
    )
    req_df = filtered[is_leave | is_wfh].copy()
    valid_appr = req_df[req_df["_applied_on"].notna() & req_df["_approved_on"].notna()].copy()

    if len(valid_appr) > 0:
        approval_days = [(appr - appl).days for appr, appl in zip(valid_appr["_approved_on"], valid_appr["_applied_on"])]
        avg_approval_days = float(np.mean(approval_days))
    else:
        avg_approval_days = 0.0

    total_approvals = len(req_df)
    appr_mgr_cnt = sum(req_df["_approved_by"].str.lower() == "manager")
    appr_admin_cnt = sum(req_df["_approved_by"].str.lower() == "admin")

    pct_appr_mgr = (appr_mgr_cnt / total_approvals * 100.0) if total_approvals > 0 else 0.0
    pct_appr_admin = (appr_admin_cnt / total_approvals * 100.0) if total_approvals > 0 else 0.0

    # -------------------------------------------------------------
    # 3. Attendance Exception Rate
    # Number of days which Attendance Type is Regularized
    # -------------------------------------------------------------
    is_reg = (
        filtered["_att_type"].str.contains("regulariz", case=False, na=False) |
        filtered["_status"].str.contains(r'\(r\)|ar|pr', case=False, regex=True, na=False)
    )
    regularized_days = int(sum(is_reg))
    reg_rate_pct = (regularized_days / total_records * 100.0) if total_records > 0 else 0.0

    # -------------------------------------------------------------
    # 4. WFH Exception Rate
    # Number of WFH availed above 3 days per employee
    # -------------------------------------------------------------
    wfh_df = filtered[is_wfh].copy()
    wfh_per_emp = wfh_df.groupby("_emp_num").size()
    wfh_excess_days = 0
    wfh_violating_emp_count = 0

    for emp_id, count in wfh_per_emp.items():
        if count > 3:
            wfh_excess_days += (count - 3)
            wfh_violating_emp_count += 1

    total_wfh_days = len(wfh_df)
    wfh_exception_rate_pct = (wfh_excess_days / total_wfh_days * 100.0) if total_wfh_days > 0 else 0.0

    # -------------------------------------------------------------
    # 5. Repeat Attendance Non-Compliance Rate
    # Employees and managers with repeated deviation from above matrix
    # -------------------------------------------------------------
    # Deviation criteria per employee:
    # - regularized_days > 1
    # - wfh_days > 3
    # - late applied leaves > 1
    reg_per_emp = {}
    if is_reg.any():
        reg_per_emp = filtered[is_reg].groupby("_emp_num").size().to_dict()

    wfh_per_emp = {}
    if is_wfh.any():
        wfh_per_emp = filtered[is_wfh].groupby("_emp_num").size().to_dict()

    late_leaves_per_emp = {}
    if len(valid_leave_app) > 0:
        late_mask = [dt < app for dt, app in zip(valid_leave_app["_date"], valid_leave_app["_applied_on"])]
        late_df = valid_leave_app[late_mask]
        if len(late_df) > 0 and "_emp_num" in late_df.columns:
            late_leaves_per_emp = late_df.groupby("_emp_num").size().to_dict()

    all_emps = set(filtered["_emp_num"].unique()) - {"", "nan"}
    repeat_deviant_emps = set()

    for emp in all_emps:
        dev_score = 0
        if reg_per_emp.get(emp, 0) > 1:
            dev_score += 1
        if wfh_per_emp.get(emp, 0) > 3:
            dev_score += 1
        if late_leaves_per_emp.get(emp, 0) > 1:
            dev_score += 1
        if dev_score >= 1:
            repeat_deviant_emps.add(emp)

    repeat_emp_count = len(repeat_deviant_emps)
    repeat_emp_pct = (repeat_emp_count / unique_employees * 100.0) if unique_employees > 0 else 0.0

    # Manager repeat deviation: RMs managing 2+ deviant employees or having avg approval > 3 days
    emp_to_rm = filtered.drop_duplicates(subset=["_emp_num"]).set_index("_emp_num")["_rm"].to_dict()
    rm_deviant_counts: Dict[str, int] = {}
    for d_emp in repeat_deviant_emps:
        rm = emp_to_rm.get(d_emp, "Unknown")
        if rm and rm not in ("Unknown", "-", "NA"):
            rm_deviant_counts[rm] = rm_deviant_counts.get(rm, 0) + 1

    unique_rms = set(filtered["_rm"].unique()) - {"", "nan", "Unknown", "-", "NA"}
    repeat_deviant_rms = {rm for rm, count in rm_deviant_counts.items() if count >= 2}
    repeat_rm_count = len(repeat_deviant_rms)
    repeat_rm_pct = (repeat_rm_count / len(unique_rms) * 100.0) if unique_rms else 0.0

    # -------------------------------------------------------------
    # 6. AVG In Time
    # 7. AVG Out Time
    # 8. Avg Working Hours
    # Only consider if Attendance Type is Present and Missing Swipes
    # -------------------------------------------------------------
    is_pres_ms = (
        filtered["_att_type"].str.contains("present|missing swipes", case=False, na=False) |
        filtered["_status"].str.lower().isin(["p", "p(ms)", "ms"])
    )
    pres_ms_df = filtered[is_pres_ms].copy()

    valid_in = pres_ms_df["_in_mins"].dropna()
    valid_out = pres_ms_df["_out_mins"].dropna()
    valid_work = pres_ms_df["_work_hours"].dropna()

    avg_in_mins = float(valid_in.mean()) if len(valid_in) > 0 else None
    avg_out_mins = float(valid_out.mean()) if len(valid_out) > 0 else None
    avg_work_hrs = float(valid_work.mean()) if len(valid_work) > 0 else None

    return {
        "total_records": total_records,
        "unique_employees": unique_employees,
        # 1. Leave Compliance
        "avg_leave_apply_days": round(avg_leave_apply_days, 1),
        "total_leaves_applied": total_leaves_applied,
        "applied_by_emp_cnt": applied_by_emp_cnt,
        "applied_by_emp_pct": round(pct_leave_emp, 1),
        "applied_by_admin_cnt": applied_by_admin_cnt,
        "applied_by_admin_pct": round(pct_leave_admin, 1),
        # 2. Manager Approval Compliance
        "avg_approval_days": round(avg_approval_days, 1),
        "total_approvals": total_approvals,
        "appr_mgr_cnt": appr_mgr_cnt,
        "appr_mgr_pct": round(pct_appr_mgr, 1),
        "appr_admin_cnt": appr_admin_cnt,
        "appr_admin_pct": round(pct_appr_admin, 1),
        # 3. Attendance Exception
        "regularized_days": regularized_days,
        "reg_rate_pct": round(reg_rate_pct, 1),
        # 4. WFH Exception
        "total_wfh_days": total_wfh_days,
        "wfh_excess_days": wfh_excess_days,
        "wfh_violating_emp_count": wfh_violating_emp_count,
        "wfh_exception_rate_pct": round(wfh_exception_rate_pct, 1),
        # 5. Repeat Attendance Non-Compliance
        "repeat_emp_count": repeat_emp_count,
        "repeat_emp_pct": round(repeat_emp_pct, 1),
        "repeat_rm_count": repeat_rm_count,
        "repeat_rm_pct": round(repeat_rm_pct, 1),
        # 6 & 7 & 8. Swipe & Hours
        "avg_in_time": minutes_to_time_str(avg_in_mins, use_12hr=True),
        "avg_out_time": minutes_to_time_str(avg_out_mins, use_12hr=True),
        "avg_working_hours": hours_to_duration_str(avg_work_hrs),
        "avg_working_hours_decimal": round(avg_work_hrs, 2) if avg_work_hrs else 0.0,
    }


def _empty_metrics() -> Dict[str, Any]:
    """Return default empty metric dictionary."""
    return {
        "total_records": 0, "unique_employees": 0,
        "avg_leave_apply_days": 0.0, "total_leaves_applied": 0,
        "applied_by_emp_cnt": 0, "applied_by_emp_pct": 0.0,
        "applied_by_admin_cnt": 0, "applied_by_admin_pct": 0.0,
        "avg_approval_days": 0.0, "total_approvals": 0,
        "appr_mgr_cnt": 0, "appr_mgr_pct": 0.0,
        "appr_admin_cnt": 0, "appr_admin_pct": 0.0,
        "regularized_days": 0, "reg_rate_pct": 0.0,
        "total_wfh_days": 0, "wfh_excess_days": 0,
        "wfh_violating_emp_count": 0, "wfh_exception_rate_pct": 0.0,
        "repeat_emp_count": 0, "repeat_emp_pct": 0.0,
        "repeat_rm_count": 0, "repeat_rm_pct": 0.0,
        "avg_in_time": "-", "avg_out_time": "-",
        "avg_working_hours": "-", "avg_working_hours_decimal": 0.0,
    }


# ════════════════════════════════════════════════════════════════
# Multi-Level Drilldown Engine
# ════════════════════════════════════════════════════════════════

def compute_level_breakdown(df: pd.DataFrame,
                            level: str,
                            business_unit: Optional[str] = None,
                            department: Optional[str] = None,
                            month: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Compute breakdown table for a specific dimension:
    - 'Business Unit'
    - 'Department'
    - 'Reporting Manager'
    - 'Employee'
    """
    filtered = df.copy()
    if business_unit and business_unit not in ("All", "All Business Units", ""):
        filtered = filtered[filtered["_bu"].str.lower() == business_unit.strip().lower()]
    if department and department not in ("All", "All Departments", ""):
        filtered = filtered[filtered["_dept"].str.lower() == department.strip().lower()]
    if month and month not in ("All", "All Months", ""):
        filtered = filtered[filtered["_month_clean"].str.lower() == month.strip().lower()]

    if len(filtered) == 0:
        return []

    level_key = level.strip().lower()
    if "business unit" in level_key or level_key == "bu":
        group_col = "_bu"
        entity_name_col = "_bu"
    elif "department" in level_key or level_key == "dept":
        group_col = "_dept"
        entity_name_col = "_dept"
    elif "reporting manager" in level_key or level_key in ("rm", "manager"):
        group_col = "_rm"
        entity_name_col = "_rm"
    else:
        # Employee level
        group_col = "_emp_num"
        entity_name_col = "_emp_name"

    results = []
    for entity_val, group in filtered.groupby(group_col, sort=False):
        if pd.isna(entity_val) or str(entity_val).strip() in ("", "nan", "None"):
            continue

        e_name = str(group.iloc[0][entity_name_col]) if entity_name_col in group.columns else str(entity_val)
        m = compute_time_series_metrics(group)

        row = {
            "Entity ID": str(entity_val),
            "Entity Name": e_name,
            "Total Records": m["total_records"],
            "Unique Employees": m["unique_employees"],
            # Leave Compliance
            "Avg Days to Apply Leave": m["avg_leave_apply_days"],
            "Leave Applied % (Emp)": f"{m['applied_by_emp_pct']}%",
            "Leave Applied % (Admin)": f"{m['applied_by_admin_pct']}%",
            # Approval Compliance
            "Avg Approval Days": m["avg_approval_days"],
            "Approval % (Mgr)": f"{m['appr_mgr_pct']}%",
            "Approval % (Admin)": f"{m['appr_admin_pct']}%",
            # Exceptions
            "Regularized Days": m["regularized_days"],
            "Regularization Rate": f"{m['reg_rate_pct']}%",
            "WFH Total Days": m["total_wfh_days"],
            "WFH Exception Days (>3)": m["wfh_excess_days"],
            "Employees with >3 WFH": m["wfh_violating_emp_count"],
            "Repeat Deviant Emps": m["repeat_emp_count"],
            # Swipes & Hours
            "Avg In Time": m["avg_in_time"],
            "Avg Out Time": m["avg_out_time"],
            "Avg Working Hours": m["avg_working_hours"],
        }
        results.append(row)

    # Sort by Total Records descending
    results.sort(key=lambda r: r["Total Records"], reverse=True)
    return results


# ════════════════════════════════════════════════════════════════
# Excel Report Exporter
# ════════════════════════════════════════════════════════════════

def export_time_series_report(df: pd.DataFrame,
                              output_path: Union[str, Path],
                              business_unit: Optional[str] = None,
                              department: Optional[str] = None,
                              month: Optional[str] = None) -> Path:
    """
    Export comprehensive Time Series Analysis workbook with styled tabs:
    1. Summary KPIs
    2. Business Unit Level
    3. Department Level
    4. Reporting Manager Level
    5. Employee Level
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    summary_metrics = compute_time_series_metrics(df, business_unit, department, month)
    bu_data = compute_level_breakdown(df, "Business Unit", business_unit, department, month)
    dept_data = compute_level_breakdown(df, "Department", business_unit, department, month)
    rm_data = compute_level_breakdown(df, "Reporting Manager", business_unit, department, month)
    emp_data = compute_level_breakdown(df, "Employee", business_unit, department, month)

    df_summary = pd.DataFrame([
        {"Metric Category": "Scope", "Metric Name": "Total Records Analyzed", "Value": summary_metrics["total_records"]},
        {"Metric Category": "Scope", "Metric Name": "Unique Employees", "Value": summary_metrics["unique_employees"]},
        {"Metric Category": "Leave Compliance", "Metric Name": "Avg Days to Apply Leave (From Availed Date)", "Value": f"{summary_metrics['avg_leave_apply_days']} days"},
        {"Metric Category": "Leave Compliance", "Metric Name": "% Leaves Applied by Employee", "Value": f"{summary_metrics['applied_by_emp_pct']}%"},
        {"Metric Category": "Leave Compliance", "Metric Name": "% Leaves Applied by Admin", "Value": f"{summary_metrics['applied_by_admin_pct']}%"},
        {"Metric Category": "Approval Compliance", "Metric Name": "Avg Days to Approve (Leave & WFH)", "Value": f"{summary_metrics['avg_approval_days']} days"},
        {"Metric Category": "Approval Compliance", "Metric Name": "% Approvals by Manager", "Value": f"{summary_metrics['appr_mgr_pct']}%"},
        {"Metric Category": "Approval Compliance", "Metric Name": "% Approvals by Admin", "Value": f"{summary_metrics['appr_admin_pct']}%"},
        {"Metric Category": "Attendance Exception", "Metric Name": "Regularized Attendance Days", "Value": summary_metrics["regularized_days"]},
        {"Metric Category": "Attendance Exception", "Metric Name": "Attendance Regularization Rate", "Value": f"{summary_metrics['reg_rate_pct']}%"},
        {"Metric Category": "WFH Exception", "Metric Name": "Total WFH Days Availed", "Value": summary_metrics["total_wfh_days"]},
        {"Metric Category": "WFH Exception", "Metric Name": "WFH Excess Days (>3 days/emp)", "Value": summary_metrics["wfh_excess_days"]},
        {"Metric Category": "WFH Exception", "Metric Name": "Employees Exceeding 3 WFH Days", "Value": summary_metrics["wfh_violating_emp_count"]},
        {"Metric Category": "Repeat Non-Compliance", "Metric Name": "Employees with Repeat Deviations", "Value": f"{summary_metrics['repeat_emp_count']} ({summary_metrics['repeat_emp_pct']}%)"},
        {"Metric Category": "Repeat Non-Compliance", "Metric Name": "Managers with Repeat Deviations", "Value": f"{summary_metrics['repeat_rm_count']} ({summary_metrics['repeat_rm_pct']}%)"},
        {"Metric Category": "Swipes & Hours", "Metric Name": "AVG In Time (Present & Missing Swipes)", "Value": summary_metrics["avg_in_time"]},
        {"Metric Category": "Swipes & Hours", "Metric Name": "AVG Out Time (Present & Missing Swipes)", "Value": summary_metrics["avg_out_time"]},
        {"Metric Category": "Swipes & Hours", "Metric Name": "AVG Working Hours", "Value": summary_metrics["avg_working_hours"]},
    ])

    font_header = Font(name="Calibri", size=10, bold=True)
    font_data = Font(name="Calibri", size=10, bold=False)
    fill_header = PatternFill(start_color="00FF99", end_color="00FF99", fill_type="solid")
    no_border = Border()

    with pd.ExcelWriter(out_p, engine="openpyxl") as writer:
        df_summary.to_excel(writer, index=False, sheet_name="KPI Summary")
        if bu_data:
            pd.DataFrame(bu_data).to_excel(writer, index=False, sheet_name="Business Unit")
        if dept_data:
            pd.DataFrame(dept_data).to_excel(writer, index=False, sheet_name="Department")
        if rm_data:
            pd.DataFrame(rm_data).to_excel(writer, index=False, sheet_name="Reporting Manager")
        if emp_data:
            pd.DataFrame(emp_data).to_excel(writer, index=False, sheet_name="Employee Breakdown")

        for s_name in writer.sheets:
            ws = writer.sheets[s_name]
            for row in ws.iter_rows():
                for cell in row:
                    cell.border = no_border
                    if cell.row == 1:
                        cell.font = font_header
                        cell.fill = fill_header
                    else:
                        cell.font = font_data

    return out_p
