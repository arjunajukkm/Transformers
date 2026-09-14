"""
normalization.py
────────────────
Data type normalization, time parsing, attendance categorization,
and derived analytical field calculations for workforce datasets.
"""

import math
import re
from datetime import date, datetime, time
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd

# Sentinel values that represent null/missing in text fields
NULL_STRINGS = {"", "-", "--", "na", "n/a", "nan", "none", "null", "nil", "n.a.", "n.a"}


def normalize_employee_number(val: Any) -> Optional[str]:
    """
    Safely normalize an Employee Number:
    - Converts to string and trims whitespace.
    - Strips accidental float '.0' suffixes (e.g., 12345.0 -> '12345').
    - Preserves leading zeros (e.g., '0042' -> '0042').
    - Returns None if null/empty (never string 'nan' or 'None').
    """
    if val is None or pd.isna(val):
        return None

    # Handle float / int types directly
    if isinstance(val, float):
        if math.isnan(val):
            return None
        if val.is_integer():
            return str(int(val))
        val_str = str(val)
    else:
        val_str = str(val).strip()

    if not val_str or val_str.lower() in NULL_STRINGS:
        return None

    # Remove accidental trailing '.0' if all other chars are digits
    if val_str.endswith(".0"):
        prefix = val_str[:-2]
        if prefix.isdigit() or prefix.isalnum():
            return prefix

    return val_str


def normalize_text(val: Any) -> Optional[str]:
    """
    Normalize human-readable text dimensions:
    - Strips whitespace.
    - Converts blanks and sentinel null strings to None.
    - Preserves original casing.
    """
    if val is None or pd.isna(val):
        return None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in NULL_STRINGS:
        return None
    return val_str


def parse_time_to_minutes(val: Any) -> Optional[int]:
    """
    Parse a time value (In Time, Out Time) to minutes from midnight (0..1439).
    Handles 'HH:MM', 'H:MM', 'HH:MM:SS', datetime.time, datetime.datetime,
    and Excel fractional day floats (e.g. 0.5 -> 720).
    Returns None if null, empty, or unparseable.
    """
    if val is None or pd.isna(val):
        return None

    # Already an int or float
    if isinstance(val, (int, np.integer)):
        return int(val) if 0 <= val < 1440 else None

    # Excel time represented as fraction of 24-hour day (0.0 to 1.0)
    if isinstance(val, float):
        if math.isnan(val):
            return None
        if 0.0 <= val <= 1.0:
            return int(round(val * 1440)) % 1440
        return None

    # datetime.time object
    if isinstance(val, time):
        return val.hour * 60 + val.minute

    # datetime.datetime or pd.Timestamp
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.hour * 60 + val.minute

    val_str = str(val).strip()
    if not val_str or val_str.lower() in NULL_STRINGS:
        return None

    # Match HH:MM or HH:MM:SS (optional AM/PM)
    match = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*(am|pm)?$", val_str, re.IGNORECASE)
    if match:
        h, m, am_pm = match.groups()
        hours = int(h)
        mins = int(m)
        if am_pm:
            am_pm = am_pm.lower()
            if am_pm == "pm" and hours < 12:
                hours += 12
            elif am_pm == "am" and hours == 12:
                hours = 0
        if 0 <= hours <= 23 and 0 <= mins <= 59:
            return hours * 60 + mins

    return None


def parse_duration_to_minutes(val: Any) -> Optional[int]:
    """
    Parse duration fields (Total Hours, Break Duration, Effective Hours)
    into elapsed minutes.
    Unlike time-of-day, duration hours can exceed 23 (e.g. '28:15' -> 1695).
    Handles 'H:MM', 'HH:MM', 'HH:MM:SS', Excel time, or integer minutes.
    Returns None if missing or invalid.
    """
    if val is None or pd.isna(val):
        return None

    if isinstance(val, (int, np.integer)):
        return int(val) if val >= 0 else None

    if isinstance(val, float):
        if math.isnan(val):
            return None
        # Excel duration stored as day fraction
        if 0.0 <= val <= 10.0: # up to 10 days
            return int(round(val * 1440))
        return None

    if isinstance(val, time):
        return val.hour * 60 + val.minute

    if isinstance(val, (datetime, pd.Timestamp)):
        return val.hour * 60 + val.minute

    val_str = str(val).strip()
    if not val_str or val_str.lower() in NULL_STRINGS:
        return None

    match = re.match(r"^(\d+):(\d{2})(?::\d{2})?$", val_str)
    if match:
        h, m = match.groups()
        hours = int(h)
        mins = int(m)
        if 0 <= mins <= 59:
            return hours * 60 + mins

    # Decimal hours e.g. '8.5'
    try:
        fval = float(val_str)
        if not math.isnan(fval) and fval >= 0:
            return int(round(fval * 60))
    except ValueError:
        pass

    return None


# ── Attendance Category Mapping ───────────────────────────────────────

# Explicit mappings based on normalized lowercase Attendance Type or Status
ATTENDANCE_TYPE_MAP: Dict[str, str] = {
    "present": "Present",
    "worked on week off": "Present",
    "worked on weekoff": "Present",
    "worked on holiday": "Present",
    "half day present": "Present",
    "absent": "Absent",
    "work from home": "Work From Home",
    "wfh": "Work From Home",
    "leave": "Leave",
    "casual leave": "Leave",
    "sick leave": "Leave",
    "privilege leave": "Leave",
    "earned leave": "Leave",
    "maternity leave": "Leave",
    "paternity leave": "Leave",
    "bereavement leave": "Leave",
    "week off": "Week Off",
    "weekly off": "Week Off",
    "holiday": "Holiday",
    "public holiday": "Holiday",
    "onduty": "On Duty",
    "on duty": "On Duty",
    "attendance regularized": "Attendance Regularized",
    "regularized": "Attendance Regularized",
    "missing swipes": "Missing Swipes",
    "missing swipe": "Missing Swipes",
}

STATUS_MAP: Dict[str, str] = {
    "p": "Present",
    "wow": "Present",
    "wo-w": "Present",
    "woh": "Present",
    "h-w": "Present",
    "a": "Absent",
    "ab": "Absent",
    "wfh": "Work From Home",
    "cl": "Leave",
    "sl": "Leave",
    "clsl": "Leave",
    "pl": "Leave",
    "el": "Leave",
    "ml": "Leave",
    "l": "Leave",
    "wo": "Week Off",
    "w/o": "Week Off",
    "h": "Holiday",
    "ph": "Holiday",
    "od": "On Duty",
    "a(r)": "Attendance Regularized",
    "p(r)": "Attendance Regularized",
    "ar": "Attendance Regularized",
    "pr": "Attendance Regularized",
    "p(ms)": "Missing Swipes",
    "ms": "Missing Swipes",
}


def normalize_attendance_category(
    status: Optional[str], attendance_type: Optional[str]
) -> str:
    """
    Map source Status and Attendance Type into a canonical attendance category.
    Categories:
      - Present
      - Absent
      - Work From Home
      - Leave
      - Week Off
      - Holiday
      - On Duty
      - Attendance Regularized
      - Missing Swipes
      - Unknown
    """
    st_clean = (str(status).strip().lower()) if status is not None and not pd.isna(status) else ""
    at_clean = (str(attendance_type).strip().lower()) if attendance_type is not None and not pd.isna(attendance_type) else ""

    # 1. Check Attendance Type first
    if at_clean in ATTENDANCE_TYPE_MAP:
        return ATTENDANCE_TYPE_MAP[at_clean]

    # Partial / substring check for Attendance Type
    if "missing swipe" in at_clean:
        return "Missing Swipes"
    if "regulariz" in at_clean:
        return "Attendance Regularized"
    if "work from home" in at_clean or at_clean == "wfh":
        return "Work From Home"
    if "on duty" in at_clean or "onduty" in at_clean:
        return "On Duty"
    if "week off" in at_clean:
        return "Week Off"
    if "holiday" in at_clean:
        return "Holiday"
    if "leave" in at_clean:
        return "Leave"
    if "present" in at_clean:
        return "Present"
    if "absent" in at_clean:
        return "Absent"

    # 2. Check Status code
    if st_clean in STATUS_MAP:
        return STATUS_MAP[st_clean]

    if st_clean.startswith("p(ms)") or "ms" in st_clean:
        return "Missing Swipes"
    if "(r)" in st_clean or st_clean in ("ar", "pr"):
        return "Attendance Regularized"
    if st_clean == "p":
        return "Present"
    if st_clean == "a":
        return "Absent"
    if st_clean == "wfh":
        return "Work From Home"
    if st_clean == "od":
        return "On Duty"
    if st_clean in ("wo", "w/o"):
        return "Week Off"
    if st_clean in ("h", "ph"):
        return "Holiday"

    return "Unknown"


# ── DataFrame Normalization Pipeline ──────────────────────────────────

def normalize_workforce_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Apply full normalization and derived field generation to a dataframe
    whose columns have already been mapped to canonical names.
    Returns: (normalized_df, normalization_metadata)
    """
    df = df.copy()
    meta: Dict[str, Any] = {
        "invalid_date_count": 0,
        "invalid_applied_on_count": 0,
        "invalid_approved_on_count": 0,
    }

    # 1. Normalize Employee Number
    if "Employee Number" in df.columns:
        df["Employee Number"] = df["Employee Number"].apply(normalize_employee_number)

    # 2. Normalize Text Dimensions
    text_cols = [
        "Employee Name",
        "Job Title",
        "Business Unit",
        "Department",
        "Sub Department",
        "Location",
        "Reporting Manager",
        "Status",
        "Attendance Type",
        "Leave Name",
        "Applied By",
        "Approval Status",
        "Approved By",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].apply(normalize_text)

    # 3. Normalize Date fields safely
    date_cols = ["Date", "Month", "Applied On", "Approved On"]
    for col in date_cols:
        if col in df.columns:
            raw_series = df[col]
            # Detect raw non-empty items
            raw_non_empty = raw_series.apply(
                lambda v: v is not None and not pd.isna(v) and str(v).strip().lower() not in NULL_STRINGS
            )
            parsed_series = pd.to_datetime(raw_series, errors="coerce")
            invalid_mask = raw_non_empty & parsed_series.isna()
            df[col] = parsed_series

            if col == "Date":
                meta["invalid_date_count"] = int(invalid_mask.sum())
                df["_invalid_date_raw"] = invalid_mask
            elif col == "Applied On":
                meta["invalid_applied_on_count"] = int(invalid_mask.sum())
            elif col == "Approved On":
                meta["invalid_approved_on_count"] = int(invalid_mask.sum())

    # 4. Time Fields: in_time_minutes, out_time_minutes
    if "In Time" in df.columns:
        df["in_time_minutes"] = df["In Time"].apply(parse_time_to_minutes).astype("Int64")
    else:
        df["in_time_minutes"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    if "Out Time" in df.columns:
        df["out_time_minutes"] = df["Out Time"].apply(parse_time_to_minutes).astype("Int64")
    else:
        df["out_time_minutes"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    # 5. Duration Fields: total_hours_minutes, break_duration_minutes, effective_hours_minutes
    if "Total Hours" in df.columns:
        df["total_hours_minutes"] = df["Total Hours"].apply(parse_duration_to_minutes).astype("Int64")
    else:
        df["total_hours_minutes"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    if "Break Duration" in df.columns:
        df["break_duration_minutes"] = df["Break Duration"].apply(parse_duration_to_minutes).astype("Int64")
    else:
        df["break_duration_minutes"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    if "Effective Hours" in df.columns:
        df["effective_hours_minutes"] = df["Effective Hours"].apply(parse_duration_to_minutes).astype("Int64")
    else:
        df["effective_hours_minutes"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    # 6. Derived Calendar Fields from Date
    if "Date" in df.columns:
        dt_series = df["Date"].dt
        df["event_month"] = dt_series.month.astype("Int64")
        df["event_year"] = dt_series.year.astype("Int64")
        df["day_of_week"] = dt_series.day_name()
        df["day_of_week_number"] = dt_series.dayofweek.astype("Int64")
        df["is_weekend"] = df["Date"].apply(
            lambda d: bool(d.dayofweek >= 5) if pd.notna(d) else None
        ).astype("boolean")
    else:
        df["event_month"] = pd.Series([pd.NA] * len(df), dtype="Int64")
        df["event_year"] = pd.Series([pd.NA] * len(df), dtype="Int64")
        df["day_of_week"] = pd.Series([None] * len(df), dtype="object")
        df["day_of_week_number"] = pd.Series([pd.NA] * len(df), dtype="Int64")
        df["is_weekend"] = pd.Series([pd.NA] * len(df), dtype="boolean")

    # 7. Derived Lag & Turnaround Fields
    # application_lag_days = Applied On date - Date date
    # Negative = applied before event date; 0 = same day; Positive = applied after
    if "Applied On" in df.columns and "Date" in df.columns:
        def calc_lag(row):
            app_on = row["Applied On"]
            evt_date = row["Date"]
            if pd.notna(app_on) and pd.notna(evt_date):
                # Compare calendar dates
                return (pd.to_datetime(app_on).floor("D") - pd.to_datetime(evt_date).floor("D")).days
            return None

        df["application_lag_days"] = df.apply(calc_lag, axis=1).astype("Int64")
    else:
        df["application_lag_days"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    # approval_turnaround_days = Approved On - Applied On
    if "Approved On" in df.columns and "Applied On" in df.columns:
        def calc_turnaround(row):
            app_on = row["Applied On"]
            apr_on = row["Approved On"]
            if pd.notna(app_on) and pd.notna(apr_on):
                return (pd.to_datetime(apr_on).floor("D") - pd.to_datetime(app_on).floor("D")).days
            return None

        df["approval_turnaround_days"] = df.apply(calc_turnaround, axis=1).astype("Int64")
    else:
        df["approval_turnaround_days"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    # 8. Normalized Attendance Category
    status_col = df["Status"] if "Status" in df.columns else pd.Series([None] * len(df))
    type_col = df["Attendance Type"] if "Attendance Type" in df.columns else pd.Series([None] * len(df))

    df["attendance_category"] = [
        normalize_attendance_category(st, at) for st, at in zip(status_col, type_col)
    ]

    return df, meta
