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

# ── Required vs. Optional Fields ──────────────────────────────────────

REQUIRED_COLUMNS: List[str] = [
    "Employee Number",
    "Employee Name",
    "Date",
    "Status",
    "Attendance Type",
]

OPTIONAL_COLUMNS: List[str] = [
    col for col in CANONICAL_COLUMNS if col not in REQUIRED_COLUMNS
]

# ── Case-Insensitive / Alias Normalization Mapping ────────────────────

def _build_column_lookup() -> Dict[str, str]:
    """Create normalized key lookup dictionary for standard column names."""
    lookup: Dict[str, str] = {}
    for col in CANONICAL_COLUMNS:
        # standard normalized key: lowercase with spaces and special chars stripped
        norm_key = "".join(ch for ch in col.lower() if ch.isalnum())
        lookup[norm_key] = col
        # also exact lower stripped key
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
    # Direct case-insensitive match
    if cleaned.lower() in COLUMN_LOOKUP:
        return COLUMN_LOOKUP[cleaned.lower()]
    # Alphanumeric normalized match
    norm_key = "".join(ch for ch in cleaned.lower() if ch.isalnum())
    if norm_key in COLUMN_LOOKUP:
        return COLUMN_LOOKUP[norm_key]
    return cleaned
