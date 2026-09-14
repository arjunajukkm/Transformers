"""
test_workforce_api.py
─────────────────────
Unit and integration tests for the FastAPI Workforce Intelligence endpoints.
Covers health, file upload, error handling, session summaries, governed KPI calculation,
pre-policy labeling, dynamic filter recalculation, and JSON serialization.
"""

import io
from pathlib import Path
import pandas as pd
import pytest
from starlette.testclient import TestClient

from workforce_app.backend.main import app
from workforce_app.backend.services.analysis_service import SESSION


@pytest.fixture(autouse=True)
def reset_session():
    """Reset the in-memory session between tests."""
    SESSION.filename = None
    SESSION.cleaned_df = None
    SESSION.evaluated_df = None
    SESSION.leave_requests = None
    SESSION.employee_day_facts = None
    SESSION.quality_report = None
    SESSION.upload_timestamp = None
    yield


client = TestClient(app)


# 1. Health endpoint
def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["service"] == "workforce-intelligence-api"
    assert data["dataset_loaded"] is False


# 2. Summary with no dataset loaded
def test_summary_no_dataset():
    res = client.get("/api/workforce/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is False
    assert "No workforce dataset loaded" in data["message"]


# 3. Unsupported file format rejection
def test_upload_unsupported_format():
    fake_file = io.BytesIO(b"dummy text content")
    res = client.post(
        "/api/workforce/upload",
        files={"file": ("test.txt", fake_file, "text/plain")},
    )
    assert res.status_code == 400
    assert "Unsupported file format" in res.json()["detail"]


# 4. Missing required columns
def test_upload_missing_required_columns():
    df = pd.DataFrame({
        "Employee Number": ["E01"],
        "Employee Name": ["Alice"],
        # Missing Date, Status, Attendance Type
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    res = client.post(
        "/api/workforce/upload",
        files={"file": ("missing_cols.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res.status_code == 422
    assert "missing required canonical columns" in res.json()["detail"].lower()


# 5. Upload valid dataset & verify summary
def test_upload_valid_sample_and_summary():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP02"],
        "Employee Name": ["Alice", "Bob"],
        "Date": ["2026-09-04", "2026-09-04"],
        "Status": ["P", "WFH"],
        "Attendance Type": ["Present", "Work From Home"],
        "Applied On": [None, "2026-09-04"],
        "Quantity": [1.0, 1.0],
        "Department": ["Engineering", "Product"],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    res = client.post(
        "/api/workforce/upload",
        files={"file": ("valid_sample.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is True
    assert data["dataset"]["rows"] == 2
    assert data["dataset"]["unique_employees"] == 2
    assert data["dataset"]["policy_period"] == "PRE_POLICY"
    assert data["quality"]["core_completeness"] == 100.0

    # Verify subsequent GET /api/workforce/summary
    res2 = client.get("/api/workforce/summary")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["loaded"] is True
    assert data2["dataset"]["rows"] == 2


# 6. Governed attendance metric & data-quality exclusion
def test_governed_attendance_metric_via_api():
    # 2 rows on same day with quantity = 2.0 (exceeds 1.0)
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-09-01", "2026-09-01"],
        "Status": ["A(R)", "WOH"],
        "Attendance Type": ["Regularized", "Worked on Holiday"],
        "Quantity": [1.0, 1.0],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    res = client.post(
        "/api/workforce/upload",
        files={"file": ("exceed_qty.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res.status_code == 200
    data = res.json()
    att = data["metrics"]["attendance_exception_rate"]
    assert att["eligible_employee_days_raw"] == 1
    assert att["data_quality_excluded_employee_days"] == 1
    assert att["evaluable_employee_days"] == 0
    assert att["attendance_exception_days"] == 0
    assert att["rate"] is None  # Safe when evaluable is 0


# 7. Pre-policy labels & observations
def test_pre_policy_labels_and_observations():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-09-04"],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Applied On": ["2026-09-04"],
        "Quantity": [1.0],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    res = client.post(
        "/api/workforce/upload",
        files={"file": ("pre_policy.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["dataset"]["policy_period"] == "PRE_POLICY"
    assert data["dataset"]["display_period"] is not None
    obs_texts = [o["text"] for o in data["observations"]]
    assert any("leave application compliance was" in t.lower() for t in obs_texts)


# 8. Filter endpoint & dynamic recalculation
def test_filters_recalculate_metrics():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP02"],
        "Employee Name": ["Alice", "Bob"],
        "Date": ["2026-09-04", "2026-09-04"],
        "Status": ["P", "A"],
        "Attendance Type": ["Present", "Absent"],
        "Quantity": [1.0, 1.0],
        "Department": ["Engineering", "Sales"],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    client.post(
        "/api/workforce/upload",
        files={"file": ("filtered.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    # Check available filters
    filter_res = client.get("/api/workforce/filters")
    assert filter_res.status_code == 200
    filters = filter_res.json()
    assert "Engineering" in filters["department"]
    assert "Sales" in filters["department"]

    # Filter to Engineering: only Alice (Present), 0 exceptions
    res_eng = client.get("/api/workforce/summary?department=Engineering")
    data_eng = res_eng.json()
    assert data_eng["dataset"]["rows"] == 1
    assert data_eng["metrics"]["attendance_exception_rate"]["attendance_exception_days"] == 0

    # Filter to Sales: only Bob (Absent), 1 exception
    res_sales = client.get("/api/workforce/summary?department=Sales")
    data_sales = res_sales.json()
    assert data_sales["dataset"]["rows"] == 1
    assert data_sales["metrics"]["attendance_exception_rate"]["attendance_exception_days"] == 1


# 9. Data quality findings serialization
def test_data_quality_findings_serialization():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-09-04", "2026-09-04"],
        "Status": ["P", "P"],
        "Attendance Type": ["Present", "Present"],
        "Quantity": ["1.0", "1.0"],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    res = client.post(
        "/api/workforce/upload",
        files={"file": ("dup.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert res.status_code == 200
    data = res.json()
    findings = data["quality"]["findings"]
    assert isinstance(findings, list)
    codes = [f["code"] for f in findings]
    assert "EXACT_DUPLICATE" in codes


# 10. Actual sample file upload via API endpoint
def test_actual_sample_file_api_smoke_test():
    sample_path = Path("local_data/Daily Performance Report 01 Sep 2026 - 13 Sep 2026 - FinBox.xlsx")
    if not sample_path.exists():
        pytest.skip("Local sample file not present.")

    with open(sample_path, "rb") as f:
        res = client.post(
            "/api/workforce/upload",
            files={"file": (sample_path.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["dataset"]["unique_employees"] == 6
    assert data["dataset"]["policy_period"] == "PRE_POLICY"
    assert data["dataset"]["display_period"] == "1–12 September 2026"
    assert data["quality"]["core_completeness"] == 100.0
    assert data["quality"]["critical_findings"] == 1
    att = data["metrics"]["attendance_exception_rate"]
    assert att["eligible_employee_days_raw"] == 8
    assert att["evaluable_employee_days"] == 7
    assert att["data_quality_excluded_employee_days"] == 1
    assert att["attendance_exception_days"] == 2
    assert att["rate"] == 28.57

    # Section 21 real September regressions
    leave_comp = data["metrics"]["pre_policy_leave_benchmark"]
    assert leave_comp["denominator"] == 1
    assert leave_comp["numerator"] == 1
    assert leave_comp["rate"] == 100.0

    wfh_comp = data["metrics"]["pre_policy_wfh_benchmark"]
    assert wfh_comp["denominator"] == 1
    assert wfh_comp["numerator"] == 1
    assert wfh_comp["rate"] == 100.0

    app = data["metrics"]["approval_turnaround"]
    assert app["median_approval_turnaround_days"] == 11.0



# 11. GET /api/workforce/trends/metrics returns grouped catalogue
def test_get_trend_metrics_catalogue():
    res = client.get("/api/workforce/trends/metrics")
    assert res.status_code == 200
    data = res.json()
    assert "Compliance" in data
    assert "Attendance" in data
    assert "Approval" in data
    assert "Working Time" in data
    comp_ids = [m["id"] for m in data["Compliance"]]
    assert "leave_application_compliance" in comp_ids
    att_ids = [m["id"] for m in data["Attendance"]]
    assert "attendance_exception_rate" in att_ids


# 12. GET /api/workforce/trends with no dataset loaded
def test_get_trends_no_dataset():
    res = client.get("/api/workforce/trends")
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is False
    assert "No workforce dataset loaded" in data["message"]


# 13. GET /api/workforce/trends invalid metric
def test_get_trends_invalid_metric():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-09-04"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
        "Quantity": [1.0],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    client.post(
        "/api/workforce/upload",
        files={"file": ("sample.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    res = client.get("/api/workforce/trends?metric=non_existent_metric")
    assert res.status_code == 400
    assert "Unknown trend metric" in res.json()["detail"]


# 14. GET /api/workforce/trends single-month dataset
def test_get_trends_single_month():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP02"],
        "Employee Name": ["Alice", "Bob"],
        "Date": ["2026-09-04", "2026-09-05"],
        "Status": ["P", "A"],
        "Attendance Type": ["Present", "Absent"],
        "Quantity": [1.0, 1.0],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    client.post(
        "/api/workforce/upload",
        files={"file": ("single_month.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    res = client.get("/api/workforce/trends?metric=attendance_exception_rate")
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is True
    assert len(data["time_series"]) == 1
    assert data["time_series"][0]["period_display"] == "Sep 2026"
    assert data["trend_direction"] == "INSUFFICIENT_DATA"
    assert data["current_value"] == 50.0
    assert any("more history is required" in o.lower() for o in data["observations"])


# 15. Multi-file upload via API
def test_multi_file_upload_via_api():
    df1 = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-08-04"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
        "Quantity": [1.0],
    })
    df2 = pd.DataFrame({
        "Employee Number": ["EMP02"],
        "Employee Name": ["Bob"],
        "Date": ["2026-09-04"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
        "Quantity": [1.0],
    })
    b1 = df1.to_csv(index=False).encode("utf-8")
    b2 = df2.to_csv(index=False).encode("utf-8")

    res = client.post(
        "/api/workforce/upload",
        files=[
            ("files", ("August.csv", io.BytesIO(b1), "text/csv")),
            ("files", ("September.csv", io.BytesIO(b2), "text/csv")),
        ],
    )
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is True
    assert data["dataset"]["rows"] == 2
    assert len(data["quality"]["source_files"]) == 2
    f_names = [f["file_name"] for f in data["quality"]["source_files"]]
    assert "August.csv" in f_names
    assert "September.csv" in f_names


# 16. Multi-file upload cross-file duplicate warning via API
def test_multi_file_cross_duplicate_via_api():
    df1 = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-09-04"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
        "Quantity": [1.0],
    })
    b1 = df1.to_csv(index=False).encode("utf-8")
    b2 = df1.to_csv(index=False).encode("utf-8")

    res = client.post(
        "/api/workforce/upload",
        files=[
            ("files", ("Month1.csv", io.BytesIO(b1), "text/csv")),
            ("files", ("Month2.csv", io.BytesIO(b2), "text/csv")),
        ],
    )
    assert res.status_code == 200
    data = res.json()
    assert data["quality"]["cross_file_exact_duplicate_rows"] == 1
    codes = [f["code"] for f in data["quality"]["findings"]]
    assert "CROSS_FILE_EXACT_DUPLICATE" in codes


# 17. Filter recalculation for trends
def test_trends_filter_recalculation():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP02", "EMP01", "EMP02"],
        "Employee Name": ["Alice", "Bob", "Alice", "Bob"],
        "Date": ["2026-08-01", "2026-08-01", "2026-09-01", "2026-09-01"],
        "Status": ["P", "A", "P", "P"],
        "Attendance Type": ["Present", "Absent", "Present", "Present"],
        "Quantity": [1.0, 1.0, 1.0, 1.0],
        "Department": ["Eng", "Sales", "Eng", "Sales"],
    })
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    client.post(
        "/api/workforce/upload",
        files={"file": ("dept_trends.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    # Filter by Eng: 0 exceptions in both Aug and Sep
    res_eng = client.get("/api/workforce/trends?metric=attendance_exception_rate&department=Eng")
    assert res_eng.status_code == 200
    data_eng = res_eng.json()
    assert len(data_eng["time_series"]) == 2
    assert all(pt["rate"] == 0.0 for pt in data_eng["time_series"])

    # Filter by Sales: Aug exception is 100%, Sep exception is 0%
    res_sales = client.get("/api/workforce/trends?metric=attendance_exception_rate&department=Sales")
    assert res_sales.status_code == 200
    data_sales = res_sales.json()
    assert len(data_sales["time_series"]) == 2
    assert data_sales["time_series"][0]["rate"] == 100.0
    assert data_sales["time_series"][1]["rate"] == 0.0


# 18. Multi-file duplicate governance via API: metrics not doubled
def test_multi_file_duplicate_governance_via_api():
    """
    Upload two files with overlapping records.
    Verify:
    - Source row count includes both
    - Duplicate warning returned
    - Duplicate exclusion count returned
    - Overview metric not doubled
    - Trend metric not doubled
    """
    # File 1: Sep 1, Sep 2
    df1 = pd.DataFrame([
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-02", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
    ])
    # File 2: Sep 2 (exact duplicate), Sep 3
    df2 = pd.DataFrame([
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-02", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-03", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
    ])

    b1 = df1.to_csv(index=False).encode("utf-8")
    b2 = df2.to_csv(index=False).encode("utf-8")

    res = client.post(
        "/api/workforce/upload",
        files=[
            ("files", ("Sep_Part1.csv", io.BytesIO(b1), "text/csv")),
            ("files", ("Sep_Part2.csv", io.BytesIO(b2), "text/csv")),
        ],
    )
    assert res.status_code == 200
    data = res.json()

    # 1. Source row count includes both
    assert data["dataset"]["rows"] == 4

    # 2. Duplicate warning and exclusion count returned
    assert data["quality"]["cross_file_exact_duplicate_rows"] == 1
    assert data["quality"]["duplicate_rows_excluded_from_analysis"] == 1
    codes = [f["code"] for f in data["quality"]["findings"]]
    assert "CROSS_FILE_EXACT_DUPLICATE" in codes

    # 3. Overview metric not doubled (3 evaluable employee-days, not 4)
    summary_res = client.get("/api/workforce/summary")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert summary_data["metrics"]["attendance_exception_rate"]["evaluable_employee_days"] == 3

    # 4. Trend metric not doubled (3 evaluable in Sep 2026 point, not 4)
    trend_res = client.get("/api/workforce/trends?metric=attendance_exception_rate")
    assert trend_res.status_code == 200
    trend_data = trend_res.json()
    assert len(trend_data["time_series"]) == 1
    assert trend_data["time_series"][0]["evaluable"] == 3


# 19. GET /api/workforce/patterns/catalogue
def test_get_pattern_catalogue():
    res = client.get("/api/workforce/patterns/catalogue")
    assert res.status_code == 200
    data = res.json()
    assert "Attendance" in data
    assert "Leave" in data
    assert "WFH" in data
    assert "Approval" in data
    assert "Calendar" in data
    assert "Sequence" in data
    assert "Process" in data
    p_types = [item["pattern_type"] for items in data.values() for item in items]
    assert "WEEKDAY_EXCEPTION_CONCENTRATION" in p_types
    assert "RECURRING_LATE_LEAVE_APPLICATION" in p_types


# 20. GET /api/workforce/patterns with no dataset loaded
def test_get_patterns_no_dataset():
    res = client.get("/api/workforce/patterns")
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is False
    assert "No workforce dataset loaded" in data["message"]
    assert data["patterns"] == []


# 21. GET /api/workforce/patterns with detected synthetic patterns and drilldown
def test_patterns_detection_and_drilldown_via_api():
    # 3 Missing Swipes for EMP01 (Attendance pattern), 3 Late CL for EMP02 (Leave pattern)
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Department": "Eng", "Date": "2026-09-01", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Department": "Eng", "Date": "2026-09-02", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Department": "Eng", "Date": "2026-09-03", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0},

        {"Employee Number": "EMP02", "Employee Name": "Bob", "Department": "Sales", "Date": "2026-09-01", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": "2026-09-06"},
        {"Employee Number": "EMP02", "Employee Name": "Bob", "Department": "Sales", "Date": "2026-09-10", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": "2026-09-15"},
        {"Employee Number": "EMP02", "Employee Name": "Bob", "Department": "Sales", "Date": "2026-10-01", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": "2026-10-06"},
    ]
    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
    client.post(
        "/api/workforce/upload",
        files={"file": ("patterns_sample.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    # 1. Fetch all patterns
    res = client.get("/api/workforce/patterns")
    assert res.status_code == 200
    data = res.json()
    assert data["loaded"] is True
    assert data["summary"]["total_patterns"] >= 2
    assert "category_counts" in data["summary"]

    p_ids = [p["pattern_id"] for p in data["patterns"]]
    assert any("RECURRING_MISSING_SWIPE" in pid for pid in p_ids)
    assert any("RECURRING_LATE_LEAVE_APPLICATION" in pid for pid in p_ids)

    # 2. Category filter: Leave
    res_leave = client.get("/api/workforce/patterns?category=Leave")
    assert res_leave.status_code == 200
    leave_data = res_leave.json()
    assert all(p["pattern_category"] == "Leave" for p in leave_data["patterns"])

    # 3. Department filter: Eng (recalculated population)
    res_eng = client.get("/api/workforce/patterns?department=Eng")
    assert res_eng.status_code == 200
    eng_data = res_eng.json()
    assert all(p["entity_id"] == "EMP01" or p["pattern_category"] == "Attendance" for p in eng_data["patterns"])

    # 4. Detail drilldown
    first_pid = data["patterns"][0]["pattern_id"]
    res_detail = client.get(f"/api/workforce/patterns/{first_pid}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["pattern_id"] == first_pid
    assert "evidence_items" in detail
    assert len(detail["evidence_items"]) >= 3



