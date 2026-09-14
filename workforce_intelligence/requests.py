"""
requests.py
───────────
Leave request reconstruction layer.
Aggregates daily workforce event records into logical, multi-day leave requests
with preserved source-row traceability and quantity duration calculations.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from workforce_intelligence.policy_config import DEFAULT_POLICY_CONFIG, PolicyConfig


@dataclass
class LeaveRequest:
    """Reconstructed multi-day or single-day leave request."""
    request_id: str
    employee_number: str
    employee_name: Optional[str]
    reporting_manager: Optional[str]
    leave_name_normalized: Optional[str]
    is_pl: bool

    request_start_date: Optional[date]
    request_end_date: Optional[date]
    request_event_rows: int
    request_total_quantity: Optional[float]

    applied_on: Optional[datetime]
    approved_on: Optional[datetime]
    approval_status: Optional[str]
    approved_by: Optional[str]

    request_application_lag_days: Optional[int]
    approval_turnaround_days: Optional[int]

    record_ids: List[str] = field(default_factory=list)
    source_row_numbers: List[int] = field(default_factory=list)
    has_data_quality_issue: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert request to dictionary."""
        d = asdict(self)
        if self.request_start_date:
            d["request_start_date"] = self.request_start_date.isoformat()
        if self.request_end_date:
            d["request_end_date"] = self.request_end_date.isoformat()
        if self.applied_on:
            d["applied_on"] = self.applied_on.isoformat()
        if self.approved_on:
            d["approved_on"] = self.approved_on.isoformat()
        return d


def build_leave_requests(
    df: pd.DataFrame,
    config: Optional[PolicyConfig] = None,
) -> Tuple[List[LeaveRequest], pd.DataFrame]:
    """
    Reconstruct leave requests from daily event records.

    Grouping strategy:
    - Filters rows where attendance_category == 'Leave' or Status represents Leave.
    - Groups rows sharing:
        (Employee Number, normalized Leave Name, Applied On, Approved On, Approved By, Approval Status).
    - If Applied On is missing/null, groups consecutive days with the same Employee Number and Leave Name.
    - Preserves exact source-row traceability (record_id and source_row_number).
    - Returns (list_of_leave_requests, updated_dataframe_with_request_id).
    """
    if config is None:
        config = DEFAULT_POLICY_CONFIG

    df = df.copy()
    if "request_id" not in df.columns:
        df["request_id"] = None

    if len(df) == 0:
        return [], df

    # Identify leave rows
    is_leave = pd.Series(False, index=df.index)
    if "attendance_category" in df.columns:
        is_leave = is_leave | (df["attendance_category"] == "Leave")
    if "Attendance Type" in df.columns:
        is_leave = is_leave | df["Attendance Type"].astype(str).str.lower().str.contains("leave", na=False)

    leave_indices = df[is_leave].index
    if len(leave_indices) == 0:
        return [], df

    leave_df = df.loc[leave_indices].copy()

    # Normalize grouping columns
    emp_series = leave_df["Employee Number"].fillna("UNKNOWN_EMP")
    if "Leave Name" in leave_df.columns:
        leave_name_series = (
            leave_df["Leave Name"]
            .fillna(leave_df["Attendance Type"] if "Attendance Type" in leave_df.columns else "Leave")
            .astype(str)
            .str.strip()
        )
    elif "Attendance Type" in leave_df.columns:
        leave_name_series = leave_df["Attendance Type"].astype(str).str.strip()
    else:
        leave_name_series = pd.Series("Leave", index=leave_df.index)
    applied_series = leave_df["Applied On"] if "Applied On" in leave_df.columns else pd.Series(None, index=leave_df.index)
    approved_on_series = leave_df["Approved On"] if "Approved On" in leave_df.columns else pd.Series(None, index=leave_df.index)
    approved_by_series = leave_df["Approved By"] if "Approved By" in leave_df.columns else pd.Series(None, index=leave_df.index)
    approval_st_series = leave_df["Approval Status"] if "Approval Status" in leave_df.columns else pd.Series(None, index=leave_df.index)

    # Sort to ensure chronological continuity
    leave_df["_sort_date"] = pd.to_datetime(leave_df["Date"]) if "Date" in leave_df.columns else pd.NaT
    leave_df["_orig_idx"] = leave_df.index
    leave_df = leave_df.sort_values(by=["Employee Number", "_sort_date", "_orig_idx"])

    # Build deterministic grouping keys
    group_keys = []
    curr_group_id = 0
    prev_row = None

    for _, row in leave_df.iterrows():
        emp = row.get("Employee Number")
        lname = str(row.get("Leave Name") or row.get("Attendance Type") or "Leave").strip().lower()
        app_on = row.get("Applied On")
        app_on_str = app_on.isoformat() if pd.notna(app_on) and hasattr(app_on, "isoformat") else str(app_on)
        apr_on = row.get("Approved On")
        apr_on_str = apr_on.isoformat() if pd.notna(apr_on) and hasattr(apr_on, "isoformat") else str(apr_on)
        apr_by = str(row.get("Approved By")).strip().lower()
        apr_st = str(row.get("Approval Status")).strip().lower()
        evt_date = pd.to_datetime(row.get("Date")) if pd.notna(row.get("Date")) else None

        if prev_row is None:
            curr_group_id = 1
        else:
            prev_emp, prev_lname, prev_app, prev_apr_on, prev_apr_by, prev_apr_st, prev_date = prev_row
            # Check if this row belongs to the same request
            same_emp_leave = (emp == prev_emp) and (lname == prev_lname)
            if pd.notna(app_on):
                # Strongest evidence: Same employee, leave type, and applied on
                same_group = (
                    same_emp_leave
                    and (app_on_str == prev_app)
                    and (apr_on_str == prev_apr_on)
                    and (apr_by == prev_apr_by)
                    and (apr_st == prev_apr_st)
                )
            else:
                # If Applied On is missing, group consecutive calendar days
                if same_emp_leave and prev_app == "None" and evt_date and prev_date:
                    day_diff = (evt_date.floor("D") - prev_date.floor("D")).days
                    same_group = (day_diff <= 1)
                else:
                    same_group = False

            if not same_group:
                curr_group_id += 1

        group_keys.append(f"req_{curr_group_id:06d}")
        prev_row = (emp, lname, app_on_str, apr_on_str, apr_by, apr_st, evt_date)

    leave_df["request_id"] = group_keys

    # Assign back to original dataframe
    df.loc[leave_df["_orig_idx"], "request_id"] = leave_df["request_id"]

    # Reconstruct LeaveRequest objects
    requests: List[LeaveRequest] = []
    for req_id, group in leave_df.groupby("request_id", sort=False):
        first_row = group.iloc[0]
        emp_num = str(first_row.get("Employee Number") or "UNKNOWN")
        emp_name = first_row.get("Employee Name")
        emp_name = str(emp_name) if pd.notna(emp_name) else None
        manager = first_row.get("Reporting Manager")
        manager = str(manager) if pd.notna(manager) else None
        leave_name = first_row.get("Leave Name") or first_row.get("Attendance Type")
        leave_name_norm = str(leave_name).strip() if pd.notna(leave_name) else None

        status_val = first_row.get("Status") or ""
        is_pl = config.is_pl_leave(leave_name_norm or "", str(status_val))

        # Dates & Quantity
        valid_dates = pd.to_datetime(group["Date"]).dropna()
        start_date: Optional[date] = valid_dates.min().date() if not valid_dates.empty else None
        end_date: Optional[date] = valid_dates.max().date() if not valid_dates.empty else None

        # Total quantity
        quantities = group["Quantity"].dropna() if "Quantity" in group.columns else pd.Series([], dtype=float)
        if not quantities.empty:
            total_qty = round(float(quantities.sum()), 4)
        else:
            total_qty = None

        # Application & Approval metadata
        applied_on_val = first_row.get("Applied On")
        applied_dt: Optional[datetime] = (
            pd.to_datetime(applied_on_val).to_pydatetime() if pd.notna(applied_on_val) else None
        )

        approved_on_val = first_row.get("Approved On")
        approved_dt: Optional[datetime] = (
            pd.to_datetime(approved_on_val).to_pydatetime() if pd.notna(approved_on_val) else None
        )

        approval_status = first_row.get("Approval Status")
        approval_status_str = str(approval_status).strip() if pd.notna(approval_status) else None

        approved_by = first_row.get("Approved By")
        approved_by_str = str(approved_by).strip() if pd.notna(approved_by) else None

        # Application lag from request start date
        req_lag_days: Optional[int] = None
        if applied_dt and start_date:
            req_lag_days = (applied_dt.date() - start_date).days

        # Turnaround days
        turnaround: Optional[int] = None
        if approved_dt and applied_dt:
            turnaround = (approved_dt.date() - applied_dt.date()).days

        # Traceability lists
        record_ids = group["record_id"].tolist() if "record_id" in group.columns else []
        source_rows = group["source_row_number"].tolist() if "source_row_number" in group.columns else []

        # Data quality checks
        has_dq_issue = False
        if "dq_daily_quantity_exceeds_one" in group.columns:
            has_dq_issue = bool(group["dq_daily_quantity_exceeds_one"].any())

        req = LeaveRequest(
            request_id=req_id,
            employee_number=emp_num,
            employee_name=emp_name,
            reporting_manager=manager,
            leave_name_normalized=leave_name_norm,
            is_pl=is_pl,
            request_start_date=start_date,
            request_end_date=end_date,
            request_event_rows=len(group),
            request_total_quantity=total_qty,
            applied_on=applied_dt,
            approved_on=approved_dt,
            approval_status=approval_status_str,
            approved_by=approved_by_str,
            request_application_lag_days=req_lag_days,
            approval_turnaround_days=turnaround,
            record_ids=record_ids,
            source_row_numbers=source_rows,
            has_data_quality_issue=has_dq_issue,
        )
        requests.append(req)

    return requests, df
