"""
test_workforce_ingestion.py
───────────────────────────
Comprehensive test suite for the Workforce Intelligence ingestion layer,
schema validation, normalization, derived field calculations, and data quality engine.
"""

import tempfile
from pathlib import Path
import pandas as pd
import pytest

from workforce_intelligence.ingestion import load_workforce_data
from workforce_intelligence.normalization import (
    normalize_attendance_category,
    normalize_employee_number,
    normalize_quantity,
    parse_duration_to_minutes,
    parse_time_to_minutes,
)
from workforce_intelligence.validation import MissingRequiredColumnsError


# ── Stage 1 Core Tests ────────────────────────────────────────────────

def test_employee_number_normalization():
    assert normalize_employee_number(12345.0) == "12345"
    assert normalize_employee_number("12345.0") == "12345"
    assert normalize_employee_number("  FINBC003  ") == "FINBC003"
    assert normalize_employee_number("0042") == "0042"
    assert normalize_employee_number("000123") == "000123"
    assert normalize_employee_number(None) is None
    assert normalize_employee_number(float("nan")) is None
    assert normalize_employee_number("nan") is None
    assert normalize_employee_number("NaN") is None
    assert normalize_employee_number("None") is None
    assert normalize_employee_number("") is None
    assert normalize_employee_number("-") is None
    assert normalize_employee_number("N/A") is None


def test_date_parsing():
    df = pd.DataFrame({
        "Employee Number": ["E01", "E02"],
        "Employee Name": ["Alice", "Bob"],
        "Date": ["2026-09-04", "2026-09-05"],
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
        assert cleaned_df.loc[1, "day_of_week"] == "Saturday"
        assert cleaned_df.loc[1, "day_of_week_number"] == 5
        assert cleaned_df.loc[1, "is_weekend"] == True
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_duration_and_time_to_minutes():
    assert parse_time_to_minutes("09:30") == 570
    assert parse_time_to_minutes("12:07") == 727
    assert parse_time_to_minutes("20:40") == 1240
    assert parse_time_to_minutes("0:00") == 0
    assert parse_time_to_minutes(None) is None
    assert parse_time_to_minutes("invalid") is None

    assert parse_duration_to_minutes("8:30") == 510
    assert parse_duration_to_minutes("8:33") == 513
    assert parse_duration_to_minutes("04:26") == 266
    assert parse_duration_to_minutes("4:06") == 246
    assert parse_duration_to_minutes("0:00") == 0
    assert parse_duration_to_minutes("28:15") == 28 * 60 + 15
    assert parse_duration_to_minutes(None) is None
    assert parse_duration_to_minutes("-") is None


def test_application_lag_calculation():
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
        assert cleaned_df.loc[0, "application_lag_days"] == -3
        assert cleaned_df.loc[1, "application_lag_days"] == 0
        assert cleaned_df.loc[2, "application_lag_days"] == 3
        assert pd.isna(cleaned_df.loc[3, "application_lag_days"])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_approval_turnaround_calculation():
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
        assert cleaned_df.loc[0, "approval_turnaround_days"] == 6
        assert pd.isna(cleaned_df.loc[1, "approval_turnaround_days"])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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


def test_missing_optional_columns():
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
        assert pd.isna(cleaned_df.loc[0, "in_time_minutes"])
        assert "Job Title" in report.missing_expected_optional_columns
        assert "Total Hours" in report.missing_expected_optional_columns
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_missing_required_columns():
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
        assert pd.notna(cleaned_df.loc[0, "Date"])
        assert cleaned_df.loc[0, "dq_invalid_date"] == False
        assert pd.isna(cleaned_df.loc[1, "Date"])
        assert cleaned_df.loc[1, "dq_invalid_date"] == True
        assert report.invalid_date_count == 1
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Targeted Stage 1 Hardening Tests (Tests 1 - 12) ───────────────────

# TEST 1 — HALF DAY PRESENT + LEAVE
def test_1_half_day_present_and_leave():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_A"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-01", "2026-10-01"],
        "Status": ["P", "CL"],
        "Attendance Type": ["Present", "Leave"],
        "Quantity": [0.5, 0.5],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert cleaned_df.loc[0, "daily_total_quantity"] == 1.0
        assert cleaned_df.loc[1, "daily_total_quantity"] == 1.0
        assert cleaned_df.loc[0, "dq_multiple_records_same_date"] == True
        assert cleaned_df.loc[1, "dq_multiple_records_same_date"] == True
        assert cleaned_df.loc[0, "dq_daily_quantity_exceeds_one"] == False
        assert cleaned_df.loc[1, "dq_daily_quantity_exceeds_one"] == False
        assert report.daily_quantity_exceeds_one_groups == 0
        critical_codes = [f["code"] for f in report.quality_findings if f["severity"] == "CRITICAL"]
        assert "DAILY_QUANTITY_EXCEEDS_ONE" not in critical_codes
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 2 — HALF DAY PRESENT + WFH
def test_2_half_day_present_and_wfh():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_A"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-01", "2026-10-01"],
        "Status": ["P", "WFH"],
        "Attendance Type": ["Present", "Work From Home"],
        "Quantity": [0.5, 0.5],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert cleaned_df.loc[0, "daily_total_quantity"] == 1.0
        assert cleaned_df.loc[0, "dq_daily_quantity_exceeds_one"] == False
        assert report.daily_quantity_exceeds_one_groups == 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 3 — QUANTITY EXCEEDS ONE
def test_3_quantity_exceeds_one():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_A"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-01", "2026-10-01"],
        "Status": ["P", "CL"],
        "Attendance Type": ["Present", "Leave"],
        "Quantity": [1.0, 0.5],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert cleaned_df.loc[0, "daily_total_quantity"] == 1.5
        assert cleaned_df.loc[1, "daily_total_quantity"] == 1.5
        assert cleaned_df.loc[0, "dq_daily_quantity_exceeds_one"] == True
        assert cleaned_df.loc[1, "dq_daily_quantity_exceeds_one"] == True
        assert report.daily_quantity_exceeds_one_groups == 1
        assert report.daily_quantity_exceeds_one_rows == 2
        assert report.max_daily_quantity == 1.5
        critical_codes = [f["code"] for f in report.quality_findings if f["severity"] == "CRITICAL"]
        assert "DAILY_QUANTITY_EXCEEDS_ONE" in critical_codes
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 4 — PARTIAL DAY ONLY
def test_4_partial_day_only():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-01"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
        "Quantity": [0.5],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert cleaned_df.loc[0, "daily_total_quantity"] == 0.5
        assert cleaned_df.loc[0, "dq_daily_quantity_exceeds_one"] == False
        assert report.daily_quantity_exceeds_one_groups == 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 5 — TWO SAME LEAVE ROWS
def test_5_two_same_leave_rows():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_A"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-01", "2026-10-01"],
        "Status": ["CL", "CL"],
        "Attendance Type": ["Leave", "Leave"],
        "Leave Name": ["Casual Leave Session 1", "Casual Leave Session 2"],
        "Quantity": [0.5, 0.5],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert cleaned_df.loc[0, "daily_total_quantity"] == 1.0
        # Not exact duplicates because Leave Name differs
        assert cleaned_df.loc[0, "dq_exact_duplicate"] == False
        assert cleaned_df.loc[1, "dq_exact_duplicate"] == False
        assert report.exact_duplicate_rows == 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 6 — EXACT DUPLICATE
def test_6_exact_duplicate():
    # Two completely identical original source rows
    row = {
        "Employee Number": "EMP_A",
        "Employee Name": "Alice",
        "Date": "2026-10-01",
        "Status": "P",
        "Attendance Type": "Present",
        "Quantity": "1.0",
    }
    df = pd.DataFrame([row, row])
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert len(cleaned_df) == 2  # Both rows preserved
        assert report.exact_duplicate_rows == 1
        assert cleaned_df.loc[0, "dq_exact_duplicate"] == False
        assert cleaned_df.loc[1, "dq_exact_duplicate"] == True
        warning_codes = [f["code"] for f in report.quality_findings if f["severity"] == "WARNING"]
        assert "EXACT_DUPLICATE" in warning_codes
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 7 — MISSING QUANTITY
def test_7_missing_quantity():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-01"],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Quantity": [None],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        assert pd.isna(cleaned_df.loc[0, "Quantity"])
        assert cleaned_df.loc[0, "dq_missing_quantity"] == True
        assert report.missing_quantity_count == 1
        warning_codes = [f["code"] for f in report.quality_findings if f["severity"] == "WARNING"]
        assert "MISSING_QUANTITY" in warning_codes
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 8 — RECORD ID
def test_8_record_id():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_A", "EMP_B"],
        "Employee Name": ["Alice", "Alice", "Bob"],
        "Date": ["2026-10-01", "2026-10-01", "2026-10-01"],
        "Status": ["P", "CL", "P"],
        "Attendance Type": ["Present", "Leave", "Present"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, _ = load_workforce_data(tmp_path)
        ids = cleaned_df["record_id"].tolist()
        assert len(ids) == 3
        assert len(set(ids)) == 3
        assert all(isinstance(rid, str) and rid.startswith("rec_") for rid in ids)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 9 — SOURCE ROW NUMBER
def test_9_source_row_number():
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_B", "EMP_C"],
        "Employee Name": ["Alice", "Bob", "Charlie"],
        "Date": ["2026-10-01", "2026-10-01", "2026-10-01"],
        "Status": ["P", "P", "P"],
        "Attendance Type": ["Present", "Present", "Present"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, _ = load_workforce_data(tmp_path)
        assert cleaned_df.loc[0, "source_row_number"] == 2
        assert cleaned_df.loc[1, "source_row_number"] == 3
        assert cleaned_df.loc[2, "source_row_number"] == 4
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 10 — CORE COMPLETENESS
def test_10_core_completeness():
    # 2 rows, in row 1 Employee Name is missing
    df = pd.DataFrame({
        "Employee Number": ["EMP_A", "EMP_B"],
        "Employee Name": ["Alice", None],
        "Date": ["2026-10-01", "2026-10-01"],
        "Status": ["P", "P"],
        "Attendance Type": ["Present", "Present"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        _, report = load_workforce_data(tmp_path)
        # Total core cells = 2 * 5 = 10; filled = 9 -> 90.0%
        assert report.core_data_completeness_percentage == 90.0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 11 — FULL COMPLETENESS
def test_11_full_completeness():
    # Only 5 core columns exist in file; optional columns are absent
    df = pd.DataFrame({
        "Employee Number": ["EMP_A"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-01"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        _, report = load_workforce_data(tmp_path)
        # Should not be penalized for absent optional columns; 5/5 = 100.0%
        assert report.full_data_completeness_percentage == 100.0
        assert len(report.missing_expected_optional_columns) > 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# TEST 12 — SEVERITY CLASSIFICATIONS
def test_12_severity_classifications():
    # Row 1 & 2: valid multiple records on same day (Quantity 0.5 + 0.5 = 1.0) -> INFO
    # Row 3 & 4: exact duplicates -> WARNING
    # Row 5 & 6: daily quantity exceeds 1 (1.0 + 0.5 = 1.5) -> CRITICAL
    df = pd.DataFrame({
        "Employee Number": ["E1", "E1", "E2", "E2", "E3", "E3"],
        "Employee Name": ["A", "A", "B", "B", "C", "C"],
        "Date": ["2026-10-01", "2026-10-01", "2026-10-02", "2026-10-02", "2026-10-03", "2026-10-03"],
        "Status": ["P", "CL", "P", "P", "P", "CL"],
        "Attendance Type": ["Present", "Leave", "Present", "Present", "Present", "Leave"],
        "Quantity": [0.5, 0.5, 1.0, 1.0, 1.0, 0.5],
    })
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        _, report = load_workforce_data(tmp_path)
        severities = {f["code"]: f["severity"] for f in report.quality_findings}
        assert severities.get("MULTIPLE_RECORDS_SAME_DATE") == "INFO"
        assert severities.get("EXACT_DUPLICATE") == "WARNING"
        assert severities.get("DAILY_QUANTITY_EXCEEDS_ONE") == "CRITICAL"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
