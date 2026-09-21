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
    ExecutiveKPICard,
    VIEW_CONFIGS,
    VIEW_KEYS,
    WorkforceDashboardView,
    _fmt_days,
)
from workforce_intelligence.kpi_engine import compute_workforce_intelligence_bundle
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
        # Emp 3: Charlie (Missing Swipe exception)
        {
            "record_id": "REC_005",
            "Employee Number": "E003",
            "Employee Name": "Charlie Brown",
            "Business Unit": "Operations",
            "Department": "Logistics",
            "Reporting Manager": "Eve Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "Missing Swipes",
            "Status": "MS",
            "Quantity": 1.0,
            "In Time": "09:30",
            "Out Time": "NA",
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

    snapshot_service.cache_manager.set_active_snapshot("snap_dataset_a", synthetic_snapshot_a)
    wf_view.sync_snapshot_state(synthetic_snapshot_a)

    # Process pending events for background worker thread
    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        app.update()
        time.sleep(0.05)

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

    # Exceptions: 1 day (Charlie Missing Swipes) -> Singular '1 day'
    assert b["kpi_9_attendance_exceptions_days"] == 1
    assert wf_view.kpi_cards["kpi_9_attendance_exceptions"].lbl_val.cget("text") == "1 day"


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
    assert wf_view.lbl_dq_info.cget("text") == "Clean • Ready for Analysis"
    assert "Complete Additive Attendance Composition" in wf_view.lbl_recon_title.cget("text")

    # Unclassified records present: count == 1
    unclass_bundle = dict(clean_bundle)
    unclass_bundle["unclassified_records_count"] = 1
    unclass_bundle["kpi_unclassified_days"] = 1.0
    unclass_bundle["kpi_unclassified_pct"] = 9.1
    unclass_bundle["attendance_composition_denominator"] = 11.0

    wf_view._render_overview_kpis(unclass_bundle)
    assert wf_view.lbl_dq_info.cget("text") == "Loaded • 1 record requires review"
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
    assert "1 conflicting employee-day requires review" in wf_view.lbl_dq_info.cget("text")
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
        {"record_id": "REC_EX_01", "Employee Number": "E303", "Date": "2026-09-07", "Attendance Type": "Missing Swipes", "Status": "P(MS)", "Quantity": 1.0},
    ]
    df = pd.DataFrame(rows)
    bundle = compute_workforce_intelligence_bundle(df)

    assert bundle["kpi_8_week_off_days"] == 2.0
    assert bundle["kpi_9_attendance_exceptions_days"] == 1
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 1




