"""
test_workforce_trends.py
─────────────────────────
Comprehensive test suite for Workforce Intelligence Time-Series & Trends Engine.
Validates monthly aggregations, governed denominators, time fields, trend direction,
streaks, regression detection, volume classification, multi-file IDs, and cross-file duplicates.
"""

from datetime import date, datetime
from pathlib import Path
import tempfile
import pandas as pd
import pytest

from workforce_intelligence import (
    DataQualityReport,
    build_employee_day_facts,
    calculate_time_series_trends,
    get_trend_metric_catalogue,
    load_workforce_data,
)
from workforce_intelligence.policy import evaluate_policy
from workforce_intelligence.trends import (
    TREND_METRICS,
    TrendPoint,
    calculate_streak,
    calculate_trend_direction,
    classify_volume_status,
    detect_regression,
    extract_canonical_month,
    format_duration_minutes,
    format_time_minutes,
)


@pytest.fixture
def synthetic_multi_month_data():
    """
    Generate synthetic workforce dataset spanning Aug 2026 to Dec 2026:
    - Aug: 2026-08-10, 2026-08-11
    - Sep: 2026-09-10, 2026-09-11
    - Oct: 2026-10-10, 2026-10-11 (Post-policy)
    - Nov: 2026-11-10, 2026-11-11
    - Dec: 2026-12-10, 2026-12-11
    """
    records = []
    # Aug: 10 days, 2 exceptions (20%)
    for i in range(1, 11):
        status = "A" if i <= 2 else "P"
        records.append({
            "Employee Number": f"EMP{i:03d}",
            "Employee Name": f"Employee {i}",
            "Date": "2026-08-10",
            "Status": status,
            "Attendance Type": "Present" if status == "P" else "Absent",
            "Quantity": 1.0,
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Sub Department": "Backend",
            "Location": "Mumbai",
            "Reporting Manager": "Manager Alpha",
            "In Time": "09:30",
            "Out Time": "18:30",
            "Effective Hours": "8:30",
            "Applied On": "2026-08-05",
            "Approved On": "2026-08-07",
            "Approval Status": "Approved",
            "Approved By": "Manager Alpha",
        })

    # Sep: 10 days, 1 exception (10%)
    for i in range(1, 11):
        status = "MS" if i == 1 else "P"
        records.append({
            "Employee Number": f"EMP{i:03d}",
            "Employee Name": f"Employee {i}",
            "Date": "2026-09-10",
            "Status": status,
            "Attendance Type": "Present" if status == "P" else "Missing Swipes",
            "Quantity": 1.0,
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Sub Department": "Backend",
            "Location": "Mumbai",
            "Reporting Manager": "Manager Alpha",
            "In Time": "09:15",
            "Out Time": "18:45",
            "Effective Hours": "8:45",
            "Applied On": "2026-09-05",
            "Approved On": "2026-09-06",
            "Approval Status": "Approved",
            "Approved By": "Manager Alpha",
        })

    # Oct: 10 days, 1 exception (10%)
    for i in range(1, 11):
        status = "A(R)" if i == 1 else "P"
        records.append({
            "Employee Number": f"EMP{i:03d}",
            "Employee Name": f"Employee {i}",
            "Date": "2026-10-10",
            "Status": status,
            "Attendance Type": "Present" if status == "P" else "Attendance Regularized",
            "Quantity": 1.0,
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Sub Department": "Backend",
            "Location": "Mumbai",
            "Reporting Manager": "Manager Alpha",
            "In Time": "09:00",
            "Out Time": "18:00",
            "Effective Hours": "8:15",
            "Applied On": "2026-10-05",
            "Approved On": "2026-10-06",
            "Approval Status": "Approved",
            "Approved By": "Manager Alpha",
        })

    # Nov: 10 days, 0 exceptions (0%)
    for i in range(1, 11):
        records.append({
            "Employee Number": f"EMP{i:03d}",
            "Employee Name": f"Employee {i}",
            "Date": "2026-11-10",
            "Status": "P",
            "Attendance Type": "Present",
            "Quantity": 1.0,
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Sub Department": "Backend",
            "Location": "Mumbai",
            "Reporting Manager": "Manager Alpha",
            "In Time": "09:10",
            "Out Time": "18:10",
            "Effective Hours": "8:00",
            "Applied On": "2026-11-05",
            "Approved On": "2026-11-06",
            "Approval Status": "Approved",
            "Approved By": "Manager Alpha",
        })

    # Dec: 10 days, 0 exceptions (0%)
    for i in range(1, 11):
        records.append({
            "Employee Number": f"EMP{i:03d}",
            "Employee Name": f"Employee {i}",
            "Date": "2026-12-10",
            "Status": "P",
            "Attendance Type": "Present",
            "Quantity": 1.0,
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Sub Department": "Backend",
            "Location": "Mumbai",
            "Reporting Manager": "Manager Alpha",
            "In Time": "09:20",
            "Out Time": "18:20",
            "Effective Hours": "8:10",
            "Applied On": "2026-12-05",
            "Approved On": "2026-12-06",
            "Approval Status": "Approved",
            "Approved By": "Manager Alpha",
        })

    raw_df = pd.DataFrame(records)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8") as f:
        raw_df.to_csv(f.name, index=False)
        temp_path = f.name

    cleaned_df, report = load_workforce_data(temp_path)
    eval_df, reqs = evaluate_policy(cleaned_df)
    facts = build_employee_day_facts(eval_df)
    Path(temp_path).unlink(missing_ok=True)
    return eval_df, reqs, facts


# 1. Canonical month generation
def test_1_canonical_month_generation():
    assert extract_canonical_month("2026-08-15") == "2026-08-01"
    assert extract_canonical_month("2026-09-01") == "2026-09-01"
    assert extract_canonical_month(pd.Timestamp("2026-10-31")) == "2026-10-01"
    assert extract_canonical_month(date(2026, 12, 5)) == "2026-12-01"
    assert extract_canonical_month(None) is None


# 2. Monthly compliance aggregation
def test_2_monthly_compliance_aggregation(synthetic_multi_month_data):
    eval_df, reqs, facts = synthetic_multi_month_data
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="leave_application_compliance")
    assert "time_series" in res
    assert res["metric"]["id"] == "leave_application_compliance"
    assert res["metric"]["direction"] == "higher_is_better"


# 3. Monthly governed attendance aggregation
def test_3_monthly_governed_attendance_aggregation(synthetic_multi_month_data):
    eval_df, reqs, facts = synthetic_multi_month_data
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="attendance_exception_rate")
    ts = res["time_series"]
    assert len(ts) == 5
    # Aug: 2 exceptions out of 10 = 20.0%
    assert ts[0]["period"] == "2026-08-01"
    assert ts[0]["rate"] == 20.0
    assert ts[0]["numerator"] == 2
    assert ts[0]["denominator"] == 10
    # Sep: 1 exception out of 10 = 10.0%
    assert ts[1]["period"] == "2026-09-01"
    assert ts[1]["rate"] == 10.0
    # Nov: 0 exceptions = 0.0%
    assert ts[3]["rate"] == 0.0


# 4. Missing swipe monthly rate
def test_4_missing_swipe_monthly_rate(synthetic_multi_month_data):
    eval_df, reqs, facts = synthetic_multi_month_data
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="missing_swipe_rate")
    ts = res["time_series"]
    # Sep has 1 missing swipe out of 10 = 10.0%
    sep_pt = [p for p in ts if p["period"] == "2026-09-01"][0]
    assert sep_pt["numerator"] == 1
    assert sep_pt["rate"] == 10.0


# 5. Absence monthly rate
def test_5_absence_monthly_rate(synthetic_multi_month_data):
    eval_df, reqs, facts = synthetic_multi_month_data
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="absence_rate")
    ts = res["time_series"]
    # Aug has 2 absents out of 10 = 20.0%
    aug_pt = [p for p in ts if p["period"] == "2026-08-01"][0]
    assert aug_pt["numerator"] == 2
    assert aug_pt["rate"] == 20.0


# 6. Regularisation monthly rate
def test_6_regularisation_monthly_rate(synthetic_multi_month_data):
    eval_df, reqs, facts = synthetic_multi_month_data
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="regularization_rate")
    ts = res["time_series"]
    # Oct has 1 regularized out of 10 = 10.0%
    oct_pt = [p for p in ts if p["period"] == "2026-10-01"][0]
    assert oct_pt["numerator"] == 1
    assert oct_pt["rate"] == 10.0
    assert res["metric"]["direction"] == "neutral"


# 7. Approval turnaround monthly aggregation
def test_7_approval_turnaround_monthly_aggregation(synthetic_multi_month_data):
    eval_df, reqs, facts = synthetic_multi_month_data
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="median_approval_turnaround")
    ts = res["time_series"]
    assert len(ts) == 5
    # Aug turnaround: applied 2026-08-05, approved 2026-08-07 -> 2 days
    aug_pt = [p for p in ts if p["period"] == "2026-08-01"][0]
    assert aug_pt["value"] == 2.0
    assert aug_pt["valid_observation_count"] == 10


# 8. Working time average ignores nulls
def test_8_working_time_average_ignores_nulls():
    df = pd.DataFrame([
        {"Date": "2026-08-01", "effective_hours_minutes": 480},
        {"Date": "2026-08-02", "effective_hours_minutes": pd.NA},
        {"Date": "2026-08-03", "effective_hours_minutes": 540},
    ])
    df["Date"] = pd.to_datetime(df["Date"])
    res = calculate_time_series_trends(df, metric_id="average_effective_hours")
    ts = res["time_series"]
    assert len(ts) == 1
    # mean of 480 and 540 is 510 minutes (8h 30m)
    assert ts[0]["value"] == 510.0
    assert ts[0]["valid_observation_count"] == 2
    assert ts[0]["formatted_value"] == "8h 30m"


# 9. Monthly median effective hours
def test_9_monthly_median_effective_hours():
    df = pd.DataFrame([
        {"Date": "2026-09-01", "effective_hours_minutes": 420},
        {"Date": "2026-09-02", "effective_hours_minutes": 480},
        {"Date": "2026-09-03", "effective_hours_minutes": 600},
    ])
    df["Date"] = pd.to_datetime(df["Date"])
    res = calculate_time_series_trends(df, metric_id="median_effective_hours")
    ts = res["time_series"]
    assert ts[0]["value"] == 480.0
    assert ts[0]["formatted_value"] == "8h 00m"


# 10. Arrival time aggregation
def test_10_arrival_time_aggregation():
    # 09:15 = 555 mins, 09:45 = 585 mins. Mean = 570 mins (09:30 AM)
    df = pd.DataFrame([
        {"Date": "2026-10-01", "in_time_minutes": 555},
        {"Date": "2026-10-02", "in_time_minutes": 585},
    ])
    df["Date"] = pd.to_datetime(df["Date"])
    res = calculate_time_series_trends(df, metric_id="average_arrival_time")
    ts = res["time_series"]
    assert ts[0]["value"] == 570.0
    assert ts[0]["formatted_value"] == "09:30 AM"


# 11. Exit time aggregation
def test_11_exit_time_aggregation():
    # 18:30 = 1110 mins (06:30 PM)
    df = pd.DataFrame([
        {"Date": "2026-10-01", "out_time_minutes": 1110},
    ])
    df["Date"] = pd.to_datetime(df["Date"])
    res = calculate_time_series_trends(df, metric_id="average_exit_time")
    ts = res["time_series"]
    assert ts[0]["value"] == 1110.0
    assert ts[0]["formatted_value"] == "06:30 PM"


# 12. Percentage-point change
def test_12_percentage_point_change():
    p1 = TrendPoint(period="2026-08-01", period_display="Aug 2026", value=72.0, formatted_value="72.0%")
    p2 = TrendPoint(period="2026-09-01", period_display="Sep 2026", value=81.0, formatted_value="81.0%")
    m_def = TREND_METRICS["leave_application_compliance"]
    from workforce_intelligence.trends import attach_mom_comparisons
    pts = attach_mom_comparisons([p1, p2], m_def)
    assert pts[1].mom_change == 9.0
    assert pts[1].mom_change_pp == 9.0


# 13. Higher-is-better improvement
def test_13_higher_is_better_improvement():
    m_def = TREND_METRICS["leave_application_compliance"]
    pts = [
        TrendPoint(period="2026-08-01", period_display="Aug 2026", value=70.0, formatted_value="70.0%"),
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=75.0, formatted_value="75.0%"),
        TrendPoint(period="2026-10-01", period_display="Oct 2026", value=80.0, formatted_value="80.0%"),
    ]
    direction = calculate_trend_direction(pts, m_def)
    assert direction == "IMPROVING"


# 14. Lower-is-better improvement
def test_14_lower_is_better_improvement():
    m_def = TREND_METRICS["attendance_exception_rate"]
    pts = [
        TrendPoint(period="2026-08-01", period_display="Aug 2026", value=15.0, formatted_value="15.0%"),
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=10.0, formatted_value="10.0%"),
        TrendPoint(period="2026-10-01", period_display="Oct 2026", value=5.0, formatted_value="5.0%"),
    ]
    direction = calculate_trend_direction(pts, m_def)
    assert direction == "IMPROVING"


# 15. Deterioration
def test_15_deterioration():
    m_def = TREND_METRICS["leave_application_compliance"]
    pts = [
        TrendPoint(period="2026-08-01", period_display="Aug 2026", value=90.0, formatted_value="90.0%"),
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=85.0, formatted_value="85.0%"),
        TrendPoint(period="2026-10-01", period_display="Oct 2026", value=78.0, formatted_value="78.0%"),
    ]
    direction = calculate_trend_direction(pts, m_def)
    assert direction == "DETERIORATING"


# 16. Stable classification
def test_16_stable_classification():
    m_def = TREND_METRICS["leave_application_compliance"]
    pts = [
        TrendPoint(period="2026-08-01", period_display="Aug 2026", value=80.0, formatted_value="80.0%"),
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=80.2, formatted_value="80.2%"),
        TrendPoint(period="2026-10-01", period_display="Oct 2026", value=80.1, formatted_value="80.1%"),
    ]
    direction = calculate_trend_direction(pts, m_def)
    assert direction == "STABLE"


# 17. Insufficient data
def test_17_insufficient_data():
    m_def = TREND_METRICS["attendance_exception_rate"]
    pts = [
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=6.8, formatted_value="6.8%"),
    ]
    direction = calculate_trend_direction(pts, m_def)
    assert direction == "INSUFFICIENT_DATA"


# 18. 3-month streak
def test_18_three_month_streak():
    m_def = TREND_METRICS["leave_application_compliance"]
    pts = [
        TrendPoint(period="2026-08-01", period_display="Aug 2026", value=70.0, formatted_value="70.0%"),
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=75.0, formatted_value="75.0%"),
        TrendPoint(period="2026-10-01", period_display="Oct 2026", value=80.0, formatted_value="80.0%"),
        TrendPoint(period="2026-11-01", period_display="Nov 2026", value=85.0, formatted_value="85.0%"),
    ]
    streak_dir, streak_months = calculate_streak(pts, m_def)
    assert streak_dir == "IMPROVING"
    assert streak_months == 3


# 19. Regression detection
def test_19_regression_detection():
    m_def = TREND_METRICS["leave_application_compliance"]
    # Oct improved, Nov improved, Dec worsened materially, Jan worsened again
    pts = [
        TrendPoint(period="2026-09-01", period_display="Sep 2026", value=70.0, formatted_value="70.0%"),
        TrendPoint(period="2026-10-01", period_display="Oct 2026", value=80.0, formatted_value="80.0%"),
        TrendPoint(period="2026-11-01", period_display="Nov 2026", value=72.0, formatted_value="72.0%"),
        TrendPoint(period="2026-12-01", period_display="Dec 2026", value=65.0, formatted_value="65.0%"),
    ]
    is_regression = detect_regression(pts, m_def)
    assert is_regression is True


# 20. LOW volume
def test_20_low_volume():
    assert classify_volume_status(5) == "LOW"
    assert classify_volume_status(1) == "LOW"
    assert classify_volume_status(9) == "LOW"


# 21. MODERATE volume
def test_21_moderate_volume():
    assert classify_volume_status(10) == "MODERATE"
    assert classify_volume_status(25) == "MODERATE"
    assert classify_volume_status(49) == "MODERATE"


# 22. HIGH volume
def test_22_high_volume():
    assert classify_volume_status(50) == "HIGH"
    assert classify_volume_status(150) == "HIGH"


# 23. Denominator zero returns None
def test_23_denominator_zero_returns_none():
    from workforce_intelligence.metrics import _safe_rate
    assert _safe_rate(0, 0) is None
    assert _safe_rate(5, 0) is None


# 24. Data-quality exclusions preserved
def test_24_data_quality_exclusions_preserved():
    # Employee day with quantity > 1.0 is excluded from evaluable attendance days
    df = pd.DataFrame([
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Date": "2026-09-01",
            "Status": "P",
            "Attendance Type": "Present",
            "Quantity": 2.0,
            "Business Unit": "Sales",
            "Department": "Sales",
            "Sub Department": "Field",
            "Location": "Mumbai",
            "Reporting Manager": "Bob",
        },
        {
            "Employee Number": "EMP002",
            "Employee Name": "Charlie",
            "Date": "2026-09-01",
            "Status": "P",
            "Attendance Type": "Present",
            "Quantity": 1.0,
            "Business Unit": "Sales",
            "Department": "Sales",
            "Sub Department": "Field",
            "Location": "Mumbai",
            "Reporting Manager": "Bob",
        }
    ])
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8") as f:
        df.to_csv(f.name, index=False)
        temp_path = f.name

    cleaned_df, report = load_workforce_data(temp_path)
    eval_df, reqs = evaluate_policy(cleaned_df)
    facts = build_employee_day_facts(eval_df)
    res = calculate_time_series_trends(eval_df, reqs, facts, metric_id="attendance_exception_rate")
    pt = res["time_series"][0]
    # Total raw = 2, excluded DQ = 1, evaluable = 1
    assert pt["total_applicable"] == 2
    assert pt["excluded_data_quality"] == 1
    assert pt["evaluable"] == 1
    assert pt["denominator"] == 1
    Path(temp_path).unlink(missing_ok=True)


# 25. Unique record IDs across files
def test_25_unique_record_ids_across_files():
    row1 = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-08-01",
        "Status": "P", "Attendance Type": "Present", "Quantity": 1.0,
        "Business Unit": "Sales", "Department": "Sales", "Sub Department": "Direct",
        "Location": "Pune", "Reporting Manager": "Boss 1",
    }
    row2 = {
        "Employee Number": "EMP002", "Employee Name": "Bob", "Date": "2026-09-01",
        "Status": "P", "Attendance Type": "Present", "Quantity": 1.0,
        "Business Unit": "Sales", "Department": "Sales", "Sub Department": "Direct",
        "Location": "Pune", "Reporting Manager": "Boss 1",
    }

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row1]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row2]).to_csv(f2.name, index=False)
        path2 = f2.name

    combined_df, report = load_workforce_data([path1, path2])
    assert len(combined_df) == 2
    ids = combined_df["record_id"].tolist()
    assert ids[0] == "f001_rec_000001"
    assert ids[1] == "f002_rec_000001"
    assert len(set(ids)) == 2
    assert len(report.source_files) == 2
    Path(path1).unlink(missing_ok=True)
    Path(path2).unlink(missing_ok=True)


# 26. Cross-file duplicate detection
def test_26_cross_file_duplicate_detection():
    identical_row = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-01",
        "Status": "P", "Attendance Type": "Present", "Quantity": 1.0,
        "Business Unit": "Sales", "Department": "Sales", "Sub Department": "Direct",
        "Location": "Pune", "Reporting Manager": "Boss 1",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([identical_row]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([identical_row]).to_csv(f2.name, index=False)
        path2 = f2.name

    combined_df, report = load_workforce_data([path1, path2])
    assert len(combined_df) == 2
    # First row is from file 1, not a cross-file duplicate
    assert combined_df.iloc[0]["dq_cross_file_exact_duplicate"] == False
    # Second row is from file 2, matches row in file 1 -> cross-file duplicate!
    assert combined_df.iloc[1]["dq_cross_file_exact_duplicate"] == True
    assert report.cross_file_exact_duplicate_rows == 1
    dup_findings = [f for f in report.quality_findings if f["code"] == "CROSS_FILE_EXACT_DUPLICATE"]
    assert len(dup_findings) == 1
    assert dup_findings[0]["severity"] == "WARNING"
    Path(path1).unlink(missing_ok=True)
    Path(path2).unlink(missing_ok=True)
