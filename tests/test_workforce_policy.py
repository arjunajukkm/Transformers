"""
test_workforce_policy.py
────────────────────────
Comprehensive test suite for the Workforce Intelligence Policy & Compliance Engine.
Validates notice periods, WFH application limits, multi-day PL request reconstruction,
pre-policy benchmarks vs post-policy enforcement, employee-day fact aggregation,
and data-quality uncertainty handling.
"""

import tempfile
from pathlib import Path
import pandas as pd
import pytest

from workforce_intelligence.ingestion import load_workforce_data
from workforce_intelligence.metrics import (
    build_employee_day_facts,
    calculate_compliance_breakdown,
    calculate_core_metrics,
)
from workforce_intelligence.policy import evaluate_policy
from workforce_intelligence.requests import build_leave_requests


# ── Helper for loading test data ──────────────────────────────────────

def _load_and_evaluate(df: pd.DataFrame):
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = tmp.name

    try:
        cleaned_df, report = load_workforce_data(tmp_path)
        eval_df, eval_reqs = evaluate_policy(cleaned_df)
        return eval_df, eval_reqs, report
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Test Cases 1 - 23 ─────────────────────────────────────────────────

# TEST 1 — NON-PL +3 DAYS
def test_1_non_pl_plus_3_days():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-10"],
        "Applied On": ["2026-10-13"],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "compliance_status"] == "COMPLIANT"
    assert eval_df.loc[0, "policy_rule_code"] == "NON_PL_APPLY_WITHIN_3D"


# TEST 2 — NON-PL +4 DAYS
def test_2_non_pl_plus_4_days():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-10"],
        "Applied On": ["2026-10-14"],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == False
    assert eval_df.loc[0, "compliance_status"] == "NON_COMPLIANT"
    assert eval_df.loc[0, "non_compliance_reason"] == "LATE_APPLICATION"


# TEST 3 — NON-PL ADVANCE APPLICATION
def test_3_non_pl_advance_application():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-10"],
        "Applied On": ["2026-10-05"],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "compliance_status"] == "COMPLIANT"


# TEST 4 — WFH +3 DAYS
def test_4_wfh_plus_3_days():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-10"],
        "Applied On": ["2026-10-13"],
        "Status": ["WFH"],
        "Attendance Type": ["Work From Home"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "compliance_status"] == "COMPLIANT"
    assert eval_df.loc[0, "policy_rule_code"] == "WFH_APPLY_WITHIN_3D"


# TEST 5 — WFH +4 DAYS
def test_5_wfh_plus_4_days():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-10"],
        "Applied On": ["2026-10-14"],
        "Status": ["WFH"],
        "Attendance Type": ["Work From Home"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == False
    assert eval_df.loc[0, "compliance_status"] == "NON_COMPLIANT"
    assert eval_df.loc[0, "non_compliance_reason"] == "LATE_APPLICATION"


# TEST 6 — PL <= 3 UNITS AT -2 DAYS
def test_6_pl_le_3_units_at_minus_2_days():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-20", "2026-10-21"],
        "Applied On": ["2026-10-18", "2026-10-18"],
        "Status": ["PL", "PL"],
        "Attendance Type": ["Leave", "Leave"],
        "Leave Name": ["Privilege Leave", "Privilege Leave"],
        "Quantity": [1.0, 1.0],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "policy_rule_code"] == "PL_NOTICE_2D"
    assert eval_df.loc[0, "compliance_status"] == "COMPLIANT"


# TEST 7 — PL <= 3 UNITS AT -1 DAY
def test_7_pl_le_3_units_at_minus_1_day():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-20", "2026-10-21"],
        "Applied On": ["2026-10-19", "2026-10-19"],
        "Status": ["PL", "PL"],
        "Attendance Type": ["Leave", "Leave"],
        "Leave Name": ["Privilege Leave", "Privilege Leave"],
        "Quantity": [1.0, 1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == False
    assert eval_df.loc[0, "compliance_status"] == "NON_COMPLIANT"
    assert eval_df.loc[0, "non_compliance_reason"] == "INSUFFICIENT_ADVANCE_NOTICE"


# TEST 8 — PL > 3 AND <= 7 AT -15 DAYS
def test_8_pl_medium_at_minus_15_days():
    dates = [f"2026-10-{d:02d}" for d in range(20, 25)]  # 5 days
    df = pd.DataFrame({
        "Employee Number": ["EMP01"] * 5,
        "Employee Name": ["Alice"] * 5,
        "Date": dates,
        "Applied On": ["2026-10-05"] * 5,  # 15 days prior to 20 Oct
        "Status": ["PL"] * 5,
        "Attendance Type": ["Leave"] * 5,
        "Leave Name": ["Privilege Leave"] * 5,
        "Quantity": [1.0] * 5,
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "policy_rule_code"] == "PL_NOTICE_15D"


# TEST 9 — PL > 3 AND <= 7 AT -14 DAYS
def test_9_pl_medium_at_minus_14_days():
    dates = [f"2026-10-{d:02d}" for d in range(20, 25)]  # 5 days
    df = pd.DataFrame({
        "Employee Number": ["EMP01"] * 5,
        "Employee Name": ["Alice"] * 5,
        "Date": dates,
        "Applied On": ["2026-10-06"] * 5,  # 14 days prior to 20 Oct
        "Status": ["PL"] * 5,
        "Attendance Type": ["Leave"] * 5,
        "Leave Name": ["Privilege Leave"] * 5,
        "Quantity": [1.0] * 5,
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == False
    assert eval_df.loc[0, "non_compliance_reason"] == "INSUFFICIENT_ADVANCE_NOTICE"


# TEST 10 — PL > 7 AT -30 DAYS
def test_10_pl_long_at_minus_30_days():
    dates = [f"2026-11-{d:02d}" for d in range(20, 28)]  # 8 days
    df = pd.DataFrame({
        "Employee Number": ["EMP01"] * 8,
        "Employee Name": ["Alice"] * 8,
        "Date": dates,
        "Applied On": ["2026-10-21"] * 8,  # 30 days prior to 20 Nov
        "Status": ["PL"] * 8,
        "Attendance Type": ["Leave"] * 8,
        "Leave Name": ["Privilege Leave"] * 8,
        "Quantity": [1.0] * 8,
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "policy_rule_code"] == "PL_NOTICE_30D"


# TEST 11 — PL > 7 AT -29 DAYS
def test_11_pl_long_at_minus_29_days():
    dates = [f"2026-11-{d:02d}" for d in range(20, 28)]  # 8 days
    df = pd.DataFrame({
        "Employee Number": ["EMP01"] * 8,
        "Employee Name": ["Alice"] * 8,
        "Date": dates,
        "Applied On": ["2026-10-22"] * 8,  # 29 days prior to 20 Nov
        "Status": ["PL"] * 8,
        "Attendance Type": ["Leave"] * 8,
        "Leave Name": ["Privilege Leave"] * 8,
        "Quantity": [1.0] * 8,
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == False
    assert eval_df.loc[0, "non_compliance_reason"] == "INSUFFICIENT_ADVANCE_NOTICE"


# TEST 12 — HALF-DAY PL
def test_12_half_day_pl():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-20"],
        "Applied On": ["2026-10-18"],
        "Status": ["PL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Privilege Leave"],
        "Quantity": [0.5],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_rule_code"] == "PL_NOTICE_2D"
    assert eval_df.loc[0, "required_notice_days"] == 2
    assert eval_df.loc[0, "policy_compliant"] == True


# TEST 13 — MULTI-DAY PL REQUEST
def test_13_multi_day_pl_request():
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice", "Alice"],
        "Date": ["2026-10-20", "2026-10-21", "2026-10-22"],
        "Applied On": ["2026-10-18", "2026-10-18", "2026-10-18"],
        "Status": ["PL", "PL", "PL"],
        "Attendance Type": ["Leave", "Leave", "Leave"],
        "Leave Name": ["Privilege Leave", "Privilege Leave", "Privilege Leave"],
        "Quantity": [1.0, 1.0, 0.5],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert len(eval_reqs) == 1
    req = eval_reqs[0]
    assert req["request_total_quantity"] == 2.5
    assert req["policy_rule_code"] == "PL_NOTICE_2D"
    assert req["policy_compliant"] == True
    assert len(req["record_ids"]) == 3
    assert len(req["source_row_numbers"]) == 3


# TEST 14 — PRE-POLICY FAIL
def test_14_pre_policy_fail():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-09-20"],
        "Applied On": ["2026-09-26"],  # +6 days
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_period"] == "PRE_POLICY"
    assert eval_df.loc[0, "benchmark_compliant"] == False
    assert pd.isna(eval_df.loc[0, "policy_compliant"])
    assert eval_df.loc[0, "compliance_status"] == "PRE_POLICY_BENCHMARK_FAIL"


# TEST 15 — PRE-POLICY PASS
def test_15_pre_policy_pass():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-09-20"],
        "Applied On": ["2026-09-22"],  # +2 days
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_period"] == "PRE_POLICY"
    assert eval_df.loc[0, "benchmark_compliant"] == True
    assert pd.isna(eval_df.loc[0, "policy_compliant"])
    assert eval_df.loc[0, "compliance_status"] == "PRE_POLICY_BENCHMARK_PASS"


# TEST 16 — EXACT EFFECTIVE DATE
def test_16_exact_effective_date():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-01"],
        "Applied On": ["2026-10-02"],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_period"] == "POST_POLICY"
    assert eval_df.loc[0, "policy_compliant"] == True
    assert eval_df.loc[0, "compliance_status"] == "COMPLIANT"


# TEST 17 — MISSING APPLIED ON
def test_17_missing_applied_on():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-05"],
        "Applied On": [None],
        "Status": ["CL"],
        "Attendance Type": ["Leave"],
        "Leave Name": ["Casual Leave"],
        "Quantity": [1.0],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_compliant"] == False
    assert eval_df.loc[0, "compliance_status"] == "NON_COMPLIANT"
    assert eval_df.loc[0, "non_compliance_reason"] == "MISSING_APPLICATION_DATE"


# TEST 18 — CRITICAL DATA QUALITY
def test_18_critical_data_quality():
    # Leave on day where daily quantity exceeds 1 (e.g. 1.0 + 0.5 = 1.5)
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-05", "2026-10-05"],
        "Applied On": ["2026-10-05", "2026-10-05"],
        "Status": ["CL", "CL"],
        "Attendance Type": ["Leave", "Leave"],
        "Leave Name": ["Casual Leave", "Casual Leave"],
        "Quantity": [1.0, 0.5],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "compliance_status"] == "DATA_QUALITY_UNCERTAIN"
    assert pd.isna(eval_df.loc[0, "policy_compliant"])
    assert eval_df.loc[0, "non_compliance_reason"] == "SOURCE_DATA_QUALITY_CRITICAL"


# TEST 19 — NON-APPLICABLE PRESENT
def test_19_non_applicable_present():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-05"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    assert eval_df.loc[0, "policy_rule_code"] == "NOT_APPLICABLE"
    assert eval_df.loc[0, "compliance_status"] == "NOT_APPLICABLE"
    assert pd.isna(eval_df.loc[0, "policy_compliant"])


# TEST 20 — EMPLOYEE-DAY EXCEPTION
def test_20_employee_day_exception():
    # Present 0.5 + Leave 0.5
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-05", "2026-10-05"],
        "Status": ["P", "CL"],
        "Attendance Type": ["Present", "Leave"],
        "Quantity": [0.5, 0.5],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert len(facts) == 1
    assert facts.loc[0, "has_present"] == True
    assert facts.loc[0, "has_leave"] == True
    assert facts.loc[0, "is_attendance_exception"] == False


# TEST 21 — MISSING SWIPE
def test_21_missing_swipe():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-05"],
        "Status": ["P(MS)"],
        "Attendance Type": ["Missing Swipes"],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert facts.loc[0, "is_attendance_exception"] == True
    assert "MISSING_SWIPE" in facts.loc[0, "attendance_exception_types"]


# TEST 22 — PURE WEEK OFF
def test_22_pure_week_off():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-04"],
        "Status": ["WO"],
        "Attendance Type": ["Week Off"],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert facts.loc[0, "has_week_off"] == True
    assert facts.loc[0, "is_eligible_attendance_day"] == False


# TEST 23 — WORKED HOLIDAY / ACTIVE EVENT
def test_23_worked_holiday_active_event():
    # Worked on Holiday
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-02"],
        "Status": ["WOH"],
        "Attendance Type": ["Worked on Holiday"],
    })
    eval_df, _, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert facts.loc[0, "has_present"] == True
    assert facts.loc[0, "is_eligible_attendance_day"] == True


# ── Additional Core Metrics & Breakdown Tests ─────────────────────────

def test_core_metrics_calculation():
    df = pd.DataFrame({
        "Employee Number": ["E1", "E2", "E3"],
        "Employee Name": ["A", "B", "C"],
        "Date": ["2026-10-01", "2026-10-01", "2026-10-01"],
        "Applied On": ["2026-10-02", "2026-10-06", "2026-10-02"],
        "Status": ["CL", "CL", "WFH"],
        "Attendance Type": ["Leave", "Leave", "Work From Home"],
        "Leave Name": ["Casual Leave", "Casual Leave", None],
        "Quantity": [1.0, 1.0, 1.0],
        "Approval Status": ["Approved", "Pending", "Approved"],
        "Approved On": ["2026-10-05", None, "2026-10-04"],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    metrics = calculate_core_metrics(eval_df, eval_reqs)

    # Leave: E1 compliant (applied +1d), E2 non-compliant (applied +5d) -> 1/2 = 50.0%
    assert metrics["overall_leave_application_compliance"]["numerator"] == 1
    assert metrics["overall_leave_application_compliance"]["denominator"] == 2
    assert metrics["overall_leave_application_compliance"]["rate"] == 50.0

    # WFH: E3 compliant (applied +1d) -> 1/1 = 100.0%
    assert metrics["wfh_application_compliance"]["numerator"] == 1
    assert metrics["wfh_application_compliance"]["denominator"] == 1
    assert metrics["wfh_application_compliance"]["rate"] == 100.0

    # Approvals: 2 approved records (turnarounds: 3 days, 2 days)
    assert metrics["approval_turnaround"]["approval_count"] == 2
    assert metrics["approval_turnaround"]["average_approval_turnaround_days"] == 2.5
    assert metrics["approval_turnaround"]["pending_approval_count"] == 1


# ── Analytical Correction Tests: Governed Metrics & DQ Exclusions ─────

def test_governed_attendance_exception_dq_excluded():
    # Employee-day is an attendance exception but has daily quantity exceeds one
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-01", "2026-10-01"],
        "Status": ["A(R)", "WOH"],
        "Attendance Type": ["Regularized", "Worked on Holiday"],
        "Quantity": [1.0, 1.0],  # sum = 2.0 > 1.0
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert len(facts) == 1
    assert facts.loc[0, "employee_day_quality_status"] == "CRITICAL"
    assert facts.loc[0, "is_metric_evaluable"] == False
    assert "DAILY_QUANTITY_EXCEEDS_ONE" in facts.loc[0, "metric_exclusion_reason"]
    assert facts.loc[0, "is_attendance_exception"] == True

    # Governed metrics check: excluded from denominator and numerator
    metrics = calculate_core_metrics(eval_df, eval_reqs, facts)
    att = metrics["attendance_exception_rate"]
    assert att["eligible_employee_days_raw"] == 1
    assert att["evaluable_employee_days"] == 0
    assert att["data_quality_excluded_employee_days"] == 1
    assert att["attendance_exception_days"] == 0
    assert att["rate"] is None  # safe when denominator is 0
    # Raw metrics check
    assert att["raw_attendance_exception_days"] == 1
    assert att["raw_attendance_exception_rate"] == 100.0


def test_governed_attendance_exception_valid_missing_swipe():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-01"],
        "Status": ["P(MS)"],
        "Attendance Type": ["Missing Swipes"],
        "Quantity": [1.0],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert facts.loc[0, "is_metric_evaluable"] == True
    assert facts.loc[0, "is_attendance_exception"] == True

    metrics = calculate_core_metrics(eval_df, eval_reqs, facts)
    att = metrics["attendance_exception_rate"]
    assert att["evaluable_employee_days"] == 1
    assert att["attendance_exception_days"] == 1
    assert att["rate"] == 100.0


def test_governed_attendance_valid_present():
    df = pd.DataFrame({
        "Employee Number": ["EMP01"],
        "Employee Name": ["Alice"],
        "Date": ["2026-10-01"],
        "Status": ["P"],
        "Attendance Type": ["Present"],
        "Quantity": [1.0],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    facts = build_employee_day_facts(eval_df)
    assert facts.loc[0, "is_metric_evaluable"] == True
    assert facts.loc[0, "is_attendance_exception"] == False

    metrics = calculate_core_metrics(eval_df, eval_reqs, facts)
    att = metrics["attendance_exception_rate"]
    assert att["evaluable_employee_days"] == 1
    assert att["attendance_exception_days"] == 0
    assert att["rate"] == 0.0


def test_governed_leave_compliance_dq_uncertain():
    # Leave request on day with daily quantity exceeds 1
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-05", "2026-10-05"],
        "Applied On": ["2026-10-05", "2026-10-05"],
        "Status": ["CL", "CL"],
        "Attendance Type": ["Leave", "Leave"],
        "Leave Name": ["Casual Leave", "Casual Leave"],
        "Quantity": [1.0, 0.5],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    metrics = calculate_core_metrics(eval_df, eval_reqs)
    leave_met = metrics["overall_leave_application_compliance"]
    assert leave_met["total_applicable"] == 1
    assert leave_met["excluded_data_quality"] == 1
    assert leave_met["data_quality_uncertain_count"] == 1
    assert leave_met["evaluable"] == 0
    assert leave_met["denominator"] == 0
    assert leave_met["numerator"] == 0
    assert leave_met["rate"] is None


def test_governed_wfh_compliance_dq_uncertain():
    # WFH event on day with daily quantity exceeds 1
    df = pd.DataFrame({
        "Employee Number": ["EMP01", "EMP01"],
        "Employee Name": ["Alice", "Alice"],
        "Date": ["2026-10-05", "2026-10-05"],
        "Applied On": ["2026-10-05", "2026-10-05"],
        "Status": ["WFH", "P"],
        "Attendance Type": ["Work From Home", "Present"],
        "Quantity": [1.0, 0.5],
    })
    eval_df, eval_reqs, _ = _load_and_evaluate(df)
    metrics = calculate_core_metrics(eval_df, eval_reqs)
    wfh_met = metrics["wfh_application_compliance"]
    assert wfh_met["total_applicable"] == 1
    assert wfh_met["excluded_data_quality"] == 1
    assert wfh_met["data_quality_uncertain_count"] == 1
    assert wfh_met["evaluable"] == 0
    assert wfh_met["rate"] is None

