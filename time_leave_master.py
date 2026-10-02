"""
time_leave_master.py
────────────────────
Core transformation and reconciliation engine for Time and Leave Master.

Reconciles Daily Performance Report data against multi-month Leave Applications
(Active and Inactive) and WFH Applications. Expands multi-day requests, matches
date-wise entries, applies role-based rules for Applied By and Approved By,
and checks quantity limits (max 1.0 per employee per date).
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import re
import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════════
# Column Aliases and Lookup Helpers
# ════════════════════════════════════════════════════════════════

ALIASES = {
    # Employee identifiers
    "employee number": [
        "employee number", "employee id", "emp no", "emp id", 
        "employee code", "emp code", "empid", "empno"
    ],
    "employee name": [
        "employee name", "emp name", "name", "employee", "employeename"
    ],
    # Dates
    "date": ["date", "attendance date", "event date"],
    "from date": ["from date", "from", "start date", "start"],
    "to date": ["to date", "to", "end date", "end"],
    # Duration
    "duration": ["total duration", "duration", "total days", "days", "no of days", "quantity", "qty"],
    # Requester / Applied By
    "requester": ["requester", "requested by", "applied by", "applicant", "applied_by"],
    # Applied On
    "applied on": ["requested on", "applied on", "application date", "applied date", "created on", "request date"],
    # Approver / Action Taken By
    "action taken by": [
        "last action taken by", "action taken by", "approved by", "approver", 
        "action by", "manager", "last action by"
    ],
    # Approved On
    "approved on": [
        "last action taken on", "action taken on", "approved on", "action on", 
        "approval date", "approved date", "action date"
    ],
    # Status / Type
    "status": [
        "status", "attendance status", "att status", "request status", "approval status", "leave status",
        "application status", "wfh status", "od status", "action status"
    ],
    "attendance type": ["attendance type", "attendancetype", "type"],
    "leave name": ["leave name", "leave type", "leavename"],
    # Employee Master enrichment fields
    "reporting manager": [
        "reporting manager", "reporting manager name", "manager name", "reports to", "rm name"
    ],
    "reporting manager email": [
        "reporting manager email", "rm mail id", "rm email", "manager email", "rm mail"
    ],
    "email": [
        "work email", "email", "mail id", "employee email", "official email", "email id"
    ],
    "last working day": [
        "last working day", "last working date", "lwd", "exit date", "relieving date"
    ],
    "location": [
        "location", "work location", "branch", "city", "base location"
    ],
}


def find_column(df: pd.DataFrame, alias_category: str) -> Optional[str]:
    """Find matching column name in DataFrame for a canonical alias category."""
    candidates = ALIASES.get(alias_category.lower(), [alias_category.lower()])
    col_lookup = {str(c).strip().lower(): c for c in df.columns}

    # Direct match
    for cand in candidates:
        if cand in col_lookup:
            return col_lookup[cand]

    # Normalized alphanumeric match
    col_alnum = {re.sub(r'[^a-z0-9]', '', str(c).lower()): c for c in df.columns}
    for cand in candidates:
        clean_cand = re.sub(r'[^a-z0-9]', '', cand.lower())
        if clean_cand in col_alnum:
            return col_alnum[clean_cand]

    return None


def clean_emp_str(val: Any) -> str:
    """Normalize employee number or text for reliable matching."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.strip()


def parse_date(val: Any) -> Optional[date]:
    """Parse various date representations to datetime.date object."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date()
    if isinstance(val, date):
        return val

    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none", "-", "", "na", "n/a", "#n/a"):
        return None

    try:
        # Check if year is first (YYYY-MM-DD or YYYY/MM/DD)
        if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', s):
            dt = pd.to_datetime(s, errors="coerce")
        else:
            dt = pd.to_datetime(s, dayfirst=True, errors="coerce")

        if pd.notna(dt):
            return dt.date()
    except Exception:
        pass

    return None


def format_date_str(val: Any) -> Any:
    """Format date for Excel output in dd-mmm-yy format (e.g. 01-Sep-26), preserving 'NA' and empty values."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if s.upper() in ("NA", "N/A", "#N/A", "NOT APPLICABLE"):
        return s
    d = parse_date(val)
    if d:
        return d.strftime("%d-%b-%y")
    return s


def to_excel_date(val: Any) -> Any:
    """Convert value to python date object if possible, preserving 'NA' and empty values."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.upper() in ("NA", "N/A", "#N/A", "NONE", "NULL", "-", "NAN"):
        return s
    for fmt in (
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d",
        "%d-%b-%y", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.notna(dt):
            return dt.date()
    except Exception:
        pass
    return s


# ════════════════════════════════════════════════════════════════
# File Loader & Multi-File Aggregator
# ════════════════════════════════════════════════════════════════

def read_single_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """Read .xlsx, .xls, or .csv into a DataFrame while preserving literal 'NA'."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    ext = p.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(p, keep_default_na=False)
    elif ext == ".csv":
        return pd.read_csv(p, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Expected .xlsx, .xls, or .csv.")


def load_and_combine_files(file_paths: List[Union[str, Path]]) -> pd.DataFrame:
    """
    Read multiple files for a section and combine into a single DataFrame.
    Drops duplicate rows if identical records exist across monthly exports.
    """
    if not file_paths:
        return pd.DataFrame()

    dfs = []
    for fp in file_paths:
        df = read_single_file(fp)
        if not df.empty:
            dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)
    # Deduplicate exact duplicate rows across months
    combined = combined.drop_duplicates().reset_index(drop=True)
    return combined


# ════════════════════════════════════════════════════════════════
# Application Logic: Applied By and Approved By
# ════════════════════════════════════════════════════════════════

ADMIN_USERS = {"arjun s", "e janani sri", "janani sri e", "janani sri"}
ADMIN_APPROVERS = ADMIN_USERS  # alias for backwards-compatibility


def compute_applied_by(
    requester_name: Any,
    employee_name: Any,
    leave_name: str = "",
    requested_on: str = "",
    action_taken_on: str = ""
) -> str:
    """
    Applied By Logic:
    Admin users are Arjun S and E Janani Sri.
    If the leave or WFH applied by Admin and if it is not for themself, consider that the application is applied by Admin,
    else applied by Employee.
    If leave_name is Garden Leave, always Admin.
    If requested_on and action_taken_on are identical (instant admin application/approval), consider Admin.
    If requester is blank, default to 'Employee'.
    """
    ln = str(leave_name or "").strip().lower()
    if "garden" in ln:
        return "Admin"

    req_str = str(requested_on or "").strip()
    act_str = str(action_taken_on or "").strip()
    has_time = (":" in req_str or "T" in req_str)

    req = clean_emp_str(requester_name).lower()
    emp = clean_emp_str(employee_name).lower()

    if req:
        clean_r = re.sub(r'[^a-z0-9]', '', req)
        clean_e = re.sub(r'[^a-z0-9]', '', emp)
        if clean_r and clean_r == clean_e:
            # If self-application but identical high-precision timestamp (instant admin approval), tag as Admin
            if has_time and req_str and act_str and req_str == act_str:
                return "Admin"
            return "Employee"

        is_admin = any(admin in req or clean_r == re.sub(r'[^a-z0-9]', '', admin) for admin in ADMIN_USERS)
        if is_admin:
            return "Admin"
        return "Admin"

    # If requester not provided, check identical timestamps
    if req_str and act_str and req_str == act_str and req_str.upper() not in ("", "NA", "NONE"):
        return "Admin"

    return "Employee"


def compute_approved_by(action_taken_by: Any, reporting_manager: Any = "", is_admin_applied: bool = False) -> str:
    """
    Approved By Logic:
    If the leave is approved by Name matching with the name under Reporting Manager column -> 'Manager'.
    Else if the approved by is Arjun S or E Janani Sri (or if admin applied) -> 'Admin'.
    Approved By should NEVER come as 'Employee', it must always be 'Manager' or 'Admin'.
    If action_taken_by is empty/unknown:
      If is_admin_applied or reporting_manager is Admin -> 'Admin'.
      Else -> 'Manager'.
    """
    act = clean_emp_str(action_taken_by).lower()
    rm = clean_emp_str(reporting_manager).lower()

    if not act:
        if is_admin_applied:
            return "Admin"
        if rm and any(admin in rm for admin in ADMIN_USERS):
            return "Admin"
        return "Manager"

    clean_act = re.sub(r'[^a-z0-9]', '', act)
    clean_rm = re.sub(r'[^a-z0-9]', '', rm)

    # 1. Match against Reporting Manager -> Manager
    if clean_rm and (clean_act == clean_rm or clean_rm in clean_act or clean_act in clean_rm):
        return "Manager"

    # 2. Check against admin approvers -> Admin
    for admin in ADMIN_USERS:
        clean_adm = re.sub(r'[^a-z0-9]', '', admin)
        if clean_adm and (clean_act == clean_adm or admin in act):
            return "Admin"

    if is_admin_applied:
        return "Admin"

    # 3. Default to Manager (never Employee)
    return "Manager"


def get_leave_status_code(leave_name: str, fallback: str = "CL/SL") -> str:
    """Maps leave type name to its correct status abbreviation."""
    name_clean = str(leave_name or "").strip()
    nl = name_clean.lower()
    if not nl or nl == "-":
        return fallback
    if "casual" in nl and "sick" in nl:
        return "CL/SL"
    if "casual" in nl:
        return "CL"
    if "sick" in nl:
        return "SL"
    if "earned" in nl:
        return "EL"
    if "privilege" in nl:
        return "PL"
    if "annual" in nl:
        return "AL"
    if "maternity" in nl:
        return "ML"
    if "paternity" in nl:
        return "PT"
    if "compensatory" in nl or "comp" in nl:
        return "CO"
    if "bereavement" in nl:
        return "BL"
    if "wedding" in nl:
        return "WL"
    if "marriage" in nl:
        return "ML"
    if "garden" in nl:
        return "GL"
    if "wellness" in nl:
        return "WL"
    if "happiness" in nl:
        return "HL"
    if "loss of pay" in nl or "unpaid" in nl or "without pay" in nl or "lwp" in nl:
        return "LWP"
    if "floating" in nl or "optional" in nl:
        return "FL"
    if re.match(r'^[A-Z]{1,4}(?:/[A-Z]{1,4})?$', name_clean):
        return name_clean
    words = [w for w in re.split(r'[^a-zA-Z]', name_clean) if w and w.lower() != "leave"]
    if words:
        abbr = "".join(w[0].upper() for w in words[:3])
        if abbr:
            return abbr
    return fallback


# ════════════════════════════════════════════════════════════════
# Application Expansion (Date Splitting)
# ════════════════════════════════════════════════════════════════

def expand_application_records(
    df_apps: pd.DataFrame, app_type: str = "leave", emp_rm_map: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """
    Splits multi-day applications where duration > 1 into individual date records.

    Returns a list of dicts:
    {
        'emp_num': normalized employee number,
        'emp_name': normalized employee name,
        'date': datetime.date,
        'duration': float,
        'applied_by': 'Employee' | 'Admin',
        'applied_on': str (YYYY-MM-DD or formatted),
        'approved_by': 'Admin' | 'Manager',
        'approved_on': str,
        'leave_name': str,
        'app_type': 'leave' | 'wfh',
        'raw_row': dict
    }
    """
    if df_apps.empty:
        return []

    col_emp_num = find_column(df_apps, "employee number")
    col_emp_name = find_column(df_apps, "employee name")
    col_from_date = find_column(df_apps, "from date")
    col_to_date = find_column(df_apps, "to date")
    col_duration = find_column(df_apps, "duration")
    col_requester = find_column(df_apps, "requester")
    col_applied_on = find_column(df_apps, "applied on")
    col_action_by = find_column(df_apps, "action taken by")
    col_approved_on = find_column(df_apps, "approved on")
    col_leave_name = find_column(df_apps, "leave name")
    col_status = find_column(df_apps, "status")
    col_rm = find_column(df_apps, "reporting manager") or find_column(df_apps, "manager")

    expanded_records = []

    for _, row in df_apps.iterrows():
        emp_num = clean_emp_str(row.get(col_emp_num)) if col_emp_num else ""
        emp_name = clean_emp_str(row.get(col_emp_name)) if col_emp_name else ""
        req_name = clean_emp_str(row.get(col_requester)) if col_requester else ""
        action_by = clean_emp_str(row.get(col_action_by)) if col_action_by else ""

        # Retrieve reporting manager for matching
        rm_val = ""
        if col_rm and pd.notna(row.get(col_rm)):
            rm_val = clean_emp_str(row.get(col_rm))
        elif emp_rm_map and emp_num in emp_rm_map:
            rm_val = emp_rm_map.get(emp_num, "")

        leave_name_val = clean_emp_str(row.get(col_leave_name)) if col_leave_name else ""
        status_val = clean_emp_str(row.get(col_status)) if col_status else ""
        applied_on_raw = row.get(col_applied_on) if col_applied_on else ""
        approved_on_raw = row.get(col_approved_on) if col_approved_on else ""

        applied_by_val = compute_applied_by(
            req_name, emp_name,
            leave_name=leave_name_val,
            requested_on=str(applied_on_raw or ""),
            action_taken_on=str(approved_on_raw or "")
        )
        applied_on_val = format_date_str(applied_on_raw)

        # Strictly ignore any Cancelled, Rejected, Revoked, or Withdrawn applications
        # Such requests must never be brought to the final report or unmatched applications
        st_lower = status_val.lower()
        if any(term in st_lower for term in ["cancel", "reject", "revok", "withdraw"]) or status_val in ["2", "3", "4", "5"]:
            continue

        is_invalid_status = False
        for c in df_apps.columns:
            c_low = str(c).strip().lower()
            if any(k in c_low for k in ["status", "cancel", "state"]):
                val_s = str(row.get(c) or "").strip().lower()
                if any(term in val_s for term in ["cancel", "reject", "revok", "withdraw"]):
                    is_invalid_status = True
                    break
        if is_invalid_status:
            continue

        # Check approval status: only if approved, populate approved_by and approved_on
        if col_status and str(status_val).strip():
            is_approved = (str(status_val).strip().lower() == "approved")
        else:
            # If no status column in file, treat as approved if approver/action_by exists
            is_approved = bool(action_by and str(action_by).strip().upper() not in ("NA", "N/A", ""))
            if is_approved and not status_val:
                status_val = "Approved"

        if is_approved:
            approved_by_val = compute_approved_by(action_by, rm_val, is_admin_applied=(applied_by_val == "Admin"))
            approved_on_val = format_date_str(approved_on_raw)
            if not approved_on_val or approved_on_val.upper() in ("NA", "N/A", ""):
                approved_on_val = applied_on_val if (applied_on_val and applied_on_val.upper() not in ("NA", "N/A", "")) else "NA"
        else:
            approved_by_val = "NA"
            approved_on_val = "NA"

        # Dates
        from_dt = parse_date(row.get(col_from_date)) if col_from_date else None
        to_dt = parse_date(row.get(col_to_date)) if col_to_date else None

        if is_approved and (not approved_on_val or approved_on_val == "NA"):
            approved_on_val = format_date_str(from_dt) if from_dt else "NA"

        # Duration
        dur_val = row.get(col_duration) if col_duration else None
        try:
            total_dur = float(dur_val) if pd.notna(dur_val) else 1.0
        except (ValueError, TypeError):
            total_dur = 1.0

        if not from_dt:
            # If from_dt missing, check to_dt
            from_dt = to_dt
        if not to_dt:
            to_dt = from_dt

        if not from_dt:
            continue

        # If from_dt > to_dt, swap
        if from_dt > to_dt:
            from_dt, to_dt = to_dt, from_dt

        # Check if single half day or half day in leave name or session
        col_sess = find_column(df_apps, "session") or ""
        sess_val = str(row.get(col_sess) or "").lower() if col_sess else ""
        is_half_day = (total_dur <= 0.5) or ("half" in str(leave_name_val).lower()) or ("half" in sess_val)
        day_duration = 0.5 if is_half_day else 1.0

        if is_half_day and from_dt == to_dt:
            expanded_records.append({
                "emp_num": emp_num,
                "emp_name": emp_name,
                "date": from_dt,
                "duration": 0.5,
                "applied_by": applied_by_val,
                "applied_on": applied_on_val,
                "approved_by": approved_by_val,
                "approved_on": approved_on_val,
                "leave_name": leave_name_val,
                "status": status_val,
                "app_type": app_type,
            })
            continue

        # Multi-day or single full day expansion
        # Generate all calendar days from from_dt to to_dt
        dt_range = pd.date_range(from_dt, to_dt, freq="D")
        for dt_val in dt_range:
            day_dt = dt_val.date()
            expanded_records.append({
                "emp_num": emp_num,
                "emp_name": emp_name,
                "date": day_dt,
                "duration": day_duration,
                "applied_by": applied_by_val,
                "applied_on": applied_on_val,
                "approved_by": approved_by_val,
                "approved_on": approved_on_val,
                "leave_name": leave_name_val,
                "status": status_val,
                "app_type": app_type,
            })

    return expanded_records


# ════════════════════════════════════════════════════════════════
# Reconciliation Engine
# ════════════════════════════════════════════════════════════════

def reconcile_time_and_leave(
    perf_files: List[Union[str, Path]],
    leave_active_files: Optional[List[Union[str, Path]]] = None,
    leave_inactive_files: Optional[List[Union[str, Path]]] = None,
    wfh_files: Optional[List[Union[str, Path]]] = None,
    output_path: Optional[Union[str, Path]] = None,
    employee_master_files: Optional[List[Union[str, Path]]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """
    Reconciles Daily Performance Report files with Leave (Active + Inactive)
    and WFH applications, updating Applied By, Applied On, Approved By, and Approved On.

    Enforces quantity validation: no employee should have > 1 quantity on any date.
    Reports real-time progress based on actual volume of uploaded data.
    """
    def notify(ratio: float, msg: str):
        if progress_callback:
            progress_callback(min(1.0, max(0.0, ratio)), msg)

    notify(0.01, "Initializing data sources...")

    # Normalize inputs
    leave_active_files = leave_active_files or []
    leave_inactive_files = leave_inactive_files or []
    wfh_files = wfh_files or []
    emp_files_list = employee_master_files or []

    # 1. Load files with real-time progress tracking
    total_files = len(perf_files) + len(leave_active_files) + len(leave_inactive_files) + len(wfh_files) + len(emp_files_list)
    files_loaded = 0

    def load_group(files: List[Union[str, Path]], label: str) -> pd.DataFrame:
        nonlocal files_loaded
        if not files:
            return pd.DataFrame()
        dfs = []
        for fp in files:
            files_loaded += 1
            p = Path(fp)
            ratio = 0.02 + 0.13 * (files_loaded / max(1, total_files))
            notify(ratio, f"Loading {label} ({files_loaded}/{total_files}): {p.name}...")
            df = read_single_file(p)
            if not df.empty:
                dfs.append(df)
        if not dfs:
            return pd.DataFrame()
        combined = pd.concat(dfs, ignore_index=True)
        return combined.drop_duplicates().reset_index(drop=True)

    df_perf = load_group(perf_files, "Daily Performance Report")
    if df_perf.empty:
        raise ValueError("Daily Performance Report is empty or no files provided.")

    df_leave_active = load_group(leave_active_files, "Active Leave Applications")
    df_leave_inactive = load_group(leave_inactive_files, "Inactive Leave Applications")
    df_wfh = load_group(wfh_files, "WFH Applications")
    df_emp_master = load_group(emp_files_list, "Employee Master")

    total_perf_rows = len(df_perf)
    notify(0.16, f"Loaded {total_perf_rows:,} daily records across {len(perf_files)} performance file(s)...")

    # Build Employee Master lookup dictionaries if master provided
    rm_map: Dict[str, str] = {}
    rm_email_map: Dict[str, str] = {}
    email_map: Dict[str, str] = {}
    lwd_map: Dict[str, Any] = {}
    loc_map: Dict[str, str] = {}

    if not df_emp_master.empty:
        col_m_emp = find_column(df_emp_master, "employee number") or "Employee Number"
        col_m_rm = find_column(df_emp_master, "reporting manager")
        col_m_rm_mail = find_column(df_emp_master, "reporting manager email") or find_column(df_emp_master, "rm mail")
        col_m_mail = find_column(df_emp_master, "email") or find_column(df_emp_master, "work email")
        col_m_lwd = find_column(df_emp_master, "last working day") or find_column(df_emp_master, "lwd")
        col_m_loc = find_column(df_emp_master, "location")

        if col_m_emp in df_emp_master.columns:
            df_m_clean = df_emp_master.drop_duplicates(subset=[col_m_emp])
            if col_m_rm:
                rm_map = dict(zip(df_m_clean[col_m_emp].astype(str).str.strip(), df_m_clean[col_m_rm].astype(str).str.strip()))
            if col_m_rm_mail:
                rm_email_map = dict(zip(df_m_clean[col_m_emp].astype(str).str.strip(), df_m_clean[col_m_rm_mail].astype(str).str.strip()))
            if col_m_mail:
                email_map = dict(zip(df_m_clean[col_m_emp].astype(str).str.strip(), df_m_clean[col_m_mail].astype(str).str.strip()))
            if col_m_lwd:
                lwd_map = dict(zip(df_m_clean[col_m_emp].astype(str).str.strip(), df_m_clean[col_m_lwd]))
            if col_m_loc:
                loc_map = dict(zip(df_m_clean[col_m_emp].astype(str).str.strip(), df_m_clean[col_m_loc].astype(str).str.strip()))

    # 2. Identify Daily Performance Columns
    col_p_emp_num = find_column(df_perf, "employee number")
    col_p_emp_name = find_column(df_perf, "employee name")
    col_p_date = find_column(df_perf, "date")
    col_p_quantity = find_column(df_perf, "duration")  # quantity/duration
    col_p_status = find_column(df_perf, "status")
    col_p_att_type = find_column(df_perf, "attendance type")
    col_p_leave_name = find_column(df_perf, "leave name")

    if not col_p_date:
        raise ValueError("Daily Performance Report is missing 'Date' column.")

    # Populate Reporting Manager and Location from master if missing in df_perf
    if rm_map and col_p_emp_num and col_p_emp_num in df_perf.columns:
        if "Reporting Manager" not in df_perf.columns:
            df_perf["Reporting Manager"] = df_perf[col_p_emp_num].astype(str).str.strip().map(rm_map).fillna("")
        else:
            df_perf["Reporting Manager"] = df_perf["Reporting Manager"].replace("", pd.NA).fillna(
                df_perf[col_p_emp_num].astype(str).str.strip().map(rm_map)
            ).fillna("")

    if loc_map and col_p_emp_num and col_p_emp_num in df_perf.columns:
        if "Location" not in df_perf.columns:
            df_perf["Location"] = df_perf[col_p_emp_num].astype(str).str.strip().map(loc_map).fillna("")
        else:
            df_perf["Location"] = df_perf["Location"].replace("", pd.NA).fillna(
                df_perf[col_p_emp_num].astype(str).str.strip().map(loc_map)
            ).fillna("")

    # Identify status column in Daily Performance Report to match WFH Request Status / Leave Status
    target_status_col = None
    if "Approval Status" in df_perf.columns:
        target_status_col = "Approval Status"
    elif "Request Status" in df_perf.columns:
        target_status_col = "Request Status"
    else:
        target_status_col = "Approval Status"
        df_perf[target_status_col] = "NA"

    # Ensure required update columns exist in df_perf with object dtype, defaulting to "NA"
    update_cols = ["Applied By", "Applied On", "Approved By", "Approved On", target_status_col]
    for col in update_cols:
        if col not in df_perf.columns:
            df_perf[col] = "NA"
        else:
            df_perf[col] = df_perf[col].astype(object)
            # If the column already exists in df_perf, preserve existing values, but any empty or NaN cells default to "NA"
            df_perf[col] = df_perf[col].apply(lambda v: "NA" if (pd.isna(v) or str(v).strip() == "") else v)

    # 3. Expand Applications into Date-wise records
    total_raw_leaves = len(df_leave_active) + len(df_leave_inactive)
    notify(0.18, f"Expanding {total_raw_leaves:,} leave applications across date ranges...")
    leave_records = []
    if not df_leave_active.empty:
        leave_records.extend(expand_application_records(df_leave_active, app_type="leave", emp_rm_map=rm_map))
    if not df_leave_inactive.empty:
        leave_records.extend(expand_application_records(df_leave_inactive, app_type="leave", emp_rm_map=rm_map))

    notify(0.22, f"Expanding {len(df_wfh):,} WFH applications across date ranges...")
    wfh_records = []
    if not df_wfh.empty:
        wfh_records.extend(expand_application_records(df_wfh, app_type="wfh", emp_rm_map=rm_map))

    notify(0.25, f"Indexed {len(leave_records):,} leave and {len(wfh_records):,} WFH daily applications...")

    # Index application records by (emp_id, date) and (emp_name_clean, date)
    # Using a list per key to handle multiple applications (e.g. half days)
    leave_by_emp_dt: Dict[Tuple[str, date], List[Dict[str, Any]]] = {}
    leave_by_name_dt: Dict[Tuple[str, date], List[Dict[str, Any]]] = {}

    for rec in leave_records:
        dt = rec["date"]
        if rec["emp_num"]:
            leave_by_emp_dt.setdefault((rec["emp_num"], dt), []).append(rec)
        if rec["emp_name"]:
            name_clean = rec["emp_name"].lower()
            leave_by_name_dt.setdefault((name_clean, dt), []).append(rec)

    wfh_by_emp_dt: Dict[Tuple[str, date], List[Dict[str, Any]]] = {}
    wfh_by_name_dt: Dict[Tuple[str, date], List[Dict[str, Any]]] = {}

    for rec in wfh_records:
        dt = rec["date"]
        if rec["emp_num"]:
            wfh_by_emp_dt.setdefault((rec["emp_num"], dt), []).append(rec)
        if rec["emp_name"]:
            name_clean = rec["emp_name"].lower()
            wfh_by_name_dt.setdefault((name_clean, dt), []).append(rec)

    # 4. Check Daily Performance Employee Quantity Constraint
    notify(0.28, f"Validating daily quantities across {total_perf_rows:,} records...")
    # "There should not be any situation for an employee has more than 1 quantity for any date."
    quantity_violations: List[Dict[str, Any]] = []
    parsed_dates = []
    parsed_quantities = []

    for idx, row in df_perf.iterrows():
        p_dt = parse_date(row.get(col_p_date))
        parsed_dates.append(p_dt)
        q_val = row.get(col_p_quantity) if col_p_quantity else 1.0
        try:
            q_flt = float(q_val) if pd.notna(q_val) else 1.0
        except (ValueError, TypeError):
            q_flt = 1.0
        parsed_quantities.append(q_flt)

    df_perf["_parsed_date"] = parsed_dates
    df_perf["_parsed_quantity"] = parsed_quantities

    # Filter out records where Date is after Last Working Day
    has_lwd_col = any(c in df_perf.columns for c in ["Last Working Day", "LWD", "Last Working Date", "Relieving Date", "Exit Date"])
    if col_p_emp_num and (lwd_map or has_lwd_col):
        def is_after_lwd(r):
            p_dt = r.get("_parsed_date")
            if not p_dt:
                return False
            eno = clean_emp_str(r.get(col_p_emp_num))
            lwd_raw = (lwd_map.get(eno) if lwd_map else None) or r.get("Last Working Day") or r.get("LWD") or r.get("Last Working Date")
            if not lwd_raw or pd.isna(lwd_raw) or str(lwd_raw).strip().lower() in ("nan", "nat", "none", "na", "-", "#n/a"):
                return False
            l_dt = parse_date(lwd_raw)
            if l_dt and p_dt > l_dt:
                return True
            return False

        valid_perf_mask = ~df_perf.apply(is_after_lwd, axis=1)
        df_perf = df_perf[valid_perf_mask].reset_index(drop=True)
        total_perf_rows = len(df_perf)

    # Split composite colon status rows (e.g. 'CL/SL:A') into two line items of 0.5 quantity each
    if col_p_status and col_p_status in df_perf.columns:
        has_colon = df_perf[col_p_status].astype(str).str.contains(":")
        if has_colon.any():
            split_perf_rows = []
            for _, r in df_perf.iterrows():
                st_val = str(r.get(col_p_status) or "").strip()
                if ":" in st_val:
                    p1, p2 = [p.strip() for p in st_val.split(":", 1)]
                    # Part 1
                    r1 = r.to_dict()
                    r1[col_p_status] = p1
                    if col_p_quantity:
                        r1[col_p_quantity] = 0.5
                    r1["_parsed_quantity"] = 0.5
                    if p1 in ("P", "P(MS)", "MS"):
                        if col_p_att_type: r1[col_p_att_type] = "Present" if p1 == "P" else "Missing Swipes"
                        if col_p_leave_name: r1[col_p_leave_name] = "-"
                    elif p1 == "WFH":
                        if col_p_att_type: r1[col_p_att_type] = "Work From Home"
                        if col_p_leave_name: r1[col_p_leave_name] = "-"
                    elif p1 == "A":
                        if col_p_att_type: r1[col_p_att_type] = "Absent"
                        if col_p_leave_name: r1[col_p_leave_name] = "-"
                    else:
                        if col_p_att_type: r1[col_p_att_type] = "Leave"
                        r1[col_p_status] = get_leave_status_code(r1.get(col_p_leave_name, p1))
                    
                    # Part 2
                    r2 = r.to_dict()
                    r2[col_p_status] = p2
                    if col_p_quantity:
                        r2[col_p_quantity] = 0.5
                    r2["_parsed_quantity"] = 0.5
                    if p2 == "A":
                        if col_p_att_type: r2[col_p_att_type] = "Absent"
                        if col_p_leave_name: r2[col_p_leave_name] = "-"
                        r2["Applied By"] = "NA"
                        r2["Applied On"] = "NA"
                        r2["Approved By"] = "NA"
                        r2["Approved On"] = "NA"
                        if target_status_col: r2[target_status_col] = "NA"
                    elif p2 in ("P", "P(MS)", "MS"):
                        if col_p_att_type: r2[col_p_att_type] = "Present" if p2 == "P" else "Missing Swipes"
                        if col_p_leave_name: r2[col_p_leave_name] = "-"
                        r2["Applied By"] = "NA"
                        r2["Applied On"] = "NA"
                        r2["Approved By"] = "NA"
                        r2["Approved On"] = "NA"
                        if target_status_col: r2[target_status_col] = "NA"
                    elif p2 == "WFH":
                        if col_p_att_type: r2[col_p_att_type] = "Work From Home"
                        if col_p_leave_name: r2[col_p_leave_name] = "-"
                    else:
                        if col_p_att_type: r2[col_p_att_type] = "Leave"
                        r2[col_p_status] = get_leave_status_code(r2.get(col_p_leave_name, p2))

                    split_perf_rows.extend([r1, r2])
                else:
                    split_perf_rows.append(r.to_dict())
            df_perf = pd.DataFrame(split_perf_rows)
            total_perf_rows = len(df_perf)

    # Group by (Employee, Date) to sum quantity
    emp_col_for_grp = col_p_emp_num if col_p_emp_num else col_p_emp_name
    if emp_col_for_grp:
        valid_grp = df_perf[df_perf["_parsed_date"].notna()].copy()
        grp_sums = valid_grp.groupby([emp_col_for_grp, "_parsed_date"])["_parsed_quantity"].sum()
        for (emp_key, dt_key), total_qty in grp_sums.items():
            if total_qty > 1.001:  # small float tolerance
                emp_display_name = ""
                if col_p_emp_name:
                    matching = valid_grp[(valid_grp[emp_col_for_grp] == emp_key) & (valid_grp["_parsed_date"] == dt_key)]
                    if not matching.empty:
                        emp_display_name = str(matching.iloc[0].get(col_p_emp_name, ""))
                quantity_violations.append({
                    "employee": str(emp_key),
                    "employee_name": emp_display_name,
                    "date": dt_key.strftime("%Y-%m-%d"),
                    "total_quantity": round(float(total_qty), 2),
                })

    # 5. Match and Update Daily Performance Rows with Realtime Progress
    matched_leave_count = 0
    matched_wfh_count = 0

    # Determine update frequency based on row volume so UI gets smooth, high-resolution updates
    update_freq = max(1, min(100, total_perf_rows // 50))
    notify(0.30, f"Reconciling 0 / {total_perf_rows:,} records (0%)...")

    # Track consumed application records for 1-to-1 matching (especially for half-days)
    consumed_rec_ids: Set[int] = set()

    def find_match(emp_id: str, emp_name: str, p_dt_val: date, event_type: str, leave_type_pref: str = "") -> Optional[Dict[str, Any]]:
        pool = []
        if event_type == "leave":
            if emp_id and (emp_id, p_dt_val) in leave_by_emp_dt:
                pool.extend(leave_by_emp_dt[(emp_id, p_dt_val)])
            elif emp_name and (emp_name.lower(), p_dt_val) in leave_by_name_dt:
                pool.extend(leave_by_name_dt[(emp_name.lower(), p_dt_val)])
        elif event_type == "wfh":
            if emp_id and (emp_id, p_dt_val) in wfh_by_emp_dt:
                pool.extend(wfh_by_emp_dt[(emp_id, p_dt_val)])
            elif emp_name and (emp_name.lower(), p_dt_val) in wfh_by_name_dt:
                pool.extend(wfh_by_name_dt[(emp_name.lower(), p_dt_val)])
        else:
            # Check leave first, then wfh
            if emp_id and (emp_id, p_dt_val) in leave_by_emp_dt:
                pool.extend(leave_by_emp_dt[(emp_id, p_dt_val)])
            elif emp_name and (emp_name.lower(), p_dt_val) in leave_by_name_dt:
                pool.extend(leave_by_name_dt[(emp_name.lower(), p_dt_val)])
            if not pool:
                if emp_id and (emp_id, p_dt_val) in wfh_by_emp_dt:
                    pool.extend(wfh_by_emp_dt[(emp_id, p_dt_val)])
                elif emp_name and (emp_name.lower(), p_dt_val) in wfh_by_name_dt:
                    pool.extend(wfh_by_name_dt[(emp_name.lower(), p_dt_val)])

        # Pick first unconsumed record
        for candidate in pool:
            cand_id = id(candidate)
            if cand_id not in consumed_rec_ids:
                # If specific leave type preferred, check if match
                if leave_type_pref and candidate.get("leave_name"):
                    if leave_type_pref.lower() in candidate["leave_name"].lower() or candidate["leave_name"].lower() in leave_type_pref.lower():
                        consumed_rec_ids.add(cand_id)
                        return candidate
                else:
                    consumed_rec_ids.add(cand_id)
                    return candidate

        # Fallback to any matching candidate even if reused
        return pool[0] if pool else None

    for idx in range(total_perf_rows):
        p_dt = df_perf.at[idx, "_parsed_date"]
        if not p_dt:
            continue

        emp_id = clean_emp_str(df_perf.at[idx, col_p_emp_num]) if col_p_emp_num else ""
        emp_name = clean_emp_str(df_perf.at[idx, col_p_emp_name]) if col_p_emp_name else ""
        att_type = str(df_perf.at[idx, col_p_att_type] or "").strip().lower() if col_p_att_type else ""
        status = str(df_perf.at[idx, col_p_status] or "").strip().lower() if col_p_status else ""
        lname = str(df_perf.at[idx, col_p_leave_name] or "").strip() if col_p_leave_name else ""

        # Determine target category:
        # WFH application data is merged ONLY if Attendance Type is Work From Home.
        # Leave application data is merged ONLY if Attendance Type is Leave.
        is_wfh = ("work from home" in att_type or att_type == "wfh")
        is_leave = ("leave" in att_type)

        matched_rec = None
        if is_wfh:
            matched_rec = find_match(emp_id, emp_name, p_dt, event_type="wfh")
            if matched_rec:
                matched_wfh_count += 1
        elif is_leave:
            matched_rec = find_match(emp_id, emp_name, p_dt, event_type="leave", leave_type_pref=lname)
            if matched_rec:
                matched_leave_count += 1

        if matched_rec:
            st = str(matched_rec.get("status") or "").strip().lower()
            is_rec_approved = (st == "approved")
            df_perf.at[idx, "Applied By"] = matched_rec["applied_by"] if matched_rec.get("applied_by") else "NA"
            df_perf.at[idx, "Applied On"] = matched_rec["applied_on"] if matched_rec.get("applied_on") else "NA"
            if is_rec_approved:
                df_perf.at[idx, "Approved By"] = matched_rec["approved_by"] if matched_rec.get("approved_by") else "Manager"
                appr_date = matched_rec.get("approved_on") or matched_rec.get("applied_on") or format_date_str(p_dt)
                df_perf.at[idx, "Approved On"] = appr_date if appr_date else "NA"
            else:
                df_perf.at[idx, "Approved By"] = "NA"
                df_perf.at[idx, "Approved On"] = "NA"

            if target_status_col and matched_rec.get("status"):
                df_perf.at[idx, target_status_col] = matched_rec["status"]

            # Map leave status code if currently CLSL or generic
            if is_leave and col_p_status and col_p_status in df_perf.columns:
                cur_st = str(df_perf.at[idx, col_p_status] or "").strip()
                if cur_st.upper() in ("CLSL", "LEAVE", ""):
                    df_perf.at[idx, col_p_status] = get_leave_status_code(matched_rec.get("leave_name") or lname)

            if col_p_quantity and col_p_quantity in df_perf.columns:
                rec_dur = matched_rec.get("duration", 1.0)
                if rec_dur <= 0.5 or "half" in str(lname).lower():
                    df_perf.at[idx, col_p_quantity] = 0.5
                else:
                    df_perf.at[idx, col_p_quantity] = 1.0

        # Report realtime progress based on processed volume
        if (idx + 1) % update_freq == 0 or idx == total_perf_rows - 1:
            rows_done = idx + 1
            prog_ratio = 0.30 + 0.55 * (rows_done / total_perf_rows)
            pct_int = int((rows_done / total_perf_rows) * 100)
            notify(
                prog_ratio,
                f"Reconciling: {rows_done:,} / {total_perf_rows:,} rows ({pct_int}%) • {matched_leave_count:,} leave, {matched_wfh_count:,} WFH matched"
            )

    # 5.1 Identify Unmatched Applications (Applications with no matching performance row)
    perf_att_by_emp_dt: Dict[Tuple[str, date], str] = {}
    perf_att_by_name_dt: Dict[Tuple[str, date], str] = {}
    for idx in range(total_perf_rows):
        p_dt = df_perf.at[idx, "_parsed_date"]
        if p_dt:
            e_num = clean_emp_str(df_perf.at[idx, col_p_emp_num]) if col_p_emp_num else ""
            e_name = clean_emp_str(df_perf.at[idx, col_p_emp_name]) if col_p_emp_name else ""
            att_t = str(df_perf.at[idx, col_p_att_type] or "").strip() if col_p_att_type else ""
            if e_num:
                perf_att_by_emp_dt[(e_num, p_dt)] = att_t
            if e_name:
                perf_att_by_name_dt[(e_name.lower(), p_dt)] = att_t

    unmatched_applications: List[Dict[str, Any]] = []
    for rec in leave_records:
        if id(rec) not in consumed_rec_ids:
            dt = rec["date"]
            emp_id = rec.get("emp_num", "")
            emp_name = rec.get("emp_name", "")
            reason = "Date not present for employee in Daily Performance Report"
            if emp_id and (emp_id, dt) in perf_att_by_emp_dt:
                att_found = perf_att_by_emp_dt[(emp_id, dt)]
                reason = f"Attendance Type in Daily Performance is '{att_found}', not 'Leave'"
            elif emp_name and (emp_name.lower(), dt) in perf_att_by_name_dt:
                att_found = perf_att_by_name_dt[(emp_name.lower(), dt)]
                reason = f"Attendance Type in Daily Performance is '{att_found}', not 'Leave'"

            unmatched_applications.append({
                "Application Type": "Leave",
                "Employee Number": emp_id,
                "Employee Name": emp_name,
                "Date": dt.strftime("%d-%b-%y") if isinstance(dt, (date, datetime)) else str(dt),
                "Duration": rec.get("duration", 1.0),
                "Leave / Request Name": rec.get("leave_name", ""),
                "Status": rec.get("status", ""),
                "Reason / Issue": reason,
            })

    for rec in wfh_records:
        if id(rec) not in consumed_rec_ids:
            dt = rec["date"]
            emp_id = rec.get("emp_num", "")
            emp_name = rec.get("emp_name", "")
            reason = "Date not present for employee in Daily Performance Report"
            if emp_id and (emp_id, dt) in perf_att_by_emp_dt:
                att_found = perf_att_by_emp_dt[(emp_id, dt)]
                reason = f"Attendance Type in Daily Performance is '{att_found}', not 'Work From Home'"
            elif emp_name and (emp_name.lower(), dt) in perf_att_by_name_dt:
                att_found = perf_att_by_name_dt[(emp_name.lower(), dt)]
                reason = f"Attendance Type in Daily Performance is '{att_found}', not 'Work From Home'"

            unmatched_applications.append({
                "Application Type": "Work From Home",
                "Employee Number": emp_id,
                "Employee Name": emp_name,
                "Date": dt.strftime("%d-%b-%y") if isinstance(dt, (date, datetime)) else str(dt),
                "Duration": rec.get("duration", 1.0),
                "Leave / Request Name": "WFH",
                "Status": rec.get("status", ""),
                "Reason / Issue": reason,
            })

    # Format date columns in dd-mmm-yy format (e.g. 01-Sep-26)
    notify(0.87, f"Formatting {total_perf_rows:,} records into dd-mmm-yy date format...")
    if col_p_date and col_p_date in df_perf.columns:
        df_perf[col_p_date] = df_perf[col_p_date].apply(lambda v: format_date_str(v) if pd.notna(v) and str(v).strip() != "" else v)

    for d_col in ["Applied On", "Approved On", "LWD", "Last Working Day", "Month"]:
        if d_col in df_perf.columns:
            df_perf[d_col] = df_perf[d_col].apply(lambda v: format_date_str(v) if pd.notna(v) and str(v).strip() != "" else v)

    # Deduplicate LWD vs Last Working Day into a single canonical 'Last Working Day' column
    if "LWD" in df_perf.columns:
        if "Last Working Day" in df_perf.columns:
            df_perf["Last Working Day"] = df_perf["Last Working Day"].replace("", pd.NA).fillna(df_perf["LWD"]).fillna("")
            df_perf = df_perf.drop(columns=["LWD"])
        else:
            df_perf = df_perf.rename(columns={"LWD": "Last Working Day"})
    elif lwd_map and col_p_emp_num in df_perf.columns:
        if "Last Working Day" not in df_perf.columns:
            df_perf["Last Working Day"] = df_perf[col_p_emp_num].astype(str).str.strip().map(lwd_map).apply(format_date_str).fillna("")
        else:
            df_perf["Last Working Day"] = df_perf["Last Working Day"].replace("", pd.NA).fillna(
                df_perf[col_p_emp_num].astype(str).str.strip().map(lwd_map).apply(format_date_str)
            ).fillna("")

    # Ensure consistency across all rows: if Approval Status is Pending or rejected,
    # Approved By and Approved On MUST be "NA"
    if target_status_col in df_perf.columns:
        st_lower = df_perf[target_status_col].astype(str).str.strip().str.lower()
        is_pending = st_lower.isin(["pending", "rejected", "cancelled", "revoked", "withdrawn"])
        if "Approved By" in df_perf.columns:
            df_perf.loc[is_pending, "Approved By"] = "NA"
        if "Approved On" in df_perf.columns:
            df_perf.loc[is_pending, "Approved On"] = "NA"

    # Enforce quantity constraints on df_perf: all entries are single date records,
    # so quantity must be 0.5 if half day, and max 1.0 (never 0.0 or > 1.0).
    if col_p_quantity and col_p_quantity in df_perf.columns:
        def _cap_perf_qty(val: Any) -> float:
            try:
                v = float(val)
                if 0 < v <= 0.5:
                    return 0.5
                return 1.0
            except (ValueError, TypeError):
                return 1.0
        df_perf[col_p_quantity] = df_perf[col_p_quantity].apply(_cap_perf_qty)

    # Drop temporary helper columns
    df_perf = df_perf.drop(columns=["_parsed_date", "_parsed_quantity"])

    # 6. Build 'Absent Mailer' sheet
    emp_id_col = col_p_emp_num or "Employee Number"
    emp_nm_col = col_p_emp_name or "Employee Name"

    # Filter for actionable absent / missing swipes cases if any exist, else full sheet
    status_series = df_perf[col_p_status].astype(str).str.strip().str.upper() if (col_p_status and col_p_status in df_perf.columns) else pd.Series([""] * len(df_perf))
    att_type_series = df_perf[col_p_att_type].astype(str).str.strip().str.lower() if (col_p_att_type and col_p_att_type in df_perf.columns) else pd.Series([""] * len(df_perf))

    absent_mask = (
        status_series.isin(["A", "P(MS)", "MS"]) |
        status_series.str.contains(r'(?:^|:)A(?::|$)|P\(MS\)', regex=True) |
        att_type_series.isin(["absent", "missing swipes"])
    )
    df_mailer_source = df_perf[absent_mask].copy() if absent_mask.any() else pd.DataFrame(columns=df_perf.columns)

    def _clean_mailer_qty(val: Any) -> float:
        try:
            v = float(val)
            if 0 < v <= 0.5:
                return 0.5
            return 1.0
        except (ValueError, TypeError):
            return 1.0

    df_mailer = pd.DataFrame()
    df_mailer["Employee Number"] = df_mailer_source[emp_id_col] if emp_id_col in df_mailer_source.columns else ""
    df_mailer["Employee Name"] = df_mailer_source[emp_nm_col] if emp_nm_col in df_mailer_source.columns else ""
    df_mailer["Date"] = df_mailer_source[col_p_date] if col_p_date in df_mailer_source.columns else ""
    df_mailer["Status"] = df_mailer_source[col_p_status] if (col_p_status and col_p_status in df_mailer_source.columns) else ""
    df_mailer["Quantity"] = (
        df_mailer_source[col_p_quantity].apply(_clean_mailer_qty)
        if (col_p_quantity and col_p_quantity in df_mailer_source.columns)
        else 1.0
    )

    if email_map and emp_id_col in df_mailer_source.columns:
        df_mailer["Employee Mail ID"] = df_mailer_source[emp_id_col].astype(str).str.strip().map(email_map).fillna("")
    else:
        df_mailer["Employee Mail ID"] = df_mailer_source.get("Work Email", df_mailer_source.get("Employee Mail ID", ""))

    if "Reporting Manager" in df_mailer_source.columns and not df_mailer_source["Reporting Manager"].replace("", pd.NA).isna().all():
        df_mailer["Reporting Manager"] = df_mailer_source["Reporting Manager"]
    elif rm_map and emp_id_col in df_mailer_source.columns:
        df_mailer["Reporting Manager"] = df_mailer_source[emp_id_col].astype(str).str.strip().map(rm_map).fillna("")
    else:
        df_mailer["Reporting Manager"] = ""

    if rm_email_map and emp_id_col in df_mailer_source.columns:
        df_mailer["RM Mail ID"] = df_mailer_source[emp_id_col].astype(str).str.strip().map(rm_email_map).fillna("")
    else:
        df_mailer["RM Mail ID"] = df_mailer_source.get("Reporting Manager Email", df_mailer_source.get("RM Mail ID", ""))

    if "Location" in df_mailer_source.columns and not df_mailer_source["Location"].replace("", pd.NA).isna().all():
        df_mailer["Location"] = df_mailer_source["Location"]
    elif loc_map and emp_id_col in df_mailer_source.columns:
        df_mailer["Location"] = df_mailer_source[emp_id_col].astype(str).str.strip().map(loc_map).fillna("")
    else:
        df_mailer["Location"] = ""

    if "Month" in df_mailer_source.columns:
        df_mailer["Month"] = df_mailer_source["Month"]
    else:
        df_mailer["Month"] = df_mailer["Date"].apply(lambda v: format_date_str(v)[:7] if v else "")

    if "Last Working Day" in df_mailer_source.columns:
        df_mailer["Last Working Day"] = df_mailer_source["Last Working Day"]
    elif lwd_map and emp_id_col in df_mailer_source.columns:
        df_mailer["Last Working Day"] = df_mailer_source[emp_id_col].astype(str).str.strip().map(lwd_map).apply(format_date_str).fillna("")
    else:
        df_mailer["Last Working Day"] = ""

    mailer_cols = [
        "Employee Number", "Employee Name", "Date", "Status", "Quantity",
        "Employee Mail ID", "Reporting Manager", "RM Mail ID", "Location",
        "Month", "Last Working Day"
    ]
    df_mailer = df_mailer[mailer_cols]

    # Save output Excel in Calibri 10 format, header bold with #00FF99 fill and no borders
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    notify(0.91, f"Writing styled unified Excel workbook ({total_perf_rows:,} rows) to {out_p.name}...")

    from openpyxl.styles import Font, PatternFill, Border
    font_header = Font(name="Calibri", size=10, bold=True)
    font_data = Font(name="Calibri", size=10, bold=False)
    fill_header = PatternFill(start_color="00FF99", end_color="00FF99", fill_type="solid")
    no_border = Border()

    try:
        with pd.ExcelWriter(out_p, engine="openpyxl") as writer:
            df_perf.to_excel(writer, index=False, sheet_name="Daily Performance")
            df_mailer.to_excel(writer, index=False, sheet_name="Absent Mailer")

            for sheetname in writer.sheets:
                ws = writer.sheets[sheetname]
                date_col_indices = set()
                for col_idx in range(1, ws.max_column + 1):
                    h_val = str(ws.cell(row=1, column=col_idx).value or "").strip().lower()
                    if any(term in h_val for term in ["date", "last working day", "applied on", "approved on", "requested on", "action taken on", "exit date", "month"]):
                        date_col_indices.add(col_idx)

                for row in ws.iter_rows():
                    for cell in row:
                        cell.border = no_border
                        if cell.row == 1:
                            cell.font = font_header
                            cell.fill = fill_header
                        else:
                            cell.font = font_data
                            if cell.column in date_col_indices or isinstance(cell.value, (datetime, date)):
                                d_obj = to_excel_date(cell.value)
                                if isinstance(d_obj, (datetime, date)):
                                    cell.value = d_obj if isinstance(d_obj, date) else d_obj.date()
                                    cell.number_format = "dd-mmm-yy"
    except PermissionError:
        raise PermissionError(
            f"Cannot save to '{out_p.name}'. The file is currently open in Microsoft Excel or locked by another application.\n"
            f"Please close '{out_p.name}' in Excel and try again, or save to a different file name."
        )

    # 7. Generate Error Logs Excel File
    error_log_path = out_p.parent / f"{out_p.stem}_Error_Log.xlsx"
    notify(0.96, f"Writing Error Log report: {error_log_path.name}...")

    q_rows = []
    for qv in quantity_violations:
        d_val = qv["date"]
        d_formatted = format_date_str(d_val)
        q_rows.append({
            "Employee Number": qv.get("employee", ""),
            "Employee Name": qv.get("employee_name", ""),
            "Date": d_formatted,
            "Total Quantity": qv.get("total_quantity", 0.0),
            "Violation": "Total quantity on this date exceeds 1.0 day limit",
        })
    df_qv = pd.DataFrame(q_rows) if q_rows else pd.DataFrame(columns=["Employee Number", "Employee Name", "Date", "Total Quantity", "Violation"])

    df_unmatched = pd.DataFrame(unmatched_applications) if unmatched_applications else pd.DataFrame(columns=[
        "Application Type", "Employee Number", "Employee Name", "Date", "Duration", "Leave / Request Name", "Status", "Reason / Issue"
    ])

    df_summary = pd.DataFrame([
        {"Metric": "Total Daily Performance Rows", "Value": total_perf_rows},
        {"Metric": "Total Leave Records Matched", "Value": matched_leave_count},
        {"Metric": "Total WFH Records Matched", "Value": matched_wfh_count},
        {"Metric": "Quantity Violations (> 1.0 Day)", "Value": len(quantity_violations)},
        {"Metric": "Unmatched Leave Applications", "Value": sum(1 for u in unmatched_applications if u["Application Type"] == "Leave")},
        {"Metric": "Unmatched WFH Applications", "Value": sum(1 for u in unmatched_applications if u["Application Type"] == "Work From Home")},
    ])

    try:
        with pd.ExcelWriter(error_log_path, engine="openpyxl") as err_writer:
            df_summary.to_excel(err_writer, index=False, sheet_name="Summary")
            df_qv.to_excel(err_writer, index=False, sheet_name="Quantity Violations")
            df_unmatched.to_excel(err_writer, index=False, sheet_name="Unmatched Applications")

            for s_name in err_writer.sheets:
                s_ws = err_writer.sheets[s_name]
                for r in s_ws.iter_rows():
                    for c in r:
                        c.border = no_border
                        if c.row == 1:
                            c.font = font_header
                            c.fill = fill_header
                        else:
                            c.font = font_data
    except Exception:
        pass

    notify(1.0, f"Complete: {total_perf_rows:,} rows reconciled • {matched_leave_count:,} leave, {matched_wfh_count:,} WFH matched")

    return {
        "output_path": str(out_p),
        "error_log_path": str(error_log_path) if error_log_path.exists() else "",
        "total_rows": total_perf_rows,
        "matched_leave_count": matched_leave_count,
        "matched_wfh_count": matched_wfh_count,
        "quantity_violations": quantity_violations,
        "quantity_violation_count": len(quantity_violations),
        "unmatched_applications": unmatched_applications,
        "unmatched_applications_count": len(unmatched_applications),
        "leave_apps_expanded": len(leave_records),
        "wfh_apps_expanded": len(wfh_records),
        "absent_mailer_rows": len(df_mailer),
    }

