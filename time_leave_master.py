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
    "status": ["status", "request status", "approval status"],
    "attendance type": ["attendance type", "attendancetype", "type"],
    "leave name": ["leave name", "leave type", "leavename"],
}


def find_column(df: pd.DataFrame, alias_category: str) -> Optional[str]:
    """Find matching column name in DataFrame for a canonical alias category."""
    candidates = ALIASES.get(alias_category.lower(), [])
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

ADMIN_APPROVERS = {"arjun s", "e janani sri", "janani sri e"}


def compute_applied_by(requester_name: Any, employee_name: Any) -> str:
    """
    Applied By Logic:
    If requester or requested by data is matching with Employee Name -> 'Employee', else 'Admin'.
    """
    req = clean_emp_str(requester_name).lower()
    emp = clean_emp_str(employee_name).lower()

    if not req:
        # If requester is blank, default to Employee if employee name exists, else Admin
        return "Employee" if emp else "Admin"

    if req == emp:
        return "Employee"

    # Also handle partial clean match if names have minor whitespace differences
    clean_r = re.sub(r'[^a-z0-9]', '', req)
    clean_e = re.sub(r'[^a-z0-9]', '', emp)
    if clean_r and clean_r == clean_e:
        return "Employee"

    return "Admin"


def compute_approved_by(action_taken_by: Any) -> str:
    """
    Approved By Logic:
    If Last Action Taken by or Action Taken By name is 'Arjun S' or 'E Janani Sri' -> 'Admin',
    else -> 'Manager'.
    Approved By should NEVER come as 'Employee', it must always be 'Manager'.
    """
    act = clean_emp_str(action_taken_by).lower()
    if not act:
        return "Manager"

    # Check against admin approvers
    for admin in ADMIN_APPROVERS:
        if admin in act or act == admin:
            return "Admin"

    return "Manager"


# ════════════════════════════════════════════════════════════════
# Application Expansion (Date Splitting)
# ════════════════════════════════════════════════════════════════

def expand_application_records(
    df_apps: pd.DataFrame, app_type: str = "leave"
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
        'approved_by': 'Admin' | 'Employee',
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

    expanded_records = []

    for _, row in df_apps.iterrows():
        emp_num = clean_emp_str(row.get(col_emp_num)) if col_emp_num else ""
        emp_name = clean_emp_str(row.get(col_emp_name)) if col_emp_name else ""
        req_name = clean_emp_str(row.get(col_requester)) if col_requester else ""
        action_by = clean_emp_str(row.get(col_action_by)) if col_action_by else ""

        applied_by_val = compute_applied_by(req_name, emp_name)
        approved_by_val = compute_approved_by(action_by)

        applied_on_raw = row.get(col_applied_on) if col_applied_on else None
        approved_on_raw = row.get(col_approved_on) if col_approved_on else None

        applied_on_val = format_date_str(applied_on_raw)
        approved_on_val = format_date_str(approved_on_raw)

        leave_name_val = clean_emp_str(row.get(col_leave_name)) if col_leave_name else ""
        status_val = clean_emp_str(row.get(col_status)) if col_status else ""

        # Dates
        from_dt = parse_date(row.get(col_from_date)) if col_from_date else None
        to_dt = parse_date(row.get(col_to_date)) if col_to_date else None

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

        # Check if single half day
        if total_dur <= 0.5 and from_dt == to_dt:
            expanded_records.append({
                "emp_num": emp_num,
                "emp_name": emp_name,
                "date": from_dt,
                "duration": total_dur,
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
                "duration": 1.0 if total_dur >= 1.0 else total_dur,
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
    leave_active_files: List[Union[str, Path]],
    leave_inactive_files: List[Union[str, Path]],
    wfh_files: List[Union[str, Path]],
    output_path: Union[str, Path],
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

    # 1. Load files with real-time progress tracking
    total_files = len(perf_files) + len(leave_active_files) + len(leave_inactive_files) + len(wfh_files)
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

    total_perf_rows = len(df_perf)
    notify(0.16, f"Loaded {total_perf_rows:,} daily records across {len(perf_files)} performance file(s)...")

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
        leave_records.extend(expand_application_records(df_leave_active, app_type="leave"))
    if not df_leave_inactive.empty:
        leave_records.extend(expand_application_records(df_leave_inactive, app_type="leave"))

    notify(0.22, f"Expanding {len(df_wfh):,} WFH applications across date ranges...")
    wfh_records = []
    if not df_wfh.empty:
        wfh_records.extend(expand_application_records(df_wfh, app_type="wfh"))

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

    def find_match(emp_id: str, emp_name: str, p_date: date, event_type: str, leave_type_pref: str = "") -> Optional[Dict[str, Any]]:
        pool = []
        if event_type == "leave":
            if emp_id and (emp_id, p_date) in leave_by_emp_dt:
                pool.extend(leave_by_emp_dt[(emp_id, p_date)])
            elif emp_name and (emp_name.lower(), p_date) in leave_by_name_dt:
                pool.extend(leave_by_name_dt[(emp_name.lower(), p_date)])
        elif event_type == "wfh":
            if emp_id and (emp_id, p_date) in wfh_by_emp_dt:
                pool.extend(wfh_by_emp_dt[(emp_id, p_date)])
            elif emp_name and (emp_name.lower(), p_date) in wfh_by_name_dt:
                pool.extend(wfh_by_name_dt[(emp_name.lower(), p_date)])
        else:
            # Check leave first, then wfh
            if emp_id and (emp_id, p_date) in leave_by_emp_dt:
                pool.extend(leave_by_emp_dt[(emp_id, p_date)])
            elif emp_name and (emp_name.lower(), p_date) in leave_by_name_dt:
                pool.extend(leave_by_name_dt[(emp_name.lower(), p_date)])
            if not pool:
                if emp_id and (emp_id, p_date) in wfh_by_emp_dt:
                    pool.extend(wfh_by_emp_dt[(emp_id, p_date)])
                elif emp_name and (emp_name.lower(), p_date) in wfh_by_name_dt:
                    pool.extend(wfh_by_name_dt[(emp_name.lower(), p_date)])

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
            df_perf.at[idx, "Applied By"] = matched_rec["applied_by"] if matched_rec.get("applied_by") else "NA"
            df_perf.at[idx, "Applied On"] = matched_rec["applied_on"] if matched_rec.get("applied_on") else "NA"
            df_perf.at[idx, "Approved By"] = matched_rec["approved_by"] if matched_rec.get("approved_by") else "NA"
            df_perf.at[idx, "Approved On"] = matched_rec["approved_on"] if matched_rec.get("approved_on") else "NA"
            if target_status_col and matched_rec.get("status"):
                df_perf.at[idx, target_status_col] = matched_rec["status"]

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

    for d_col in ["Applied On", "Approved On"]:
        if d_col in df_perf.columns:
            df_perf[d_col] = df_perf[d_col].apply(lambda v: format_date_str(v) if pd.notna(v) and str(v).strip() != "" else v)

    # Drop temporary helper columns
    df_perf = df_perf.drop(columns=["_parsed_date", "_parsed_quantity"])

    # 6. Save output Excel in Calibri 10 format, header bold with #00FF99 fill and no borders
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    notify(0.91, f"Writing styled Excel workbook ({total_perf_rows:,} rows) to {out_p.name}...")

    from openpyxl.styles import Font, PatternFill, Border
    font_header = Font(name="Calibri", size=10, bold=True)
    font_data = Font(name="Calibri", size=10, bold=False)
    fill_header = PatternFill(start_color="00FF99", end_color="00FF99", fill_type="solid")
    no_border = Border()

    try:
        with pd.ExcelWriter(out_p, engine="openpyxl") as writer:
            df_perf.to_excel(writer, index=False, sheet_name="Daily Performance")

            for sheetname in writer.sheets:
                ws = writer.sheets[sheetname]
                for row in ws.iter_rows():
                    for cell in row:
                        cell.border = no_border
                        if cell.row == 1:
                            cell.font = font_header
                            cell.fill = fill_header
                        else:
                            cell.font = font_data
                        if isinstance(cell.value, (datetime, date)):
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
    }

