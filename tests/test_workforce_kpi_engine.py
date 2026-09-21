"""
tests/test_workforce_kpi_engine.py
───────────────────────────────────
Deterministic, comprehensive automated test suite for the Transformers 2.0
Workforce Intelligence KPI Calculation Engine (Step 18).

Covers all 24 required test scenarios from Part 8:
 1. Distinct employee headcount.
 2. Half-day attendance composition.
 3. Attendance exceptions overlapping with Present.
 4. Explicit absence and unresolved-status handling.
 5. Leave request identity and inferred-grouping separation.
 6. Prior, same-day, and retrospective applications.
 7. Approval ownership and turnaround.
 8. Independent Leave and WFH calculations.
 9. Monthly WFH allowance reset.
10. Half-day WFH quantities.
11. Multi-month WFH excess.
12. Distinct employee counting across months.
13. Partially observed calendar months.
14. Employee transfers between Business Units.
15. Business Unit average punch calculations.
16. Exactly 60-minute versus greater-than-60-minute deviations.
17. Overnight punch handling.
18. Missing-punch and invalid-duration handling.
19. Duration-band reconciliation.
20. Adjustable repeated-exception threshold.
21. Correct filtered-scope numerators and denominators.
22. Source-record traceability.
23. No input DataFrame mutation.
24. Compatibility with existing snapshots and legacy calculations.
"""

from datetime import date
import pandas as pd
import pytest

from storage.cache_manager import AnalyticalSnapshot
from storage.snapshot_service import (
    TimeSeriesSnapshotService,
    create_snapshot,
    normalize_dataset_dataframe,
)
from workforce_intelligence.data_foundation import (
    CanonicalWorkforceData,
    WorkforceRequest,
)
from workforce_intelligence.kpi_engine import (
    compute_punch_deviations_bu,
    compute_repeated_exceptions,
    compute_wfh_allowance_monthly,
    compute_workforce_intelligence_bundle,
    hours_to_duration_str,
    minutes_to_time_str,
)
from workforce_intelligence.snapshot_bridge import (
    WorkforceIntelligenceBridge,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures & Synthetic Datasets
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base_workforce_df() -> pd.DataFrame:
    """
    Multi-employee, multi-month synthetic dataset covering:
    - E001 (Alice): Half-day Present + Half-day Leave, WFH, Missing Swipe, Absent, Dec WFH excess (5 days)
    - E002 (Bob): Nov WFH excess (4 days), Dec within allowance (2 days)
    - E003 (Charlie): BU transfer (Nov Lending -> Dec Retail), Overnight punch (22:00 -> 06:00)
    - E004 (David): Late punch deviation test (>60 min)
    - E005 (Emma): Exact 60 min deviation test
    """
    rows = [
        # ── E001 (Alice) - Nov 2026 ──
        # Nov 2: Full day present (09:00 - 18:00 = 9h)
        {
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-11-02",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "18:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # Nov 3: Half-day Present (0.5), Half-day Leave (0.5)
        {
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-11-03",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 0.5,
            "In Time": "09:00",
            "Out Time": "13:30",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        {
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-11-03",
            "Month": "Nov 2026",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 0.5,
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Employee",
            "Applied On": "2026-11-01",  # Prior (+2 days)
            "Approved By": "Manager",
            "Approved On": "2026-11-02", # 1 day turnaround
        },
        # Nov 4: WFH (1.0) applied same-day
        {
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-11-04",
            "Month": "Nov 2026",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Employee",
            "Applied On": "2026-11-04",  # Same-day (0 days)
            "Approved By": "Manager",
            "Approved On": "2026-11-05", # 1 day turnaround
        },
        # Nov 5: Present with Missing Swipe exception
        {
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-11-05",
            "Month": "Nov 2026",
            "Attendance Type": "Missing Swipes",
            "Status": "P(MS)",
            "Quantity": 1.0,
            "In Time": "09:15",
            "Out Time": "NA",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # Nov 6: Explicit Absent
        {
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-11-06",
            "Month": "Nov 2026",
            "Attendance Type": "Absent",
            "Status": "AB",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
    ]

    # ── E001 (Alice) - Dec 2026 (5 WFH days -> 2 excess days) ──
    for d in range(1, 6):
        rows.append({
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Frank Mgr",
            "Date": f"2026-12-0{d}",
            "Month": "Dec 2026",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Employee",
            "Applied On": "2026-12-01",
            "Approved By": "Manager",
            "Approved On": "2026-12-02",
        })

    # ── E002 (Bob) - Nov 2026 (4 WFH days -> 1 excess day) ──
    for d in range(2, 6):
        rows.append({
            "Employee Number": "E002",
            "Employee Name": "Bob Jones",
            "Business Unit": "Technology",
            "Department": "QA",
            "Reporting Manager": "Frank Mgr",
            "Date": f"2026-11-0{d}",
            "Month": "Nov 2026",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Admin",
            "Applied On": "2026-11-08",  # Retrospective (Applied after date)
            "Approved By": "Admin",
            "Approved On": "2026-11-09",
        })

    # ── E002 (Bob) - Dec 2026 (2 WFH days -> 0 excess days) ──
    for d in range(1, 3):
        rows.append({
            "Employee Number": "E002",
            "Employee Name": "Bob Jones",
            "Business Unit": "Technology",
            "Department": "QA",
            "Reporting Manager": "Frank Mgr",
            "Date": f"2026-12-0{d}",
            "Month": "Dec 2026",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Employee",
            "Applied On": "2026-12-01",
            "Approved By": "Manager",
            "Approved On": "2026-12-01",
        })

    rows.extend([
        # ── E003 (Charlie) - BU Transfer & Overnight Punch ──
        # Nov 2 (Lending): Overnight shift 22:00 to 06:00 (8.0 hours)
        {
            "Employee Number": "E003",
            "Employee Name": "Charlie Brown",
            "Business Unit": "Lending",
            "Department": "Operations",
            "Reporting Manager": "Grace Mgr",
            "Date": "2026-11-02",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "22:00",
            "Out Time": "06:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # Dec 1 (Transferred to Retail): Day shift 09:00 to 17:30 (8.5 hours)
        {
            "Employee Number": "E003",
            "Employee Name": "Charlie Brown",
            "Business Unit": "Retail",
            "Department": "Operations",
            "Reporting Manager": "Helen Mgr",
            "Date": "2026-12-01",
            "Month": "Dec 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "17:30",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },

        # ── E004 (David) & E005 (Emma) - Deviation Testing in BU "Finance" ──
        # Standard BU benchmark records for Finance: 09:00 (540m) to 18:00 (1080m)
        {
            "Employee Number": "E010",
            "Employee Name": "Base Fin",
            "Business Unit": "Finance",
            "Department": "Accounts",
            "Reporting Manager": "Ian Mgr",
            "Date": "2026-11-02",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "18:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # E004: In Time 10:01 (601m) -> BU is 540m -> In Diff = +61m (>60m) -> FLAGGED
        {
            "Employee Number": "E004",
            "Employee Name": "David Late",
            "Business Unit": "Finance",
            "Department": "Accounts",
            "Reporting Manager": "Ian Mgr",
            "Date": "2026-11-02",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "10:01",
            "Out Time": "18:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        # E005: In Time 10:00 (600m) -> BU is 540m (if evaluated alone vs 540m) -> diff = 60m (NOT flagged)
        {
            "Employee Number": "E005",
            "Employee Name": "Emma Boundary",
            "Business Unit": "Finance",
            "Department": "Accounts",
            "Reporting Manager": "Ian Mgr",
            "Date": "2026-11-03",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "10:00",
            "Out Time": "18:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
    ])
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Distinct Employee Headcount
# ─────────────────────────────────────────────────────────────────────────────

def test_01_distinct_employee_headcount(base_workforce_df):
    bundle = compute_workforce_intelligence_bundle(base_workforce_df)
    # Distinct employees: E001, E002, E003, E004, E005, E010 -> exactly 6
    assert bundle["kpi_1_emp_hc"] == 6
    assert bundle["unique_employees"] == 6

    # Adding a row with NaN/empty employee number does not inflate headcount
    dirty_df = pd.concat([
        base_workforce_df,
        pd.DataFrame([{
            "Employee Number": "",
            "Employee Name": "",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Date": "2026-11-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        }])
    ], ignore_index=True)
    bundle_dirty = compute_workforce_intelligence_bundle(dirty_df)
    assert bundle_dirty["kpi_1_emp_hc"] == 6


# ─────────────────────────────────────────────────────────────────────────────
# 2. Half-Day Attendance Composition
# ─────────────────────────────────────────────────────────────────────────────

def test_02_half_day_attendance_composition():
    # 1 employee, 1 date: 0.5 Present, 0.5 Leave
    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Tech",
            "Department": "Dev",
            "Reporting Manager": "Frank",
            "Date": "2026-11-03",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 0.5,
        },
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Tech",
            "Department": "Dev",
            "Reporting Manager": "Frank",
            "Date": "2026-11-03",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 0.5,
        },
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    # Recorded employee-days: exactly 1
    assert bundle["recorded_employee_days"] == 1
    assert bundle["kpi_2_attendance_days"] == 1
    # Quantities: exactly 0.5 each
    assert bundle["kpi_3_present_days"] == 0.5
    assert bundle["kpi_5_leave_days"] == 0.5
    # Total composition denominator: 1.0
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_3_present_pct"] == 50.0
    assert bundle["kpi_5_leave_pct"] == 50.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Attendance Exceptions Overlapping with Present
# ─────────────────────────────────────────────────────────────────────────────

def test_03_attendance_exceptions_overlapping_present():
    # Missing Swipe record is both physical attendance (Present) and an Attendance Exception
    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Date": "2026-11-02",
            "Attendance Type": "Missing Swipes",
            "Status": "P(MS)",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "NA",
        }
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    # Physical present includes the missing swipe day
    assert bundle["kpi_3_present_days"] == 1.0
    # Also flagged in attendance exceptions
    assert bundle["kpi_9_attendance_exceptions_days"] == 1
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 1
    # Attendance composition denominator does not double-count
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["recorded_employee_days"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Explicit Absence and Unresolved-Status Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_04_explicit_absence_and_unresolved_status():
    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Date": "2026-11-02",
            "Attendance Type": "Absent",
            "Status": "AB",
            "Quantity": 1.0,
        },
        {
            "Employee Number": "E001",
            "Date": "2026-11-03",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    assert bundle["kpi_absent_days"] == 1.0
    assert bundle["kpi_absent_pct"] == 50.0
    assert bundle["kpi_3_present_days"] == 1.0
    assert bundle["kpi_3_present_pct"] == 50.0
    assert bundle["attendance_composition_denominator"] == 2.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Leave Request Identity and Inferred-Grouping Separation
# ─────────────────────────────────────────────────────────────────────────────

def test_05_leave_request_identity_and_inferred_grouping():
    # Test separation of confirmed request ID vs inferred grouping using CanonicalWorkforceData
    r1 = WorkforceRequest(
        request_id="REQ_CONFIRMED_01",
        employee_id="E001",
        request_type="LEAVE",
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 2),
        total_quantity=1.0,
        is_inferred=False,
    )
    r2 = WorkforceRequest(
        request_id="REQ_INFERRED_02",
        employee_id="E001",
        request_type="LEAVE",
        start_date=date(2026, 11, 3),
        end_date=date(2026, 11, 3),
        total_quantity=1.0,
        is_inferred=True,
    )
    from types import SimpleNamespace
    mock_foundation = SimpleNamespace(requests=[r1, r2])

    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Date": "2026-11-02",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
        },
        {
            "Employee Number": "E001",
            "Date": "2026-11-03",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
        },
    ])
    bundle = compute_workforce_intelligence_bundle(df, canonical_data=mock_foundation)
    assert bundle["total_leave_requests"] == 2
    assert bundle["confirmed_leave_requests"] == 1
    assert bundle["inferred_leave_requests"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. Prior, Same-Day, and Retrospective Applications
# ─────────────────────────────────────────────────────────────────────────────

def test_06_prior_same_day_retro_applications():
    df = pd.DataFrame([
        # Prior application: Start Nov 5, Applied Nov 1 -> Lead time = +4 days
        {
            "Employee Number": "E001",
            "Date": "2026-11-05",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Applied On": "2026-11-01",
            "Approved On": "2026-11-02",
        },
        # Same-day application: Start Nov 6, Applied Nov 6 -> Lead time = 0 days
        {
            "Employee Number": "E001",
            "Date": "2026-11-06",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Applied On": "2026-11-06",
            "Approved On": "2026-11-07",
        },
        # Retrospective application: Start Nov 7, Applied Nov 10 -> Lead time = -3 days
        {
            "Employee Number": "E001",
            "Date": "2026-11-07",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Applied On": "2026-11-10",
            "Approved On": "2026-11-11",
        },
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    assert bundle["leave_prior_cnt"] == 1
    assert bundle["leave_same_day_cnt"] == 1
    assert bundle["leave_retro_cnt"] == 1
    # Lead times: +4, 0, -3 -> avg = (4 + 0 - 3) / 3 = 1 / 3 = 0.33 -> rounded 0.3
    assert bundle["leave_avg_lead_time_days"] == 0.3
    # Median: sorted [-3, 0, 4] -> median is 0.0
    assert bundle["leave_median_lead_time_days"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Approval Ownership and Turnaround
# ─────────────────────────────────────────────────────────────────────────────

def test_07_approval_ownership_and_turnaround():
    df = pd.DataFrame([
        # Manager approval, turnaround = 2 days
        {
            "Employee Number": "E001",
            "Date": "2026-11-05",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Applied On": "2026-11-01",
            "Approved By": "Manager",
            "Approved On": "2026-11-03",
        },
        # Admin approval, turnaround = 4 days
        {
            "Employee Number": "E001",
            "Date": "2026-11-06",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Applied On": "2026-11-01",
            "Approved By": "Admin",
            "Approved On": "2026-11-05",
        },
        # Pending approval (NA approved on) -> must not dilute completed turnaround
        {
            "Employee Number": "E001",
            "Date": "2026-11-07",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Applied On": "2026-11-01",
            "Approved By": "Pending",
            "Approved On": "NA",
        },
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    assert bundle["leave_approved_by_mgr_cnt"] == 1
    assert bundle["leave_approved_by_admin_cnt"] == 1
    assert bundle["leave_completed_approvals"] == 2
    assert bundle["leave_pending_approvals"] == 1
    # Turnarounds: [2.0, 4.0] -> avg = 3.0, median = 3.0
    assert bundle["leave_avg_approval_turnaround_days"] == 3.0
    assert bundle["leave_median_approval_turnaround_days"] == 3.0


# ─────────────────────────────────────────────────────────────────────────────
# 8. Independent Leave and WFH Calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_08_independent_leave_and_wfh_calculations(base_workforce_df):
    bundle = compute_workforce_intelligence_bundle(base_workforce_df)
    # Leave days and WFH days are strictly distinct
    assert bundle["total_leave_days"] == 0.5
    assert bundle["employees_taking_leave"] == 1
    # E001 (1 in Nov + 5 in Dec = 6) + E002 (4 in Nov + 2 in Dec = 6) = 12 WFH days
    assert bundle["total_wfh_days"] == 12.0
    assert bundle["employees_taking_wfh"] == 2
    # Ensure WFH metrics did not alter Leave counts
    assert bundle["kpi_5_leave_days"] == 0.5
    assert bundle["kpi_6_wfh_days"] == 12.0


# ─────────────────────────────────────────────────────────────────────────────
# 9. Monthly WFH Allowance Reset
# ─────────────────────────────────────────────────────────────────────────────

def test_09_monthly_wfh_allowance_reset():
    # E001 has 3 WFH days in Nov, and 3 WFH days in Dec
    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Tech",
            "Department": "Dev",
            "Date": f"2026-11-0{d}",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
        } for d in range(1, 4)
    ] + [
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Tech",
            "Department": "Dev",
            "Date": f"2026-12-0{d}",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
        } for d in range(1, 4)
    ])
    res = compute_wfh_allowance_monthly(df, allowance_days=3.0)
    # Total WFH days = 6, but allowance is 3 per calendar month
    assert res["total_wfh_days"] == 6.0
    # In each month, exactly 3.0 days taken <= 3.0 allowance -> 0 excess days
    assert res["total_additional_wfh_days"] == 0.0
    assert res["employees_exceeding_allowance"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10. Half-Day WFH Quantities
# ─────────────────────────────────────────────────────────────────────────────

def test_10_half_day_wfh_quantities():
    # 3 full days (1.0 each) + 1 half-day (0.5) in the same month = 3.5 days -> excess 0.5
    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Date": f"2026-11-0{d}",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
        } for d in range(1, 4)
    ] + [
        {
            "Employee Number": "E001",
            "Date": "2026-11-04",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 0.5,
        }
    ])
    res = compute_wfh_allowance_monthly(df, allowance_days=3.0)
    assert res["total_wfh_days"] == 3.5
    assert res["total_additional_wfh_days"] == 0.5
    assert res["employees_exceeding_allowance"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 11. Multi-Month WFH Excess
# ─────────────────────────────────────────────────────────────────────────────

def test_11_multi_month_wfh_excess():
    # E001:
    # Jan: 5 WFH days -> 2 excess
    # Feb: 2 WFH days -> 0 excess
    # Mar: 4 WFH days -> 1 excess
    # Total additional days = 3.0
    df = pd.DataFrame([
        {"Employee Number": "E001", "Date": f"2026-01-0{d}", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0}
        for d in range(1, 6)
    ] + [
        {"Employee Number": "E001", "Date": f"2026-02-0{d}", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0}
        for d in range(1, 3)
    ] + [
        {"Employee Number": "E001", "Date": f"2026-03-0{d}", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0}
        for d in range(1, 5)
    ])
    res = compute_wfh_allowance_monthly(df, allowance_days=3.0)
    assert res["total_wfh_days"] == 11.0
    assert res["total_additional_wfh_days"] == 3.0
    assert res["employees_exceeding_allowance"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 12. Distinct Employee Counting Across Months
# ─────────────────────────────────────────────────────────────────────────────

def test_12_distinct_employee_counting_across_months(base_workforce_df):
    res = compute_wfh_allowance_monthly(base_workforce_df, allowance_days=3.0)
    # E001 exceeds in Dec (5 days -> 2 excess)
    # E002 exceeds in Nov (4 days -> 1 excess)
    # Total additional days: 2 + 1 = 3.0
    assert res["total_additional_wfh_days"] == 3.0
    # Distinct employees exceeding: E001 and E002 -> exactly 2
    assert res["employees_exceeding_allowance"] == 2
    assert res["exceeding_employee_ids"] == {"E001", "E002"}


# ─────────────────────────────────────────────────────────────────────────────
# 13. Partially Observed Calendar Months
# ─────────────────────────────────────────────────────────────────────────────

def test_13_partially_observed_calendar_months():
    # Data only covers Nov 2 to Nov 6 (incomplete November)
    df = pd.DataFrame([
        {
            "Employee Number": "E001",
            "Date": "2026-11-02",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
        },
        {
            "Employee Number": "E001",
            "Date": "2026-11-06",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
        },
    ])
    res = compute_wfh_allowance_monthly(df, allowance_days=3.0)
    assert "2026-11" in res["partially_observed_months"]
    summary = res["monthly_summary"]["2026-11"]
    assert summary["is_partially_observed"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 14. Employee Transfers Between Business Units
# ─────────────────────────────────────────────────────────────────────────────

def test_14_employee_transfers_between_business_units(base_workforce_df):
    # E003 was in Lending on Nov 2, and Retail on Dec 1
    # Verify date-specific attribution
    lending_bundle = compute_workforce_intelligence_bundle(base_workforce_df, business_unit="Lending")
    retail_bundle = compute_workforce_intelligence_bundle(base_workforce_df, business_unit="Retail")

    # In Lending, E003 is observed
    assert lending_bundle["unique_employees"] == 1
    assert lending_bundle["recorded_employee_days"] == 1

    # In Retail, E003 is observed
    assert retail_bundle["unique_employees"] == 1
    assert retail_bundle["recorded_employee_days"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 15. Business Unit Average Punch Calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_15_business_unit_average_punch_calculations():
    df = pd.DataFrame([
        {"Employee Number": "E1", "Business Unit": "Finance", "In Time": "09:00", "Out Time": "17:00", "Attendance Type": "Present", "Status": "P"},
        {"Employee Number": "E2", "Business Unit": "Finance", "In Time": "10:00", "Out Time": "19:00", "Attendance Type": "Present", "Status": "P"},
    ])
    devs = compute_punch_deviations_bu(df)
    fin_bm = devs["bu_benchmarks"]["Finance"]
    # In time: avg(540, 600) = 570 mins (09:30 AM)
    assert fin_bm["avg_in_mins"] == 570.0
    assert fin_bm["avg_in_time_str"] == "09:30 AM"
    assert fin_bm["avg_in_str"] == "09:30 AM"
    # Out time: avg(1020, 1140) = 1080 mins (06:00 PM)
    assert fin_bm["avg_out_mins"] == 1080.0
    assert fin_bm["avg_out_time_str"] == "06:00 PM"
    assert fin_bm["avg_out_str"] == "06:00 PM"


# ─────────────────────────────────────────────────────────────────────────────
# 16. Exactly 60-Minute vs Greater-Than-60-Minute Deviations
# ─────────────────────────────────────────────────────────────────────────────

def test_16_exact_60m_vs_greater_than_60m_deviations():
    # BU Ops: E_BASE (08:00 = 480m) + E_EXACT (10:00 = 600m) -> BU avg = 540m (09:00)
    # E_EXACT deviation = 600 - 540 = +60.0 mins (Exact 60.0 -> NOT flagged)
    # BU Tech: 3 base (09:00 = 540m) + E_LATE (11:00 = 660m) -> BU avg = 570m (09:30)
    # E_LATE deviation = 660 - 570 = +90.0 mins (> 60.0 -> FLAGGED Late Arrival)
    df = pd.DataFrame([
        {"Employee Number": "E_BASE", "Business Unit": "Ops", "In Time": "08:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
        {"Employee Number": "E_EXACT", "Business Unit": "Ops", "In Time": "10:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
        {"Employee Number": "E_T1", "Business Unit": "Tech", "In Time": "09:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
        {"Employee Number": "E_T2", "Business Unit": "Tech", "In Time": "09:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
        {"Employee Number": "E_T3", "Business Unit": "Tech", "In Time": "09:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
        {"Employee Number": "E_LATE", "Business Unit": "Tech", "In Time": "11:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
    ])
    devs = compute_punch_deviations_bu(df, threshold_mins=60.0)
    exact_dev = next(d for d in devs["employee_deviations"] if d["employee_id"] == "E_EXACT")
    late_dev = next(d for d in devs["employee_deviations"] if d["employee_id"] == "E_LATE")

    # Exact 60 min deviation: must NOT be flagged
    assert exact_dev["in_deviation_mins"] == 60.0
    assert exact_dev["is_late_arrival"] is False

    # Greater than 60 min deviation: MUST be flagged
    assert late_dev["in_deviation_mins"] == 90.0
    assert late_dev["is_late_arrival"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 17. Overnight Punch Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_17_overnight_punch_handling():
    # Night shift: In 22:00, Out 06:00 -> 8.0 hours
    df = pd.DataFrame([
        {
            "Employee Number": "E003",
            "Date": "2026-11-02",
            "In Time": "22:00",
            "Out Time": "06:00",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        }
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    assert bundle["avg_working_hours_decimal"] == 8.0
    assert bundle["avg_working_hours"] == "8h 00m"
    assert bundle["duration_8_10h_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 18. Missing-Punch and Invalid-Duration Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_18_missing_punch_and_invalid_duration_handling():
    df = pd.DataFrame([
        # Complete swipe: 8.0h
        {"Employee Number": "E1", "In Time": "09:00", "Out Time": "17:00", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        # Missing out punch: excluded from working duration
        {"Employee Number": "E2", "In Time": "09:00", "Out Time": "NA", "Attendance Type": "Missing Swipes", "Status": "P(MS)", "Quantity": 1.0},
        # Both punches missing
        {"Employee Number": "E3", "In Time": "NA", "Out Time": "NA", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    assert bundle["complete_swipe_records"] == 1
    assert bundle["missing_out_punch_count"] == 1
    assert bundle["both_punches_missing_count"] == 1
    # Average working duration computed only from the 1 complete swipe record
    assert bundle["avg_working_hours_decimal"] == 8.0


# ─────────────────────────────────────────────────────────────────────────────
# 19. Duration-Band Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def test_19_duration_band_reconciliation():
    # Under 4h (3h), 4-8h (6h), 8-10h (9h), Over 10h (11h) -> exactly 4 complete records
    df = pd.DataFrame([
        {"Employee Number": "E1", "In Time": "09:00", "Out Time": "12:00", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},  # 3h
        {"Employee Number": "E2", "In Time": "09:00", "Out Time": "15:00", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},  # 6h
        {"Employee Number": "E3", "In Time": "09:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},  # 9h
        {"Employee Number": "E4", "In Time": "08:00", "Out Time": "19:00", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},  # 11h
        {"Employee Number": "E5", "In Time": "09:00", "Out Time": "NA", "Attendance Type": "Missing Swipes", "Status": "P(MS)", "Quantity": 1.0}, # Incomplete
    ])
    bundle = compute_workforce_intelligence_bundle(df)
    assert bundle["duration_under_4h_count"] == 1
    assert bundle["duration_4_8h_count"] == 1
    assert bundle["duration_8_10h_count"] == 1
    assert bundle["duration_over_10h_count"] == 1
    # Sum of duration bands must reconcile exactly to complete swipes
    band_sum = (
        bundle["duration_under_4h_count"] +
        bundle["duration_4_8h_count"] +
        bundle["duration_8_10h_count"] +
        bundle["duration_over_10h_count"]
    )
    assert band_sum == bundle["complete_swipe_records"]
    assert band_sum == 4


# ─────────────────────────────────────────────────────────────────────────────
# 20. Adjustable Repeated-Exception Threshold
# ─────────────────────────────────────────────────────────────────────────────

def test_20_adjustable_repeated_exception_threshold():
    # E001 has 3 exception days: Nov 2 (MS), Nov 3 (AB), Nov 4 (MS + Reg on same day)
    # Same day with multiple exception types counts as 1 qualifying exception day!
    df = pd.DataFrame([
        {"Employee Number": "E001", "Date": "2026-11-02", "Attendance Type": "Missing Swipes", "Status": "MS"},
        {"Employee Number": "E001", "Date": "2026-11-03", "Attendance Type": "Absent", "Status": "AB"},
        # Nov 4: 2 rows on same day
        {"Employee Number": "E001", "Date": "2026-11-04", "Attendance Type": "Missing Swipes", "Status": "MS"},
        {"Employee Number": "E001", "Date": "2026-11-04", "Attendance Type": "Regularized", "Status": "P(R)"},
    ])
    # Threshold = 3 -> Meets threshold (qualifying days = 3)
    res_t3 = compute_repeated_exceptions(df, threshold=3)
    assert res_t3["total_repeat_employees"] == 1
    dossier = res_t3["dossiers"][0]
    assert dossier["qualifying_exception_days"] == 3
    assert dossier["meets_threshold"] is True
    # Multiple records on Nov 4 were collapsed into 1 exception day
    assert len(dossier["exception_dates"]) == 3

    # Threshold = 4 -> Does NOT meet threshold
    res_t4 = compute_repeated_exceptions(df, threshold=4)
    assert res_t4["total_repeat_employees"] == 0
    dossier_t4 = res_t4["dossiers"][0]
    assert dossier_t4["meets_threshold"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 21. Correct Filtered-Scope Numerators and Denominators
# ─────────────────────────────────────────────────────────────────────────────

def test_21_filtered_scope_numerators_and_denominators(base_workforce_df):
    # Filter by Business Unit = "Technology"
    tech_bundle = compute_workforce_intelligence_bundle(base_workforce_df, business_unit="Technology")
    # Only Alice (E001) and Bob (E002) belong to Technology
    assert tech_bundle["kpi_1_emp_hc"] == 2
    assert tech_bundle["unique_employees"] == 2

    # Denominator reflects Technology records only
    assert tech_bundle["attendance_composition_denominator"] > 0
    total_tech_days = (
        tech_bundle["kpi_3_present_days"] +
        tech_bundle["kpi_4_od_days"] +
        tech_bundle["kpi_5_leave_days"] +
        tech_bundle["kpi_6_wfh_days"] +
        tech_bundle["kpi_7_holiday_days"] +
        tech_bundle["kpi_8_week_off_days"] +
        tech_bundle["kpi_absent_days"]
    )
    assert round(total_tech_days, 1) == round(tech_bundle["attendance_composition_denominator"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# 22. Source-Record Traceability
# ─────────────────────────────────────────────────────────────────────────────

def test_22_source_record_traceability():
    df = pd.DataFrame([
        {"Employee Number": "E001", "Date": "2026-11-02", "Attendance Type": "Missing Swipes", "Status": "MS"},
        {"Employee Number": "E001", "Date": "2026-11-03", "Attendance Type": "Absent", "Status": "AB"},
        {"Employee Number": "E001", "Date": "2026-11-04", "Attendance Type": "Missing Swipes", "Status": "MS"},
    ])
    res = compute_repeated_exceptions(df, threshold=3)
    dossier = res["dossiers"][0]
    # Traceability fields populated
    assert len(dossier["source_record_ids"]) == 3
    assert len(dossier["exception_dates"]) == 3
    assert len(dossier["exception_types"]) == 2
    assert "Missing Swipe" in dossier["exception_types"]
    assert "Absent" in dossier["exception_types"]
    assert "2026-11-02" in dossier["exception_dates"]


# ─────────────────────────────────────────────────────────────────────────────
# 23. No Input DataFrame Mutation
# ─────────────────────────────────────────────────────────────────────────────

def test_23_no_input_dataframe_mutation(base_workforce_df):
    original_cols = list(base_workforce_df.columns)
    original_len = len(base_workforce_df)
    original_values = base_workforce_df.iloc[0].to_dict()

    _ = compute_workforce_intelligence_bundle(base_workforce_df)
    _ = compute_wfh_allowance_monthly(base_workforce_df)
    _ = compute_punch_deviations_bu(base_workforce_df)
    _ = compute_repeated_exceptions(base_workforce_df)

    assert list(base_workforce_df.columns) == original_cols
    assert len(base_workforce_df) == original_len
    assert base_workforce_df.iloc[0].to_dict() == original_values


# ─────────────────────────────────────────────────────────────────────────────
# 24. Compatibility with Existing Snapshots and Legacy Calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_24_compatibility_with_existing_snapshots_and_legacy_calculations(base_workforce_df):
    # Test that AnalyticalSnapshot and snapshot_service integrate smoothly with the Bridge
    service = TimeSeriesSnapshotService()
    snap = service.prepare_dataset(base_workforce_df, dataset_id="test_ds_v1")
    assert snap.is_valid()

    bridge = WorkforceIntelligenceBridge(snapshot_service=service)
    bundle = bridge.get_workforce_metrics()

    # 1. 32 Tier-A metrics exist
    assert "kpi_1_emp_hc" in bundle
    assert "kpi_2_attendance_days" in bundle
    assert "kpi_3_present_days" in bundle
    assert "kpi_6_wfh_days" in bundle
    assert "wfh_employees_exceeding_allowance" in bundle
    assert "leave_completed_approvals" in bundle

    # 2. Legacy 18 Time Series Analysis keys are preserved and populated
    legacy_keys = [
        "total_records", "unique_employees", "avg_leave_apply_days",
        "total_leaves_applied", "applied_by_emp_cnt", "applied_by_emp_pct",
        "avg_approval_days", "total_approvals", "appr_mgr_cnt", "appr_mgr_pct",
        "regularized_days", "reg_rate_pct", "total_wfh_days", "wfh_excess_days",
        "wfh_violating_emp_count", "wfh_exception_rate_pct", "repeat_emp_count",
        "repeat_emp_pct", "avg_in_time", "avg_out_time", "avg_working_hours",
    ]
    for k in legacy_keys:
        assert k in bundle, f"Legacy key '{k}' missing from bundle"

    # 3. LRU caching works
    stats_1 = bridge.get_filter_cache_stats()
    assert stats_1["cached_bundles"] == 1

    # Second fetch returns cached result
    bundle_cached = bridge.get_workforce_metrics()
    assert bundle_cached["kpi_1_emp_hc"] == bundle["kpi_1_emp_hc"]

    # Invalidate dataset clears cache
    service.prepare_dataset(base_workforce_df, dataset_id="test_ds_v2")
    stats_2 = bridge.get_filter_cache_stats()
    # Cache cleared on new dataset
    assert stats_2["cached_bundles"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 25. Unclassified Attendance Composition Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def test_25_unclassified_attendance_composition_reconciliation():
    """
    Step 19 Part 1: If a dataset contains 100 recorded employee-days, including 5 unclassified days,
    the dashboard must not silently calculate percentages using only the 95 classified days while
    presenting the result as 100% of all recorded employee-days.
    """
    rows = []
    # 50 Present
    for i in range(1, 51):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        })
    # 10 On Duty
    for i in range(51, 61):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "On Duty",
            "Status": "OD",
            "Quantity": 1.0,
        })
    # 15 Leave
    for i in range(61, 76):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
        })
    # 10 WFH
    for i in range(76, 86):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
        })
    # 5 Holiday
    for i in range(86, 91):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "Holiday",
            "Status": "H",
            "Quantity": 1.0,
        })
    # 5 Absent
    for i in range(91, 96):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "Absent",
            "Status": "AB",
            "Quantity": 1.0,
        })
    # 5 Unclassified / Unresolved records
    for i in range(96, 101):
        rows.append({
            "Employee Number": f"EMP{i:03d}",
            "Date": "2026-11-02",
            "Attendance Type": "Unknown Category",
            "Status": "PENDING_REVIEW",
            "Quantity": 1.0,
            "record_id": f"REC_UNCL_{i}",
        })

    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # 100 distinct employee days
    assert bundle["recorded_employee_days"] == 100
    assert bundle["kpi_2_attendance_days"] == 100

    # Denominators
    assert bundle["attendance_composition_denominator"] == 100.0
    assert bundle["classified_attendance_denominator"] == 95.0
    assert bundle["unclassified_records_count"] == 5
    assert bundle["kpi_unclassified_days"] == 5.0
    assert bundle["kpi_unclassified_pct"] == 5.0

    # Percentages must be based on the complete recorded denominator (100.0), NOT 95.0
    assert bundle["kpi_3_present_days"] == 50.0
    assert bundle["kpi_3_present_pct"] == 50.0   # Not 50/95 = 52.6%
    assert bundle["kpi_4_od_days"] == 10.0
    assert bundle["kpi_4_od_pct"] == 10.0
    assert bundle["kpi_5_leave_days"] == 15.0
    assert bundle["kpi_5_leave_pct"] == 15.0
    assert bundle["kpi_6_wfh_days"] == 10.0
    assert bundle["kpi_6_wfh_pct"] == 10.0
    assert bundle["kpi_7_holiday_days"] == 5.0
    assert bundle["kpi_7_holiday_pct"] == 5.0
    assert bundle["kpi_absent_days"] == 5.0
    assert bundle["kpi_absent_pct"] == 5.0

    # All 8 categories strictly reconcile to 100.0%
    total_pct = (
        bundle["kpi_3_present_pct"] +
        bundle["kpi_4_od_pct"] +
        bundle["kpi_5_leave_pct"] +
        bundle["kpi_6_wfh_pct"] +
        bundle["kpi_7_holiday_pct"] +
        bundle["kpi_8_week_off_pct"] +
        bundle["kpi_absent_pct"] +
        bundle["kpi_unclassified_pct"]
    )
    assert abs(total_pct - 100.0) < 1e-6

    # Source record traceability
    assert len(bundle["unclassified_record_ids"]) == 5
    assert "REC_UNCL_96" in bundle["unclassified_record_ids"]


# ─────────────────────────────────────────────────────────────────────────────
# 26. Monthly WFH Allowance with Date Filter (Synthetic Example)
# ─────────────────────────────────────────────────────────────────────────────

def test_26_monthly_wfh_allowance_with_date_filter_synthetic_example():
    """
    Step 19 Part 2: Verify the exact synthetic example:
    Employee EMP001:
      September 2:  1 WFH day
      September 5:  1 WFH day
      September 18: 1 WFH day
      September 20: 1 WFH day
      September 25: 1 WFH day
      Total September WFH: 5 days. September excess: 2 days.
    Now apply a dashboard date filter: September 15 to September 30.
    Selected range contains 3 WFH days.
    Complete available September dataset contains 5 WFH days.
    Monthly excess must remain 2 days when the September monthly allowance is evaluated.
    """
    rows = [
        {"Employee Number": "EMP001", "Date": "2026-09-02", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0, "record_id": "R1"},
        {"Employee Number": "EMP001", "Date": "2026-09-05", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0, "record_id": "R2"},
        {"Employee Number": "EMP001", "Date": "2026-09-18", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0, "record_id": "R3"},
        {"Employee Number": "EMP001", "Date": "2026-09-20", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0, "record_id": "R4"},
        {"Employee Number": "EMP001", "Date": "2026-09-25", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0, "record_id": "R5"},
    ]
    df = pd.DataFrame(rows)

    # Apply date filter: Sept 15 to Sept 30
    date_range = (date(2026, 9, 15), date(2026, 9, 30))
    bundle = compute_workforce_intelligence_bundle(df, date_range=date_range, wfh_allowance=3.0)

    # In-scope reporting period contains 3 WFH days
    assert bundle["kpi_6_wfh_days"] == 3.0
    assert bundle["total_wfh_days"] == 3.0

    # Allowance evaluation preserves complete month: 5 days total, 2 excess days
    assert bundle["wfh_employees_exceeding_allowance"] == 1
    assert bundle["wfh_total_additional_days"] == 2.0

    # Breakdown verification
    breakdown = bundle["wfh_employee_month_breakdown"]
    assert len(breakdown) == 1
    emp_record = breakdown[0]
    assert emp_record["employee_id"] == "EMP001"
    assert emp_record["calendar_month"] == "2026-09"
    assert emp_record["eligible_wfh_days"] == 5.0
    assert emp_record["wfh_days_in_scope"] == 3.0
    assert emp_record["allowed_days"] == 3.0
    assert emp_record["excess_days"] == 2.0
    assert emp_record["is_exceeding"] is True

    # Monthly summary verification
    summary = bundle["wfh_monthly_summary"]["2026-09"]
    assert summary["total_wfh_days"] == 5.0
    assert summary["wfh_days_in_scope"] == 3.0
    assert summary["excess_days"] == 2.0
    assert summary["employees_taking_wfh"] == 1
    assert summary["employees_exceeding"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 27. WFH Allowance with Organizational Transfer
# ─────────────────────────────────────────────────────────────────────────────

def test_27_wfh_allowance_organizational_transfer():
    """
    Step 19 Part 2: Business Unit and department filters apply consistently,
    including employees who transferred between organizational units during the month.
    Do not silently apply the same monthly allowance multiple times to one employee
    because they moved between Business Units.
    """
    # EMP001 transferred from Lending to Retail mid-month:
    # In Lending: 2 WFH days (Sept 2, 5)
    # In Retail:  3 WFH days (Sept 18, 20, 25)
    # Total monthly WFH = 5 days. Total company excess = 2 days.
    rows = [
        {"Employee Number": "EMP001", "Business Unit": "Lending", "Date": "2026-09-02", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Business Unit": "Lending", "Date": "2026-09-05", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Business Unit": "Retail",  "Date": "2026-09-18", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Business Unit": "Retail",  "Date": "2026-09-20", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "EMP001", "Business Unit": "Retail",  "Date": "2026-09-25", "Attendance Type": "WFH", "Status": "WFH", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)

    # 1. Company-wide evaluation
    company_bundle = compute_workforce_intelligence_bundle(df, wfh_allowance=3.0)
    assert company_bundle["wfh_employees_exceeding_allowance"] == 1
    assert company_bundle["wfh_total_additional_days"] == 2.0
    # Exactly 1 breakdown entry for EMP001 in 2026-09 (allowance not duplicated!)
    assert len(company_bundle["wfh_employee_month_breakdown"]) == 1

    # 2. Filtered to Retail
    retail_bundle = compute_workforce_intelligence_bundle(df, business_unit="Retail", wfh_allowance=3.0)
    assert retail_bundle["unique_employees"] == 1
    assert retail_bundle["kpi_6_wfh_days"] == 3.0
    # In Retail, EMP001 is evaluated against complete monthly WFH (5 days), so excess remains 2.0
    # and is NOT reset to 0.0 (3 - 3 = 0) by silently granting a second allowance
    assert retail_bundle["wfh_employees_exceeding_allowance"] == 1
    assert retail_bundle["wfh_total_additional_days"] == 2.0


# ─────────────────────────────────────────────────────────────────────────────
# 28. Non-Comparable Shift Deviation Returns N/A Cohort
# ─────────────────────────────────────────────────────────────────────────────

def test_28_non_comparable_shift_deviation_returns_na():
    """
    Step 19 Part 3: Employees belonging to different shifts are not compared
    using misleading clock-time averages when a comparable cohort cannot be established.
    Result remains a descriptive pattern, not a confirmed attendance-policy violation.
    """
    df = pd.DataFrame([
        # Daytime shift employees in Support (In 09:00, Out 18:00)
        {"Employee Number": f"E_DAY_{i}", "Business Unit": "Support", "In Time": "09:00", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"}
        for i in range(1, 5)
    ] + [
        # Night shift employee in Support (In 22:00, Out 06:00)
        {"Employee Number": "E_NIGHT", "Business Unit": "Support", "In Time": "22:00", "Out Time": "06:00", "Attendance Type": "Present", "Status": "P"}
    ])
    devs = compute_punch_deviations_bu(df, threshold_mins=60.0)

    night_dev = next(d for d in devs["employee_deviations"] if d["employee_id"] == "E_NIGHT")
    assert "Non-comparable shift schedule" in night_dev["comparison_status"]
    assert night_dev["in_deviation_mins"] is None
    assert night_dev["out_deviation_mins"] is None
    # Crucial: Must NOT be falsely flagged as arriving late
    assert night_dev["is_late_arrival"] is False
    assert night_dev["is_early_departure"] is False
    assert devs["late_arrival_employees_count"] == 0
    assert "Descriptive workforce pattern" in night_dev["notes"]


# ─────────────────────────────────────────────────────────────────────────────
# 29. Earlier Arrivals and Later Departures Not Flagged
# ─────────────────────────────────────────────────────────────────────────────

def test_29_earlier_arrivals_and_later_departures_not_flagged():
    """
    Step 19 Part 3: Earlier arrivals and later departures are not incorrectly labelled late-in or early-out.
    """
    df = pd.DataFrame([
        # Baseline: 09:30 AM in, 06:00 PM out
        {"Employee Number": "E_BASE", "Business Unit": "Finance", "In Time": "09:30", "Out Time": "18:00", "Attendance Type": "Present", "Status": "P"},
        # Early arrival: 08:00 AM (90 mins early) & Late departure: 20:00 (120 mins late)
        {"Employee Number": "E_DILIGENT", "Business Unit": "Finance", "In Time": "08:00", "Out Time": "20:00", "Attendance Type": "Present", "Status": "P"},
    ])
    devs = compute_punch_deviations_bu(df, threshold_mins=60.0)
    e_diligent = next(d for d in devs["employee_deviations"] if d["employee_id"] == "E_DILIGENT")

    # In deviation: 480 - 525 = -45.0 (arrived earlier than average) -> NOT late
    assert e_diligent["in_deviation_mins"] < 0
    assert e_diligent["is_late_arrival"] is False

    # Out deviation: 1200 - 1140 = +60.0 (departed later than average) -> NOT early departure
    assert e_diligent["out_deviation_mins"] > 0
    assert e_diligent["is_early_departure"] is False

