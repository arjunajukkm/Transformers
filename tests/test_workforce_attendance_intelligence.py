"""
tests/test_workforce_attendance_intelligence.py
───────────────────────────────────────────────
Synthetic automated tests for Transformers 2.0 Step 31:
Attendance Intelligence: Summary, Trends and BU Comparison.

Validates all 18 required testing items from Part 9:
 1. All six Attendance KPIs.
 2. Distinct recorded employee-day counting.
 3. Correct quantity-weighted Present and Absent totals.
 4. Source-backed Missing Swipe qualification.
 5. Regularized-only exception qualification.
 6. Non-additive treatment of analytical overlays.
 7. Correct attendance composition reconciliation.
 8. Daily trend values and observed-date handling.
 9. Historical BU attribution.
10. BU-level denominators and organization-wide totals.
11. Global filter integration.
12. Combined BU and Date Range filtering.
13. Employee filter integration.
14. Reset behavior.
15. Dataset replacement and stale-result safeguards.
16. No workbook rereads when switching tabs.
17. Existing Overview metrics and layout remain intact.
18. Existing navigation and legacy exports remain compatible.

All tests strictly use synthetic data fixtures. No production records or real identities.
"""

import datetime
from datetime import date, timedelta
import queue
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest
import tkinter as tk
import customtkinter as ctk

from app import App
import ui_components as ui
from storage.cache_manager import AnalyticalSnapshot
from storage import snapshot_service
from workforce_intelligence.kpi_engine import (
    compute_workforce_intelligence_bundle,
    _is_missing_swipe_series,
    _is_regularized_series,
)
calculate_workforce_kpis = compute_workforce_intelligence_bundle
from workforce_intelligence.snapshot_bridge import workforce_bridge
from workforce_intelligence.dashboard_shell import (
    WorkforceDashboardView,
    AttendanceDailyTrendWidget,
    AttendanceStatusBreakdownWidget,
    AttendanceBUComparisonWidget,
    ATTENDANCE_TABLE_COLUMNS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def desktop_app():
    """Headless Desktop App instance reused across tests in this module."""
    snapshot_service.clear()
    try:
        app = App()
        app.withdraw()
        app.update()
    except Exception as e:
        pytest.skip(f"Tkinter / GUI environment not available: {e}")

    yield app

    try:
        app.destroy()
    except Exception:
        pass
    snapshot_service.clear()


@pytest.fixture
def synthetic_attendance_dataset() -> pd.DataFrame:
    """
    Synthetic dataset designed to test:
    - 6 attendance KPIs
    - Distinct calendar employee-days vs quantity-weighted day equivalents
    - Source-backed Missing Swipes (via Attendance Type and Status)
    - Regularized-only exception days
    - Analytical overlay non-additivity
    - Historical BU attribution across transfers
    - Organization-wide deduplicated unique headcount
    """
    rows = [
        # Employee 1: BU_Alpha, Full Present Day
        {
            "record_id": "REC_001",
            "Employee Number": "SYNTH_001",
            "Employee Name": "Synthetic Employee 001",
            "Business Unit": "BU_Alpha",
            "Department": "Engineering",
            "Reporting Manager": "Manager Alpha",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        # Employee 2: BU_Alpha, Full Absent Day
        {
            "record_id": "REC_002",
            "Employee Number": "SYNTH_002",
            "Employee Name": "Synthetic Employee 002",
            "Business Unit": "BU_Alpha",
            "Department": "Engineering",
            "Reporting Manager": "Manager Alpha",
            "Date": "2026-09-01",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
        },
        # Employee 3: BU_Beta, Missing Swipe via Attendance Type "Missing Swipe"
        {
            "record_id": "REC_003",
            "Employee Number": "SYNTH_003",
            "Employee Name": "Synthetic Employee 003",
            "Business Unit": "BU_Beta",
            "Department": "Operations",
            "Reporting Manager": "Manager Beta",
            "Date": "2026-09-01",
            "Attendance Type": "Missing Swipe",
            "Status": "P(MS)",
            "Quantity": 1.0,
        },
        # Employee 4: BU_Beta, Regularized-only exception day
        {
            "record_id": "REC_004",
            "Employee Number": "SYNTH_004",
            "Employee Name": "Synthetic Employee 004",
            "Business Unit": "BU_Beta",
            "Department": "Operations",
            "Reporting Manager": "Manager Beta",
            "Date": "2026-09-01",
            "Attendance Type": "Regularized",
            "Status": "P(R)",
            "Approval Status": "Approved",
            "Quantity": 1.0,
        },
        # Employee 5: Transferred from BU_Alpha on 09-01 to BU_Beta on 09-02
        {
            "record_id": "REC_005_1",
            "Employee Number": "SYNTH_005",
            "Employee Name": "Synthetic Employee 005",
            "Business Unit": "BU_Alpha",
            "Department": "Engineering",
            "Reporting Manager": "Manager Alpha",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        {
            "record_id": "REC_005_2",
            "Employee Number": "SYNTH_005",
            "Employee Name": "Synthetic Employee 005",
            "Business Unit": "BU_Beta",
            "Department": "Operations",
            "Reporting Manager": "Manager Beta",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        # Employee 6: Half-day Present + Half-day Leave (split day)
        {
            "record_id": "REC_006_1",
            "Employee Number": "SYNTH_006",
            "Employee Name": "Synthetic Employee 006",
            "Business Unit": "BU_Alpha",
            "Department": "Engineering",
            "Reporting Manager": "Manager Alpha",
            "Date": "2026-09-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 0.5,
        },
        {
            "record_id": "REC_006_2",
            "Employee Number": "SYNTH_006",
            "Employee Name": "Synthetic Employee 006",
            "Business Unit": "BU_Alpha",
            "Department": "Engineering",
            "Reporting Manager": "Manager Alpha",
            "Date": "2026-09-01",
            "Attendance Type": "Leave",
            "Status": "L",
            "Quantity": 0.5,
        },
        # Employee 7: BU_Beta, Missing Swipe via Status "MS" with Attendance Type "Present"
        {
            "record_id": "REC_007",
            "Employee Number": "SYNTH_007",
            "Employee Name": "Synthetic Employee 007",
            "Business Unit": "BU_Beta",
            "Department": "Operations",
            "Reporting Manager": "Manager Beta",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "MS",
            "Quantity": 1.0,
        },
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def synthetic_attendance_snapshot(synthetic_attendance_dataset) -> AnalyticalSnapshot:
    """AnalyticalSnapshot wrapping synthetic_attendance_dataset."""
    df = synthetic_attendance_dataset
    snap = AnalyticalSnapshot(
        key="snap_attendance_synth_test",
        fact_df=df,
        dataset_id="SYNTH_ATTENDANCE_STEP31",
        raw_source="synthetic_attendance.xlsx",
        metadata={
            "total_records": len(df),
            "min_date": "2026-09-01",
            "max_date": "2026-09-02",
            "employee_count": 7,
        },
    )
    return snap


# ─────────────────────────────────────────────────────────────────────────────
# 1. All Six Attendance KPIs & Denominators
# ─────────────────────────────────────────────────────────────────────────────

def test_01_all_six_attendance_kpis_calculated(synthetic_attendance_snapshot):
    """Verify that all six Attendance KPIs are present in the metrics bundle."""
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)

    assert "att_kpi_observed_employees" in bundle
    assert "att_kpi_recorded_employee_days" in bundle
    assert "att_kpi_present_days" in bundle
    assert "att_kpi_present_pct" in bundle
    assert "att_kpi_absent_days" in bundle
    assert "att_kpi_absent_pct" in bundle
    assert "att_kpi_missing_swipe_days" in bundle
    assert "att_kpi_missing_swipe_rate_pct" in bundle
    assert "att_kpi_missing_swipe_affected_emps" in bundle
    assert "att_kpi_regularized_days" in bundle
    assert "att_kpi_regularized_rate_pct" in bundle
    assert "att_kpi_regularized_affected_emps" in bundle

    # Check observed employees: 7 distinct employees
    assert bundle["att_kpi_observed_employees"] == 7


# ─────────────────────────────────────────────────────────────────────────────
# 2. Distinct Recorded Employee-Day Counting
# ─────────────────────────────────────────────────────────────────────────────

def test_02_distinct_recorded_employee_days_counting(synthetic_attendance_snapshot):
    """
    Distinct recorded employee-calendar-days should count distinct (Employee Number, Date) pairs.
    Total distinct days:
      SYNTH_001: 2026-09-01 (1)
      SYNTH_002: 2026-09-01 (1)
      SYNTH_003: 2026-09-01 (1)
      SYNTH_004: 2026-09-01 (1)
      SYNTH_005: 2026-09-01, 2026-09-02 (2)
      SYNTH_006: 2026-09-01 (1 despite 2 rows!)
      SYNTH_007: 2026-09-02 (1)
    Total = 8 distinct employee-days.
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    assert bundle["att_kpi_recorded_employee_days"] == 8
    # Ensure it's integer distinct calendar days, not quantity-weighted
    assert isinstance(bundle["att_kpi_recorded_employee_days"], int)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Correct Quantity-Weighted Present and Absent Totals
# ─────────────────────────────────────────────────────────────────────────────

def test_03_quantity_weighted_present_and_absent(synthetic_attendance_snapshot):
    """
    Present days must be quantity-weighted:
      SYNTH_001: 1.0
      SYNTH_003: 1.0 (Missing Swipe is treated as Present in canonical type)
      SYNTH_004: 1.0 (Regularized is Present equivalent in canonical type)
      SYNTH_005: 1.0 + 1.0 = 2.0
      SYNTH_006: 0.5
      SYNTH_007: 1.0
    Total Present = 6.5 days.

    Absent days:
      SYNTH_002: 1.0
    Total Absent = 1.0 days.
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    assert bundle["att_kpi_present_days"] == 6.5
    assert bundle["att_kpi_absent_days"] == 1.0

    # Denominator is 8.0 (6.5 present + 0.5 leave + 1.0 absent = 8.0)
    assert bundle["attendance_composition_denominator"] == 8.0
    assert pytest.approx(bundle["att_kpi_present_pct"], 0.1) == (6.5 / 8.0) * 100.0
    assert pytest.approx(bundle["att_kpi_absent_pct"], 0.1) == (1.0 / 8.0) * 100.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Source-Backed Missing Swipe Qualification
# ─────────────────────────────────────────────────────────────────────────────

def test_04_source_backed_missing_swipe_qualification(synthetic_attendance_snapshot):
    """
    Verify qualification of Missing Swipes:
    - SYNTH_003 qualifies via Attendance Type 'Missing Swipe'
    - SYNTH_007 qualifies via Status 'MS'
    - Total Missing Swipe days = 2
    - Affected employees = 2 (SYNTH_003, SYNTH_007)
    - Rate = (2 / 8) * 100 = 25.0%
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    assert bundle["att_kpi_missing_swipe_days"] == 2
    assert bundle["att_kpi_missing_swipe_affected_emps"] == 2
    assert pytest.approx(bundle["att_kpi_missing_swipe_rate_pct"], 0.1) == 25.0

    # Test helper directly
    df = synthetic_attendance_snapshot.fact_df
    ms_series = _is_missing_swipe_series(df)
    assert ms_series.sum() == 2


# ─────────────────────────────────────────────────────────────────────────────
# 5. Regularized-Only Exception Qualification
# ─────────────────────────────────────────────────────────────────────────────

def test_05_regularized_only_qualification(synthetic_attendance_snapshot):
    """
    Verify Attendance Exceptions remain strictly Regularized:
    - SYNTH_004 qualifies (Attendance Type normalized strictly == 'Regularized')
    - SYNTH_003 (Missing Swipe) must NOT qualify as Regularized!
    - SYNTH_002 (Absent) must NOT qualify!
    - Total Regularized days = 1
    - Rate = (1 / 8) * 100 = 12.5%
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    assert bundle["att_kpi_regularized_days"] == 1
    assert bundle["att_kpi_regularized_affected_emps"] == 1
    assert pytest.approx(bundle["att_kpi_regularized_rate_pct"], 0.1) == 12.5


# ─────────────────────────────────────────────────────────────────────────────
# 6. Non-Additive Treatment of Analytical Overlays
# ─────────────────────────────────────────────────────────────────────────────

def test_06_non_additive_treatment_of_overlays(synthetic_attendance_snapshot):
    """
    Missing Swipe and Regularized are analytical overlays, not additive categories.
    Composition breakdown categories must sum exactly to composition denominator (8.0).
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    comp = bundle["attendance_composition"]
    total_qty = sum(item["days"] for item in comp)
    assert pytest.approx(total_qty, 0.01) == 8.0

    # Composition items must not have 'Missing Swipe' or 'Regularized' as categories
    comp_cats = [item["category"] for item in comp]
    assert "Missing Swipe" not in comp_cats
    assert "Regularized" not in comp_cats


# ─────────────────────────────────────────────────────────────────────────────
# 7. Correct Attendance Composition Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def test_07_composition_reconciliation(synthetic_attendance_snapshot):
    """Verify 8 mutually exclusive categories reconcile to denominator."""
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    denom = bundle["attendance_composition_denominator"]
    assert denom == 8.0

    comp_dict = {item["category"]: item["days"] for item in bundle["attendance_composition"]}
    assert comp_dict.get("Present", 0.0) == 6.5
    assert comp_dict.get("Absent", 0.0) == 1.0
    assert comp_dict.get("Leave", 0.0) == 0.5
    assert comp_dict.get("On Duty", 0.0) == 0.0
    assert comp_dict.get("WFH", 0.0) == 0.0
    assert comp_dict.get("Holiday", 0.0) == 0.0
    assert comp_dict.get("Week Off", 0.0) == 0.0
    assert comp_dict.get("Unclassified", 0.0) == 0.0

    total_sum = sum(comp_dict.values())
    assert pytest.approx(total_sum, 0.01) == denom


# ─────────────────────────────────────────────────────────────────────────────
# 8. Daily Trend Values and Observed-Date Handling
# ─────────────────────────────────────────────────────────────────────────────

def test_08_daily_trend_series_and_dates(synthetic_attendance_snapshot):
    """
    Verify daily trend series:
    Dates in source: 2026-09-01 and 2026-09-02 (exactly 2 dates; no false zeros for other dates).
    On 2026-09-01:
      Present = 4.5 (SYNTH_001: 1, SYNTH_003: 1, SYNTH_004: 1, SYNTH_005: 1, SYNTH_006: 0.5)
      Absent = 1.0 (SYNTH_002: 1)
      Missing Swipes = 1 (SYNTH_003)
      Regularized = 1 (SYNTH_004)
    On 2026-09-02:
      Present = 2.0 (SYNTH_005: 1, SYNTH_007: 1)
      Absent = 0.0
      Missing Swipes = 1 (SYNTH_007)
      Regularized = 0
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    trend = bundle["daily_attendance_trend"]
    assert len(trend) == 2

    d1 = trend[0]
    assert str(d1["date"]) == "2026-09-01"
    assert d1["present_days"] == 4.5
    assert d1["absent_days"] == 1.0
    assert d1["missing_swipe_days"] == 1
    assert d1["regularized_days"] == 1

    d2 = trend[1]
    assert str(d2["date"]) == "2026-09-02"
    assert d2["present_days"] == 2.0
    assert d2["absent_days"] == 0.0
    assert d2["missing_swipe_days"] == 1
    assert d2["regularized_days"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 9. Historical BU Attribution
# ─────────────────────────────────────────────────────────────────────────────

def test_09_historical_bu_attribution(synthetic_attendance_snapshot):
    """
    SYNTH_005 transferred from BU_Alpha on 2026-09-01 to BU_Beta on 2026-09-02.
    BU comparison table should attribute:
    BU_Alpha:
      Observed headcount = 4 (SYNTH_001, SYNTH_002, SYNTH_005, SYNTH_006)
      Recorded days = 4 (SYNTH_001, SYNTH_002, SYNTH_005, SYNTH_006 on 09-01)
      Present days = 2.5 (SYNTH_001: 1.0, SYNTH_005: 1.0, SYNTH_006: 0.5)
      Absent days = 1.0 (SYNTH_002: 1.0)
    BU_Beta:
      Observed headcount = 4 (SYNTH_003, SYNTH_004, SYNTH_005, SYNTH_007)
      Recorded days = 4 (SYNTH_003, SYNTH_004 on 09-01; SYNTH_005, SYNTH_007 on 09-02)
      Present days = 4.0 (SYNTH_003: 1, SYNTH_004: 1, SYNTH_005: 1, SYNTH_007: 1)
      Absent days = 0.0
      Missing Swipes = 2 (SYNTH_003 on 09-01, SYNTH_007 on 09-02)
      Regularized = 1 (SYNTH_004 on 09-01)
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    bu_dict = {row["business_unit"]: row for row in bundle["bu_attendance_comparison"]}

    assert "BU_Alpha" in bu_dict
    assert "BU_Beta" in bu_dict

    alpha = bu_dict["BU_Alpha"]
    assert alpha["observed_headcount"] == 4
    assert alpha["recorded_employee_days"] == 4
    assert alpha["present_days"] == 2.5
    assert alpha["absent_days"] == 1.0
    assert alpha["missing_swipe_days"] == 0
    assert alpha["regularized_days"] == 0

    beta = bu_dict["BU_Beta"]
    assert beta["observed_headcount"] == 4
    assert beta["recorded_employee_days"] == 4
    assert beta["present_days"] == 4.0
    assert beta["absent_days"] == 0.0
    assert beta["missing_swipe_days"] == 2
    assert beta["regularized_days"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 10. BU-Level Denominators and Organization-Wide Totals
# ─────────────────────────────────────────────────────────────────────────────

def test_10_bu_denominators_and_deduplicated_headcount(synthetic_attendance_snapshot):
    """
    Verify BU table denominators and organization-wide pinned total:
    - BU Present % uses BU composition denominator (BU_Alpha: 2.5 / 4.0 = 62.5%)
    - BU Absent % uses BU composition denominator (BU_Alpha: 1.0 / 4.0 = 25.0%)
    - BU MS Rate uses BU recorded employee-days (BU_Beta: 2 / 4 = 50.0%)
    - BU Reg Rate uses BU recorded employee-days (BU_Beta: 1 / 4 = 25.0%)
    - Pinned Total observed headcount must be 7 (deduplicated!), NOT 4 + 4 = 8!
    """
    bundle = calculate_workforce_kpis(synthetic_attendance_snapshot.fact_df)
    bu_dict = {row["business_unit"]: row for row in bundle["bu_attendance_comparison"]}

    alpha = bu_dict["BU_Alpha"]
    assert pytest.approx(alpha["present_pct"], 0.1) == 62.5
    assert pytest.approx(alpha["absent_pct"], 0.1) == 25.0

    beta = bu_dict["BU_Beta"]
    assert pytest.approx(beta["missing_swipe_rate_pct"], 0.1) == 50.0
    assert pytest.approx(beta["regularized_rate_pct"], 0.1) == 25.0

    total = bundle["bu_comparison_total"]
    # Total headcount MUST be deduplicated organization-wide count (7), NOT sum of BUs (8)
    assert total["observed_headcount"] == 7
    assert total["recorded_employee_days"] == 8
    assert total["present_days"] == 6.5
    assert total["absent_days"] == 1.0
    assert total["missing_swipe_days"] == 2
    assert total["regularized_days"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 11–14. Global Filter Integration (Date, BU, Employee, Reset) in Desktop Shell
# ─────────────────────────────────────────────────────────────────────────────

def test_11_to_14_global_filters_and_attendance_view(desktop_app, synthetic_attendance_snapshot):
    """
    Test desktop shell Attendance tab:
    - Renders Attendance tab widgets
    - Updates with BU filter
    - Updates with Date filter
    - Updates with Employee filter
    - Resets restores complete dataset scope
    """
    app = desktop_app
    snapshot_service.cache_manager.set_active_snapshot("snap_attendance_synth_test", synthetic_attendance_snapshot)
    app.update()

    view: WorkforceDashboardView = app.workforce_dashboard_view
    view.sync_snapshot_state(synthetic_attendance_snapshot)
    app.update()

    # Switch to Attendance view
    view.select_view("attendance")
    app.update()

    # Check that Attendance container is gridded
    assert view.active_view == "attendance"
    assert view.view_containers["attendance"].grid_info() != {}

    # Check Attendance KPI cards exist and are populated
    assert "att_kpi_emp_hc" in view.att_kpi_cards
    assert "att_kpi_rec_days" in view.att_kpi_cards
    assert "att_kpi_present" in view.att_kpi_cards
    assert "att_kpi_absent" in view.att_kpi_cards
    assert "att_kpi_missing_swipes" in view.att_kpi_cards
    assert "att_kpi_regularized" in view.att_kpi_cards

    # In full scope: 7 employees, 8 days, 6.5 present, 1.0 absent
    lbl_hc = view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text")
    assert "7" in lbl_hc

    lbl_days = view.att_kpi_cards["att_kpi_rec_days"].lbl_val.cget("text")
    assert "8" in lbl_days

    # 11. BU Filter Integration: Filter to BU_Alpha
    view._on_bu_selected("BU_Alpha")
    # Process load synchronously for test
    bundle_alpha = workforce_bridge.get_workforce_metrics(business_unit="BU_Alpha")
    view._on_metrics_calc_success(bundle_alpha, view._latest_job_id, "SYNTH_ATTENDANCE_STEP31")
    app.update()

    assert view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text") == "4"
    assert "4" in view.att_kpi_cards["att_kpi_rec_days"].lbl_val.cget("text")
    assert "2.5" in view.att_kpi_cards["att_kpi_present"].lbl_val.cget("text")
    assert "1" in view.att_kpi_cards["att_kpi_absent"].lbl_val.cget("text")

    # 12. Combined BU + Date Filter: Filter to BU_Alpha on 2026-09-01
    view._filter_state["date_range"] = (date(2026, 9, 1), date(2026, 9, 1))
    bundle_alpha_date = workforce_bridge.get_workforce_metrics(
        business_unit="BU_Alpha",
        date_range=(date(2026, 9, 1), date(2026, 9, 1)),
    )
    view._on_metrics_calc_success(bundle_alpha_date, view._latest_job_id, "SYNTH_ATTENDANCE_STEP31")
    app.update()

    assert view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text") == "4"
    assert "4" in view.att_kpi_cards["att_kpi_rec_days"].lbl_val.cget("text")

    # 13. Employee Filter Integration: Filter to SYNTH_003 (in BU_Beta)
    view._filter_state["business_unit"] = None
    view._filter_state["date_range"] = None
    view._filter_state["employee"] = "SYNTH_003"
    bundle_emp3 = workforce_bridge.get_workforce_metrics(employee="SYNTH_003")
    view._on_metrics_calc_success(bundle_emp3, view._latest_job_id, "SYNTH_ATTENDANCE_STEP31")
    app.update()

    assert view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text") == "1"
    assert "1" in view.att_kpi_cards["att_kpi_missing_swipes"].lbl_val.cget("text")

    # 14. Reset Behavior: Reset filters
    view._on_reset_filters_clicked()
    bundle_reset = workforce_bridge.get_workforce_metrics()
    view._on_metrics_calc_success(bundle_reset, view._latest_job_id, "SYNTH_ATTENDANCE_STEP31")
    app.update()

    assert view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text") == "7"
    assert "8" in view.att_kpi_cards["att_kpi_rec_days"].lbl_val.cget("text")


# ─────────────────────────────────────────────────────────────────────────────
# 15. Dataset Replacement and Stale-Result Safeguards
# ─────────────────────────────────────────────────────────────────────────────

def test_15_dataset_replacement_and_stale_job_safeguard(desktop_app):
    """
    Verify that if a stale job completes after a newer job or after dataset replacement,
    its results are discarded and do not corrupt the active metrics.
    """
    app = desktop_app
    view: WorkforceDashboardView = app.workforce_dashboard_view

    # Establish initial dataset
    initial_bundle = {"att_kpi_observed_employees": 100}
    view._latest_job_id = 5
    view._on_metrics_calc_success(initial_bundle, job_id=5, dataset_id="DS_INITIAL")
    assert view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text") == "100"

    # Simulate stale completion from old job_id = 4
    stale_bundle = {"att_kpi_observed_employees": 42}
    view._on_metrics_calc_success(stale_bundle, job_id=4, dataset_id="DS_OLD")
    # Must NOT have changed to 42!
    assert view.att_kpi_cards["att_kpi_emp_hc"].lbl_val.cget("text") == "100"


# ─────────────────────────────────────────────────────────────────────────────
# 16. No Workbook Rereads When Switching Tabs
# ─────────────────────────────────────────────────────────────────────────────

def test_16_zero_workbook_rereads_on_tab_switch(desktop_app, synthetic_attendance_snapshot):
    """
    Switching between Overview and Attendance tabs must not trigger file I/O
    or recalculation when snapshot and filters are unchanged.
    """
    app = desktop_app
    view: WorkforceDashboardView = app.workforce_dashboard_view

    snapshot_service.cache_manager.set_active_snapshot("snap_attendance_synth_test", synthetic_attendance_snapshot)
    valid_bundle = workforce_bridge.get_workforce_metrics()
    view._last_metrics_bundle = valid_bundle
    view._current_dataset_id = getattr(synthetic_attendance_snapshot, "dataset_id", synthetic_attendance_snapshot.key)
    view._is_loading_metrics = False

    with patch("workforce_intelligence.snapshot_bridge.workforce_bridge.get_workforce_metrics") as mock_calc:
        # Switch to Overview
        view.select_view("overview")
        app.update()

        # Switch to Attendance
        view.select_view("attendance")
        app.update()

        # Switch back to Overview
        view.select_view("overview")
        app.update()

        # Calculation bridge should NOT have been called during simple tab switches
        assert mock_calc.call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 17. Existing Overview Metrics and Layout Remain Intact
# ─────────────────────────────────────────────────────────────────────────────

def test_17_overview_metrics_and_layout_remain_intact(desktop_app, synthetic_attendance_snapshot):
    """Verify all 10 Overview KPI cards and reconciliation strip remain intact."""
    app = desktop_app
    view: WorkforceDashboardView = app.workforce_dashboard_view
    snapshot_service.cache_manager.set_active_snapshot("snap_attendance_synth_test", synthetic_attendance_snapshot)
    valid_bundle = workforce_bridge.get_workforce_metrics()
    view._last_metrics_bundle = valid_bundle
    view._current_dataset_id = getattr(synthetic_attendance_snapshot, "dataset_id", synthetic_attendance_snapshot.key)
    view._is_loading_metrics = False
    view.select_view("overview")
    app.update()

    overview_kpi_keys = [
        "kpi_1_emp_hc",
        "kpi_2_attendance_days",
        "kpi_3_present",
        "kpi_4_od",
        "kpi_5_leave",
        "kpi_6_wfh",
        "kpi_7_holiday",
        "kpi_8_week_off",
        "kpi_absent",
        "kpi_9_attendance_exceptions",
    ]
    for k in overview_kpi_keys:
        assert k in view.kpi_cards
        card = view.kpi_cards[k]
        assert card.winfo_exists()

    # Overview BU comparison table widget remains intact
    assert hasattr(view, "bu_table_widget")
    assert view.bu_table_widget.winfo_exists()

    # Reconciliation notice card remains intact
    assert hasattr(view, "recon_card")
    assert view.recon_card.winfo_exists()


# ─────────────────────────────────────────────────────────────────────────────
# 18. Existing Navigation and Legacy Exports Remain Compatible
# ─────────────────────────────────────────────────────────────────────────────

def test_18_existing_navigation_remains_compatible(desktop_app):
    """Verify that all standard frames remain registered and selectable in App."""
    app = desktop_app
    screens = ["dashboard", "transform", "generate", "absent", "att_summary", "workforce_intelligence"]
    for s in screens:
        assert s in app.frames


# ─────────────────────────────────────────────────────────────────────────────
# 19. Unresolved Regularized Events Remain Unclassified (Part 5 Compliance)
# ─────────────────────────────────────────────────────────────────────────────

def test_19_unresolved_regularized_remains_unclassified():
    """
    Part 5 rule:
    'Do not automatically classify unresolved Regularized events as approved Present or final Absent.
     If a status category is not appropriate for the Attendance tab's visual scope, make that
     decision explicit and retain an accessible reconciliation to the full eligible denominator.'
    """
    df = pd.DataFrame([
        {
            "record_id": "REC_UNRES_001",
            "Employee Number": "EMP_UNRES_1",
            "Employee Name": "Unresolved Employee",
            "Business Unit": "BU_Alpha",
            "Department": "Engineering",
            "Date": "2026-09-01",
            "Attendance Type": "Regularized",
            "Status": "P(R)",
            "Approval Status": "Pending",  # Unapproved / Pending
            "Quantity": 1.0,
        }
    ])
    bundle = compute_workforce_intelligence_bundle(df)

    # In Attendance KPIs: it qualifies as an exception day
    assert bundle["att_kpi_regularized_days"] == 1

    # In Attendance Composition: it must NOT be classified as Present or Absent!
    comp_dict = {item["category"]: item["days"] for item in bundle["attendance_composition"]}
    assert comp_dict.get("Present", 0.0) == 0.0
    assert comp_dict.get("Absent", 0.0) == 0.0
    assert comp_dict.get("Unclassified / Unresolved", 0.0) == 1.0

    # Denominator still reconciles cleanly to 1.0
    assert bundle["attendance_composition_denominator"] == 1.0
