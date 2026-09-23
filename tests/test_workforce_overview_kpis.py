"""
tests/test_workforce_overview_kpis.py
─────────────────────────────────────
Focused automated test suite for Transformers 2.0 Step 23:
Connecting Live KPI Data to the Executive Overview.

Covers all 14 test requirements from Part 8:
 1. Overview renders all nine KPI cards.
 2. All displayed KPI values originate from the actual analytical result bundle.
 3. No synthetic mockup values are hard-coded.
 4. The correct active snapshot is used.
 5. Opening Overview does not reread the Excel workbook.
 6. Repeated tab switching does not rebuild the canonical data foundation.
 7. A valid cached result can be reused.
 8. Replacing a dataset updates all nine cards and rejects stale results from the previous dataset.
 9. The no-dataset state displays correctly.
10. Missing-data and calculation-error states are handled without crashing the application.
11. Fractional day quantities and correct units are displayed appropriately.
12. The five other dashboard tabs continue to work.
13. Existing Time Series Analysis and Excel export functionality remain compatible.
14. Tkinter widgets are updated on the main UI thread.
"""

from datetime import date
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from app import App
from storage.cache_manager import AnalyticalSnapshot
from storage import snapshot_service
import ui_components as ui
from workforce_intelligence.dashboard_shell import (
    AttendanceCompositionWidget,
    BusinessUnitComparisonTableWidget,
    DailyAttendanceTrendWidget,
    DataQualityDetailDialog,
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
    compute_repeated_exceptions,
    ensure_clean_dataframe,
)
from workforce_intelligence.snapshot_bridge import workforce_bridge


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_snapshot_a() -> AnalyticalSnapshot:
    """Multi-employee synthetic dataset with fractional days and exceptions."""
    rows = [
        # Emp 1: Alice (Full day Present)
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
            "In Time": "09:00",
            "Out Time": "18:00",
        },
        # Emp 1: Alice (0.5 Present + 0.5 Leave)
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
            "In Time": "09:00",
            "Out Time": "13:00",
        },
        {
            "record_id": "REC_003",
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Bob Mgr",
            "Date": "2026-09-02",
            "Attendance Type": "Casual Leave",
            "Status": "CL",
            "Quantity": 0.5,
            "In Time": "NA",
            "Out Time": "NA",
        },
        # Emp 2: Bob (WFH)
        {
            "record_id": "REC_004",
            "Employee Number": "E002",
            "Employee Name": "Bob Jones",
            "Business Unit": "Sales",
            "Department": "Direct Sales",
            "Reporting Manager": "David RM",
            "Date": "2026-09-01",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
        },
        # Emp 3: Charlie (Regularized exception)
        {
            "record_id": "REC_005",
            "Employee Number": "E003",
            "Employee Name": "Charlie Brown",
            "Business Unit": "Operations",
            "Department": "Logistics",
            "Reporting Manager": "Eve Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "Regularized",
            "Status": "P(R)",
            "Quantity": 1.0,
            "In Time": "09:30",
            "Out Time": "18:00",
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    snap = AnalyticalSnapshot(
        key="snap_dataset_a",
        raw_source="Dataset_Alpha.xlsx",
        fact_df=df,
        metadata={
            "employee_count": 3,
            "min_date": "2026-09-01",
            "max_date": "2026-09-02",
        },
        metrics={"total_records": 5},
    )
    return snap


@pytest.fixture
def synthetic_snapshot_b() -> AnalyticalSnapshot:
    """Alternative replacement dataset with different counts (2 emps, 2 rows)."""
    rows = [
        {
            "record_id": "REC_B01",
            "Employee Number": "E010",
            "Employee Name": "Dan Tech",
            "Business Unit": "Finance",
            "Department": "Accounts",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-10-01",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "In Time": "09:00",
            "Out Time": "17:30",
        },
        {
            "record_id": "REC_B02",
            "Employee Number": "E011",
            "Employee Name": "Elena Sales",
            "Business Unit": "Finance",
            "Department": "Accounts",
            "Reporting Manager": "Frank Mgr",
            "Date": "2026-10-01",
            "Attendance Type": "On Duty",
            "Status": "OD",
            "Quantity": 1.0,
            "In Time": "NA",
            "Out Time": "NA",
        },
    ]
    df = pd.DataFrame(rows)
    snap = AnalyticalSnapshot(
        key="snap_dataset_b",
        raw_source="Dataset_Beta.xlsx",
        fact_df=df,
        metadata={
            "employee_count": 2,
            "min_date": "2026-10-01",
            "max_date": "2026-10-01",
        },
        metrics={"total_records": 2},
    )
    return snap


@pytest.fixture(scope="module")
def desktop_app():
    """Headless Desktop App instance reused across tests."""
    snapshot_service.clear()
    app = App()
    app.withdraw()
    app.update()

    yield app

    try:
        app.destroy()
    except Exception:
        pass
    snapshot_service.clear()


# =========================================================================
# =========================================================================
# 1. Overview renders all ten KPI cards
# =========================================================================
def test_overview_renders_all_ten_kpi_cards(desktop_app):
    """Verify that all 10 expected KPI card instances are constructed in overview."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    expected_cards = [
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

    assert len(wf_view.kpi_cards) == 10
    for cid in expected_cards:
        assert cid in wf_view.kpi_cards
        card = wf_view.kpi_cards[cid]
        assert isinstance(card, ExecutiveKPICard)
        assert card.winfo_exists()


# =========================================================================
# 2. All displayed KPI values originate from actual analytical result bundle
# =========================================================================
def test_kpi_values_originate_from_actual_bundle(desktop_app, synthetic_snapshot_a):
    """Verify cards display calculated values from the KPI engine."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    wf_view.sync_snapshot_state(None)
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)

    # Process pending events for background worker thread
    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 15.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)

    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    assert wf_view._last_metrics_bundle is not None
    b = wf_view._last_metrics_bundle

    # Headcount: 3 employees (E001, E002, E003)
    assert b["kpi_1_emp_hc"] == 3
    assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "3"

    # Present days: E001 (1.0 + 0.5) + Charlie MS (1.0) = 2.5 days
    assert b["kpi_3_present_days"] == 2.5
    assert wf_view.kpi_cards["kpi_3_present"].lbl_val.cget("text") == "2.5 days"

    # Leave days: E001 (0.5)
    assert b["kpi_5_leave_days"] == 0.5
    assert wf_view.kpi_cards["kpi_5_leave"].lbl_val.cget("text") == "0.5 days"

    # WFH days: E002 (1.0) -> Singular '1 day'
    assert b["kpi_6_wfh_days"] == 1.0
    assert wf_view.kpi_cards["kpi_6_wfh"].lbl_val.cget("text") == "1 day"

    # Absent days: 0.0 -> '0 days'
    assert b["kpi_absent_days"] == 0.0
    assert wf_view.kpi_cards["kpi_absent"].lbl_val.cget("text") == "0 days"

    # Exceptions: 1 day (Charlie Regularized) -> Singular '1 exception day'
    assert b["kpi_9_attendance_exceptions_days"] == 1
    assert wf_view.kpi_cards["kpi_9_attendance_exceptions"].lbl_val.cget("text") == "1 exception day"


# =========================================================================
# 3. No synthetic mockup values are hard-coded
# =========================================================================
def test_no_synthetic_mockup_values_hardcoded(desktop_app):
    """Verify that synthetic mockup values (1,248, 24,960, 18,920) are not hardcoded."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    # Verify that Card 1, 2, 3 values do NOT default to the Step 16/17 mockup numbers
    hc_text = wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text")
    att_text = wf_view.kpi_cards["kpi_2_attendance_days"].lbl_val.cget("text")
    pres_text = wf_view.kpi_cards["kpi_3_present"].lbl_val.cget("text")

    assert "1,248" not in hc_text
    assert "24,960" not in att_text
    assert "18,920" not in pres_text


# =========================================================================
# 4. Correct active snapshot is used
# =========================================================================
def test_correct_active_snapshot_used(synthetic_snapshot_a):
    """Verify bridge queries the active snapshot from snapshot_service."""
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    active = snapshot_service.get_active_snapshot()
    assert active is synthetic_snapshot_a
    assert active.key == "snap_dataset_a"

    metrics = workforce_bridge.get_workforce_metrics()
    assert metrics["kpi_1_emp_hc"] == 3


# =========================================================================
# 5. Opening Overview does not reread the Excel workbook
# =========================================================================
def test_opening_overview_does_not_reread_excel(desktop_app):
    """Verify zero openpyxl or pandas file reads when opening/selecting Overview."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    with patch("openpyxl.load_workbook") as mock_load_wb, \
         patch("pandas.read_excel") as mock_read_excel, \
         patch("pandas.read_csv") as mock_read_csv:

        wf_view.select_view("overview")
        desktop_app.update()

        assert mock_load_wb.call_count == 0
        assert mock_read_excel.call_count == 0
        assert mock_read_csv.call_count == 0


# =========================================================================
# 6. Repeated tab switching does not rebuild data foundation
# =========================================================================
def test_repeated_tab_switching_does_not_rebuild_data_foundation(desktop_app):
    """Verify zero data foundation builds when switching between tabs."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    with patch("storage.snapshot_service.TimeSeriesSnapshotService.prepare_dataset") as mock_prep, \
         patch("workforce_intelligence.load_workforce_data") as mock_load_wf:

        for key in VIEW_KEYS:
            wf_view.select_view(key)
            desktop_app.update()

        assert mock_prep.call_count == 0
        assert mock_load_wf.call_count == 0


# =========================================================================
# 7. Valid cached result can be reused
# =========================================================================
def test_valid_cached_result_reused(desktop_app, synthetic_snapshot_a):
    """Verify that when dataset has not changed, cached metrics bundle is reused."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)
    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        desktop_app.update()
        time.sleep(0.05)
    desktop_app.update()

    cached_bundle = wf_view._last_metrics_bundle
    assert cached_bundle is not None

    with patch("workforce_intelligence.snapshot_bridge.workforce_bridge.get_workforce_metrics") as mock_bridge:
        wf_view.sync_snapshot_state(synthetic_snapshot_a)
        desktop_app.update()
        # Should reuse cached bundle without calling bridge
        assert mock_bridge.call_count == 0
        assert wf_view._last_metrics_bundle is cached_bundle


# =========================================================================
# 8. Replacing a dataset updates all nine cards and rejects stale results
# =========================================================================
def test_replacing_dataset_updates_cards_and_rejects_stale(desktop_app, synthetic_snapshot_a, synthetic_snapshot_b):
    """Verify dataset replacement updates all 9 cards with fresh metrics."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    # Ingest Dataset A
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        app.update()
        time.sleep(0.05)
    app.update()

    assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "3"

    # Replace with Dataset B
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_b", synthetic_snapshot_b)
    wf_view.sync_snapshot_state(synthetic_snapshot_b)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        app.update()
        time.sleep(0.05)
    app.update()

    # Cards must now reflect Dataset B: 2 employees (E010, E011), 1.0 Present, 1.0 OD
    assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "2"
    assert wf_view.kpi_cards["kpi_3_present"].lbl_val.cget("text") == "1 day"
    assert wf_view.kpi_cards["kpi_4_od"].lbl_val.cget("text") == "1 day"
    assert "Dataset_Beta" in wf_view.lbl_dataset_name.cget("text")


# =========================================================================
# 9. No-dataset state displays correctly
# =========================================================================
def test_no_dataset_state_displays_correctly(desktop_app):
    """Verify empty state notice and action button when snapshot is None."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    snapshot_service.clear()
    wf_view.sync_snapshot_state(None)
    app.update()

    # Empty frame must be gridded; KPI frame must be removed
    assert bool(wf_view.overview_empty_frame.grid_info())
    assert not bool(wf_view.overview_kpi_frame.grid_info())
    assert "No dataset loaded" in wf_view.lbl_dataset_name.cget("text")


# =========================================================================
# 10. Missing-data and calculation-error states handled without crash
# =========================================================================
def test_calculation_error_state_handled_gracefully(desktop_app, synthetic_snapshot_a):
    """Verify calculation error displays notice and does not crash app."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)

    with patch("workforce_intelligence.snapshot_bridge.workforce_bridge.get_workforce_metrics", side_effect=ValueError("Test analytical error")):
        wf_view._load_overview_metrics()

        start_time = time.time()
        while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
            app.update()
            time.sleep(0.05)
        app.update()

        assert bool(wf_view.overview_error_frame.grid_info())
        assert "Test analytical error" in wf_view.lbl_error_msg.cget("text")
        assert not bool(wf_view.overview_kpi_frame.grid_info())


# =========================================================================
# 11. Fractional day quantities and correct units displayed appropriately
# =========================================================================
def test_fractional_day_quantities_and_units():
    """Verify _fmt_days handles integers, floats, None, and NaN cleanly."""
    assert _fmt_days(0.0) == "0 days"
    assert _fmt_days(1.0) == "1 day"
    assert _fmt_days(2.0) == "2 days"
    assert _fmt_days(14.5) == "14.5 days"
    assert _fmt_days(0.5) == "0.5 days"
    assert _fmt_days(18920.0) == "18,920 days"
    assert _fmt_days(18920.5) == "18,920.5 days"
    assert _fmt_days(None) == "N/A"
    assert _fmt_days(float("nan")) == "N/A"


# =========================================================================
# 12. The five other dashboard tabs continue to work
# =========================================================================
def test_other_five_dashboard_tabs_continue_to_work(desktop_app):
    """Verify that Attendance, Leave, WFH, Working Hours, and Investigations retain containers."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    other_tabs = ["attendance", "leave", "wfh", "working_hours", "investigations"]

    for tab_key in other_tabs:
        wf_view.select_view(tab_key)
        desktop_app.update()
        assert wf_view.active_view == tab_key
        container = wf_view.view_containers[tab_key]
        assert bool(container.grid_info())


# =========================================================================
# 13. Existing Time Series Analysis and Excel export remain compatible
# =========================================================================
def test_existing_tsa_and_excel_export_compatible(desktop_app):
    """Verify that Time Series Analysis and Excel export exist and are functional."""
    app = desktop_app
    assert "analyse_time_series" in app.frames
    assert hasattr(app, "_export_ts_excel")
    assert callable(app._export_ts_excel)


# =========================================================================
# 14. Tkinter widgets are updated on the main UI thread
# =========================================================================
def test_tkinter_widgets_updated_on_main_thread(desktop_app, synthetic_snapshot_a):
    """Verify that card updates execute on the main thread."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    update_threads = []

    def wrapped_update(*args, **kwargs):
        update_threads.append(threading.current_thread().name)
        return ExecutiveKPICard.update_values(wf_view.kpi_cards["kpi_1_emp_hc"], *args, **kwargs)

    with patch.object(wf_view.kpi_cards["kpi_1_emp_hc"], "update_values", side_effect=wrapped_update):
        wf_view.sync_snapshot_state(None)
        snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
        wf_view.sync_snapshot_state(synthetic_snapshot_a)

        start_time = time.time()
        while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
            app.update()
            time.sleep(0.05)
        app.update()

    assert len(update_threads) > 0
    # Must be MainThread
    assert all("MainThread" in t for t in update_threads)


# =========================================================================
# 15. Dynamic Data Quality indicator reflects unclassified records
# =========================================================================
def test_data_quality_indicator_reflects_unclassified_records(desktop_app):
    """Verify that DQ label reflects unresolved records instead of unconditional Clean."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    # Clean bundle: unclassified == 0
    clean_bundle = {
        "kpi_1_emp_hc": 5,
        "kpi_2_attendance_days": 10,
        "kpi_3_present_days": 5.0,
        "kpi_3_present_pct": 50.0,
        "kpi_4_od_days": 0.0,
        "kpi_4_od_pct": 0.0,
        "kpi_5_leave_days": 0.0,
        "kpi_5_leave_pct": 0.0,
        "kpi_6_wfh_days": 2.0,
        "kpi_6_wfh_pct": 20.0,
        "kpi_7_holiday_days": 1.0,
        "kpi_7_holiday_pct": 10.0,
        "kpi_8_week_off_days": 1.0,
        "kpi_8_week_off_pct": 10.0,
        "kpi_absent_days": 1.0,
        "kpi_absent_pct": 10.0,
        "unclassified_records_count": 0,
        "kpi_unclassified_days": 0.0,
        "kpi_unclassified_pct": 0.0,
        "attendance_composition_denominator": 10.0,
        "kpi_9_attendance_exceptions_days": 0,
        "kpi_9_attendance_exceptions_rate_pct": 0.0,
        "kpi_9_attendance_exceptions_affected_emps": 0,
    }
    wf_view._render_overview_kpis(clean_bundle)
    assert wf_view.lbl_dq_info.cget("text") == "DQ: Clean"
    assert "Complete Additive Attendance Composition" in wf_view.lbl_recon_title.cget("text")

    # Unclassified records present: count == 1
    unclass_bundle = dict(clean_bundle)
    unclass_bundle["unclassified_records_count"] = 1
    unclass_bundle["kpi_unclassified_days"] = 1.0
    unclass_bundle["kpi_unclassified_pct"] = 9.1
    unclass_bundle["attendance_composition_denominator"] = 11.0

    wf_view._render_overview_kpis(unclass_bundle)
    assert wf_view.lbl_dq_info.cget("text") == "DQ: 1 to review"
    assert "Reconciliation Notice: 1 Unclassified Record" in wf_view.lbl_recon_title.cget("text")
    assert "11 days" in wf_view.lbl_recon_desc.cget("text")


# =========================================================================
# 16. Attendance composition reconciliation includes Absent days
# =========================================================================
def test_attendance_composition_reconciliation_includes_absent(desktop_app):
    """Verify that Absent days are factored into the categorized total."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    bundle = {
        "kpi_1_emp_hc": 6,
        "kpi_2_attendance_days": 9,
        "kpi_3_present_days": 2.0,
        "kpi_3_present_pct": 22.2,
        "kpi_4_od_days": 1.0,
        "kpi_4_od_pct": 11.1,
        "kpi_5_leave_days": 1.0,
        "kpi_5_leave_pct": 11.1,
        "kpi_6_wfh_days": 1.0,
        "kpi_6_wfh_pct": 11.1,
        "kpi_7_holiday_days": 0.0,
        "kpi_7_holiday_pct": 0.0,
        "kpi_8_week_off_days": 2.0,
        "kpi_8_week_off_pct": 22.2,
        "kpi_absent_days": 1.0,
        "kpi_absent_pct": 11.1,
        "unclassified_records_count": 1,
        "conflicting_employee_days_count": 1,
        "kpi_unclassified_days": 1.0,
        "kpi_unclassified_pct": 11.1,
        "attendance_composition_denominator": 9.0,
        "kpi_9_attendance_exceptions_days": 3,
        "kpi_9_attendance_exceptions_rate_pct": 33.3,
        "kpi_9_attendance_exceptions_affected_emps": 2,
    }

    wf_view._render_overview_kpis(bundle)
    # Absent card displays 1 day
    assert wf_view.kpi_cards["kpi_absent"].lbl_val.cget("text") == "1 day"
    assert "11.1%" in wf_view.kpi_cards["kpi_absent"].lbl_sub.cget("text")

    # Reconciliation description mentions 8.0 days categorized across 7 categories
    assert "8 days" in wf_view.lbl_recon_desc.cget("text") or "8.0 days" in wf_view.lbl_recon_desc.cget("text")
    assert "Absent" in wf_view.lbl_recon_desc.cget("text")
    assert "1 Conflicting Employee-Day" in wf_view.lbl_recon_title.cget("text")


# =========================================================================
# 17. Three overlapping full-day source events on one employee-date
# =========================================================================
def test_three_overlapping_full_day_events_on_same_date():
    """Verify that 3 full-day records on 1 date are capped at 1.0 day unresolved/conflicting."""
    rows = [
        {
            "record_id": "REC_SYNTH_01",
            "Employee Number": "E099",
            "Employee Name": "Test Employee",
            "Date": "2026-09-01",
            "Attendance Type": "Regularized",
            "Status": "A(R)",
            "Quantity": 1.0,
            "Approval Status": "Rejected",
            "Applied By": "Admin",
        },
        {
            "record_id": "REC_SYNTH_02",
            "Employee Number": "E099",
            "Employee Name": "Test Employee",
            "Date": "2026-09-01",
            "Attendance Type": "Holiday",
            "Status": "H",
            "Quantity": 1.0,
            "Approval Status": "NA",
            "Applied By": "NA",
        },
        {
            "record_id": "REC_SYNTH_03",
            "Employee Number": "E099",
            "Employee Name": "Test Employee",
            "Date": "2026-09-01",
            "Attendance Type": "Worked on Holiday",
            "Status": "WOH",
            "Quantity": 1.0,
            "Approval Status": "NA",
            "Applied By": "NA",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_unclassified_days"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1
    assert bundle["kpi_7_holiday_days"] == 0.0
    assert bundle["kpi_3_present_days"] == 0.0


# =========================================================================
# 18. Holiday plus Worked on Holiday on one employee-date
# =========================================================================
def test_holiday_plus_worked_on_holiday_on_same_date():
    """Verify Holiday + Worked on Holiday does not double-count to 2 days."""
    rows = [
        {
            "record_id": "REC_H01",
            "Employee Number": "E099",
            "Employee Name": "Test Employee",
            "Date": "2026-10-02",
            "Attendance Type": "Holiday",
            "Status": "H",
            "Quantity": 1.0,
        },
        {
            "record_id": "REC_H02",
            "Employee Number": "E099",
            "Employee Name": "Test Employee",
            "Date": "2026-10-02",
            "Attendance Type": "Worked on Holiday",
            "Status": "WOH",
            "Quantity": 1.0,
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # Must be 1 distinct attendance day, NOT 2 days
    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1
    assert bundle["kpi_unclassified_days"] == 1.0


# =========================================================================
# 19. Original status plus subsequent approved regularization
# =========================================================================
def test_original_status_plus_subsequent_regularization():
    """Verify original Absent status resolved by approved Regularized A(R) counts as 1.0 Present."""
    rows = [
        {
            "record_id": "REC_REG_01",
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Date": "2026-09-03",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_REG_02",
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Date": "2026-09-03",
            "Attendance Type": "Regularized",
            "Status": "A(R)",
            "Quantity": 1.0,
            "Approval Status": "Approved",
            "Applied By": "Employee",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_3_present_days"] == 1.0
    assert bundle["kpi_absent_days"] == 0.0
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["unclassified_records_count"] == 0


# =========================================================================
# 20. Legitimate half-day combinations
# =========================================================================
def test_legitimate_half_day_combinations():
    """Verify 0.5 Present + 0.5 Casual Leave yields 1.0 clean day with exact component weights."""
    rows = [
        {
            "record_id": "REC_HALF_01",
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Date": "2026-09-04",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 0.5,
        },
        {
            "record_id": "REC_HALF_02",
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Date": "2026-09-04",
            "Attendance Type": "Casual Leave",
            "Status": "CL",
            "Quantity": 0.5,
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_3_present_days"] == 0.5
    assert bundle["kpi_5_leave_days"] == 0.5
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["unclassified_records_count"] == 0


# =========================================================================
# 21. Conflicting records with no reliable final status
# =========================================================================
def test_conflicting_records_with_no_reliable_final_status(desktop_app):
    """Verify conflicting claims with no approval surface as 1.0 unresolved day with UI warning."""
    rows = [
        {
            "record_id": "REC_CONF_01",
            "Employee Number": "E005",
            "Employee Name": "Emma",
            "Date": "2026-09-05",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
            "Approval Status": "Pending",
        },
        {
            "record_id": "REC_CONF_02",
            "Employee Number": "E005",
            "Employee Name": "Emma",
            "Date": "2026-09-05",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "Pending",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1
    assert bundle["kpi_unclassified_days"] == 1.0

    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    wf_view._render_overview_kpis(bundle)
    assert wf_view.lbl_dq_info.cget("text") == "DQ: 1 to review"
    assert "1 Conflicting Employee-Day" in wf_view.lbl_recon_title.cget("text")


# =========================================================================
# 22. Correct category totals and percentage denominators
# =========================================================================
def test_correct_category_totals_and_percentage_denominators():
    """Verify distinct employee-dates form the exact percentage denominator summing to 100%."""
    rows = [
        {"Employee Number": "E1", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E1", "Date": "2026-09-02", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "E2", "Date": "2026-09-01", "Attendance Type": "Sick Leave", "Status": "SL", "Quantity": 1.0},
        {"Employee Number": "E3", "Date": "2026-09-01", "Attendance Type": "Week Off", "Status": "WO", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 4
    assert bundle["attendance_composition_denominator"] == 4.0
    assert bundle["kpi_3_present_pct"] == 25.0
    assert bundle["kpi_6_wfh_pct"] == 25.0
    assert bundle["kpi_5_leave_pct"] == 25.0
    assert bundle["kpi_8_week_off_pct"] == 25.0
    total_pct = (
        bundle["kpi_3_present_pct"]
        + bundle["kpi_6_wfh_pct"]
        + bundle["kpi_5_leave_pct"]
        + bundle["kpi_8_week_off_pct"]
    )
    assert round(total_pct, 1) == 100.0


# =========================================================================
# 23. Preservation of source-record traceability
# =========================================================================
def test_preservation_of_source_record_traceability():
    """Verify conflicting record IDs are preserved in the bundle for auditability."""
    rows = [
        {"record_id": "REC_TR_01", "Employee Number": "E1", "Date": "2026-09-01", "Attendance Type": "Holiday", "Status": "H", "Quantity": 1.0},
        {"record_id": "REC_TR_02", "Employee Number": "E1", "Date": "2026-09-01", "Attendance Type": "Worked on Holiday", "Status": "WOH", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["conflicting_employee_days_count"] == 1
    assert "REC_TR_01" in bundle["conflicting_record_ids"]
    assert "REC_TR_02" in bundle["conflicting_record_ids"]


# =========================================================================
# 24. Live FinBox dataset 9-day attendance reconciliation
# =========================================================================
def test_live_finbox_dataset_reconciliation():
    """Verify the actual FinBox Excel dataset reconciles to exactly 9.0 days, not 11.0."""
    finbox_path = Path("local_data/Daily Performance Report 01 Sep 2026 - 13 Sep 2026 - FinBox.xlsx")
    if not finbox_path.exists():
        pytest.skip(f"FinBox dataset not found at {finbox_path}")

    from storage.snapshot_service import normalize_dataset_dataframe
    df_raw = pd.read_excel(finbox_path)
    df = normalize_dataset_dataframe(df_raw)

    bundle = compute_workforce_intelligence_bundle(df)

    # Total records = 11, distinct employee-dates = 9
    assert len(df) == 11
    assert bundle["kpi_1_emp_hc"] == 6
    assert bundle["kpi_2_attendance_days"] == 9
    assert bundle["attendance_composition_denominator"] == 9.0
    assert bundle["kpi_3_present_days"] == 2.0
    assert bundle["kpi_4_od_days"] == 1.0
    assert bundle["kpi_5_leave_days"] == 1.0
    assert bundle["kpi_6_wfh_days"] == 1.0
    assert bundle["kpi_7_holiday_days"] == 0.0
    assert bundle["kpi_8_week_off_days"] == 2.0
    assert bundle["kpi_absent_days"] == 1.0
    assert bundle["kpi_unclassified_days"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1

    # Additive sum of all 8 components must exactly equal 9.0 days
    tot_days = (
        bundle["kpi_3_present_days"]
        + bundle["kpi_4_od_days"]
        + bundle["kpi_5_leave_days"]
        + bundle["kpi_6_wfh_days"]
        + bundle["kpi_7_holiday_days"]
        + bundle["kpi_8_week_off_days"]
        + bundle["kpi_absent_days"]
        + bundle["kpi_unclassified_days"]
    )
    assert round(tot_days, 1) == 9.0


# =========================================================================
# 25. Overlapping with approved Leave resolves to Leave, NOT Present
# =========================================================================
def test_overlapping_with_approved_leave_resolves_to_leave():
    """Verify approved Leave in an overlapping employee-date resolves to Leave, NOT Present."""
    rows = [
        {
            "record_id": "REC_OL_01",
            "Employee Number": "E101",
            "Date": "2026-09-08",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_OL_02",
            "Employee Number": "E101",
            "Date": "2026-09-08",
            "Attendance Type": "Casual Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_5_leave_days"] == 1.0
    assert bundle["kpi_3_present_days"] == 0.0
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["kpi_unclassified_days"] == 0.0


# =========================================================================
# 26. Overlapping with approved WFH resolves to WFH, NOT Present
# =========================================================================
def test_overlapping_with_approved_wfh_resolves_to_wfh():
    """Verify approved WFH in an overlapping employee-date resolves to WFH, NOT Present."""
    rows = [
        {
            "record_id": "REC_OW_01",
            "Employee Number": "E102",
            "Date": "2026-09-08",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_OW_02",
            "Employee Number": "E102",
            "Date": "2026-09-08",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_6_wfh_days"] == 1.0
    assert bundle["kpi_3_present_days"] == 0.0
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["kpi_unclassified_days"] == 0.0


# =========================================================================
# 27. Overlapping with approved On Duty resolves to On Duty, NOT Present
# =========================================================================
def test_overlapping_with_approved_on_duty_resolves_to_on_duty():
    """Verify approved On Duty in an overlapping employee-date resolves to OD, NOT Present."""
    rows = [
        {
            "record_id": "REC_OD_01",
            "Employee Number": "E103",
            "Date": "2026-09-08",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_OD_02",
            "Employee Number": "E103",
            "Date": "2026-09-08",
            "Attendance Type": "On Duty",
            "Status": "OD",
            "Quantity": 1.0,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_4_od_days"] == 1.0
    assert bundle["kpi_3_present_days"] == 0.0
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["kpi_unclassified_days"] == 0.0


# =========================================================================
# 28. Overlapping with approved Regularization resolves to Present
# =========================================================================
def test_overlapping_with_approved_regularization_resolves_to_present():
    """Verify approved attendance regularization resolves to Present."""
    rows = [
        {
            "record_id": "REC_REG_A01",
            "Employee Number": "E104",
            "Date": "2026-09-08",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_REG_A02",
            "Employee Number": "E104",
            "Date": "2026-09-08",
            "Attendance Type": "Regularized",
            "Status": "A(R)",
            "Quantity": 1.0,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_3_present_days"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["kpi_unclassified_days"] == 0.0


# =========================================================================
# 29. Holiday combined with Worked on Holiday unapproved does not infer Present
# =========================================================================
def test_holiday_plus_worked_on_holiday_unapproved_does_not_infer_present():
    """Verify Holiday + Worked on Holiday without approval remains Conflicting/Unresolved."""
    rows = [
        {
            "record_id": "REC_HW_01",
            "Employee Number": "E105",
            "Date": "2026-10-02",
            "Attendance Type": "Holiday",
            "Status": "H",
            "Quantity": 1.0,
            "Approval Status": "NA",
            "In Time": "NA",
            "Out Time": "NA",
            "Total Hours": "0:00",
        },
        {
            "record_id": "REC_HW_02",
            "Employee Number": "E105",
            "Date": "2026-10-02",
            "Attendance Type": "Worked on Holiday",
            "Status": "WOH",
            "Quantity": 1.0,
            "Approval Status": "NA",
            "In Time": "NA",
            "Out Time": "NA",
            "Total Hours": "0:00",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # Must NOT replace Holiday with Present, and must NOT infer attendance from missing punches
    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1
    assert bundle["kpi_unclassified_days"] == 1.0
    assert bundle["kpi_3_present_days"] == 0.0
    assert bundle["kpi_7_holiday_days"] == 0.0
    assert "REC_HW_01" in bundle["conflicting_record_ids"]
    assert "REC_HW_02" in bundle["conflicting_record_ids"]


# =========================================================================
# 30. Overlapping with Rejected Regularization remains Conflicting
# =========================================================================
def test_overlapping_rejected_regularization_remains_conflicting():
    """Verify rejected attendance regularization is NOT treated as Present."""
    rows = [
        {
            "record_id": "REC_REJ_01",
            "Employee Number": "E106",
            "Date": "2026-09-08",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_REJ_02",
            "Employee Number": "E106",
            "Date": "2026-09-08",
            "Attendance Type": "Regularized",
            "Status": "A(R)",
            "Quantity": 1.0,
            "Approval Status": "Rejected",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1
    assert bundle["kpi_unclassified_days"] == 1.0
    assert bundle["kpi_3_present_days"] == 0.0


# =========================================================================
# 31. Multiple approved but contradictory records are Conflicting
# =========================================================================
def test_multiple_approved_contradictory_records_are_conflicting():
    """Verify multiple approved contradictory records exceeding 1.0 day remain Conflicting."""
    rows = [
        {
            "record_id": "REC_CONTRA_01",
            "Employee Number": "E107",
            "Date": "2026-09-08",
            "Attendance Type": "Casual Leave",
            "Status": "CL",
            "Quantity": 1.0,
            "Approval Status": "Approved",
        },
        {
            "record_id": "REC_CONTRA_02",
            "Employee Number": "E107",
            "Date": "2026-09-08",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 1.0,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["conflicting_employee_days_count"] == 1
    assert bundle["kpi_unclassified_days"] == 1.0
    assert bundle["kpi_5_leave_days"] == 0.0
    assert bundle["kpi_6_wfh_days"] == 0.0


# =========================================================================
# 32. Multiple approved split half-days summing to 1.0 resolve cleanly
# =========================================================================
def test_multiple_approved_split_half_days_sum_to_one():
    """Verify 0.5 Approved Leave + 0.5 Approved WFH cleanly resolves to 0.5 Leave + 0.5 WFH."""
    rows = [
        {
            "record_id": "REC_SPLIT_01",
            "Employee Number": "E108",
            "Date": "2026-09-08",
            "Attendance Type": "Absent",
            "Status": "A",
            "Quantity": 1.0,
            "Approval Status": "NA",
        },
        {
            "record_id": "REC_SPLIT_02",
            "Employee Number": "E108",
            "Date": "2026-09-08",
            "Attendance Type": "Casual Leave",
            "Status": "CL",
            "Quantity": 0.5,
            "Approval Status": "Approved",
        },
        {
            "record_id": "REC_SPLIT_03",
            "Employee Number": "E108",
            "Date": "2026-09-08",
            "Attendance Type": "Work From Home",
            "Status": "WFH",
            "Quantity": 0.5,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 1
    assert bundle["attendance_composition_denominator"] == 1.0
    assert bundle["kpi_5_leave_days"] == 0.5
    assert bundle["kpi_6_wfh_days"] == 0.5
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["kpi_unclassified_days"] == 0.0


# =========================================================================
# 33. Standalone half-day produces fractional denominator without fabrication
# =========================================================================
def test_standalone_half_day_produces_fractional_denominator_without_fabrication():
    """Verify an approved 0.5-day record with unrecorded second half produces 0.5 denominator diff."""
    rows = [
        {
            "record_id": "REC_SHD_01",
            "Employee Number": "E201",
            "Date": "2026-09-02",
            "Attendance Type": "Present",
            "Status": "P",
            "Quantity": 1.0,
        },
        {
            "record_id": "REC_SHD_02",
            "Employee Number": "E202",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Status": "WL",
            "Quantity": 0.5,
            "Approval Status": "Approved",
        },
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # 2 distinct employee-dates, but 1.5 quantity-weighted day equivalents
    assert bundle["kpi_2_attendance_days"] == 2
    assert bundle["attendance_composition_denominator"] == 1.5
    assert bundle["kpi_3_present_days"] == 1.0
    assert bundle["kpi_5_leave_days"] == 0.5
    # No phantom second-half was fabricated
    assert bundle["conflicting_employee_days_count"] == 0
    assert bundle["kpi_unclassified_days"] == 0.0


# =========================================================================
# 34. Week Off never overlaps with Attendance Exceptions
# =========================================================================
def test_week_off_never_overlaps_with_attendance_exceptions():
    """Verify ordinary Week Off and Worked on Week Off records are never counted as Exceptions."""
    rows = [
        {"record_id": "REC_WO_01", "Employee Number": "E301", "Date": "2026-09-06", "Attendance Type": "Week Off", "Status": "WO", "Quantity": 1.0},
        {"record_id": "REC_WO_02", "Employee Number": "E302", "Date": "2026-09-06", "Attendance Type": "Week Off", "Status": "WOW", "Quantity": 1.0},
        {"record_id": "REC_MS_01", "Employee Number": "E303", "Date": "2026-09-07", "Attendance Type": "Missing Swipes", "Status": "P(MS)", "Quantity": 1.0},
        {"record_id": "REC_EX_01", "Employee Number": "E304", "Date": "2026-09-07", "Attendance Type": "Regularized", "Status": "A(R)", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_8_week_off_days"] == 2.0
    # Missing Swipes (E303) does NOT qualify as an exception; ONLY Regularized (E304) qualifies
    assert bundle["kpi_9_attendance_exceptions_days"] == 1
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 1


# =========================================================================
# 35. Attendance Type = Regularized exact matching qualification
# =========================================================================
def test_attendance_exceptions_exact_regularized_matching():
    """Verify only exact normalized Attendance Type == 'Regularized' qualifies."""
    rows = [
        # Qualifies: exact case
        {"record_id": "R1", "Employee Number": "E401", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)"},
        # Qualifies: surrounding whitespace and lowercase
        {"record_id": "R2", "Employee Number": "E402", "Date": "2026-09-01", "Attendance Type": "  regularized  ", "Status": "P(R)"},
        # Qualifies: UPPERCASE
        {"record_id": "R3", "Employee Number": "E403", "Date": "2026-09-01", "Attendance Type": "REGULARIZED", "Status": "A(R)"},
        # Disqualified: Missing Swipes
        {"record_id": "R4", "Employee Number": "E404", "Date": "2026-09-01", "Attendance Type": "Missing Swipes", "Status": "P(MS)"},
        # Disqualified: Absent
        {"record_id": "R5", "Employee Number": "E405", "Date": "2026-09-01", "Attendance Type": "Absent", "Status": "A"},
        # Disqualified: Week Off
        {"record_id": "R6", "Employee Number": "E406", "Date": "2026-09-01", "Attendance Type": "Week Off", "Status": "WO"},
        # Disqualified: Holiday
        {"record_id": "R7", "Employee Number": "E407", "Date": "2026-09-01", "Attendance Type": "Holiday", "Status": "H"},
        # Disqualified: Status is A(R) but Attendance Type is Absent
        {"record_id": "R8", "Employee Number": "E408", "Date": "2026-09-01", "Attendance Type": "Absent", "Status": "A(R)"},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_9_attendance_exceptions_days"] == 3
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 3
    assert bundle["attendance_exceptions_qualifying_records_count"] == 3


# =========================================================================
# 36. Regularized approval status breakdown and distinguishability
# =========================================================================
def test_regularized_approval_status_breakdown_distinguishability():
    """Verify Approved, Pending, Rejected, and Unknown regularizations all qualify and remain distinguishable."""
    rows = [
        {"record_id": "R1", "Employee Number": "E501", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Approval Status": "Approved"},
        {"record_id": "R2", "Employee Number": "E502", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Approval Status": "Pending"},
        {"record_id": "R3", "Employee Number": "E503", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Approval Status": "Rejected"},
        {"record_id": "R4", "Employee Number": "E504", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Approval Status": None},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # All 4 count as exceptions regardless of approval status
    assert bundle["kpi_9_attendance_exceptions_days"] == 4
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 4
    assert bundle["attendance_exceptions_qualifying_records_count"] == 4

    # Approval breakdown distinguishes all states cleanly
    ab = bundle["attendance_exceptions_approval_breakdown"]
    assert ab["approved"] == 1
    assert ab["pending"] == 1
    assert ab["rejected"] == 1
    assert ab["unknown"] == 1

    # Traceability records preserved
    recs = bundle["attendance_exceptions_records"]
    assert len(recs) == 4
    statuses = {r["employee_id"]: r["approval_status"] for r in recs}
    assert statuses["E501"] == "Approved"
    assert statuses["E502"] == "Pending"
    assert statuses["E503"] == "Rejected"
    assert statuses["E504"] == "Unknown"


# =========================================================================
# 37. Multiple Regularized records on same employee-date are deduplicated
# =========================================================================
def test_multiple_regularized_records_same_date_deduplication():
    """Verify multiple regularized records on one employee-date count as one exception day."""
    rows = [
        {"record_id": "R1", "Employee Number": "E601", "Date": "2026-09-02", "Attendance Type": "Regularized", "Status": "A(R)", "Approval Status": "Approved"},
        {"record_id": "R2", "Employee Number": "E601", "Date": "2026-09-02", "Attendance Type": "Regularized", "Status": "P(R)", "Approval Status": "Pending"},
        {"record_id": "R3", "Employee Number": "E601", "Date": "2026-09-03", "Attendance Type": "Regularized", "Status": "A(R)", "Approval Status": "Approved"},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # E601 has 3 records across 2 distinct dates -> 2 exception days
    assert bundle["kpi_9_attendance_exceptions_days"] == 2
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 1
    # Underlying source records count is 3
    assert bundle["attendance_exceptions_qualifying_records_count"] == 3


# =========================================================================
# 38. Exception rate uses distinct recorded employee-day denominator
# =========================================================================
def test_exception_rate_uses_distinct_recorded_employee_days_denominator():
    """Verify exception rate denominator is distinct recorded employee-days, not composition denominator."""
    rows = [
        # 9 distinct employee-days
        {"record_id": f"R{i}", "Employee Number": f"E70{i}", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0}
        for i in range(1, 10)
    ]
    # 1 regularized employee-day
    rows.append(
        {"record_id": "R10", "Employee Number": "E710", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Quantity": 1.0}
    )
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_2_attendance_days"] == 10
    assert bundle["kpi_9_attendance_exceptions_days"] == 1
    # Rate: 1 / 10 = 10.0%
    assert bundle["kpi_9_attendance_exceptions_rate_pct"] == 10.0


# =========================================================================
# 39. Repeated exception threshold uses Regularized-only definition
# =========================================================================
def test_repeated_exception_threshold_uses_regularized_only():
    """Verify compute_repeated_exceptions only counts distinct Regularized days."""
    rows = [
        {"Employee Number": "E801", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)"},
        {"Employee Number": "E801", "Date": "2026-09-02", "Attendance Type": "Regularized", "Status": "A(R)"},
        # Missing Swipe and Absent on other dates do not count
        {"Employee Number": "E801", "Date": "2026-09-03", "Attendance Type": "Missing Swipes", "Status": "MS"},
        {"Employee Number": "E801", "Date": "2026-09-04", "Attendance Type": "Absent", "Status": "A"},
    ]
    df = pd.DataFrame(rows)

    # Threshold = 2 -> Meets threshold (qualifying days = 2)
    res_t2 = compute_repeated_exceptions(df, threshold=2)
    assert res_t2["total_repeat_employees"] == 1
    assert res_t2["dossiers"][0]["qualifying_exception_days"] == 2

    # Threshold = 3 -> Does NOT meet threshold (since MS and Absent don't count)
    res_t3 = compute_repeated_exceptions(df, threshold=3)
    assert res_t3["total_repeat_employees"] == 0
    assert res_t3["dossiers"][0]["meets_threshold"] is False


# =========================================================================
# 40. Existing attendance composition and Absent KPI remain unchanged
# =========================================================================
def test_attendance_composition_and_absent_kpi_remain_unchanged():
    """Verify Present, OD, Leave, WFH, Holiday, Week Off, and Absent KPIs are unchanged."""
    rows = [
        {"Employee Number": "E901", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E902", "Date": "2026-09-01", "Attendance Type": "On Duty", "Status": "OD", "Quantity": 1.0},
        {"Employee Number": "E903", "Date": "2026-09-01", "Attendance Type": "Leave", "Status": "CL", "Quantity": 1.0},
        {"Employee Number": "E904", "Date": "2026-09-01", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "E905", "Date": "2026-09-01", "Attendance Type": "Holiday", "Status": "H", "Quantity": 1.0},
        {"Employee Number": "E906", "Date": "2026-09-01", "Attendance Type": "Week Off", "Status": "WO", "Quantity": 1.0},
        {"Employee Number": "E907", "Date": "2026-09-01", "Attendance Type": "Absent", "Status": "A", "Quantity": 1.0},
        {"Employee Number": "E908", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_3_present_days"] == 1.0
    assert bundle["kpi_4_od_days"] == 1.0
    assert bundle["kpi_5_leave_days"] == 1.0
    assert bundle["kpi_6_wfh_days"] == 1.0
    assert bundle["kpi_7_holiday_days"] == 1.0
    assert bundle["kpi_8_week_off_days"] == 1.0
    assert bundle["kpi_absent_days"] == 1.0
    assert bundle["kpi_9_attendance_exceptions_days"] == 1
    assert bundle["attendance_composition_denominator"] == 8.0


# =========================================================================
# 41. Time Series Analysis backward compatibility preserved
# =========================================================================
def test_time_series_analysis_backward_compatibility():
    """Verify legacy time series analysis metrics remain intact."""
    rows = [
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E001", "Date": "2026-09-02", "Attendance Type": "Regularized", "Status": "A(R)", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    clean_df = ensure_clean_dataframe(df)
    legacy_metrics = tsa.compute_time_series_metrics(clean_df)

    for k in legacy_metrics.keys():
        assert k in bundle


# =========================================================================
# 42. Attendance composition includes all required attendance categories
# =========================================================================
def test_attendance_composition_all_categories_included():
    """Verify that attendance composition includes all 8 categories."""
    rows = [
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E002", "Date": "2026-09-01", "Attendance Type": "On Duty", "Status": "OD", "Quantity": 1.0},
        {"Employee Number": "E003", "Date": "2026-09-01", "Attendance Type": "Leave", "Status": "CL", "Quantity": 1.0},
        {"Employee Number": "E004", "Date": "2026-09-01", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0},
        {"Employee Number": "E005", "Date": "2026-09-01", "Attendance Type": "Holiday", "Status": "H", "Quantity": 1.0},
        {"Employee Number": "E006", "Date": "2026-09-01", "Attendance Type": "Week Off", "Status": "WO", "Quantity": 1.0},
        {"Employee Number": "E007", "Date": "2026-09-01", "Attendance Type": "Absent", "Status": "A", "Quantity": 1.0},
        {"Employee Number": "E008", "Date": "2026-09-01", "Attendance Type": "UnknownType", "Status": "XYZ", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    comp = bundle.get("attendance_composition", [])
    cat_names = [c["category"] for c in comp]

    expected_categories = [
        "Present",
        "On Duty",
        "Leave",
        "WFH",
        "Holiday",
        "Week Off",
        "Absent",
        "Unclassified / Unresolved",
    ]
    assert cat_names == expected_categories
    for c in comp:
        assert c["days"] == 1.0
        assert c["pct"] == 12.5


# =========================================================================
# 43. Composition quantities and percentages reconcile with Overview KPI bundle
# =========================================================================
def test_composition_quantities_and_pct_reconcile_with_kpi_bundle():
    """Verify composition quantities and percentages strictly reconcile to denominator."""
    rows = [
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E002", "Date": "2026-09-01", "Attendance Type": "Leave", "Status": "EL", "Quantity": 1.0},
        {"Employee Number": "E003", "Date": "2026-09-01", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    comp = bundle["attendance_composition"]
    denom = bundle["attendance_composition_denominator"]

    comp_sum = sum(c["days"] for c in comp)
    assert abs(comp_sum - denom) < 1e-6

    cat_map = {c["category"]: c for c in comp}
    assert cat_map["Present"]["days"] == bundle["kpi_3_present_days"]
    assert cat_map["Leave"]["days"] == bundle["kpi_5_leave_days"]
    assert cat_map["WFH"]["days"] == bundle["kpi_6_wfh_days"]

    pct_sum = sum(c["pct"] for c in comp)
    assert abs(pct_sum - 100.0) <= 0.2


# =========================================================================
# 44. Attendance Exceptions is not added as an independent composition segment
# =========================================================================
def test_attendance_exceptions_not_additive_segment():
    """Verify Attendance Exceptions is a separate measure, not an additive composition segment."""
    rows = [
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Regularized", "Status": "A(R)", "Quantity": 1.0},
        {"Employee Number": "E002", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    comp = bundle["attendance_composition"]

    cat_names = [c["category"] for c in comp]
    assert "Attendance Exceptions" not in cat_names
    assert "Regularized" not in cat_names

    # The denominator must only equal sum of composition categories
    assert bundle["attendance_composition_denominator"] == sum(c["days"] for c in comp)
    # The exception count is independent
    assert bundle["kpi_9_attendance_exceptions_days"] == 1


# =========================================================================
# 45. Unclassified and conflicting employee-days remain visible
# =========================================================================
def test_unclassified_and_conflicting_employee_days_remain_visible():
    """Verify unclassified/conflicting attendance days are reported with warning styling."""
    rows = [
        # Employee with two conflicting full-day records without approval: P and CL
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0, "Approval Status": "Pending"},
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Casual Leave", "Status": "CL", "Quantity": 1.0, "Approval Status": "Pending"},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    comp = bundle["attendance_composition"]

    unclass_seg = next((c for c in comp if c["category"] == "Unclassified / Unresolved"), None)
    assert unclass_seg is not None
    assert unclass_seg["days"] == 1.0
    assert unclass_seg["pct"] == 100.0
    assert unclass_seg["color"] == "#F97316"


# =========================================================================
# 46. Half-day attendance quantities remain correct
# =========================================================================
def test_half_day_attendance_quantities_remain_correct():
    """Verify half-day attendance quantities are properly preserved across all views."""
    rows = [
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 0.5, "Business Unit": "Engineering"},
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Leave", "Status": "CL", "Quantity": 0.5, "Business Unit": "Engineering"},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    # Composition
    cat_map = {c["category"]: c for c in bundle["attendance_composition"]}
    assert cat_map["Present"]["days"] == 0.5
    assert cat_map["Leave"]["days"] == 0.5

    # Daily trend
    trend = bundle["daily_attendance_trend"]
    assert len(trend) == 1
    assert trend[0]["present_days"] == 0.5
    assert trend[0]["leave_days"] == 0.5
    assert trend[0]["wfh_days"] == 0.0

    # BU Comparison
    bu_list = bundle["bu_attendance_comparison"]
    assert len(bu_list) == 1
    assert bu_list[0]["present_days"] == 0.5
    assert bu_list[0]["leave_days"] == 0.5


# =========================================================================
# 47. Daily trend quantities are calculated from the correct employee-date basis
# =========================================================================
def test_daily_trend_quantities_calculated_from_correct_basis():
    """Verify daily attendance trend reflects quantity-weighted day equivalents per date."""
    rows = [
        # Day 1: 1 Present, 1 WFH
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E002", "Date": "2026-09-01", "Attendance Type": "Work From Home", "Status": "WFH", "Quantity": 1.0},
        # Day 2: 1 Leave
        {"Employee Number": "E001", "Date": "2026-09-02", "Attendance Type": "Leave", "Status": "SL", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    trend = bundle["daily_attendance_trend"]

    assert len(trend) == 2
    assert str(trend[0]["date"]) == "2026-09-01"
    assert trend[0]["present_days"] == 1.0
    assert trend[0]["wfh_days"] == 1.0
    assert trend[0]["leave_days"] == 0.0

    assert str(trend[1]["date"]) == "2026-09-02"
    assert trend[1]["present_days"] == 0.0
    assert trend[1]["wfh_days"] == 0.0
    assert trend[1]["leave_days"] == 1.0

    # Sum of trends matches bundle KPIs
    assert sum(t["present_days"] for t in trend) == bundle["kpi_3_present_days"]
    assert sum(t["wfh_days"] for t in trend) == bundle["kpi_6_wfh_days"]
    assert sum(t["leave_days"] for t in trend) == bundle["kpi_5_leave_days"]


# =========================================================================
# 48. Missing dates are not silently treated as confirmed zero-attendance days
# =========================================================================
def test_missing_dates_not_silently_treated_as_zeros():
    """Verify that unobserved dates are not artificially inserted as zero-attendance days."""
    rows = [
        {"Employee Number": "E001", "Date": "2026-09-01", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
        {"Employee Number": "E001", "Date": "2026-09-10", "Attendance Type": "Present", "Status": "P", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    trend = bundle["daily_attendance_trend"]

    # Only 2 dates observed in data
    dates = [str(t["date"]) for t in trend]
    assert dates == ["2026-09-01", "2026-09-10"]
    assert len(trend) == 2


# =========================================================================
# 49. BU comparison values use correct organizational attribution
# =========================================================================
def test_bu_comparison_organizational_attribution():
    """Verify effective BU mapping: Lending -> Department, and empty -> Unknown / Unassigned."""
    rows = [
        # Lending with Department -> effective BU is Department
        {"Employee Number": "E001", "Date": "2026-09-01", "Business Unit": "Lending", "Department": "Collections", "Attendance Type": "Present", "Quantity": 1.0},
        # Empty BU -> Unknown / Unassigned
        {"Employee Number": "E002", "Date": "2026-09-01", "Business Unit": "", "Department": "", "Attendance Type": "Leave", "Quantity": 1.0},
        # Regular BU
        {"Employee Number": "E003", "Date": "2026-09-01", "Business Unit": "Engineering", "Department": "Core", "Attendance Type": "Work From Home", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    bu_names = [b["business_unit"] for b in bundle["bu_attendance_comparison"]]

    assert "Collections" in bu_names
    assert "Unknown / Unassigned" in bu_names
    assert "Engineering" in bu_names
    assert "Lending" not in bu_names


# =========================================================================
# 50. BU attendance-status percentages use appropriate BU composition denominator
# =========================================================================
def test_bu_percentages_use_bu_composition_denominator():
    """Verify BU percentages use BU composition denominator, not org-wide denominator."""
    rows = [
        # BU A: 3 Present, 1 Leave (total 4) -> 75% Present, 25% Leave
        {"Employee Number": "E001", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "E002", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "E003", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "E004", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Leave", "Quantity": 1.0},
        # BU B: 10 Present (total 10) -> 100% Present
        {"Employee Number": "E005", "Date": "2026-09-01", "Business Unit": "BU_B", "Attendance Type": "Present", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    bu_map = {b["business_unit"]: b for b in bundle["bu_attendance_comparison"]}

    bu_a = bu_map["BU_A"]
    assert bu_a["present_days"] == 3.0
    assert bu_a["leave_days"] == 1.0
    assert abs(bu_a["present_pct"] - 75.0) < 1e-4
    assert abs(bu_a["leave_pct"] - 25.0) < 1e-4


# =========================================================================
# 51. BU exception rates use distinct Regularized employee-days
# =========================================================================
def test_bu_exception_rates_use_distinct_regularized_days():
    """Verify BU exception rate is regularized employee-days / recorded employee-days."""
    rows = [
        # BU A: 4 recorded employee days, 1 is Regularized, 1 is Absent (Absent is NOT an exception!)
        {"Employee Number": "E001", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Regularized", "Quantity": 1.0},
        {"Employee Number": "E002", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Absent", "Quantity": 1.0},
        {"Employee Number": "E003", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Present", "Quantity": 1.0},
        {"Employee Number": "E004", "Date": "2026-09-01", "Business Unit": "BU_A", "Attendance Type": "Present", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    bu_a = bundle["bu_attendance_comparison"][0]

    assert bu_a["recorded_employee_days"] == 4
    assert bu_a["exception_days"] == 1
    assert abs(bu_a["exception_rate_pct"] - 25.0) < 1e-4


# =========================================================================
# 52. BU transfer headcount does not inflate organization total
# =========================================================================
def test_bu_transfer_headcount_does_not_inflate_org_total():
    """Verify an employee appearing in multiple BUs is deduplicated in org total."""
    rows = [
        # E001 worked in Engineering on Day 1
        {"Employee Number": "E001", "Date": "2026-09-01", "Business Unit": "Engineering", "Attendance Type": "Present", "Quantity": 1.0},
        # E001 worked in Product on Day 2
        {"Employee Number": "E001", "Date": "2026-09-02", "Business Unit": "Product", "Attendance Type": "Present", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)
    bu_list = bundle["bu_attendance_comparison"]
    tot = bundle["bu_comparison_total"]

    # Each BU has headcount 1
    assert len(bu_list) == 2
    for b in bu_list:
        assert b["observed_headcount"] == 1

    # But organization-wide total headcount is 1 (unique deduplicated headcount)
    assert tot["observed_headcount"] == 1
    assert tot["recorded_employee_days"] == 2
    assert tot["present_days"] == 2.0


# =========================================================================
# 53. Empty dataset handling in overview visualizations
# =========================================================================
def test_empty_dataset_handling_in_visualizations():
    """Verify that empty datasets yield safe, zeroed visualization structures."""
    df = pd.DataFrame()
    bundle = compute_workforce_intelligence_bundle(df)

    assert "attendance_composition" in bundle
    assert len(bundle["attendance_composition"]) == 8
    for c in bundle["attendance_composition"]:
        assert c["days"] == 0.0
        assert c["pct"] == 0.0

    assert bundle["daily_attendance_trend"] == []
    assert bundle["bu_attendance_comparison"] == []
    assert bundle["bu_comparison_total"]["observed_headcount"] == 0
    assert bundle["bu_comparison_total"]["recorded_employee_days"] == 0


# =========================================================================
# 54. UI widgets render bundle data without error
# =========================================================================
def test_ui_widgets_render_bundle_data(desktop_app, synthetic_snapshot_a):
    """Verify AttendanceCompositionWidget, DailyAttendanceTrendWidget, and BU table render without error."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    assert hasattr(wf_view, "comp_widget")
    assert hasattr(wf_view, "trend_widget")
    assert hasattr(wf_view, "bu_table_widget")

    # Load synthetic snapshot A
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        app.update()
        time.sleep(0.05)
    app.update()

    # Verify widgets received data
    assert wf_view.comp_widget._composition_data is not None
    assert len(wf_view.comp_widget._composition_data) == 8
    assert wf_view.trend_widget._trend_data is not None
    assert len(wf_view.trend_widget._trend_data) > 0
    assert wf_view.bu_table_widget._bu_data is not None
    assert len(wf_view.bu_table_widget._bu_data) > 0


# =========================================================================
# 55. Replacing active dataset refreshes charts and comparison table
# =========================================================================
def test_replacing_active_dataset_refreshes_visualizations(desktop_app, synthetic_snapshot_a, synthetic_snapshot_b):
    """Verify switching from snapshot A to snapshot B updates all 3 visualizations."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    # 1. Load A
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)
    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 10.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    data_a_comp = wf_view.comp_widget._composition_data
    assert data_a_comp is not None

    # 2. Load B
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_b", synthetic_snapshot_b)
    wf_view.sync_snapshot_state(synthetic_snapshot_b)
    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 10.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    data_b_comp = wf_view.comp_widget._composition_data
    assert data_b_comp is not None
    # Verify BU data reflects snapshot B (Finance)
    bu_names = [b["business_unit"] for b in wf_view.bu_table_widget._bu_data]
    assert "Finance" in bu_names


# =========================================================================
# 56. Stale analytical results cannot overwrite newer dataset's visualizations
# =========================================================================
def test_stale_results_cannot_overwrite_newer_dataset(desktop_app, synthetic_snapshot_a, synthetic_snapshot_b):
    """Verify request generation guard prevents out-of-order callbacks from overwriting visualizations."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    # Set up active snapshot B
    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_b", synthetic_snapshot_b)
    wf_view.sync_snapshot_state(synthetic_snapshot_b)
    current_job = wf_view._latest_job_id

    # Compute a bundle for snapshot A
    bundle_a = compute_workforce_intelligence_bundle(synthetic_snapshot_a.fact_df)

    # Attempt to deliver bundle_a with an obsolete job id
    wf_view._on_metrics_calc_success(bundle_a, current_job - 1, "snap_dataset_a")
    app.update()

    # The view must NOT have accepted snap_dataset_a
    assert wf_view._current_dataset_id != "snap_dataset_a"


# =========================================================================
# 57. Repeated tab switching does not reload or rebuild visualizations
# =========================================================================
def test_repeated_tab_switching_preserves_visualizations(desktop_app, synthetic_snapshot_a):
    """Verify switching tabs away and back preserves visualizations without recalculation."""
    app = desktop_app
    wf_view: WorkforceDashboardView = app.workforce_dashboard_view

    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        app.update()
        time.sleep(0.05)
    app.update()

    # Switch away to attendance tab
    wf_view.select_view("attendance")
    app.update()
    assert wf_view.active_view == "attendance"

    # Switch back to overview tab
    with patch.object(workforce_bridge, "get_workforce_metrics", wraps=workforce_bridge.get_workforce_metrics) as mock_get:
        wf_view.select_view("overview")
        app.update()
        assert wf_view.active_view == "overview"
        # Since snapshot hasn't changed, it should not reload or recompute
        assert not wf_view._is_loading_metrics
        mock_get.assert_not_called()


# =========================================================================
# 58. Step 27A: Attendance composition legend renders all 8 categories
# =========================================================================
def test_attendance_legend_all_eight_categories_render_with_bundle_data(desktop_app):
    """Verify all eight categories are rendered in AttendanceCompositionWidget legend."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    comp_widget = wf_view.comp_widget

    comp_data = [
        {"category": "Present", "days": 2.0, "pct": 22.2, "color": "#10B981"},
        {"category": "On Duty", "days": 1.0, "pct": 11.1, "color": "#0EA5E9"},
        {"category": "Leave", "days": 1.0, "pct": 11.1, "color": "#8B5CF6"},
        {"category": "WFH", "days": 1.0, "pct": 11.1, "color": "#6366F1"},
        {"category": "Holiday", "days": 0.0, "pct": 0.0, "color": "#F59E0B"},
        {"category": "Week Off", "days": 2.0, "pct": 22.2, "color": "#94A3B8"},
        {"category": "Absent", "days": 1.0, "pct": 11.1, "color": "#EF4444"},
        {"category": "Unclassified / Unresolved", "days": 1.0, "pct": 11.1, "color": "#F97316"},
    ]
    comp_widget.update_data(comp_data, 9.0)
    app.update()

    legend_cells = comp_widget.legend_frame.winfo_children()
    assert len(legend_cells) == 8
    # Total badge is updated
    assert "9 days" in comp_widget.lbl_denom_badge.cget("text") or "9.0" in comp_widget.lbl_denom_badge.cget("text")


# =========================================================================
# 59. Step 27A: Attendance composition legend reflows on width change
# =========================================================================
def test_attendance_legend_reflows_on_width_change(desktop_app):
    """Verify legend reflows from 4 columns to 2 columns when width is narrow."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    comp_widget = wf_view.comp_widget

    comp_data = [
        {"category": "Present", "days": 2.0, "pct": 22.2, "color": "#10B981"},
        {"category": "On Duty", "days": 1.0, "pct": 11.1, "color": "#0EA5E9"},
        {"category": "Leave", "days": 1.0, "pct": 11.1, "color": "#8B5CF6"},
        {"category": "WFH", "days": 1.0, "pct": 11.1, "color": "#6366F1"},
        {"category": "Holiday", "days": 0.0, "pct": 0.0, "color": "#F59E0B"},
        {"category": "Week Off", "days": 2.0, "pct": 22.2, "color": "#94A3B8"},
        {"category": "Absent", "days": 1.0, "pct": 11.1, "color": "#EF4444"},
        {"category": "Unclassified / Unresolved", "days": 1.0, "pct": 11.1, "color": "#F97316"},
    ]
    comp_widget.update_data(comp_data, 9.0)

    # Simulate wide configure (width >= 460) -> 4 columns
    class MockEvent:
        def __init__(self, w):
            self.width = w

    comp_widget._on_legend_configure(MockEvent(500))
    assert comp_widget._current_cols == 4

    # Simulate narrow configure (width < 460) -> 2 columns
    comp_widget._on_legend_configure(MockEvent(380))
    assert comp_widget._current_cols == 2


# =========================================================================
# 60. Step 27A: Daily attendance trend redraws on resize and hover
# =========================================================================
def test_daily_trend_canvas_redraw_and_hover(desktop_app):
    """Verify DailyAttendanceTrendWidget draws vector lines and handles hover motion."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    trend_widget = wf_view.trend_widget

    trend_data = [
        {"date": date(2026, 9, 1), "date_str": "2026-09-01", "present_days": 1.0, "wfh_days": 1.0, "leave_days": 0.0, "recorded_days": 2},
        {"date": date(2026, 9, 2), "date_str": "2026-09-02", "present_days": 2.0, "wfh_days": 0.0, "leave_days": 0.0, "recorded_days": 2},
        {"date": date(2026, 9, 3), "date_str": "2026-09-03", "present_days": 0.0, "wfh_days": 0.0, "leave_days": 1.0, "recorded_days": 1},
    ]
    trend_widget.update_data(trend_data)
    app.update()

    # Redraw chart
    trend_widget._draw_chart()
    drawn_items = trend_widget.chart_canvas.find_all()
    assert len(drawn_items) > 0

    # Simulate hover event
    class MockMotionEvent:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    if trend_widget._hover_coords:
        target_x = trend_widget._hover_coords[0][0]
        trend_widget._on_canvas_motion(MockMotionEvent(target_x, 30))
        assert "2026-09-01" in trend_widget.lbl_hover_info.cget("text")
        assert "Present: 1 day" in trend_widget.lbl_hover_info.cget("text") or "Present: 1" in trend_widget.lbl_hover_info.cget("text")


# =========================================================================
# 61. Step 27A: BU Table headers, rows, and total row use identical column widths
# =========================================================================
def test_bu_table_headers_and_cells_identical_column_widths(desktop_app):
    """Verify every column in the BU table has identical pixel widths across header, rows, and total."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    bu_widget = wf_view.bu_table_widget

    bu_data = [
        {
            "business_unit": "Implementation (Lending)",
            "observed_headcount": 2,
            "recorded_employee_days": 2,
            "present_days": 0.0,
            "present_pct": 0.0,
            "leave_days": 1.0,
            "leave_pct": 50.0,
            "wfh_days": 1.0,
            "wfh_pct": 50.0,
            "od_days": 0.0,
            "absent_days": 0.0,
            "exception_days": 0,
            "exception_rate_pct": 0.0,
        },
        {
            "business_unit": "Corporate",
            "observed_headcount": 1,
            "recorded_employee_days": 1,
            "present_days": 0.0,
            "present_pct": 0.0,
            "leave_days": 0.0,
            "leave_pct": 0.0,
            "wfh_days": 0.0,
            "wfh_pct": 0.0,
            "od_days": 0.0,
            "absent_days": 0.0,
            "exception_days": 1,
            "exception_rate_pct": 100.0,
        },
    ]
    bu_total = {
        "business_unit": "Total (Organization-Wide)",
        "observed_headcount": 3,
        "recorded_employee_days": 3,
        "present_days": 0.0,
        "present_pct": 0.0,
        "leave_days": 1.0,
        "leave_pct": 33.3,
        "wfh_days": 1.0,
        "wfh_pct": 33.3,
        "od_days": 0.0,
        "absent_days": 0.0,
        "exception_days": 1,
        "exception_rate_pct": 33.3,
    }
    bu_widget.update_data(bu_data, bu_total)
    app.update()

    # Verify 13 columns in header
    hdr_cells = bu_widget.table_hdr_frame.winfo_children()
    assert len(hdr_cells) == 13

    # Verify 13 columns in total row
    tot_cells = bu_widget.total_frame.winfo_children()
    assert len(tot_cells) == 13

    # Verify each data row has 13 cells with matching widths to header
    rows = bu_widget.rows_frame.winfo_children()
    assert len(rows) == 2
    for row_box in rows:
        row_cells = row_box.winfo_children()
        assert len(row_cells) == 13
        for c_idx in range(13):
            # The label widths configured must be identical
            assert row_cells[c_idx].cget("width") == hdr_cells[c_idx].cget("width")
            assert tot_cells[c_idx].cget("width") == hdr_cells[c_idx].cget("width")


# =========================================================================
# 62. Step 27A: Numeric table cells are right-aligned, BU is left-aligned
# =========================================================================
def test_bu_table_alignments(desktop_app):
    """Verify column 0 is left-aligned and columns 1-12 are right-aligned."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    bu_widget = wf_view.bu_table_widget

    rows = bu_widget.rows_frame.winfo_children()
    assert len(rows) > 0
    row_cells = rows[0].winfo_children()

    # Column 0: Business Unit -> anchor 'w'
    assert row_cells[0].cget("anchor") == "w"

    # Columns 1-12: All numerics -> anchor 'e'
    for c_idx in range(1, 13):
        assert row_cells[c_idx].cget("anchor") == "e"


# =========================================================================
# 63. Step 27B: Daily Trend chart dynamically expands and uses vertical height
# =========================================================================
def test_daily_trend_dynamic_height_and_visual_elements(desktop_app):
    """Verify Daily Attendance Trend card configures row 1 weight=1 and draws elements properly."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    trend_widget = wf_view.trend_widget

    # Check rowconfigure weight=1
    row_info = trend_widget.grid_rowconfigure(1)
    assert row_info["weight"] == 1

    trend_data = [
        {"date": date(2026, 9, 1), "date_str": "2026-09-01", "present_days": 150.0, "wfh_days": 20.0, "leave_days": 10.0, "recorded_days": 180},
        {"date": date(2026, 9, 2), "date_str": "2026-09-02", "present_days": 145.0, "wfh_days": 25.0, "leave_days": 10.0, "recorded_days": 180},
        {"date": date(2026, 9, 3), "date_str": "2026-09-03", "present_days": 160.0, "wfh_days": 15.0, "leave_days": 5.0, "recorded_days": 180},
    ]
    trend_widget.update_data(trend_data)
    app.update()

    # Verify canvas has elements drawn
    items = trend_widget.chart_canvas.find_all()
    assert len(items) > 5

    # Test hover motion produces vertical guide line and hover points
    class MockMotionEvent:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    if trend_widget._hover_coords:
        tx = trend_widget._hover_coords[0][0]
        trend_widget._on_canvas_motion(MockMotionEvent(tx, 50))
        hover_items = trend_widget.chart_canvas.find_withtag("hover_indicator")
        assert len(hover_items) >= 4  # 1 vertical line + 3 series points
        assert "2026-09-01" in trend_widget.lbl_hover_info.cget("text")

        # Test hover leave cleans up
        trend_widget._on_canvas_leave(MockMotionEvent(tx, 50))
        assert len(trend_widget.chart_canvas.find_withtag("hover_indicator")) == 0


# =========================================================================
# 64. Step 27B: BU table renders 26 rows with bounded viewport and vertical scrollbar
# =========================================================================
def test_bu_table_26_rows_bounded_viewport_and_vertical_scrollbar(desktop_app):
    """Verify BU table handles 26 Business Units with a bounded viewport and visible vertical scrollbar."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    bu_widget = wf_view.bu_table_widget

    bu_names = [
        "Implementation (Lending)", "Corporate", "Retail Banking", "Wealth Management",
        "Operations & Services", "Risk & Compliance", "Engineering & Architecture",
        "Human Resources", "Finance & Accounts", "Information Security",
        "Treasury", "Customer Experience", "Digital Channels", "Payments Infrastructure",
        "Credit Risk", "Fraud Prevention", "Legal & Secretarial", "Procurement & Admin",
        "Data & Analytics", "Internal Audit", "Corporate Strategy", "Marketing & PR",
        "Investor Relations", "Branch Banking North", "Branch Banking South", "Special Assets",
    ]
    assert len(bu_names) == 26

    bu_data = []
    for idx, name in enumerate(bu_names):
        bu_data.append({
            "business_unit": name,
            "observed_headcount": 10 + idx,
            "recorded_employee_days": (10 + idx) * 22,
            "present_days": float((10 + idx) * 18),
            "present_pct": 81.8,
            "leave_days": float((10 + idx) * 2),
            "leave_pct": 9.1,
            "wfh_days": float((10 + idx) * 2),
            "wfh_pct": 9.1,
            "od_days": 0.0,
            "absent_days": 0.0,
            "exception_days": 1 if idx % 3 == 0 else 0,
            "exception_rate_pct": 0.5 if idx % 3 == 0 else 0.0,
        })

    bu_total = {
        "business_unit": "Total (Organization-Wide)",
        "observed_headcount": sum(b["observed_headcount"] for b in bu_data),
        "recorded_employee_days": sum(b["recorded_employee_days"] for b in bu_data),
        "present_days": sum(b["present_days"] for b in bu_data),
        "present_pct": 81.8,
        "leave_days": sum(b["leave_days"] for b in bu_data),
        "leave_pct": 9.1,
        "wfh_days": sum(b["wfh_days"] for b in bu_data),
        "wfh_pct": 9.1,
        "od_days": 0.0,
        "absent_days": 0.0,
        "exception_days": sum(b["exception_days"] for b in bu_data),
        "exception_rate_pct": 0.3,
    }

    bu_widget.update_data(bu_data, bu_total)
    app.update()

    # 1. Check row count
    rows = bu_widget.rows_frame.winfo_children()
    assert len(rows) == 26
    assert "26 Business Units" in bu_widget.lbl_bu_count.cget("text")

    # 2. Viewport height is bounded (approx 8 rows = 192px), NOT natural 26-row height (>600px)
    viewport_h = bu_widget.rows_canvas.cget("height")
    assert int(viewport_h) <= 200

    # 3. Vertical scrollbar is visible for 26 rows
    assert bu_widget.v_scrollbar.winfo_ismapped() or bu_widget.v_scrollbar.grid_info() != {}

    # 4. Total row is pinned directly beneath rows canvas
    tot_cells = bu_widget.total_frame.winfo_children()
    assert len(tot_cells) == 13
    assert tot_cells[0].cget("text") == "Total (Organization-Wide)"


# =========================================================================
# 65. Step 27B: Synchronized horizontal scrolling across Header, Rows, Total
# =========================================================================
def test_bu_table_synchronized_horizontal_scrolling(desktop_app):
    """Verify Header, Rows, and Total canvases move in 100% lockstep during horizontal scroll."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    bu_widget = wf_view.bu_table_widget

    # Ensure data is populated so scrollregion has width > 0
    bu_data = [{"business_unit": f"BU_{i}", "observed_headcount": 10, "recorded_employee_days": 100,
                "present_days": 80.0, "present_pct": 80.0, "leave_days": 10.0, "leave_pct": 10.0,
                "wfh_days": 10.0, "wfh_pct": 10.0, "od_days": 0.0, "absent_days": 0.0,
                "exception_days": 0, "exception_rate_pct": 0.0} for i in range(10)]
    bu_total = {"business_unit": "Total (Organization-Wide)", "observed_headcount": 100, "recorded_employee_days": 1000,
                "present_days": 800.0, "present_pct": 80.0, "leave_days": 100.0, "leave_pct": 10.0,
                "wfh_days": 100.0, "wfh_pct": 10.0, "od_days": 0.0, "absent_days": 0.0,
                "exception_days": 0, "exception_rate_pct": 0.0}
    bu_widget.update_data(bu_data, bu_total)
    app.update()

    # Call _on_h_scroll
    bu_widget._on_h_scroll("moveto", "0.35")
    app.update()

    h_xview = bu_widget.header_canvas.xview()
    r_xview = bu_widget.rows_canvas.xview()
    t_xview = bu_widget.total_canvas.xview()

    # All three must match exactly
    assert abs(h_xview[0] - r_xview[0]) < 0.001
    assert abs(r_xview[0] - t_xview[0]) < 0.001

    # Scroll fully to the right (1.0)
    bu_widget._on_h_scroll("moveto", "1.0")
    app.update()
    assert bu_widget.rows_canvas.xview() == bu_widget.header_canvas.xview() == bu_widget.total_canvas.xview()


# =========================================================================
# 66. Step 27B: Mouse-wheel events isolate vertical scrolling and handle Shift-wheel
# =========================================================================
def test_bu_table_mousewheel_isolation(desktop_app):
    """Verify mousewheel over BU rows returns 'break' and Shift+wheel scrolls horizontally."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    bu_widget = wf_view.bu_table_widget

    class MockWheelEvent:
        def __init__(self, delta):
            self.delta = delta

    # Vertical mousewheel must return 'break' to prevent event bubbling to overview page
    ret_v = bu_widget._on_rows_mousewheel(MockWheelEvent(-120))
    assert ret_v == "break"

    # Shift + mousewheel must scroll horizontally and return 'break'
    ret_h = bu_widget._on_shift_mousewheel(MockWheelEvent(-120))
    assert ret_h == "break"


# =========================================================================
# 67. Step 27B: Hover row displays full unclipped BU name
# =========================================================================
def test_bu_table_hover_shows_full_bu_name(desktop_app):
    """Verify hovering over a row updates lbl_info with the complete unshortened BU name."""
    app = desktop_app
    wf_view = app.workforce_dashboard_view
    bu_widget = wf_view.bu_table_widget

    test_rec = {
        "business_unit": "Implementation (Lending)",
        "observed_headcount": 14,
        "recorded_employee_days": 308,
        "present_days": 280.0,
        "present_pct": 90.9,
        "exception_days": 2,
    }
    bu_widget._on_row_enter(test_rec)
    app.update()

    info_text = bu_widget.lbl_info.cget("text")
    assert "Implementation (Lending)" in info_text
    assert "Headcount: 14" in info_text
    assert "Recorded Days: 308" in info_text
    assert "Present: 90.9%" in info_text

    # Test leaving row restores tip
    bu_widget._on_row_leave()
    app.update()
    assert "Tip: Shift + MouseWheel" in bu_widget.lbl_info.cget("text")


# =========================================================================
# STEP 27C — COLLAPSIBLE SIDEBAR & EXPANDABLE TIME-SERIES TESTS
# =========================================================================

def test_step27c_submenus_start_collapsed(desktop_app):
    """Verify that Transform and Analyse submenus start CLOSED by default on startup."""
    app = desktop_app
    assert app.transform_menu_expanded is False
    assert app.analyse_menu_expanded is False
    assert app.nav_chevron.cget("text") == "▸"
    assert app.analyse_chevron.cget("text") == "▸"
    # Submenu containers must not be gridded on startup
    assert not bool(app.sub_menu_frame.grid_info())
    assert not bool(app.analyse_sub_menu_frame.grid_info())


def test_step27c_transform_and_analyse_submenu_toggling(desktop_app):
    """Verify clicking Transform/Analyse parent toggles child submenus and chevrons."""
    app = desktop_app

    # 1. Expand Transform
    app.toggle_transform_menu()
    app.update()
    assert app.transform_menu_expanded is True
    assert app.nav_chevron.cget("text") == "▾"
    assert bool(app.sub_menu_frame.grid_info())
    # Analyse remains closed
    assert app.analyse_menu_expanded is False
    assert not bool(app.analyse_sub_menu_frame.grid_info())

    # 2. Collapse Transform
    app.toggle_transform_menu()
    app.update()
    assert app.transform_menu_expanded is False
    assert app.nav_chevron.cget("text") == "▸"
    assert not bool(app.sub_menu_frame.grid_info())

    # 3. Expand Analyse
    app.toggle_analyse_menu()
    app.update()
    assert app.analyse_menu_expanded is True
    assert app.analyse_chevron.cget("text") == "▾"
    assert bool(app.analyse_sub_menu_frame.grid_info())

    # 4. Collapse Analyse
    app.toggle_analyse_menu()
    app.update()
    assert app.analyse_menu_expanded is False
    assert app.analyse_chevron.cget("text") == "▸"
    assert not bool(app.analyse_sub_menu_frame.grid_info())


def test_step27c_all_child_navigation_destinations_accessible(desktop_app):
    """Verify that every existing navigation destination remains accessible and functional."""
    app = desktop_app
    destinations = [
        "dashboard",
        "generate",
        "absent",
        "att_summary",
        "time_leave",
        "workforce_intelligence",
        "analyse_time_series",
        "analyse_upload",
    ]
    for dest in destinations:
        app.select_frame_by_name(dest)
        app.update()
        assert dest in app.frames
        assert bool(app.frames[dest].grid_info()), f"Frame {dest} should be gridded when selected"


def test_step27c_sidebar_collapse_and_workspace_expansion(desktop_app):
    """Verify sidebar collapses to 60px icon rail and main workspace width increases."""
    app = desktop_app
    app.geometry("1400x900")
    app.update()

    initial_main_w = app.main_content.winfo_width()

    # Collapse sidebar
    app.toggle_sidebar(force_state=True)
    app.update()

    assert app.sidebar_collapsed is True
    assert app.sidebar.cget("width") == 60
    assert app.btn_sidebar_toggle.cget("text") == "▶"
    # Main content width MUST expand
    collapsed_main_w = app.main_content.winfo_width()
    assert collapsed_main_w > initial_main_w

    # Expand sidebar back
    app.toggle_sidebar(force_state=False)
    app.update()

    assert app.sidebar_collapsed is False
    assert app.sidebar.cget("width") == 280
    assert app.btn_sidebar_toggle.cget("text") == "◀"
    restored_main_w = app.main_content.winfo_width()
    assert abs(restored_main_w - initial_main_w) < 20


def test_step27c_active_screen_preserved_on_sidebar_toggle(desktop_app):
    """Verify active screen and KPI calculations are not rebuilt solely by sidebar toggling."""
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    assert bool(app.frames["workforce_intelligence"].grid_info())
    assert wf_view.active_view == "overview"

    # Toggle multiple times
    app.toggle_sidebar()
    app.update()
    assert bool(app.frames["workforce_intelligence"].grid_info())
    assert wf_view.active_view == "overview"

    app.toggle_sidebar()
    app.update()
    assert bool(app.frames["workforce_intelligence"].grid_info())
    assert wf_view.active_view == "overview"


def test_step27c_daily_trend_short_vs_long_horizontal_scrolling(desktop_app):
    """Verify short date range does NOT activate scrollbar, but 90 and 365 days activate it."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    trend: DailyAttendanceTrendWidget = wf_view.trend_widget

    # Ensure widget is realized with a visible canvas
    wf_view._set_overview_state("ready")
    desktop_app.update()

    # Case A: Short date range (13 dates)
    data_13 = [
        {"date_str": f"2026-09-{i:02d}", "present_days": 25.0, "wfh_days": 5.0, "leave_days": 2.0}
        for i in range(1, 14)
    ]
    trend.update_data(data_13)
    desktop_app.update()

    assert len(trend._hover_coords) == 13
    assert trend._scroll_active is False
    assert not trend.h_scrollbar.winfo_ismapped()

    # Case B: Medium/Long range (90 dates)
    data_90 = [
        {"date_str": f"2026-{(i//30)+1:02d}-{(i%30)+1:02d}", "present_days": 22.0 + (i%5), "wfh_days": 4.0, "leave_days": 1.0}
        for i in range(90)
    ]
    trend.update_data(data_90)
    desktop_app.update()

    assert len(trend._hover_coords) == 90
    assert trend._scroll_active is True
    assert trend.h_scrollbar.winfo_ismapped()
    first_x = trend._hover_coords[0][0]
    last_x = trend._hover_coords[-1][0]
    assert last_x > first_x
    assert last_x > trend.chart_canvas.winfo_width()

    # Case C: Annual range (365 dates)
    data_365 = [
        {"date_str": f"2026-{(i//30)+1:02d}-{(i%30)+1:02d}", "present_days": 20.0, "wfh_days": 5.0, "leave_days": 2.0}
        for i in range(365)
    ]
    trend.update_data(data_365)
    desktop_app.update()

    assert len(trend._hover_coords) == 365
    assert trend._scroll_active is True
    assert trend.h_scrollbar.winfo_ismapped()
    # Scrollable region covers the entire 365-day width
    last_x_365 = trend._hover_coords[-1][0]
    assert last_x_365 > 8000.0


def test_step27c_expand_trend_dialog_lifecycle(desktop_app):
    """Verify Expand button opens dedicated enlarged dialog and prevents duplicate windows."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    trend: DailyAttendanceTrendWidget = wf_view.trend_widget

    data_13 = [
        {"date_str": f"2026-09-{i:02d}", "present_days": 25.0, "wfh_days": 5.0, "leave_days": 2.0}
        for i in range(1, 14)
    ]
    trend.update_data(data_13, reporting_period="01 Sep to 13 Sep 2026")
    desktop_app.update()

    assert trend._expanded_dialog is None

    # Click expand
    trend._on_expand_clicked()
    desktop_app.update()

    assert trend._expanded_dialog is not None
    assert isinstance(trend._expanded_dialog, ExpandedDailyAttendanceTrendDialog)
    dlg = trend._expanded_dialog
    assert dlg.winfo_exists()
    assert len(dlg.expanded_trend._trend_data) == 13

    # Repeated click must NOT open duplicate dialog
    trend._on_expand_clicked()
    assert trend._expanded_dialog is dlg

    # Close dialog cleanly
    dlg._on_close()
    desktop_app.update()
    assert trend._expanded_dialog is None


def test_step27c_data_quality_dialog_lifecycle(desktop_app):
    """Verify Data Quality header badge click opens diagnostic details dialog without duplicates."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    bundle = {
        "kpi_1_emp_hc": 50,
        "kpi_2_attendance_days": 100,
        "kpi_3_present_days": 80.0,
        "kpi_4_od_days": 5.0,
        "kpi_5_leave_days": 5.0,
        "kpi_6_wfh_days": 5.0,
        "kpi_7_holiday_days": 2.0,
        "kpi_8_week_off_days": 2.0,
        "kpi_absent_days": 1.0,
        "kpi_9_attendance_exceptions_days": 4,
        "attendance_composition_denominator": 100.0,
        "unclassified_records_count": 2,
        "conflicting_employee_days_count": 1,
        "kpi_unclassified_days": 2.0,
        "kpi_unclassified_pct": 2.0,
    }
    wf_view._render_overview_kpis(bundle)
    desktop_app.update()

    assert "DQ: 1 to review" in wf_view.lbl_dq_info.cget("text")

    # Click DQ badge
    wf_view._show_dq_details_dialog()
    desktop_app.update()

    assert wf_view._dq_dialog is not None
    assert isinstance(wf_view._dq_dialog, DataQualityDetailDialog)
    dlg = wf_view._dq_dialog
    assert dlg.winfo_exists()

    # Repeated click must NOT open duplicate dialog
    wf_view._show_dq_details_dialog()
    assert wf_view._dq_dialog is dlg

    # Close cleanly
    dlg._on_close()
    desktop_app.update()

def test_step27c_trend_chart_tightened_spacing_and_grid_continuity(desktop_app):
    """Verify Daily Attendance Trend tightened padding, non-colliding labels, and seamless grid lines."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    trend: DailyAttendanceTrendWidget = wf_view.trend_widget

    data = [
        {"date_str": "2026-09-01", "present_days": 10.0, "wfh_days": 2.0, "leave_days": 1.0},
        {"date_str": "2026-09-02", "present_days": 12.0, "wfh_days": 1.0, "leave_days": 0.0},
    ]
    trend.update_data(data, reporting_period="Sep 01 - Sep 02")
    desktop_app.update()

    # 1. First data point starts right at 6.0px flush with axis
    assert len(trend._hover_coords) == 2
    assert trend._hover_coords[0][0] == 6.0

    # 2. Check Y-axis canvas labels do not collide (days at y=5, top tick at y=16)
    days_items = [
        item for item in trend.y_axis_canvas.find_all()
        if trend.y_axis_canvas.type(item) == "text" and trend.y_axis_canvas.itemcget(item, "text") == "days"
    ]
    assert len(days_items) == 1
    assert trend.y_axis_canvas.coords(days_items[0])[1] == 5.0

    # 3. Y-axis extension tick lines exist connecting to the chart canvas grid
    tick_lines = [
        item for item in trend.y_axis_canvas.find_all()
        if trend.y_axis_canvas.type(item) == "line"
    ]
    assert len(tick_lines) >= 3

    # 4. Canvas heights are synchronized and do not blow out to 264px
    assert trend.y_axis_canvas.winfo_reqheight() <= 145
    assert trend.chart_canvas.winfo_reqheight() <= 145
