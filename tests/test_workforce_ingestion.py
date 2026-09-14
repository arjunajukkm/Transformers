"""
test_workforce_ingestion.py
───────────────────────────
Test suite for the Workforce Intelligence ingestion, schema validation,
normalization, derived field calculations, and data quality engine.
"""

import tempfile
from pathlib import Path
import pandas as pd
import pytest

from workforce_intelligence.ingestion import load_workforce_data
from workforce_intelligence.normalization import (
    normalize_attendance_category,
    normalize_employee_number,
    parse_duration_to_minutes,
    parse_time_to_minutes,
)
from workforce_intelligence.validation import MissingRequiredColumnsError


# ── 1. Employee Number Normalization ──────────────────────────────────

def test_employee_number_normalization():
    # Float .0 stripping
    assert normalize_employee_number(12345.0) == "12345"
    assert normalize_employee_number("12345.0") == "12345"

    # Whitespace trimming
    assert normalize_employee_number("  FINBC003  ") == "FINBC003"

    # Leading zeros preserved
    assert normalize_employee_number("0042") == "0042"
    assert normalize_employee_number("000123") == "000123"

    # Missing / sentinel values never produce string 'nan'
    assert normalize_employee_number(None) is None
    assert normalize_employee_number(float("nan")) is None
    assert normalize_employee_number("nan") is None
    assert normalize_employee_number("NaN") is None
    assert normalize_employee_number("None") is None
    assert normalize_employee_number("") is None
    assert normalize_employee_number("-") is None
    assert normalize_employee_number("N/A") is None


# ── 2. Date Parsing & Calendar Derivations ─────────────────────────────

def test_date_parsing():
    df = pd.DataFrame({
        "Employee Number": ["E01", "E02"],
        "Employee Name": ["Alice", "Bob"],
        "Date": ["2026-09-04", "2026-09-05"],  # Friday and Saturday
        "Status": ["P", "WO"],
        "Attendance Type": ["Present", "Week Off"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert pd.api.types.is_datetime64_any_dtype(cleaned_df["Date"])
        assert cleaned_df.loc[0, "event_year"] == 2026
        assert cleaned_df.loc[0, "event_month"] == 9
        assert cleaned_df.loc[0, "day_of_week"] == "Friday"
        assert cleaned_df.loc[0, "day_of_week_number"] == 4
        assert cleaned_df.loc[0, "is_weekend"] == False

        # Saturday
        assert cleaned_df.loc[1, "day_of_week"] == "Saturday"
        assert cleaned_df.loc[1, "day_of_week_number"] == 5
        assert cleaned_df.loc[1, "is_weekend"] == True
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 3. HH:MM Duration and Time to Minutes Conversion ──────────────────

def test_duration_and_time_to_minutes():
    # Time of day (In Time / Out Time)
    assert parse_time_to_minutes("09:30") == 570
    assert parse_time_to_minutes("12:07") == 727
    assert parse_time_to_minutes("20:40") == 1240
    assert parse_time_to_minutes("0:00") == 0
    assert parse_time_to_minutes(None) is None
    assert parse_time_to_minutes("invalid") is None

    # Duration fields (Total Hours / Effective Hours)
    assert parse_duration_to_minutes("8:30") == 510
    assert parse_duration_to_minutes("8:33") == 513
    assert parse_duration_to_minutes("04:26") == 266
    assert parse_duration_to_minutes("4:06") == 246
    assert parse_duration_to_minutes("0:00") == 0
    # Over 24 hours duration allowed
    assert parse_duration_to_minutes("28:15") == 28 * 60 + 15
    assert parse_duration_to_minutes(None) is None
    assert parse_duration_to_minutes("-") is None


# ── 4. Application Lag Calculation ────────────────────────────────────

def test_application_lag_calculation():
    # Lag = Applied On - Date
    df = pd.DataFrame({
        "Employee Number": ["E01", "E02", "E03", "E04"],
        "Employee Name": ["A", "B", "C", "D"],
        "Date": ["2026-09-07", "2026-09-04", "2026-09-01", "2026-09-01"],
        "Applied On": ["2026-09-04", "2026-09-04", "2026-09-04", None],
        "Status": ["OD", "CL", "WFH", "P"],
        "Attendance Type": ["On Duty", "Leave", "Work From Home", "Present"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, _ = load_workforce_data(tmp_path)
        # 2026-09-04 - 2026-09-07 = -3 days (applied 3 days before event)
        assert cleaned_df.loc[0, "application_lag_days"] == -3
        # 2026-09-04 - 2026-09-04 = 0 days (applied same day)
        assert cleaned_df.loc[1, "application_lag_days"] == 0
        # 2026-09-04 - 2026-09-01 = 3 days (applied 3 days after event)
        assert cleaned_df.loc[2, "application_lag_days"] == 3
        # Missing Applied On
        assert pd.isna(cleaned_df.loc[3, "application_lag_days"])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 5. Approval Turnaround Calculation ────────────────────────────────

def test_approval_turnaround_calculation():
    # Turnaround = Approved On - Applied On
    df = pd.DataFrame({
        "Employee Number": ["E01", "E02"],
        "Employee Name": ["A", "B"],
        "Date": ["2026-09-01", "2026-09-01"],
        "Applied On": ["2026-09-04", "2026-09-04"],
        "Approved On": ["2026-09-10", None],
        "Status": ["CL", "WFH"],
        "Attendance Type": ["Leave", "Work From Home"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, _ = load_workforce_data(tmp_path)
        # 2026-09-10 - 2026-09-04 = 6 days
        assert cleaned_df.loc[0, "approval_turnaround_days"] == 6
        # Missing Approved On -> NA
        assert pd.isna(cleaned_df.loc[1, "approval_turnaround_days"])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 6. Attendance Category Mapping ────────────────────────────────────

def test_attendance_category_mapping():
    assert normalize_attendance_category("P", "Present") == "Present"
    assert normalize_attendance_category("WOW", "Worked on Week off") == "Present"
    assert normalize_attendance_category("WOH", "Worked on Holiday") == "Present"
    assert normalize_attendance_category("A", "Absent") == "Absent"
    assert normalize_attendance_category("WFH", "Work From Home") == "Work From Home"
    assert normalize_attendance_category("CLSL", "Leave") == "Leave"
    assert normalize_attendance_category("WO", "Week Off") == "Week Off"
    assert normalize_attendance_category("H", "Holiday") == "Holiday"
    assert normalize_attendance_category("OD", "Onduty") == "On Duty"
    assert normalize_attendance_category("A(R)", "Regularized") == "Attendance Regularized"
    assert normalize_attendance_category("P(MS)", "Missing Swipes") == "Missing Swipes"
    assert normalize_attendance_category("UNKNOWN", "Unrecognized Category") == "Unknown"


# ── 7. Missing Optional Columns Handled Gracefully ────────────────────

def test_missing_optional_columns():
    # Only supply mandatory columns
    df = pd.DataFrame({
        "Employee Number": ["E01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-09-01"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert len(cleaned_df) == 1
        assert "In Time" not in df.columns
        # Result has normalized default or NA columns
        assert pd.isna(cleaned_df.loc[0, "in_time_minutes"])
        # Report identifies missing optional columns
        assert "Job Title" in report.missing_expected_optional_columns
        assert "Total Hours" in report.missing_expected_optional_columns
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 8. Missing Required Columns Raises Error ──────────────────────────

def test_missing_required_columns():
    # Missing 'Date' and 'Attendance Type'
    df = pd.DataFrame({
        "Employee Number": ["E01"],
        "Employee Name": ["Alice"],
        "Status": ["P"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        with pytest.raises(MissingRequiredColumnsError) as exc_info:
            load_workforce_data(tmp_path)
        assert "Date" in exc_info.value.missing_columns
        assert "Attendance Type" in exc_info.value.missing_columns
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 9. Invalid Date Handling (Non-Crashing & Flagged) ──────────────────

def test_invalid_date_handling():
    df = pd.DataFrame({
        "Employee Number": ["E01", "E02"],
        "Employee Name": ["Alice", "Bob"],
        "Date": ["2026-09-01", "not-a-real-date"],
        "Status": ["P", "A"],
        "Attendance Type": ["Present", "Absent"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert len(cleaned_df) == 2
        # First row is valid
        assert pd.notna(cleaned_df.loc[0, "Date"])
        assert cleaned_df.loc[0, "dq_invalid_date"] == False

        # Second row date is NaT and flagged
        assert pd.isna(cleaned_df.loc[1, "Date"])
        assert cleaned_df.loc[1, "dq_invalid_date"] == True
        assert report.invalid_date_count == 1
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── 10. Data Quality Report Generation ────────────────────────────────

def test_data_quality_report_generation():
    df = pd.DataFrame({
        "Employee Number": ["E01", "E01", None],
        "Employee Name": ["Alice", "Alice", "Charlie"],
        "Date": ["2026-09-01", "2026-09-01", "2026-09-02"],
        "Status": ["P", "P", "XYZ"],
        "Attendance Type": ["Present", "Present", "UnknownType"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert report.total_rows == 3
        assert report.unique_employees == 1  # only E01 is valid non-null
        assert report.duplicate_rows == 1   # (E01, 2026-09-01) duplicated
        assert report.missing_employee_number == 1
        assert report.unknown_attendance_category_count == 1
        assert 0.0 <= report.data_completeness_percentage <= 100.0

        # Quality flags on DataFrame
        assert cleaned_df.loc[1, "dq_missing_employee"] == False
        assert cleaned_df.loc[2, "dq_missing_employee"] == True
        assert cleaned_df.loc[2, "dq_unknown_attendance"] == True

        # Dict representation
        d = report.to_dict()
        assert isinstance(d, dict)
        assert d["total_rows"] == 3
        assert "warnings" in d
    finally:
        Path(tmp_path).unlink(missing_ok=True)
