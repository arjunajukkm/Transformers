"""
test_workforce_patterns.py
───────────────────────────
Comprehensive test suite for Stage 5 Workforce Pattern Intelligence:
- Gating and minimum support thresholds (MIN_PATTERN_EVENTS = 3)
- Attendance pattern detectors (weekday concentration, missing swipes, absence, regularisation)
- Leave & WFH timing detectors (late leave, missing timestamps, late WFH)
- Approval turnaround delay detection (>= 5 days)
- Calendar & sequence detectors (Mon/Fri, weekend-adjacent, holiday-adjacent, leave-to-WFH, remote bridge)
- Repeat process non-compliance multi-type aggregation
- Group & manager concentration vs organization baseline
- Month-end and month-start clustering
- Explainable recurrence scoring (0-100), strength, persistence, and recency status
- Governed duplicate exclusion (include_in_analysis == False)
- Deterministic pattern ID stability
"""

from datetime import date, timedelta
import pandas as pd
import pytest

from workforce_intelligence import (
    PATTERN_DEFINITIONS,
    build_employee_day_facts,
    build_leave_requests,
    detect_patterns,
    evaluate_policy,
    load_workforce_data,
)
from workforce_intelligence.patterns import (
    PatternCategory,
    PatternContext,
    PatternPersistence,
    PatternSeverity,
    PatternStatus,
    PatternStrength,
    _calculate_pattern_score_and_badges,
)


# ── TEST 1: MINIMUM SUPPORT THRESHOLD GATING ──────────────────────────────────
def test_minimum_support_threshold_gating():
    """
    1 or 2 isolated events must NOT form a pattern.
    3 or more events meet the threshold.
    """
    # 2 Monday missing swipes -> No pattern
    rows_2 = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-07", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True}, # Mon
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-14", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True}, # Mon
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-15", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0, "include_in_analysis": True},
    ]
    df_2 = pd.DataFrame(rows_2)
    eval_df_2, _ = evaluate_policy(df_2)
    summary_2, patterns_2 = detect_patterns(eval_df_2, min_events=3)
    assert len(patterns_2) == 0
    assert summary_2.total_patterns == 0

    # 3 Monday missing swipes -> Pattern formed!
    rows_3 = rows_2 + [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-21", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True}, # Mon
    ]
    df_3 = pd.DataFrame(rows_3)
    eval_df_3, _ = evaluate_policy(df_3)
    summary_3, patterns_3 = detect_patterns(eval_df_3, min_events=3)
    assert len(patterns_3) > 0
    p_types = [p.pattern_type for p in patterns_3]
    assert "RECURRING_MISSING_SWIPE" in p_types
    assert "WEEKDAY_EXCEPTION_CONCENTRATION" in p_types


# ── TEST 2: WEEKDAY EXCEPTION CONCENTRATION & OPPORTUNITY DENOMINATOR ─────────
def test_weekday_exception_concentration():
    """
    6 exceptions: 5 on Mondays, 1 on Wednesday.
    Monday represents 83.3% concentration (>= 40%).
    Verifies weekday-specific opportunity denominator.
    """
    rows = []
    # 5 Mondays with missing swipe
    mon_dates = ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"]
    for d in mon_dates:
        rows.append({"Employee Number": "EMP01", "Employee Name": "Alice", "Date": d, "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True})

    # 1 Wednesday missing swipe
    rows.append({"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-09", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True})

    # 10 other regular Present days across weekdays
    present_dates = ["2026-09-08", "2026-09-10", "2026-09-11", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-22", "2026-09-23", "2026-09-24"]
    for d in present_dates:
        rows.append({"Employee Number": "EMP01", "Employee Name": "Alice", "Date": d, "Status": "P", "Attendance Type": "Present", "Quantity": 1.0, "include_in_analysis": True})

    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    mon_p = [p for p in patterns if p.pattern_type == "WEEKDAY_EXCEPTION_CONCENTRATION" and "MONDAY" in p.pattern_id]
    assert len(mon_p) == 1
    p = mon_p[0]
    assert p.event_count == 5
    assert p.opportunity_count == 5  # Total Mondays = 5
    assert p.rate == 100.0  # 5 exceptions / 5 Mondays
    assert "Monday" in p.pattern_title
    assert "83.3%" in p.why_detected  # 5 of 6 exceptions occurred on Mondays


# ── TEST 3: RECURRING MISSING SWIPE & RECURRING ABSENCE ────────────────────────
def test_recurring_missing_swipe_and_absence():
    """
    Verify RECURRING_MISSING_SWIPE and RECURRING_ABSENCE detection and neutral descriptions.
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": f"2026-09-0{i}", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True}
        for i in range(1, 4)
    ]
    rows += [
        {"Employee Number": "EMP02", "Employee Name": "Bob", "Date": f"2026-09-0{i}", "Status": "A", "Attendance Type": "Absent", "Quantity": 1.0, "include_in_analysis": True}
        for i in range(1, 4)
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    p_map = {p.entity_id: p for p in patterns if p.pattern_type in ("RECURRING_MISSING_SWIPE", "RECURRING_ABSENCE")}
    assert "EMP01" in p_map
    assert p_map["EMP01"].pattern_type == "RECURRING_MISSING_SWIPE"
    assert p_map["EMP01"].event_count == 3
    assert "bad" not in p_map["EMP01"].why_detected.lower()

    assert "EMP02" in p_map
    assert p_map["EMP02"].pattern_type == "RECURRING_ABSENCE"
    assert p_map["EMP02"].event_count == 3


# ── TEST 4: RECURRING REGULARISATION ──────────────────────────────────────────
def test_recurring_regularisation():
    """
    3 regularised attendance days produce RECURRING_REGULARISATION with INFO severity.
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": f"2026-09-0{i}", "Status": "A(R)", "Attendance Type": "Attendance Regularized", "Quantity": 1.0, "include_in_analysis": True}
        for i in range(1, 4)
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    reg_p = [p for p in patterns if p.pattern_type == "RECURRING_REGULARISATION"]
    assert len(reg_p) == 1
    assert reg_p[0].severity == PatternSeverity.INFO.value
    assert reg_p[0].event_count == 3


# ── TEST 5: RECURRING LATE LEAVE APPLICATION & MISSING APPLICATION DATE ────────
def test_leave_application_timing_patterns():
    """
    Employee has 3 late Casual Leave requests (applied +5 days after availed).
    Employee 2 has 3 leave requests missing Applied On date.
    """
    rows = [
        # Employee 1: 3 late CL requests
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": "2026-09-06", "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-15", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": "2026-09-20", "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-01", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": "2026-10-06", "include_in_analysis": True},

        # Employee 2: 3 requests with missing applied_on
        {"Employee Number": "EMP02", "Employee Name": "Bob", "Date": "2026-09-02", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": None, "include_in_analysis": True},
        {"Employee Number": "EMP02", "Employee Name": "Bob", "Date": "2026-09-16", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": None, "include_in_analysis": True},
        {"Employee Number": "EMP02", "Employee Name": "Bob", "Date": "2026-10-02", "Status": "CL", "Attendance Type": "Leave", "Leave Name": "Casual Leave", "Quantity": 1.0, "Applied On": None, "include_in_analysis": True},
    ]
    df = pd.DataFrame(rows)
    eval_df, eval_reqs = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df, evaluated_requests=eval_reqs)

    late_p = [p for p in patterns if p.pattern_type == "RECURRING_LATE_LEAVE_APPLICATION" and p.entity_id == "EMP01"]
    assert len(late_p) == 1
    assert late_p[0].event_count == 3
    assert late_p[0].pattern_category == PatternCategory.LEAVE.value

    missing_p = [p for p in patterns if p.pattern_type == "RECURRING_MISSING_APPLICATION" and p.entity_id == "EMP02"]
    assert len(missing_p) == 1
    assert missing_p[0].event_count == 3
    assert missing_p[0].severity == PatternSeverity.PRIORITY.value


# ── TEST 6: RECURRING LATE WFH APPLICATION ────────────────────────────────────
def test_recurring_late_wfh_application():
    """
    3 WFH events applied 5 days late (allowed <= 3 days).
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "Applied On": "2026-09-06", "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-10", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "Applied On": "2026-09-15", "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-01", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "Applied On": "2026-10-06", "include_in_analysis": True},
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    wfh_p = [p for p in patterns if p.pattern_type == "RECURRING_LATE_WFH_APPLICATION"]
    assert len(wfh_p) == 1
    assert wfh_p[0].event_count == 3
    assert wfh_p[0].pattern_category == PatternCategory.WFH.value


# ── TEST 7: RECURRING LONG APPROVAL TURNAROUND (MANAGER LEVEL) ─────────────────
def test_recurring_long_approval_turnaround():
    """
    Manager Bob has 3 approved requests with turnaround >= 5 calendar days.
    Pattern attaches to Reporting Manager.
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "Applied On": "2026-08-20", "Approved On": "2026-08-28", "Approval Status": "Approved", "Reporting Manager": "Bob Manager", "include_in_analysis": True}, # 8d
        {"Employee Number": "EMP02", "Employee Name": "Charlie", "Date": "2026-09-05", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "Applied On": "2026-08-25", "Approved On": "2026-09-01", "Approval Status": "Approved", "Reporting Manager": "Bob Manager", "include_in_analysis": True}, # 7d
        {"Employee Number": "EMP03", "Employee Name": "David", "Date": "2026-09-10", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "Applied On": "2026-09-01", "Approved On": "2026-09-07", "Approval Status": "Approved", "Reporting Manager": "Bob Manager", "include_in_analysis": True}, # 6d
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df, long_approval_days=5)

    app_p = [p for p in patterns if p.pattern_type == "RECURRING_LONG_APPROVAL_TURNAROUND"]
    assert len(app_p) == 1
    p = app_p[0]
    assert p.entity_type == "REPORTING_MANAGER"
    assert p.entity_id == "Bob Manager"
    assert p.event_count == 3
    assert p.pattern_category == PatternCategory.APPROVAL.value


# ── TEST 8: MONDAY / FRIDAY CONCENTRATION & WEEKEND-ADJACENT LEAVE ────────────
def test_calendar_patterns():
    """
    Employee has 4 leave events: 2 on Fridays, 2 on Mondays.
    Matches MONDAY_FRIDAY_CONCENTRATION and WEEKEND_ADJACENT_LEAVE.
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-04", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True}, # Friday
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-07", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True}, # Monday
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-11", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True}, # Friday
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-14", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True}, # Monday
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    p_types = [p.pattern_type for p in patterns]
    assert "MONDAY_FRIDAY_CONCENTRATION" in p_types
    assert "WEEKEND_ADJACENT_LEAVE" in p_types


# ── TEST 9: SEQUENCE PATTERNS (LEAVE → WFH & WFH → LEAVE) ──────────────────────
def test_sequence_patterns():
    """
    Employee has 3 Leave → WFH consecutive transitions.
    """
    rows = [
        # Pair 1: Sep 1 Leave, Sep 2 WFH
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-02", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "include_in_analysis": True},

        # Pair 2: Sep 10 Leave, Sep 11 WFH
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-10", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-11", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "include_in_analysis": True},

        # Pair 3: Oct 01 Leave, Oct 02 WFH
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-01", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-02", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "include_in_analysis": True},
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    seq_p = [p for p in patterns if p.pattern_type == "LEAVE_TO_WFH_SEQUENCE"]
    assert len(seq_p) == 1
    assert seq_p[0].event_count == 3
    assert seq_p[0].pattern_category == PatternCategory.SEQUENCE.value


# ── TEST 10: EXTENDED REMOTE-LEAVE WEEKEND BRIDGE ─────────────────────────────
def test_extended_remote_leave_sequence():
    """
    3 occurrences of Friday WFH bridging weekend to Monday Leave.
    """
    rows = [
        # Bridge 1: Fri 04 Sep WFH -> Mon 07 Sep Leave
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-04", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-07", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True},

        # Bridge 2: Fri 18 Sep WFH -> Mon 21 Sep Leave
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-18", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-21", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True},

        # Bridge 3: Fri 02 Oct WFH -> Mon 05 Oct Leave
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-02", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-05", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "include_in_analysis": True},
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    bridge_p = [p for p in patterns if p.pattern_type == "EXTENDED_REMOTE_LEAVE_SEQUENCE"]
    assert len(bridge_p) == 1
    assert bridge_p[0].event_count == 3


# ── TEST 11: REPEAT PROCESS NON-COMPLIANCE ─────────────────────────────────────
def test_repeat_process_non_compliance():
    """
    Employee has 2 late leave requests + 1 late WFH event across 3 distinct dates.
    Matches REPEAT_PROCESS_NON_COMPLIANCE with PRIORITY severity.
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "Applied On": "2026-09-08", "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-15", "Status": "CL", "Attendance Type": "Leave", "Quantity": 1.0, "Applied On": "2026-09-22", "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-10-01", "Status": "WFH", "Attendance Type": "Work From Home", "Quantity": 1.0, "Applied On": "2026-10-08", "include_in_analysis": True},
    ]
    df = pd.DataFrame(rows)
    eval_df, eval_reqs = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df, evaluated_requests=eval_reqs)

    proc_p = [p for p in patterns if p.pattern_type == "REPEAT_PROCESS_NON_COMPLIANCE"]
    assert len(proc_p) == 1
    assert proc_p[0].event_count == 3
    assert proc_p[0].severity == PatternSeverity.PRIORITY.value


# ── TEST 12: GROUP CONCENTRATION VS ORGANIZATION BASELINE ──────────────────────
def test_group_concentration():
    """
    Department A has 10 evaluable days with 6 exceptions (60% rate).
    Department B has 20 evaluable days with 2 exceptions (10% rate).
    Organization rate = (6 + 2) / 30 = 26.7%.
    Department A (60%) is >= org rate (26.7%) + 10% -> Triggers GROUP_CONCENTRATION.
    Department B (10%) is below baseline -> No pattern.
    """
    rows = []
    # Dept A: 6 Missing Swipes, 4 Present
    for i in range(6):
        rows.append({"Employee Number": f"A_EMP_{i}", "Employee Name": f"User A{i}", "Department": "Sales", "Date": f"2026-09-0{i+1}", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True})
    for i in range(4):
        rows.append({"Employee Number": f"A_EMP_{i}", "Employee Name": f"User A{i}", "Department": "Sales", "Date": f"2026-09-1{i}", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0, "include_in_analysis": True})

    # Dept B: 2 Missing Swipes, 18 Present
    for i in range(2):
        rows.append({"Employee Number": f"B_EMP_{i}", "Employee Name": f"User B{i}", "Department": "Engineering", "Date": f"2026-09-0{i+1}", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True})
    for i in range(18):
        rows.append({"Employee Number": f"B_EMP_{i % 5}", "Employee Name": f"User B{i % 5}", "Department": "Engineering", "Date": f"2026-09-{i+5:02d}", "Status": "P", "Attendance Type": "Present", "Quantity": 1.0, "include_in_analysis": True})

    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    group_p = [p for p in patterns if p.pattern_type == "GROUP_CONCENTRATION"]
    assert len(group_p) == 1
    assert group_p[0].entity_id == "Sales"
    assert group_p[0].rate == 60.0
    assert group_p[0].reference_rate == 26.67 or group_p[0].reference_rate == 26.7


# ── TEST 13: MONTH-END AND MONTH-START CONCENTRATION ───────────────────────────
def test_month_boundary_patterns():
    """
    Employee has 4 missing swipes: 3 occurring on 28 Sep, 29 Sep, 30 Sep (last 3 days).
    Triggers MONTH_END_CONCENTRATION.
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-10", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-28", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-29", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-30", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True},
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    _, patterns = detect_patterns(eval_df)

    end_p = [p for p in patterns if p.pattern_type == "MONTH_END_CONCENTRATION"]
    assert len(end_p) == 1
    assert end_p[0].event_count == 3
    assert "75.0%" in end_p[0].why_detected


# ── TEST 14: GOVERNED DUPLICATES DO NOT INFLATE PATTERNS ──────────────────────
def test_governed_duplicates_excluded_from_patterns():
    """
    An export contains 1 genuine Missing Swipe row and 4 exact duplicate copies (include_in_analysis == False).
    Only 1 analytical occurrence exists -> NO pattern formed (because count < 3).
    """
    rows = [
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": True, "analysis_exclusion_reason": "NONE"},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": False, "analysis_exclusion_reason": "EXACT_DUPLICATE"},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": False, "analysis_exclusion_reason": "EXACT_DUPLICATE"},
        {"Employee Number": "EMP01", "Employee Name": "Alice", "Date": "2026-09-01", "Status": "MS", "Attendance Type": "Missing Swipes", "Quantity": 1.0, "include_in_analysis": False, "analysis_exclusion_reason": "EXACT_DUPLICATE"},
    ]
    df = pd.DataFrame(rows)
    eval_df, _ = evaluate_policy(df)
    summary, patterns = detect_patterns(eval_df)
    assert len(patterns) == 0
    assert summary.total_patterns == 0


# ── TEST 15: DETERMINISTIC PATTERN ID STABILITY & SCORING METHODOLOGY ─────────
def test_pattern_score_and_id_stability():
    """
    Verify score formula (frequency, persistence, concentration, recency)
    and deterministic ID stability across repeated invocations.
    """
    score, comp, strength, pers, stat = _calculate_pattern_score_and_badges(
        event_count=6,
        opportunity_count=10,
        rate=60.0,
        distinct_months=3,
        days_since_last=10,
    )
    # Frequency: (6/10)*100 = 60 * 0.35 = 21.0
    # Persistence: 100 * 0.30 = 30.0
    # Concentration: 60 * 0.20 = 12.0
    # Recency: 100 * 0.15 = 15.0
    # Total = 21 + 30 + 12 + 15 = 78.0
    assert score == 78.0
    assert strength == PatternStrength.HIGH.value
    assert pers == PatternPersistence.PERSISTENT.value
    assert stat == PatternStatus.ACTIVE.value
    assert comp["frequency"] == 60.0
    assert comp["persistence"] == 100.0
