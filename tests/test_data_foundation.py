"""
tests/test_data_foundation.py
──────────────────────────────
Focused unit tests for Transformers 2.0 — Phase 3A: Unified Workforce Data Foundation.

Verifies:
 1. Correct employee identification and isolation (no merging of distinct employees sharing names).
 2. Correct employee-day facts generation and exception flags.
 3. Preservation of source-level records and attributes.
 4. Organizational mapping and Lending business unit handling.
 5. Missing swipe and working-hour handling (missing swipe != 0.0 hrs; missing record != absent).
 6. Leave and WFH quantity preservation (0.5, 1.0, multi-day requests).
 7. Duplicate and conflicting record handling without silent deletion.
 8. Source-record traceability (record_id, source_row_number, source_file_name).
 9. Non-destructive input immutability.
10. Compatibility with existing analytical snapshot engine and snapshot_service.
"""

from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from storage import snapshot_service, TimeSeriesSnapshotService
from workforce_intelligence.data_foundation import (
    AttendanceRecord,
    CanonicalWorkforceData,
    Employee,
    EmployeeDayFact,
    OrganizationalStructure,
    WorkforceRequest,
)


@pytest.fixture
def sample_foundation_df():
    """Deterministic synthetic dataset with multiple employees, dates, and edge cases."""
    return pd.DataFrame([
        # Emp 1: Alice (ID: EMP001, Engineering, Backend, RM: Bob Manager)
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "18:00",
        },
        # Emp 1: Missing Swipe (Present with no out time)
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-02",
            "Attendance Type": "Missing Swipes",
            "Status": "P(MS)",
            "Quantity": 1.0,
            "In Time": "09:30",
            "Out Time": "NA",
        },
        # Emp 1: Leave (Casual Leave)
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-03",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 1.0,
            "Applied By": "Employee",
            "Applied On": "2026-09-01",
            "Approved By": "Manager",
            "Approved On": "2026-09-02",
            "Approval Status": "Approved",
        },
        # Emp 2: Alice with DIFFERENT ID (EMP002, Sales, Direct Sales, RM: David RM) -> Must NOT be merged!
        {
            "Employee Number": "EMP002",
            "Employee Name": "Alice",
            "Business Unit": "Sales",
            "Department": "Direct Sales",
            "Reporting Manager": "David RM",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:15",
            "Out Time": "17:45",
        },
        # Emp 3: Charlie with Float string ID "EMP003.0" -> Normalizes to EMP003
        # Lending Business Unit -> Department 'Collections' acts as effective BU
        {
            "Employee Number": "EMP003.0",
            "Employee Name": "Charlie",
            "Business Unit": "Lending",
            "Department": "Collections",
            "Reporting Manager": "Frank RM",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "10:00",
            "Out Time": "19:00",
        },
        # Emp 3: Half-day Present + Half-day Leave on same day (2026-09-02)
        {
            "Employee Number": "EMP003",
            "Employee Name": "Charlie",
            "Business Unit": "Lending",
            "Department": "Collections",
            "Reporting Manager": "Frank RM",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 0.5,
            "In Time": "09:00",
            "Out Time": "13:00",
        },
        {
            "Employee Number": "EMP003",
            "Employee Name": "Charlie",
            "Business Unit": "Lending",
            "Department": "Collections",
            "Reporting Manager": "Frank RM",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Status": "SL",
            "Leave Name": "Sick Leave",
            "Quantity": 0.5,
            "Applied By": "Employee",
            "Applied On": "2026-09-02",
            "Approved By": "Manager",
            "Approved On": "2026-09-02",
            "Approval Status": "Approved",
        },
        # Emp 4: David (Multi-day WFH: Sep 1 to Sep 3)
        *[
            {
                "Employee Number": "EMP004",
                "Employee Name": "David",
                "Business Unit": "Engineering",
                "Department": "Frontend",
                "Reporting Manager": "Bob Manager",
                "Date": f"2026-09-0{d}",
                "Attendance Type": "Work From Home",
                "Status": "WFH",
                "Quantity": 1.0,
                "Applied By": "Employee",
                "Applied On": "2026-08-31",
                "Approved By": "Manager",
                "Approved On": "2026-08-31",
                "Approval Status": "Approved",
            }
            for d in range(1, 4)
        ],
        # Emp 4: Week Off (Sep 6) -> Ineligible for attendance exception
        {
            "Employee Number": "EMP004",
            "Employee Name": "David",
            "Business Unit": "Engineering",
            "Department": "Frontend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-06",
            "Attendance Type": "Week Off",
            "Status": "WO",
            "Quantity": 1.0,
        },
    ])


# =========================================================================
# 1. Correct employee identification and isolation
# =========================================================================
def test_employee_identification_and_isolation(sample_foundation_df):
    """Verify stable ID is primary key and distinct employees sharing names are not merged."""
    foundation = CanonicalWorkforceData.from_dataframe(sample_foundation_df)

    # 4 distinct employees: EMP001, EMP002, EMP003, EMP004
    assert len(foundation.employees) == 4
    assert "EMP001" in foundation.employees
    assert "EMP002" in foundation.employees
    assert "EMP003" in foundation.employees
    assert "EMP004" in foundation.employees

    # EMP001 and EMP002 both have name 'Alice', but must be separate entities
    emp1 = foundation.get_employee("EMP001")
    emp2 = foundation.get_employee("EMP002")
    assert emp1 is not None and emp2 is not None
    assert emp1.employee_name == "Alice"
    assert emp2.employee_name == "Alice"
    assert emp1.employee_id != emp2.employee_id
    assert emp1.department == "Backend"
    assert emp2.department == "Direct Sales"
    assert emp1.reporting_manager == "Bob Manager"
    assert emp2.reporting_manager == "David RM"

    # Float string EMP003.0 normalized to EMP003
    emp3 = foundation.get_employee("EMP003")
    assert emp3 is not None
    assert emp3.employee_id == "EMP003"


# =========================================================================
# 2. Correct employee-day facts generation and exception flags
# =========================================================================
def test_employee_day_facts_generation(sample_foundation_df):
    """Verify daily facts aggregation, presence flags, and exception detection."""
    foundation = CanonicalWorkforceData.from_dataframe(sample_foundation_df)

    # Emp 1 on 2026-09-01: Present, no exception
    fact1 = foundation.get_fact("EMP001", date(2026, 9, 1))
    assert fact1 is not None
    assert fact1.has_present is True
    assert fact1.has_leave is False
    assert fact1.is_attendance_exception is False
    assert fact1.working_hours == 9.0

    # Emp 1 on 2026-09-02: Missing Swipe -> Attendance Exception
    fact2 = foundation.get_fact("EMP001", date(2026, 9, 2))
    assert fact2 is not None
    assert fact2.has_missing_swipe is True
    assert fact2.is_attendance_exception is True
    assert "MISSING_SWIPE" in fact2.attendance_exception_types

    # Emp 4 on 2026-09-06: Week Off -> Not eligible attendance day
    fact_wo = foundation.get_fact("EMP004", date(2026, 9, 6))
    assert fact_wo is not None
    assert fact_wo.has_week_off is True
    assert fact_wo.is_eligible_attendance_day is False
    assert fact_wo.is_attendance_exception is False


# =========================================================================
# 3. Preservation of source-level records and attributes
# =========================================================================
def test_source_level_record_preservation(sample_foundation_df):
    """Verify all source-level records are preserved with exact attributes."""
    foundation = CanonicalWorkforceData.from_dataframe(
        sample_foundation_df, source_file_name="test_source.xlsx"
    )

    # Total rows in sample dataframe is 11
    assert len(foundation.attendance_records) == len(sample_foundation_df)
    assert len(foundation.attendance_records) == 11

    # First record check
    rec0 = foundation.attendance_records[0]
    assert rec0.record_id == "f001_rec_000001"
    assert rec0.source_row_number == 2
    assert rec0.source_file_name == "test_source.xlsx"
    assert rec0.employee_id == "EMP001"
    assert rec0.attendance_category == "Present"
    assert rec0.attendance_status == "P"
    assert rec0.attendance_type == "Present"
    assert rec0.quantity == 1.0


# =========================================================================
# 4. Organizational mapping and Lending business unit handling
# =========================================================================
def test_organizational_mapping(sample_foundation_df):
    """Verify organizational relationships and Lending special rule."""
    foundation = CanonicalWorkforceData.from_dataframe(sample_foundation_df)
    org = foundation.org_structure

    # Direct reports for Bob Manager (Alice EMP001 and David EMP004)
    reports = org.get_direct_reports("Bob Manager")
    assert "EMP001" in reports
    assert "EMP004" in reports
    assert "EMP002" not in reports

    # Department members
    backend_members = org.get_department_members("Backend")
    assert "EMP001" in backend_members

    # Lending rule: EMP003 raw BU is 'Lending', Department is 'Collections'
    # effective_business_unit must be 'Collections', raw BU preserved as 'Lending'
    emp3 = foundation.get_employee("EMP003")
    assert emp3.business_unit == "Lending"
    assert emp3.effective_business_unit == "Collections"
    assert "EMP003" in org.get_business_unit_members("Collections")


# =========================================================================
# 5. Missing swipe and working-hour handling
# =========================================================================
def test_missing_swipes_and_working_hours(sample_foundation_df):
    """Verify missing swipe is NOT converted to 0.0 hrs and missing record != absent."""
    foundation = CanonicalWorkforceData.from_dataframe(sample_foundation_df)

    # EMP001 on Sep 2: In Time = 09:30, Out Time = NA
    rec = [r for r in foundation.attendance_records if r.employee_id == "EMP001" and r.date == date(2026, 9, 2)][0]
    assert rec.in_time == "09:30"
    assert rec.out_time is None
    assert rec.working_hours is None  # MUST be None, NOT 0.0

    # Fact for EMP001 on Sep 2 has working_hours = None
    fact = foundation.get_fact("EMP001", date(2026, 9, 2))
    assert fact.working_hours is None

    # Missing date for EMP001 on Sep 4 (no row in dataset):
    # Foundation must NOT invent an Absent record!
    fact_missing = foundation.get_fact("EMP001", date(2026, 9, 4))
    assert fact_missing is None


# =========================================================================
# 6. Leave and WFH quantity preservation
# =========================================================================
def test_leave_and_wfh_quantity_preservation(sample_foundation_df):
    """Verify half-day 0.5, full-day 1.0, and multi-day request aggregation."""
    foundation = CanonicalWorkforceData.from_dataframe(sample_foundation_df)

    # EMP003 on Sep 2 has 0.5 Present and 0.5 Leave
    emp3_recs = [r for r in foundation.attendance_records if r.employee_id == "EMP003" and r.date == date(2026, 9, 2)]
    assert len(emp3_recs) == 2
    assert emp3_recs[0].quantity == 0.5
    assert emp3_recs[1].quantity == 0.5

    fact3 = foundation.get_fact("EMP003", date(2026, 9, 2))
    assert fact3.daily_total_quantity == 1.0
    assert fact3.has_present is True
    assert fact3.has_leave is True

    # EMP004 multi-day WFH request (Sep 1 to Sep 3 = 3 days)
    wfh_reqs = foundation.get_requests_for_employee("EMP004")
    assert len(wfh_reqs) == 1
    req = wfh_reqs[0]
    assert req.request_type == "WFH"
    assert req.start_date == date(2026, 9, 1)
    assert req.end_date == date(2026, 9, 3)
    assert len(req.request_dates) == 3
    assert req.total_quantity == 3.0
    assert req.applied_on == date(2026, 8, 31)
    assert req.application_lag_days == 1  # Applied 1 day in advance


# =========================================================================
# 7. Duplicate and conflicting record handling
# =========================================================================
def test_duplicate_and_conflicting_record_handling():
    """Verify duplicate rows are flagged and preserved, not deleted."""
    row = {
        "Employee Number": "EMP100",
        "Employee Name": "Echo",
        "Business Unit": "Engineering",
        "Department": "QA",
        "Date": "2026-09-01",
        "Attendance Type": "Present",
        "Status": "P",
        "Quantity": 1.0,
        "In Time": "09:00",
        "Out Time": "18:00",
    }
    # Dataset containing exact duplicate rows
    df_dup = pd.DataFrame([row, row])
    foundation = CanonicalWorkforceData.from_dataframe(df_dup)

    # Both records preserved in attendance_records
    assert len(foundation.attendance_records) == 2
    assert foundation.attendance_records[0].include_in_analysis is True
    assert foundation.attendance_records[0].analysis_exclusion_reason == "NONE"

    assert foundation.attendance_records[1].include_in_analysis is False
    assert foundation.attendance_records[1].analysis_exclusion_reason == "EXACT_DUPLICATE"

    # Daily fact counts analytically once
    fact = foundation.get_fact("EMP100", date(2026, 9, 1))
    assert fact.record_count == 1
    assert fact.raw_record_count == 2
    assert fact.daily_total_quantity == 1.0
    assert fact.raw_daily_total_quantity == 2.0


# =========================================================================
# 8. Source-record traceability
# =========================================================================
def test_source_record_traceability(sample_foundation_df):
    """Verify record_id, source_row_number, and source_file_name link across models."""
    foundation = CanonicalWorkforceData.from_dataframe(
        sample_foundation_df, source_file_name="workforce_2026.xlsx", source_file_index=2
    )

    # Records have file-prefixed IDs
    rec = foundation.attendance_records[0]
    assert rec.record_id.startswith("f002_rec_")
    assert rec.source_file_name == "workforce_2026.xlsx"
    assert rec.source_row_number == 2

    # Request preserves constituent record IDs and row numbers
    requests = foundation.requests
    assert len(requests) > 0
    first_req = requests[0]
    assert len(first_req.record_ids) > 0
    assert len(first_req.source_row_numbers) > 0
    assert all(rid.startswith("f002_rec_") for rid in first_req.record_ids)

    # Fact preserves constituent record IDs
    facts = foundation.employee_day_facts
    assert len(facts) > 0
    first_fact = facts[0]
    assert len(first_fact.record_ids) > 0
    assert all(rid.startswith("f002_rec_") for rid in first_fact.record_ids)


# =========================================================================
# 9. Non-destructive input immutability
# =========================================================================
def test_input_dataframe_immutability(sample_foundation_df):
    """Verify input DataFrame is not modified in place."""
    df_original = sample_foundation_df.copy(deep=True)

    foundation = CanonicalWorkforceData.from_dataframe(sample_foundation_df)

    # Deep equality comparison between original and passed DataFrame
    pd.testing.assert_frame_equal(sample_foundation_df, df_original)


# =========================================================================
# 10. Compatibility with existing analytical snapshot engine
# =========================================================================
def test_compatibility_with_analytical_snapshot_engine(tmp_path, sample_foundation_df):
    """Verify AnalyticalSnapshot attaches CanonicalWorkforceData and snapshot_service exposes it."""
    file_p = tmp_path / "compat_test.xlsx"
    sample_foundation_df.to_excel(file_p, index=False)

    snapshot_service.clear()
    snapshot = snapshot_service.prepare_dataset(str(file_p))

    # AnalyticalSnapshot has workforce_foundation attached
    assert hasattr(snapshot, "workforce_foundation")
    wf = snapshot.workforce_foundation
    assert isinstance(wf, CanonicalWorkforceData)
    assert len(wf.employees) == 4

    # Service provides clean access
    service_wf = snapshot_service.get_workforce_foundation()
    assert service_wf is wf

    # Standard metrics and breakdowns continue to operate without interference
    metrics = snapshot_service.get_dashboard_metrics()
    assert metrics["total_records"] == 11
    assert metrics["unique_employees"] == 4

    bk = snapshot_service.get_breakdown("Business Unit")
    assert len(bk) > 0

    snapshot_service.clear()


# =========================================================================
# 11. Separate consecutive leave applications are NOT combined
# =========================================================================
def test_consecutive_leave_applications_not_combined_when_metadata_differs():
    """
    Employee EMP001 has two distinct leave applications on consecutive dates:
      - Application A: Monday, quantity 1.0, applied on 2026-09-01, approved by Manager A.
      - Application B: Tuesday, quantity 1.0, applied on 2026-09-04, approved by Manager B.
    Data foundation must NOT combine them into a single 2-day request.
    """
    df = pd.DataFrame([
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Date": "2026-09-07",  # Monday
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 1.0,
            "Applied On": "2026-09-01",
            "Approved On": "2026-09-02",
            "Approved By": "Manager A",
            "Approval Status": "Approved",
        },
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Date": "2026-09-08",  # Tuesday
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 1.0,
            "Applied On": "2026-09-04",
            "Approved On": "2026-09-05",
            "Approved By": "Manager B",
            "Approval Status": "Approved",
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)
    requests = foundation.get_requests_for_employee("EMP001")

    # MUST be 2 distinct requests, NOT combined into 1
    assert len(requests) == 2

    req_a = requests[0]
    req_b = requests[1]

    assert req_a.start_date == date(2026, 9, 7)
    assert req_a.end_date == date(2026, 9, 7)
    assert req_a.total_quantity == 1.0
    assert req_a.applied_on == date(2026, 9, 1)
    assert req_a.approved_by == "Manager A"
    assert req_a.is_inferred is True

    assert req_b.start_date == date(2026, 9, 8)
    assert req_b.end_date == date(2026, 9, 8)
    assert req_b.total_quantity == 1.0
    assert req_b.applied_on == date(2026, 9, 4)
    assert req_b.approved_by == "Manager B"
    assert req_b.is_inferred is True


# =========================================================================
# 12. Explicit request identifiers preserve confirmed request boundaries
# =========================================================================
def test_consecutive_applications_with_explicit_request_ids():
    """Explicit request IDs (REQ-101 and REQ-102) strictly preserve request boundaries."""
    df = pd.DataFrame([
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Date": "2026-09-07",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Request ID": "REQ-101",
            "Applied On": "2026-09-01",
        },
        {
            "Employee Number": "EMP001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Date": "2026-09-08",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Request ID": "REQ-102",
            "Applied On": "2026-09-01",
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)
    requests = foundation.get_requests_for_employee("EMP001")

    assert len(requests) == 2
    assert requests[0].request_id == "REQ-101"
    assert requests[0].source_request_id == "REQ-101"
    assert requests[0].is_inferred is False

    assert requests[1].request_id == "REQ-102"
    assert requests[1].source_request_id == "REQ-102"
    assert requests[1].is_inferred is False


# =========================================================================
# 13. Genuine multi-day application and half-day requests
# =========================================================================
def test_genuine_multi_day_application_and_half_day_request():
    """Verify single multi-day request aggregation and half-day request quantity."""
    df = pd.DataFrame([
        # EMP001: 3-day Sick Leave under one application
        {
            "Employee Number": "EMP001",
            "Date": "2026-09-01",
            "Attendance Type": "Leave",
            "Status": "SL",
            "Quantity": 1.0,
            "Applied On": "2026-08-30",
            "Approved On": "2026-08-31",
            "Approved By": "Manager Bob",
        },
        {
            "Employee Number": "EMP001",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Status": "SL",
            "Quantity": 1.0,
            "Applied On": "2026-08-30",
            "Approved On": "2026-08-31",
            "Approved By": "Manager Bob",
        },
        {
            "Employee Number": "EMP001",
            "Date": "2026-09-03",
            "Attendance Type": "Leave",
            "Status": "SL",
            "Quantity": 1.0,
            "Applied On": "2026-08-30",
            "Approved On": "2026-08-31",
            "Approved By": "Manager Bob",
        },
        # EMP002: Single half-day WFH request
        {
            "Employee Number": "EMP002",
            "Date": "2026-09-01",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 0.5,
            "Applied On": "2026-09-01",
            "Approved By": "Manager Dan",
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)

    # EMP001 has 1 multi-day request
    reqs1 = foundation.get_requests_for_employee("EMP001")
    assert len(reqs1) == 1
    assert reqs1[0].start_date == date(2026, 9, 1)
    assert reqs1[0].end_date == date(2026, 9, 3)
    assert reqs1[0].total_quantity == 3.0
    assert len(reqs1[0].request_dates) == 3

    # EMP002 has 1 half-day request
    reqs2 = foundation.get_requests_for_employee("EMP002")
    assert len(reqs2) == 1
    assert reqs2[0].total_quantity == 0.5
    assert reqs2[0].start_date == date(2026, 9, 1)
    assert reqs2[0].end_date == date(2026, 9, 1)


# =========================================================================
# 14. Two separate half-day leave entries on same date
# =========================================================================
def test_two_separate_half_day_leave_entries_same_date():
    """Verify two half-day leaves on same day sum to 1.0 without duplicate exclusion."""
    df = pd.DataFrame([
        {
            "Employee Number": "EMP010",
            "Date": "2026-09-05",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 0.5,
            "Applied On": "2026-09-01",
        },
        {
            "Employee Number": "EMP010",
            "Date": "2026-09-05",
            "Attendance Type": "Leave",
            "Status": "SL",
            "Leave Name": "Sick Leave",
            "Quantity": 0.5,
            "Applied On": "2026-09-02",
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)

    # Both records preserved and included in analysis
    assert len(foundation.attendance_records) == 2
    assert all(r.include_in_analysis for r in foundation.attendance_records)

    # Fact totals 1.0 with no conflict
    fact = foundation.get_fact("EMP010", date(2026, 9, 5))
    assert fact is not None
    assert fact.record_count == 2
    assert fact.daily_total_quantity == 1.0
    assert fact.has_leave is True
    assert fact.has_conflict is False
    assert fact.quality_status == "VALID"
    assert fact.is_evaluable is True


# =========================================================================
# 15. Conflicting full-day attendance records retain evidence and flag conflict
# =========================================================================
def test_conflicting_full_day_attendance_records_flag_conflict():
    """Verify conflicting full-day Present and Absent records are retained and flagged."""
    df = pd.DataFrame([
        {
            "Employee Number": "EMP020",
            "Employee Name": "Frank",
            "Date": "2026-09-10",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "18:00",
        },
        {
            "Employee Number": "EMP020",
            "Employee Name": "Frank",
            "Date": "2026-09-10",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)

    # Evidence retained: both records kept in attendance_records
    assert len(foundation.attendance_records) == 2

    fact = foundation.get_fact("EMP020", date(2026, 9, 10))
    assert fact is not None
    assert fact.has_conflict is True
    assert fact.quality_status == "CRITICAL"
    assert fact.is_evaluable is False
    assert "PRESENT_AND_ABSENT_COEXIST" in fact.conflict_reasons
    assert "TOTAL_QUANTITY_EXCEEDS_ONE" in fact.conflict_reasons
    assert len(fact.record_ids) == 2


# =========================================================================
# 16. Missing swipe, missing in-time/out-time, and invalid dates
# =========================================================================
def test_missing_swipes_and_invalid_dates_handling():
    """Verify missing punch does not infer 0.0 hrs and invalid dates are cleanly handled."""
    df = pd.DataFrame([
        # Missing out-time
        {
            "Employee Number": "EMP030",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "NA",
        },
        # Missing in-time and out-time
        {
            "Employee Number": "EMP030",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "-",
            "Out Time": "-",
        },
        # Invalid / missing date
        {
            "Employee Number": "EMP030",
            "Date": "InvalidDate",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)

    # 3 total records
    assert len(foundation.attendance_records) == 3

    # Sep 1: In Time 09:00, Out Time None, working_hours is None (NOT 0.0)
    fact1 = foundation.get_fact("EMP030", date(2026, 9, 1))
    assert fact1.working_hours is None
    assert fact1.in_time_minutes == 540
    assert fact1.out_time_minutes is None

    # Sep 2: Both missing -> working_hours is None
    fact2 = foundation.get_fact("EMP030", date(2026, 9, 2))
    assert fact2.working_hours is None
    assert fact2.in_time_minutes is None
    assert fact2.out_time_minutes is None

    # Invalid date record flagged as MISSING_DATE and excluded from daily analysis
    invalid_rec = foundation.attendance_records[2]
    assert invalid_rec.date is None
    assert invalid_rec.include_in_analysis is False
    assert invalid_rec.analysis_exclusion_reason == "MISSING_DATE"
    assert foundation.metadata["missing_date_records_count"] == 1


# =========================================================================
# 17. Historical organizational relationship preservation
# =========================================================================
def test_historical_organizational_relationship_preservation():
    """
    Employee changing Department and Manager mid-period retains historical attribution
    on each date's fact, not retroactively overwritten by latest profile.
    """
    df = pd.DataFrame([
        # Phase 1: Support Dept under Manager Alice
        {
            "Employee Number": "EMP050",
            "Employee Name": "Grace",
            "Business Unit": "Operations",
            "Department": "Support",
            "Reporting Manager": "Alice Lead",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        # Phase 2: Transferred to Backend Dept under Manager Bob
        {
            "Employee Number": "EMP050",
            "Employee Name": "Grace",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob VP",
            "Date": "2026-09-15",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)

    # Sep 1 Fact reflects historical Support / Alice Lead
    fact_sep01 = foundation.get_fact("EMP050", date(2026, 9, 1))
    assert fact_sep01.business_unit == "Operations"
    assert fact_sep01.department == "Support"
    assert fact_sep01.reporting_manager == "Alice Lead"

    # Sep 15 Fact reflects new Engineering / Bob VP
    fact_sep15 = foundation.get_fact("EMP050", date(2026, 9, 15))
    assert fact_sep15.business_unit == "Engineering"
    assert fact_sep15.department == "Backend"
    assert fact_sep15.reporting_manager == "Bob VP"

    # Historical attribute transfer logged in Employee entity
    emp = foundation.get_employee("EMP050")
    assert len(emp.historical_attributes) == 1
    hist = emp.historical_attributes[0]
    assert hist["department"] == "Backend"
    assert hist["reporting_manager"] == "Bob VP"
    assert hist["date"] == "2026-09-15"


# =========================================================================
# 18. Lending Business Unit preserves raw BU and maps effective BU
# =========================================================================
def test_lending_business_unit_preserves_raw_bu():
    """Lending BU preserves raw BU as 'Lending' while setting effective BU to Department."""
    df = pd.DataFrame([
        {
            "Employee Number": "EMP060",
            "Employee Name": "Hannah",
            "Business Unit": "Lending",
            "Department": "Underwriting",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        }
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)
    fact = foundation.get_fact("EMP060", date(2026, 9, 1))

    assert fact.raw_business_unit == "Lending"
    assert fact.effective_business_unit == "Underwriting"
    assert fact.business_unit == "Underwriting"

    emp = foundation.get_employee("EMP060")
    assert emp.business_unit == "Lending"
    assert emp.effective_business_unit == "Underwriting"


# =========================================================================
# 19. Public foundation operations cannot accidentally corrupt snapshot results
# =========================================================================
def test_public_foundation_operations_do_not_corrupt_subsequent_snapshot_results(tmp_path, sample_foundation_df):
    """
    Verify that accessing and executing supported public operations on CanonicalWorkforceData
    cannot corrupt subsequent snapshot metric or breakdown results.
    """
    file_p = tmp_path / "safety_test.xlsx"
    sample_foundation_df.to_excel(file_p, index=False)

    snapshot_service.clear()
    snapshot = snapshot_service.prepare_dataset(str(file_p))

    # Baseline calculations
    base_metrics = snapshot_service.get_dashboard_metrics()
    base_breakdown_bu = snapshot_service.get_breakdown("Business Unit")
    base_breakdown_emp = snapshot_service.get_breakdown("Employee")

    # Access workforce foundation and run extensive public operations
    wf = snapshot_service.get_workforce_foundation()
    assert wf is not None

    # Public lookups and entity queries
    emp = wf.get_employee("EMP001")
    assert emp is not None
    records = wf.get_records_for_employee("EMP001")
    assert len(records) > 0
    facts = wf.get_facts_for_employee("EMP001")
    assert len(facts) > 0
    fact_date = wf.get_fact("EMP001", date(2026, 9, 1))
    assert fact_date is not None
    reqs = wf.get_requests_for_employee("EMP001")

    # Hierarchy lookups
    assert len(wf.org_structure.get_all_business_units()) > 0
    assert len(wf.org_structure.get_direct_reports("Bob Manager")) > 0

    # Defensive copy retrieval
    safe_df = wf.get_raw_dataframe(copy=True)
    safe_df["_corrupt_test_col"] = "ShouldNotAffectSnapshot"

    # Re-retrieve metrics and breakdowns from snapshot service
    after_metrics = snapshot_service.get_dashboard_metrics()
    after_breakdown_bu = snapshot_service.get_breakdown("Business Unit")
    after_breakdown_emp = snapshot_service.get_breakdown("Employee")

    # Metrics and breakdowns must be perfectly identical to baseline
    assert after_metrics == base_metrics
    assert after_breakdown_bu == base_breakdown_bu
    assert after_breakdown_emp == base_breakdown_emp

    # Shared fact_df was NOT corrupted by safe_df mutation
    assert "_corrupt_test_col" not in snapshot.fact_df.columns
    assert "_corrupt_test_col" not in wf.raw_dataframe.columns

    # Verify documented ownership contract
    assert "Ownership & Mutation Rules" in wf.__class__.raw_dataframe.__doc__

    snapshot_service.clear()


# =========================================================================
# 20. Separate applications with different request IDs remain separate
# =========================================================================
def test_distinct_request_ids_remain_separate_even_with_identical_dates_and_metadata():
    """
    Two distinct applications submitted on consecutive dates with identical employee,
    type, application date, approval date, and approver MUST remain strictly separate
    if their explicit source request IDs differ.
    """
    df = pd.DataFrame([
        {
            "Employee Number": "EMP099",
            "Employee Name": "Ian",
            "Business Unit": "Product",
            "Department": "UX",
            "Reporting Manager": "Jane Lead",
            "Date": "2026-09-01",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 1.0,
            "Applied On": "2026-08-25",
            "Approved On": "2026-08-26",
            "Approved By": "Jane Lead",
            "Approval Status": "Approved",
            "Request ID": "REQ-APP-001",
        },
        {
            "Employee Number": "EMP099",
            "Employee Name": "Ian",
            "Business Unit": "Product",
            "Department": "UX",
            "Reporting Manager": "Jane Lead",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "Quantity": 1.0,
            "Applied On": "2026-08-25",
            "Approved On": "2026-08-26",
            "Approved By": "Jane Lead",
            "Approval Status": "Approved",
            "Request ID": "REQ-APP-002",
        },
    ])

    foundation = CanonicalWorkforceData.from_dataframe(df)
    requests = foundation.get_requests_for_employee("EMP099")

    # MUST be 2 distinct requests despite 100% identical dates and metadata
    assert len(requests) == 2

    assert requests[0].request_id == "REQ-APP-001"
    assert requests[0].source_request_id == "REQ-APP-001"
    assert requests[0].is_inferred is False
    assert requests[0].start_date == date(2026, 9, 1)
    assert requests[0].end_date == date(2026, 9, 1)
    assert requests[0].total_quantity == 1.0

    assert requests[1].request_id == "REQ-APP-002"
    assert requests[1].source_request_id == "REQ-APP-002"
    assert requests[1].is_inferred is False
    assert requests[1].start_date == date(2026, 9, 2)
    assert requests[1].end_date == date(2026, 9, 2)
    assert requests[1].total_quantity == 1.0


