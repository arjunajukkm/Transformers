"""
test_duplicate_governance.py
────────────────────────────
Unit and integration tests for Stage 4.1 Duplicate Governance:
- Deterministic duplicate precedence
- Analytical row governance (include_in_analysis, analysis_exclusion_reason)
- Dual daily quantities (raw_daily_total_quantity vs analytical_daily_total_quantity)
- Leave request reconstruction without duplicate inflation
- Employee-day facts duplicate governance
- WFH and approval analytics deduplication
- Working-time average weighting
- Synthetic overlapping multi-month exports
"""

from datetime import date
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pytest

from workforce_intelligence import (
    build_employee_day_facts,
    build_leave_requests,
    calculate_core_metrics,
    calculate_time_series_trends,
    evaluate_policy,
    load_workforce_data,
)


# ── TEST 1 — SAME-FILE EXACT DUPLICATE ─────────────────────────────────────────
def test_1_same_file_exact_duplicate():
    """
    Two identical source rows in a single file.
    Expected:
    - Both preserved
    - First: include_in_analysis = True, analysis_exclusion_reason = 'NONE'
    - Second: include_in_analysis = False, analysis_exclusion_reason = 'EXACT_DUPLICATE'
    - Duplicate warning exists
    - Analytics counts event once
    """
    row = {
        "Employee Number": "EMP001",
        "Employee Name": "Alice",
        "Date": "2026-09-01",
        "Status": "P",
        "Attendance Type": "Present",
        "Quantity": 1.0,
        "Business Unit": "Eng",
        "Department": "Product",
        "Sub Department": "Core",
        "Location": "Pune",
        "Reporting Manager": "Bob",
    }
    df = pd.DataFrame([row, row])
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as tmp:
        df.to_csv(tmp.name, index=False)
        path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(path)
        assert len(cleaned_df) == 2
        assert cleaned_df.iloc[0]["include_in_analysis"] == True
        assert cleaned_df.iloc[0]["analysis_exclusion_reason"] == "NONE"
        assert cleaned_df.iloc[1]["include_in_analysis"] == False
        assert cleaned_df.iloc[1]["analysis_exclusion_reason"] == "EXACT_DUPLICATE"
        assert report.exact_duplicate_rows == 1
        assert report.duplicate_rows_excluded_from_analysis == 1

        # Facts and core metrics count event once
        eval_df, _ = evaluate_policy(cleaned_df)
        facts = build_employee_day_facts(eval_df)
        assert len(facts) == 1
        assert facts.iloc[0]["record_count"] == 1
        assert facts.iloc[0]["raw_record_count"] == 2
        assert facts.iloc[0]["analytical_daily_total_quantity"] == 1.0
        assert facts.iloc[0]["raw_daily_total_quantity"] == 2.0
    finally:
        Path(path).unlink(missing_ok=True)


# ── TEST 2 — CROSS-FILE EXACT DUPLICATE ────────────────────────────────────────
def test_2_cross_file_exact_duplicate():
    """
    File A contains record X. File B contains exact record X.
    Expected:
    - Both preserved
    - File A occurrence included
    - File B duplicate excluded (analysis_exclusion_reason = 'CROSS_FILE_EXACT_DUPLICATE')
    - Cross-file warning exists
    - Analytics count once
    """
    row = {
        "Employee Number": "EMP001",
        "Employee Name": "Alice",
        "Date": "2026-09-01",
        "Status": "P",
        "Attendance Type": "Present",
        "Quantity": 1.0,
        "Business Unit": "Eng",
        "Department": "Product",
        "Sub Department": "Core",
        "Location": "Pune",
        "Reporting Manager": "Bob",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row]).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, report = load_workforce_data([path1, path2])
        assert len(combined_df) == 2
        assert combined_df.iloc[0]["include_in_analysis"] == True
        assert combined_df.iloc[0]["analysis_exclusion_reason"] == "NONE"
        assert combined_df.iloc[1]["include_in_analysis"] == False
        assert combined_df.iloc[1]["analysis_exclusion_reason"] == "CROSS_FILE_EXACT_DUPLICATE"
        assert report.cross_file_exact_duplicate_rows == 1
        assert report.duplicate_rows_excluded_from_analysis == 1

        eval_df, _ = evaluate_policy(combined_df)
        facts = build_employee_day_facts(eval_df)
        assert len(facts) == 1
        assert facts.iloc[0]["record_count"] == 1
        assert facts.iloc[0]["raw_record_count"] == 2
        assert facts.iloc[0]["analytical_daily_total_quantity"] == 1.0
        assert facts.iloc[0]["raw_daily_total_quantity"] == 2.0
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 3 — VALID HALF-DAY ───────────────────────────────────────────────────
def test_3_valid_half_day():
    """
    Present 0.5 + Leave 0.5.
    Expected:
    - Both include_in_analysis = True
    - analytical_daily_total_quantity = 1.0
    - raw_daily_total_quantity = 1.0
    - No duplicate exclusion
    """
    df = pd.DataFrame([
        {
            "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-01",
            "Status": "P", "Attendance Type": "Present", "Quantity": 0.5,
            "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
            "Location": "Pune", "Reporting Manager": "Bob",
        },
        {
            "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-01",
            "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 0.5,
            "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
            "Location": "Pune", "Reporting Manager": "Bob",
        },
    ])
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as tmp:
        df.to_csv(tmp.name, index=False)
        path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(path)
        assert len(cleaned_df) == 2
        assert cleaned_df.iloc[0]["include_in_analysis"] == True
        assert cleaned_df.iloc[1]["include_in_analysis"] == True
        assert cleaned_df.iloc[0]["analytical_daily_total_quantity"] == 1.0
        assert cleaned_df.iloc[0]["raw_daily_total_quantity"] == 1.0
        assert report.exact_duplicate_rows == 0
        assert report.duplicate_rows_excluded_from_analysis == 0
    finally:
        Path(path).unlink(missing_ok=True)


# ── TEST 4 — DUPLICATE FULL DAY ───────────────────────────────────────────────
def test_4_duplicate_full_day():
    """
    File A: Leave 1.0. File B: same Leave 1.0.
    Expected:
    - raw quantity = 2.0
    - analytical quantity = 1.0
    - no false analytical quantity >1 critical result
    - is_metric_evaluable = True
    """
    row = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-10-10",
        "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0,
        "Applied On": "2026-10-11", "Approved On": "2026-10-11", "Approval Status": "Approved",
        "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
        "Location": "Pune", "Reporting Manager": "Bob",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row]).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, report = load_workforce_data([path1, path2])
        assert combined_df.iloc[0]["raw_daily_total_quantity"] == 2.0
        assert combined_df.iloc[0]["analytical_daily_total_quantity"] == 1.0
        assert combined_df.iloc[0]["dq_analytical_daily_quantity_exceeds_one"] == False
        assert report.daily_quantity_exceeds_one_groups == 0
        crit_codes = [f["code"] for f in report.quality_findings if f["severity"] == "CRITICAL"]
        assert "DAILY_QUANTITY_EXCEEDS_ONE" not in crit_codes

        eval_df, _ = evaluate_policy(combined_df)
        facts = build_employee_day_facts(eval_df)
        assert len(facts) == 1
        assert facts.iloc[0]["is_metric_evaluable"] == True
        assert facts.iloc[0]["employee_day_quality_status"] == "WARNING"
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 5 — GENUINE OVER-QUANTITY ────────────────────────────────────────────
def test_5_genuine_over_quantity():
    """
    Present 1.0 + Leave 0.5 (distinct source rows).
    Expected:
    - both included
    - analytical quantity = 1.5
    - true critical quantity issue remains
    - is_metric_evaluable = False
    """
    df = pd.DataFrame([
        {
            "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-10-10",
            "Status": "P", "Attendance Type": "Present", "Quantity": 1.0,
            "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
            "Location": "Pune", "Reporting Manager": "Bob",
        },
        {
            "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-10-10",
            "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 0.5,
            "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
            "Location": "Pune", "Reporting Manager": "Bob",
        },
    ])
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as tmp:
        df.to_csv(tmp.name, index=False)
        path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(path)
        assert cleaned_df.iloc[0]["include_in_analysis"] == True
        assert cleaned_df.iloc[1]["include_in_analysis"] == True
        assert cleaned_df.iloc[0]["analytical_daily_total_quantity"] == 1.5
        assert cleaned_df.iloc[0]["dq_analytical_daily_quantity_exceeds_one"] == True
        assert report.daily_quantity_exceeds_one_groups == 1
        crit_codes = [f["code"] for f in report.quality_findings if f["severity"] == "CRITICAL"]
        assert "DAILY_QUANTITY_EXCEEDS_ONE" in crit_codes

        eval_df, _ = evaluate_policy(cleaned_df)
        facts = build_employee_day_facts(eval_df)
        assert len(facts) == 1
        assert facts.iloc[0]["is_metric_evaluable"] == False
        assert facts.iloc[0]["employee_day_quality_status"] == "CRITICAL"
    finally:
        Path(path).unlink(missing_ok=True)


# ── TEST 6 — DUPLICATE PL REQUEST ─────────────────────────────────────────────
def test_6_duplicate_pl_request():
    """
    Same 3-day PL request appears in two files.
    Expected:
    - request_total_quantity = 3.0 (not 6.0)
    - PL rule bucket remains <= 3 (requires 2 days advance notice)
    - Notice requirement is not distorted by duplicate rows
    """
    rows = [
        {
            "Employee Number": "EMP001", "Employee Name": "Alice", "Date": f"2026-10-0{i}",
            "Status": "PL", "Attendance Type": "Leave", "Leave Name": "Privilege Leave", "Quantity": 1.0,
            "Applied On": "2026-09-28", "Approved On": "2026-09-29", "Approval Status": "Approved",
            "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
            "Location": "Pune", "Reporting Manager": "Bob",
        }
        for i in (1, 2, 3)
    ]
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame(rows).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame(rows).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, _ = load_workforce_data([path1, path2])
        assert len(combined_df) == 6
        assert (combined_df["include_in_analysis"] == True).sum() == 3
        assert (combined_df["include_in_analysis"] == False).sum() == 3

        requests, _ = build_leave_requests(combined_df)
        assert len(requests) == 1
        req = requests[0]
        assert req.request_total_quantity == 3.0
        assert req.request_event_rows == 3

        # Evaluate policy on combined dataset
        _, eval_reqs = evaluate_policy(combined_df)
        assert len(eval_reqs) == 1
        # Applied 2026-09-28 for leave starting 2026-10-01 (3 days notice)
        # For duration <= 3, required notice is 2 days -> COMPLIANT!
        assert eval_reqs[0]["policy_compliant"] == True
        assert eval_reqs[0]["required_notice_days"] == 2
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 7 — DUPLICATE WFH ────────────────────────────────────────────────────
def test_7_duplicate_wfh():
    """
    Exact WFH event appears twice across files.
    Expected:
    - Compliance denominator = 1 (not 2)
    - Compliant count = 1
    - Rate = 100%
    """
    row = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-10-05",
        "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0,
        "Applied On": "2026-10-05", "Approved On": "2026-10-05", "Approval Status": "Approved",
        "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
        "Location": "Pune", "Reporting Manager": "Bob",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row]).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, _ = load_workforce_data([path1, path2])
        eval_df, _ = evaluate_policy(combined_df)
        metrics = calculate_core_metrics(eval_df)
        wfh_m = metrics["wfh_application_compliance"]
        assert wfh_m["denominator"] == 1
        assert wfh_m["numerator"] == 1
        assert wfh_m["rate"] == 100.0
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 8 — DUPLICATE ATTENDANCE EXCEPTION ───────────────────────────────────
def test_8_duplicate_attendance_exception():
    """
    Same Missing Swipe row appears twice across files.
    Expected:
    - Exactly 1 evaluable employee-day
    - Exactly 1 attendance exception day
    - Rate = 100%
    """
    row = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-02",
        "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0,
        "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
        "Location": "Pune", "Reporting Manager": "Bob",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row]).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, _ = load_workforce_data([path1, path2])
        eval_df, _ = evaluate_policy(combined_df)
        facts = build_employee_day_facts(eval_df)
        assert len(facts) == 1
        assert facts.iloc[0]["is_attendance_exception"] == True
        metrics = calculate_core_metrics(eval_df, employee_day_facts=facts)
        att = metrics["attendance_exception_rate"]
        assert att["evaluable_employee_days"] == 1
        assert att["attendance_exception_days"] == 1
        assert att["rate"] == 100.0
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 9 — DUPLICATE WORKING TIME ───────────────────────────────────────────
def test_9_duplicate_working_time():
    """
    Exact Present row appears twice.
    Expected:
    - Average/median hours are not double-weighted
    - Valid observation count = 2 (Alice and Charlie, not 3)
    """
    row1 = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-01",
        "Status": "P", "Attendance Type": "Present", "Quantity": 1.0,
        "Effective Hours": "8:00", "In Time": "09:00", "Out Time": "17:00",
        "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
        "Location": "Pune", "Reporting Manager": "Bob",
    }
    row2 = {
        "Employee Number": "EMP002", "Employee Name": "Charlie", "Date": "2026-09-01",
        "Status": "P", "Attendance Type": "Present", "Quantity": 1.0,
        "Effective Hours": "6:00", "In Time": "10:00", "Out Time": "16:00",
        "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
        "Location": "Pune", "Reporting Manager": "Bob",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row1, row2]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row1]).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, _ = load_workforce_data([path1, path2])
        eval_df, _ = evaluate_policy(combined_df)
        trends = calculate_time_series_trends(eval_df, metric_id="average_effective_hours")
        assert len(trends["time_series"]) == 1
        pt = trends["time_series"][0]
        assert pt["valid_observation_count"] == 2
        assert pt["value"] == 420.0  # 7 hours
        assert pt["formatted_value"] == "7h 00m"
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 10 — DUPLICATE APPROVAL ──────────────────────────────────────────────
def test_10_duplicate_approval():
    """
    Same approval record exists in overlapping files.
    Expected:
    - Approved count = 1
    - Turnaround observation count = 1
    """
    row = {
        "Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-01",
        "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0,
        "Applied On": "2026-08-25", "Approved On": "2026-08-30", "Approval Status": "Approved",
        "Business Unit": "Eng", "Department": "Product", "Sub Department": "Core",
        "Location": "Pune", "Reporting Manager": "Bob",
    }
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame([row]).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame([row]).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, _ = load_workforce_data([path1, path2])
        eval_df, _ = evaluate_policy(combined_df)
        metrics = calculate_core_metrics(eval_df)
        app = metrics["approval_turnaround"]
        assert app["approval_count"] == 1
        assert app["median_approval_turnaround_days"] == 5.0

        trend = calculate_time_series_trends(eval_df, metric_id="median_approval_turnaround")
        assert len(trend["time_series"]) == 1
        assert trend["time_series"][0]["valid_observation_count"] == 1
        assert trend["time_series"][0]["value"] == 5.0
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


# ── TEST 11 — SYNTHETIC OVERLAPPING FILE TEST ─────────────────────────────────
def test_11_synthetic_overlapping_file_exports():
    """
    Synthetic multi-month exports with deliberate overlap:
    September export includes 28 Sep, 29 Sep, 30 Sep.
    October export includes 30 Sep, 01 Oct, 02 Oct.
    30 Sep row is identical in both files.
    Verify:
    - 30 Sep duplicate is preserved
    - 30 Sep is counted once analytically
    - Monthly trend values for Sep and Oct are exact and non-inflated
    """
    sep_rows = [
        {"Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-28", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-29", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-30", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
    ]
    oct_rows = [
        {"Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-09-30", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-10-01", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Employee Name": "Alice", "Date": "2026-10-02", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f1:
        pd.DataFrame(sep_rows).to_csv(f1.name, index=False)
        path1 = f1.name

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="") as f2:
        pd.DataFrame(oct_rows).to_csv(f2.name, index=False)
        path2 = f2.name

    try:
        combined_df, report = load_workforce_data([path1, path2])
        assert len(combined_df) == 6
        assert report.cross_file_exact_duplicate_rows == 1
        assert report.duplicate_rows_excluded_from_analysis == 1

        eval_df, _ = evaluate_policy(combined_df)
        facts = build_employee_day_facts(eval_df)
        # Total days: 28 Sep, 29 Sep, 30 Sep, 01 Oct, 02 Oct = exactly 5 employee days!
        assert len(facts) == 5

        trends = calculate_time_series_trends(eval_df, metric_id="attendance_exception_rate")
        assert len(trends["time_series"]) == 2

        sep_point = [p for p in trends["time_series"] if p["period"] == "2026-09-01"][0]
        oct_point = [p for p in trends["time_series"] if p["period"] == "2026-10-01"][0]

        # Sep evaluable days: 28, 29, 30 Sep = 3 days (not 4)
        assert sep_point["evaluable"] == 3
        # Oct evaluable days: 01, 02 Oct = 2 days
        assert oct_point["evaluable"] == 2
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)
