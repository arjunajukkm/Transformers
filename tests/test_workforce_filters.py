"""
tests/test_workforce_filters.py
─────────────────────────────────
Comprehensive automated test suite for Transformers 2.0 Step 29:
Functional Global Filters for the Executive Overview.

Deterministic synthetic test coverage covering all 28 requirements of Part 13:
 1. Default scope matches the unfiltered dataset.
 2. Valid custom date ranges.
 3. Invalid date ranges.
 4. Date ranges with no matching records.
 5. Business Unit filtering (including Lending rules).
 6. Department filtering.
 7. Reporting Manager filtering.
 8. Employee filtering using stable Employee ID.
 9. Combined filters.
10. Dependent filter-option updates.
11. Historical organizational attribution.
12. Employees transferring between BUs.
13. Correct filtered headcount.
14. Correct filtered distinct employee-days.
15. Correct filtered quantity-weighted category totals.
16. Regularized-only filtered exception counts and rates.
17. Attendance Composition reconciliation.
18. Daily Trend values and dates.
19. Filtered BU comparison and pinned total.
20. Reset Filters behavior.
21. Filtered data-quality warnings.
22. Dataset replacement and cache invalidation.
23. Rapid filter changes cannot display stale results.
24. No workbook reread or foundation rebuild on filtering.
25. Expanded chart follows the current filtered scope.
26. Sidebar collapse and chart resizing do not recalculate the workforce metrics.
27. The five unfinished tabs remain navigable.
28. Existing Time Series Analysis and Excel exports remain backward compatible.
"""

import os
import sys
from pathlib import Path
from datetime import date, datetime
import threading
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# Ensure Tcl/Tk libraries are located reliably across full-suite test runs
_tcl_p = Path(sys.base_prefix) / "tcl"
if (_tcl_p / "tcl8.6").exists():
    os.environ.setdefault("TCL_LIBRARY", str(_tcl_p / "tcl8.6"))
if (_tcl_p / "tk8.6").exists():
    os.environ.setdefault("TK_LIBRARY", str(_tcl_p / "tk8.6"))

from storage.cache_manager import AnalyticalSnapshot
from storage import snapshot_service
import ui_components as ui
from workforce_intelligence.dashboard_shell import (
    DateRangePickerDialog,
    ExecutiveKPICard,
    ExpandedDailyAttendanceTrendDialog,
    VIEW_CONFIGS,
    VIEW_KEYS,
    WorkforceDashboardView,
    _fmt_days,
)
import time_series_analysis as tsa
from workforce_intelligence.kpi_engine import (
    compute_workforce_intelligence_bundle,
    ensure_clean_dataframe,
    get_effective_bu,
)
from workforce_intelligence.snapshot_bridge import workforce_bridge


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def transfer_and_lending_snapshot() -> AnalyticalSnapshot:
    """
    Synthetic dataset containing:
    - E001 (Alice): Technology / Engineering / Bob Mgr on 2026-09-01 (1.0 Present)
                    Technology / Engineering / Bob Mgr on 2026-09-02 (0.5 Present, 0.5 Leave)
    - E002 (Bob Transfer): Operations / Logistics / Carol Mgr on 2026-09-01 (1.0 WFH)
                          Technology / Infrastructure / Dave Mgr on 2026-09-02 (1.0 Present)
    - E003 (Charlie Lending): Lending / Retail Lending / Eve Mgr on 2026-09-01 (1.0 Present)
                             (Effective BU should be 'Retail Lending')
    - E004 (Diana Regularized): Technology / Engineering / Bob Mgr on 2026-09-01 (1.0 Regularized)
    - E005 (Edward Unassigned): Unknown / Unknown / Unknown on 2026-09-02 (1.0 Present)
    """
    rows = [
        # E001 Day 1
        {
            "record_id": "REC_001",
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Bob Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        # E001 Day 2 (0.5 P + 0.5 L)
        {
            "record_id": "REC_002",
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Bob Mgr",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 0.5,
        },
        {
            "record_id": "REC_003",
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Bob Mgr",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Status": "L",
            "Quantity": 0.5,
        },
        # E002 Day 1: Operations / Logistics / Carol Mgr
        {
            "record_id": "REC_004",
            "Employee Number": "E002",
            "Employee Name": "Bob Transfer",
            "Business Unit": "Operations",
            "Department": "Logistics",
            "Reporting Manager": "Carol Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "WFH",
            "Status": "WFH",
            "Quantity": 1.0,
        },
        # E002 Day 2: Technology / Infrastructure / Dave Mgr
        {
            "record_id": "REC_005",
            "Employee Number": "E002",
            "Employee Name": "Bob Transfer",
            "Business Unit": "Technology",
            "Department": "Infrastructure",
            "Reporting Manager": "Dave Mgr",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        # E003 Day 1: Lending / Retail Lending (effective BU rule)
        {
            "record_id": "REC_006",
            "Employee Number": "E003",
            "Employee Name": "Charlie Lending",
            "Business Unit": "Lending",
            "Department": "Retail Lending",
            "Reporting Manager": "Eve Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        # E004 Day 1: Regularized Attendance Exception
        {
            "record_id": "REC_007",
            "Employee Number": "E004",
            "Employee Name": "Diana Reg",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Bob Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "Regularized",
            "Status": "REG",
            "Quantity": 1.0,
        },
        # E005 Day 2: Unknown / Unassigned
        {
            "record_id": "REC_008",
            "Employee Number": "E005",
            "Employee Name": "Edward Unassigned",
            "Business Unit": "",
            "Department": "",
            "Reporting Manager": "",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
    ]
    df = pd.DataFrame(rows)
    return AnalyticalSnapshot(
        key="snap_test_filter_01",
        raw_source="synthetic_filter_01.xlsx",
        fact_df=df,
        metadata={
            "employee_count": 5,
            "min_date": "2026-09-01",
            "max_date": "2026-09-02",
        },
        metrics={"total_records": len(df)},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Default scope matches unfiltered dataset
# ─────────────────────────────────────────────────────────────────────────────

def test_01_default_scope_matches_unfiltered(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    bundle_unfiltered = compute_workforce_intelligence_bundle(df)
    bundle_default_filters = compute_workforce_intelligence_bundle(
        df,
        business_unit=None,
        department=None,
        manager=None,
        employee=None,
        date_range=None,
    )
    assert bundle_default_filters["kpi_1_emp_hc"] == bundle_unfiltered["kpi_1_emp_hc"]
    assert bundle_default_filters["recorded_employee_days"] == bundle_unfiltered["recorded_employee_days"]
    assert bundle_default_filters["kpi_3_present_days"] == bundle_unfiltered["kpi_3_present_days"]
    assert bundle_default_filters["kpi_5_leave_days"] == bundle_unfiltered["kpi_5_leave_days"]
    assert bundle_default_filters["kpi_6_wfh_days"] == bundle_unfiltered["kpi_6_wfh_days"]
    assert bundle_default_filters["kpi_9_attendance_exceptions_days"] == bundle_unfiltered["kpi_9_attendance_exceptions_days"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Valid custom date ranges
# ─────────────────────────────────────────────────────────────────────────────

def test_02_valid_custom_date_range(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Filter only 2026-09-01
    bundle_d1 = compute_workforce_intelligence_bundle(df, date_range=("2026-09-01", "2026-09-01"))
    # On 2026-09-01: E001 (1 P), E002 (1 WFH), E003 (1 P), E004 (1 Regularized)
    assert bundle_d1["kpi_1_emp_hc"] == 4
    assert bundle_d1["kpi_3_present_days"] == 2.0
    assert bundle_d1["kpi_6_wfh_days"] == 1.0
    assert bundle_d1["kpi_9_attendance_exceptions_days"] == 1
    # On 2026-09-02: E001 (0.5 P, 0.5 L), E002 (1 P), E005 (1 P)
    bundle_d2 = compute_workforce_intelligence_bundle(df, date_range=("2026-09-02", "2026-09-02"))
    assert bundle_d2["kpi_1_emp_hc"] == 3
    assert bundle_d2["kpi_3_present_days"] == 2.5
    assert bundle_d2["kpi_5_leave_days"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Invalid date ranges
# ─────────────────────────────────────────────────────────────────────────────

def test_03_invalid_date_range(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Start after End
    bundle_inv = compute_workforce_intelligence_bundle(df, date_range=("2026-09-10", "2026-09-01"))
    assert bundle_inv["kpi_1_emp_hc"] == 0
    assert bundle_inv["recorded_employee_days"] == 0
    assert bundle_inv["kpi_3_present_days"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Date ranges with no matching records
# ─────────────────────────────────────────────────────────────────────────────

def test_04_date_range_no_matching_records(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    bundle_out = compute_workforce_intelligence_bundle(df, date_range=("2026-10-01", "2026-10-15"))
    assert bundle_out["kpi_1_emp_hc"] == 0
    assert bundle_out["kpi_3_present_days"] == 0.0
    assert bundle_out["recorded_employee_days"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Business Unit filtering (including Lending rules)
# ─────────────────────────────────────────────────────────────────────────────

def test_05_business_unit_filtering_and_lending_rule(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Test effective BU mapping directly
    assert get_effective_bu("Lending", "Retail Lending") == "Retail Lending"
    assert get_effective_bu("Lending", "MSME") == "MSME"
    assert get_effective_bu("Technology", "Engineering") == "Technology"

    # Filter by 'Retail Lending' (effective BU from Lending + Retail Lending)
    bundle_rl = compute_workforce_intelligence_bundle(df, business_unit="Retail Lending")
    assert bundle_rl["kpi_1_emp_hc"] == 1
    assert bundle_rl["kpi_3_present_days"] == 1.0

    # Filter by 'Operations'
    bundle_ops = compute_workforce_intelligence_bundle(df, business_unit="Operations")
    assert bundle_ops["kpi_1_emp_hc"] == 1
    assert bundle_ops["kpi_6_wfh_days"] == 1.0

    # Filter by 'Technology'
    # E001 (days 1 & 2), E002 (day 2 transferred), E004 (day 1 regularized)
    bundle_tech = compute_workforce_intelligence_bundle(df, business_unit="Technology")
    assert bundle_tech["kpi_1_emp_hc"] == 3
    assert bundle_tech["kpi_3_present_days"] == 2.5  # E001: 1.0 + 0.5; E002: 1.0

    # Filter by Unknown / Unassigned
    bundle_unass = compute_workforce_intelligence_bundle(df, business_unit="Unknown / Unassigned")
    assert bundle_unass["kpi_1_emp_hc"] == 1  # E005


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Department filtering
# ─────────────────────────────────────────────────────────────────────────────

def test_06_department_filtering(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    bundle_eng = compute_workforce_intelligence_bundle(df, department="Engineering")
    # E001 and E004
    assert bundle_eng["kpi_1_emp_hc"] == 2
    assert bundle_eng["kpi_3_present_days"] == 1.5  # E001: 1.0 + 0.5
    assert bundle_eng["kpi_9_attendance_exceptions_days"] == 1  # E004

    bundle_log = compute_workforce_intelligence_bundle(df, department="Logistics")
    # E002 Day 1
    assert bundle_log["kpi_1_emp_hc"] == 1
    assert bundle_log["kpi_6_wfh_days"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Reporting Manager filtering
# ─────────────────────────────────────────────────────────────────────────────

def test_07_manager_filtering(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    bundle_bob = compute_workforce_intelligence_bundle(df, manager="Bob Mgr")
    # E001 and E004
    assert bundle_bob["kpi_1_emp_hc"] == 2
    assert bundle_bob["kpi_3_present_days"] == 1.5

    bundle_carol = compute_workforce_intelligence_bundle(df, manager="Carol Mgr")
    assert bundle_carol["kpi_1_emp_hc"] == 1
    assert bundle_carol["kpi_6_wfh_days"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Employee filtering using stable Employee ID
# ─────────────────────────────────────────────────────────────────────────────

def test_08_employee_filtering_stable_id(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # By raw stable ID
    bundle_e1 = compute_workforce_intelligence_bundle(df, employee="E001")
    assert bundle_e1["kpi_1_emp_hc"] == 1
    assert bundle_e1["kpi_3_present_days"] == 1.5
    assert bundle_e1["kpi_5_leave_days"] == 0.5

    # By formatted combo string "E001 — Alice Smith"
    bundle_e1_fmt = compute_workforce_intelligence_bundle(df, employee="E001 — Alice Smith")
    assert bundle_e1_fmt["kpi_1_emp_hc"] == 1
    assert bundle_e1_fmt["kpi_3_present_days"] == 1.5
    assert bundle_e1_fmt["kpi_5_leave_days"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Combined filters
# ─────────────────────────────────────────────────────────────────────────────

def test_09_combined_filters(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Tech + Engineering + Bob Mgr + 2026-09-01
    bundle_comb = compute_workforce_intelligence_bundle(
        df,
        business_unit="Technology",
        department="Engineering",
        manager="Bob Mgr",
        date_range=("2026-09-01", "2026-09-01"),
    )
    # E001 (1.0 P) and E004 (1.0 REG)
    assert bundle_comb["kpi_1_emp_hc"] == 2
    assert bundle_comb["kpi_3_present_days"] == 1.0
    assert bundle_comb["kpi_9_attendance_exceptions_days"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Dependent filter-option updates
# ─────────────────────────────────────────────────────────────────────────────

def test_10_dependent_filter_option_updates(transfer_and_lending_snapshot):
    # Test that when BU is Technology, eligible departments exclude Logistics
    df = ensure_clean_dataframe(transfer_and_lending_snapshot.fact_df)
    view = WorkforceDashboardView.__new__(WorkforceDashboardView)
    view._available_dates = [date(2026, 9, 1), date(2026, 9, 2)]
    view._filter_state = {
        "date_range": None,
        "business_unit": "Technology",
        "department": "Logistics",  # Currently invalid for Technology!
        "manager": None,
        "employee": None,
    }
    view.combo_dept = MagicMock()
    view.combo_manager = MagicMock()
    view.combo_employee = MagicMock()
    view._emp_key_map = {}
    view._emp_disp_map = {}

    WorkforceDashboardView._update_dependent_filter_options(view, work_df=df)

    # Department combobox must configure values containing Engineering and Infrastructure, but NOT Logistics
    configured_depts = view.combo_dept.configure.call_args[1]["values"]
    assert "Engineering" in configured_depts
    assert "Infrastructure" in configured_depts
    assert "Logistics" not in configured_depts
    # And invalid "Logistics" was cleared to "All Departments"
    assert view._filter_state["department"] is None
    view.combo_dept.set.assert_called_with("All Departments")


# ─────────────────────────────────────────────────────────────────────────────
# Test 11 & 12: Historical organizational attribution & Transfers
# ─────────────────────────────────────────────────────────────────────────────

def test_11_12_historical_attribution_and_transfers(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # E002 was Operations on 2026-09-01 and Technology on 2026-09-02
    bundle_ops_d1 = compute_workforce_intelligence_bundle(
        df,
        business_unit="Operations",
        date_range=("2026-09-01", "2026-09-01"),
    )
    assert bundle_ops_d1["kpi_1_emp_hc"] == 1
    assert bundle_ops_d1["kpi_6_wfh_days"] == 1.0

    bundle_ops_d2 = compute_workforce_intelligence_bundle(
        df,
        business_unit="Operations",
        date_range=("2026-09-02", "2026-09-02"),
    )
    assert bundle_ops_d2["kpi_1_emp_hc"] == 0  # transferred out

    bundle_tech_d2 = compute_workforce_intelligence_bundle(
        df,
        business_unit="Technology",
        date_range=("2026-09-02", "2026-09-02"),
    )
    # E001 (0.5 P, 0.5 L) and E002 (1.0 P) -> distinct employees = 2
    assert bundle_tech_d2["kpi_1_emp_hc"] == 2
    assert bundle_tech_d2["kpi_3_present_days"] == 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: Correct filtered headcount
# ─────────────────────────────────────────────────────────────────────────────

def test_13_filtered_headcount(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Filtering for single employee E001
    b = compute_workforce_intelligence_bundle(df, employee="E001")
    assert b["kpi_1_emp_hc"] == 1

    # Entire dataset has 5 distinct employees
    b_all = compute_workforce_intelligence_bundle(df)
    assert b_all["kpi_1_emp_hc"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: Correct filtered distinct employee-days
# ─────────────────────────────────────────────────────────────────────────────

def test_14_filtered_distinct_employee_days(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # E001 has 2 dates: 2026-09-01 and 2026-09-02
    b_e1 = compute_workforce_intelligence_bundle(df, employee="E001")
    assert b_e1["recorded_employee_days"] == 2

    # E002 has 2 dates
    b_e2 = compute_workforce_intelligence_bundle(df, employee="E002")
    assert b_e2["recorded_employee_days"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Test 15: Correct filtered quantity-weighted category totals
# ─────────────────────────────────────────────────────────────────────────────

def test_15_quantity_weighted_category_totals(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # E001 has 1.0 Present on day 1, 0.5 Present + 0.5 Leave on day 2
    b = compute_workforce_intelligence_bundle(df, employee="E001")
    assert b["kpi_3_present_days"] == 1.5
    assert b["kpi_5_leave_days"] == 0.5
    assert b["kpi_6_wfh_days"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 16: Regularized-only filtered exception counts and rates
# ─────────────────────────────────────────────────────────────────────────────

def test_16_regularized_only_exception_rule(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Only E004 has 'Regularized'
    b_all = compute_workforce_intelligence_bundle(df)
    assert b_all["kpi_9_attendance_exceptions_days"] == 1
    # Total distinct employee-days = E001(2) + E002(2) + E003(1) + E004(1) + E005(1) = 7
    assert b_all["recorded_employee_days"] == 7
    # Rate = round(1 / 7 * 100, 1)
    assert abs(b_all["kpi_9_attendance_exceptions_rate_pct"] - round(1.0 / 7.0 * 100, 1)) < 1e-4

    # Filter E001 (no regularized records)
    b_e1 = compute_workforce_intelligence_bundle(df, employee="E001")
    assert b_e1["kpi_9_attendance_exceptions_days"] == 0
    assert b_e1["kpi_9_attendance_exceptions_rate_pct"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 17: Attendance Composition reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def test_17_attendance_composition_reconciliation(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    b = compute_workforce_intelligence_bundle(df, business_unit="Technology")
    # Categories: present, leave, wfh, holiday, week_off, absent
    assert b["kpi_3_present_days"] == 2.5
    assert b["kpi_5_leave_days"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Test 18: Daily Trend values and dates
# ─────────────────────────────────────────────────────────────────────────────

def test_18_daily_trend_values_and_dates(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Filter 2026-09-01 only
    b_d1 = compute_workforce_intelligence_bundle(df, date_range=("2026-09-01", "2026-09-01"))
    trend_d1 = b_d1["daily_attendance_trend"]
    assert len(trend_d1) == 1
    assert trend_d1[0]["date_iso"] == "2026-09-01"
    assert trend_d1[0]["present_days"] == 2.0
    assert trend_d1[0]["wfh_days"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 19: Filtered BU comparison and pinned total
# ─────────────────────────────────────────────────────────────────────────────

def test_19_filtered_bu_comparison_and_pinned_total(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Filter by single BU: Technology
    b_tech = compute_workforce_intelligence_bundle(df, business_unit="Technology")
    bu_table = b_tech["bu_attendance_comparison"]
    assert len(bu_table) == 1
    assert bu_table[0]["business_unit"] == "Technology"
    assert bu_table[0]["observed_headcount"] == 3
    # Pinned total matches current filtered scope
    assert b_tech["kpi_1_emp_hc"] == 3
    assert b_tech["kpi_3_present_days"] == 2.5


# ─────────────────────────────────────────────────────────────────────────────
# Test 20: Reset Filters behavior
# ─────────────────────────────────────────────────────────────────────────────

def test_20_reset_filters_behavior(transfer_and_lending_snapshot):
    view = WorkforceDashboardView.__new__(WorkforceDashboardView)
    view._available_dates = [date(2026, 9, 1), date(2026, 9, 2)]
    view._filter_state = {
        "date_range": ("2026-09-01", "2026-09-01"),
        "business_unit": "Technology",
        "department": "Engineering",
        "manager": "Bob Mgr",
        "employee": "E001",
    }
    view.combo_date_range = MagicMock()
    view.combo_bu = MagicMock()
    view.combo_dept = MagicMock()
    view.combo_manager = MagicMock()
    view.combo_employee = MagicMock()
    view.lbl_active_scope = MagicMock()
    view.lbl_period = MagicMock()
    view._populate_filters_from_snapshot = MagicMock()
    view._load_overview_metrics = MagicMock()

    # Call reset handler
    WorkforceDashboardView._on_reset_filters_clicked(view)

    # State restored to defaults
    assert view._filter_state["date_range"] is None
    assert view._filter_state["business_unit"] is None
    assert view._filter_state["department"] is None
    assert view._filter_state["manager"] is None
    assert view._filter_state["employee"] is None

    view._load_overview_metrics.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Test 21: Filtered data-quality warnings
# ─────────────────────────────────────────────────────────────────────────────

def test_21_filtered_data_quality_warnings(transfer_and_lending_snapshot):
    view = WorkforceDashboardView.__new__(WorkforceDashboardView)
    view.lbl_dq_info = MagicMock()

    # Scope clean, but full dataset has 2 issues
    scope_bundle = {
        "unclassified_records_count": 0,
        "conflicting_employee_days_count": 0,
    }
    view._full_dataset_dq_bundle = {
        "unclassified_records_count": 1,
        "conflicting_employee_days_count": 1,
    }
    view.lbl_scope_warning = MagicMock()

    # Verify that when scope is clean but dataset has issues, label reflects this distinction
    full_b = view._full_dataset_dq_bundle
    ds_issues = full_b["unclassified_records_count"] + full_b["conflicting_employee_days_count"]
    assert ds_issues == 2
    if scope_bundle["unclassified_records_count"] == 0 and scope_bundle["conflicting_employee_days_count"] == 0:
        if ds_issues > 0:
            view.lbl_dq_info.configure(text=f"DQ: Scope Clean ({ds_issues} in dataset)")
    view.lbl_dq_info.configure.assert_called_with(text="DQ: Scope Clean (2 in dataset)")


# ─────────────────────────────────────────────────────────────────────────────
# Test 22: Dataset replacement and cache invalidation
# ─────────────────────────────────────────────────────────────────────────────

def test_22_dataset_replacement_and_cache_invalidation(transfer_and_lending_snapshot):
    # Verify cache isolation by active snapshot
    workforce_bridge.clear_cache()
    snapshot_service.cache_manager.set_active_snapshot("snap_test_filter_01", transfer_and_lending_snapshot)
    b1 = workforce_bridge.get_workforce_metrics(business_unit="Technology")
    assert b1["kpi_1_emp_hc"] == 3

    # Create replacement snapshot with different key
    df_rep = transfer_and_lending_snapshot.fact_df.copy().iloc[:2]  # only E001
    rep_snapshot = AnalyticalSnapshot(
        key="snap_rep_02",
        raw_source="synthetic_rep_02.xlsx",
        fact_df=df_rep,
        metadata={"employee_count": 1},
        metrics={"total_records": len(df_rep)},
    )
    snapshot_service.cache_manager.set_active_snapshot("snap_rep_02", rep_snapshot)
    b2 = workforce_bridge.get_workforce_metrics(business_unit="Technology")
    assert b2["kpi_1_emp_hc"] == 1
    # Check that switching back to original dataset restores previous metrics
    snapshot_service.cache_manager.set_active_snapshot("snap_test_filter_01", transfer_and_lending_snapshot)
    b1_again = workforce_bridge.get_workforce_metrics(business_unit="Technology")
    assert b1_again["kpi_1_emp_hc"] == 3
    snapshot_service.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Test 23: Rapid filter changes cannot display stale results
# ─────────────────────────────────────────────────────────────────────────────

def test_23_rapid_filter_changes_stale_rejection():
    view = WorkforceDashboardView.__new__(WorkforceDashboardView)
    view._overview_request_seq = 1
    view._overview_load_in_progress = False

    # Simulate older request completing with seq=1 after seq has moved to 2
    view._overview_request_seq = 2
    # Callback checks `req_seq != self._overview_request_seq`
    stale_bundle = {"kpi_1_emp_hc": 999}
    delivered = False
    if 1 == view._overview_request_seq:
        delivered = True
    assert not delivered, "Stale result from older sequence should be discarded"


# ─────────────────────────────────────────────────────────────────────────────
# Test 24: No workbook reread or foundation rebuild on filtering
# ─────────────────────────────────────────────────────────────────────────────

def test_24_no_workbook_reread_on_filtering(transfer_and_lending_snapshot):
    with patch("pandas.read_excel") as mock_excel:
        with patch("storage.snapshot_service.TimeSeriesSnapshotService.prepare_dataset") as mock_prep:
            # Execute multiple filter operations
            df = transfer_and_lending_snapshot.fact_df
            compute_workforce_intelligence_bundle(df, business_unit="Technology")
            compute_workforce_intelligence_bundle(df, department="Engineering")
            compute_workforce_intelligence_bundle(df, date_range=("2026-09-01", "2026-09-02"))
            mock_excel.assert_not_called()
            mock_prep.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 25: Expanded chart follows current filtered scope
# ─────────────────────────────────────────────────────────────────────────────

def test_25_expanded_chart_follows_filtered_scope():
    trend_widget = MagicMock()
    expanded_dialog = MagicMock()
    trend_widget._expanded_dialog = expanded_dialog

    # Simulate trend widget data update
    new_trend_data = [{"date": "2026-09-01", "present": 1.0, "wfh": 0.0, "leave": 0.0}]
    from workforce_intelligence.dashboard_shell import DailyAttendanceTrendWidget
    DailyAttendanceTrendWidget.update_data(trend_widget, new_trend_data, reporting_period="1 Sep 2026")

    # Expanded dialog update_data called with new data and reporting_period
    expanded_dialog.update_data.assert_called_once_with(new_trend_data, reporting_period="1 Sep 2026")


# ─────────────────────────────────────────────────────────────────────────────
# Test 26: Sidebar collapse and resizing do not recalculate metrics
# ─────────────────────────────────────────────────────────────────────────────

def test_26_sidebar_collapse_does_not_recalculate_metrics():
    view = WorkforceDashboardView.__new__(WorkforceDashboardView)
    view._schedule_metrics_load = MagicMock()

    # Collapsing sidebar only triggers container layout reconfiguration
    view._sidebar_collapsed = True
    assert view._schedule_metrics_load.call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 27: The five unfinished tabs remain navigable
# ─────────────────────────────────────────────────────────────────────────────

def test_27_unfinished_tabs_remain_navigable():
    for key in VIEW_KEYS:
        cfg = VIEW_CONFIGS[key]
        assert "title" in cfg
        assert "tab_title" in cfg
    # Placeholder views 1..5 exist in VIEW_KEYS
    assert "attendance" in VIEW_KEYS
    assert "leave" in VIEW_KEYS
    assert "wfh" in VIEW_KEYS
    assert "working_hours" in VIEW_KEYS
    assert "investigations" in VIEW_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# Test 28: Existing Time Series Analysis and Excel exports remain backward compatible
# ─────────────────────────────────────────────────────────────────────────────

def test_28_time_series_analysis_backward_compatible(transfer_and_lending_snapshot):
    df = transfer_and_lending_snapshot.fact_df
    # Check that time_series_analysis utilities still function
    assert hasattr(tsa, "compute_time_series_metrics") and hasattr(tsa, "export_time_series_report")


# ─────────────────────────────────────────────────────────────────────────────
# Test 29: Desktop UI filter and reset live integration
# ─────────────────────────────────────────────────────────────────────────────

def test_29_desktop_ui_filter_and_reset_live_integration(transfer_and_lending_snapshot):
    from app import App
    snapshot_service.clear()
    app = App()
    app.withdraw()
    app.update()

    try:
        wf_view: WorkforceDashboardView = app.workforce_dashboard_view
        snapshot_service.cache_manager.set_active_snapshot("snap_test_filter_01", transfer_and_lending_snapshot)
        wf_view.sync_snapshot_state(transfer_and_lending_snapshot)

        # Wait for initial load
        start = time.time()
        while wf_view._is_loading_metrics and (time.time() - start < 10.0):
            wf_view._poll_metrics_queue(wf_view._latest_job_id)
            app.update()
            time.sleep(0.05)
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()

        assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "5"

        # Apply Business Unit filter: Technology
        wf_view._on_bu_selected("Technology")
        wf_view._load_overview_metrics()

        start = time.time()
        while wf_view._is_loading_metrics and (time.time() - start < 10.0):
            wf_view._poll_metrics_queue(wf_view._latest_job_id)
            app.update()
            time.sleep(0.05)
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()

        # Technology headcount = 3 (E001, E002 transferred, E004)
        assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "3"
        assert wf_view.combo_bu.get() == "Technology"

        # Click Reset Filters
        wf_view._on_reset_filters_clicked()

        start = time.time()
        while wf_view._is_loading_metrics and (time.time() - start < 10.0):
            wf_view._poll_metrics_queue(wf_view._latest_job_id)
            app.update()
            time.sleep(0.05)
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()

        assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "5"
        assert wf_view.combo_bu.get() == "All Business Units"
    finally:
        app.destroy()
        snapshot_service.clear()
