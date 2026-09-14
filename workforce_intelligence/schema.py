"""
schema.py
─────────
Canonical schema definitions and column classifications for the
Workforce Intelligence data ingestion and normalization layer.
"""

from typing import Dict, List, Set

# ── Logical Column Groupings ──────────────────────────────────────────

EMPLOYEE_DIMENSIONS: List[str] = [
    "Employee Number",
    "Employee Name",
    "Job Title",
    "Business Unit",
    "Department",
    "Sub Department",
    "Location",
    "Reporting Manager",
]

EVENT_DIMENSIONS: List[str] = [
    "Date",
    "Month",
    "Status",
    "Attendance Type",
    "Leave Name",
    "Quantity",
]

APPLICATION_APPROVAL_COLUMNS: List[str] = [
    "Applied By",
    "Applied On",
    "Approval Status",
    "Approved By",
    "Approved On",
]

TIME_COLUMNS: List[str] = [
    "In Time",
    "Out Time",
    "Total Hours",
    "Break Duration",
    "Effective Hours",
]

# ── Complete Canonical Column Set ─────────────────────────────────────

CANONICAL_COLUMNS: List[str] = (
    EMPLOYEE_DIMENSIONS
    + EVENT_DIMENSIONS
    + APPLICATION_APPROVAL_COLUMNS
    + TIME_COLUMNS
)

# ── Required / Core vs. Optional Fields ───────────────────────────────

REQUIRED_COLUMNS: List[str] = [
    "Employee Number",
    "Employee Name",
    "Date",
    "Status",
    "Attendance Type",
]

CORE_COLUMNS: List[str] = REQUIRED_COLUMNS

OPTIONAL_COLUMNS: List[str] = [
    col for col in CANONICAL_COLUMNS if col not in REQUIRED_COLUMNS
]

# ── Row-Level Data Quality Flags ──────────────────────────────────────

DQ_FLAGS: List[str] = [
    "dq_missing_employee",
    "dq_missing_date",
    "dq_invalid_date",
    "dq_unknown_attendance",
    "dq_exact_duplicate",
    "dq_cross_file_exact_duplicate",
    "dq_multiple_records_same_date",
    "dq_daily_quantity_exceeds_one",
    "dq_analytical_daily_quantity_exceeds_one",
    "dq_missing_quantity",
]

# ── Derived Analytical Metric Columns ─────────────────────────────────

DERIVED_COLUMNS: List[str] = [
    "record_id",
    "source_row_number",
    "source_file_name",
    "source_file_index",
    "attendance_category",
    "period_month",
    "include_in_analysis",
    "analysis_exclusion_reason",
    "daily_total_quantity",
    "raw_daily_total_quantity",
    "analytical_daily_total_quantity",
    "in_time_minutes",
    "out_time_minutes",
    "total_hours_minutes",
    "break_duration_minutes",
    "effective_hours_minutes",
    "event_month",
    "event_year",
    "day_of_week",
    "day_of_week_number",
    "is_weekend",
    "application_lag_days",
    "approval_turnaround_days",
]

# ── Case-Insensitive / Alias Normalization Mapping ────────────────────

def _build_column_lookup() -> Dict[str, str]:
    """Create normalized key lookup dictionary for standard column names."""
    lookup: Dict[str, str] = {}
    for col in CANONICAL_COLUMNS:
        norm_key = "".join(ch for ch in col.lower() if ch.isalnum())
        lookup[norm_key] = col
        lookup[col.strip().lower()] = col

    # Common aliases
    aliases = {
        "emp id": "Employee Number",
        "empid": "Employee Number",
        "emp no": "Employee Number",
        "empno": "Employee Number",
        "employee id": "Employee Number",
        "employee code": "Employee Number",
        "emp name": "Employee Name",
        "employeename": "Employee Name",
        "manager": "Reporting Manager",
        "manager name": "Reporting Manager",
        "reporting to": "Reporting Manager",
        "attendancedate": "Date",
        "event date": "Date",
        "attendancetype": "Attendance Type",
        "approvalstatus": "Approval Status",
        "applieddate": "Applied On",
        "approveddate": "Approved On",
        "totalhours": "Total Hours",
        "effectivehours": "Effective Hours",
        "breakduration": "Break Duration",
        "intime": "In Time",
        "outtime": "Out Time",
        "qty": "Quantity",
    }
    for alias_key, canonical in aliases.items():
        lookup[alias_key] = canonical
        norm_alias = "".join(ch for ch in alias_key.lower() if ch.isalnum())
        lookup[norm_alias] = canonical

    return lookup

COLUMN_LOOKUP: Dict[str, str] = _build_column_lookup()


def resolve_canonical_column(col_name: str) -> str:
    """
    Resolve a source column name to its canonical name if matched.
    If no match is found, returns the original column name stripped of whitespace.
    """
    cleaned = str(col_name).strip()
    if cleaned.lower() in COLUMN_LOOKUP:
        return COLUMN_LOOKUP[cleaned.lower()]
    norm_key = "".join(ch for ch in cleaned.lower() if ch.isalnum())
    if norm_key in COLUMN_LOOKUP:
        return COLUMN_LOOKUP[norm_key]
    return cleaned
