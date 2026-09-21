"""
tests/test_workforce_dashboard_shell.py
───────────────────────────────────────
Focused automated test suite for Transformers 2.0 Step 21:
Workforce Intelligence Desktop Dashboard Shell.

Validates all 10 required testing items from Part 8:
 1. Existing desktop application startup remains compatible.
 2. Existing navigation remains accessible.
 3. Workforce Intelligence is accessible through the intended desktop navigation.
 4. All six analytical views can be selected.
 5. The selected navigation state updates correctly.
 6. View switching does not trigger workbook reads.
 7. View switching does not rebuild the analytical data foundation or snapshot.
 8. Repeated navigation does not create unnecessary duplicate view instances.
 9. No Qt or web framework dependencies are introduced.
10. Existing desktop modules and Excel export remain compatible.
"""

from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from app import App
from storage.cache_manager import AnalyticalSnapshot
from storage import snapshot_service
import ui_components as ui
from workforce_intelligence.dashboard_shell import (
    VIEW_CONFIGS,
    VIEW_KEYS,
    WorkforceDashboardView,
)


@pytest.fixture(scope="module")
def desktop_app():
    """Headless Desktop App instance reused across dashboard shell tests."""
    snapshot_service.clear()
    app = App()
    app.withdraw()  # Headless mode for automated tests
    app.update()

    yield app

    try:
        app.destroy()
    except Exception:
        pass
    snapshot_service.clear()


# =========================================================================
# 1. Existing desktop application startup remains compatible
# =========================================================================
def test_desktop_app_startup_compatibility(desktop_app):
    """Verify App initializes cleanly with Workforce Dashboard frame registered."""
    app = desktop_app
    assert app.winfo_exists()
    assert "workforce_intelligence" in app.frames
    assert isinstance(app.frames["workforce_intelligence"], WorkforceDashboardView)
    assert hasattr(app, "workforce_dashboard_view")
    assert app.workforce_dashboard_view is app.frames["workforce_intelligence"]


# =========================================================================
# 2. Existing navigation remains accessible
# =========================================================================
def test_existing_navigation_remains_accessible(desktop_app):
    """Verify that all existing screens remain navigable and intact."""
    app = desktop_app
    existing_screens = [
        "dashboard",
        "transform",
        "generate",
        "absent",
        "att_summary",
        "time_leave",
        "analyse_time_series",
        "analyse_upload",
    ]

    for name in existing_screens:
        app.select_frame_by_name(name)
        app.update()
        assert name in app.frames
        frame = app.frames[name]
        # Verify frame is gridded in main_content
        info = frame.grid_info()
        assert bool(info), f"Frame {name} should be gridded when selected"


# =========================================================================
# 3. Workforce Intelligence accessible through desktop navigation
# =========================================================================
def test_workforce_intelligence_accessible_via_navigation(desktop_app):
    """Verify that Workforce Intelligence is accessible via sidebar button and name."""
    app = desktop_app
    assert "workforce_intelligence" in app.sub_nav_btns
    btn = app.sub_nav_btns["workforce_intelligence"]
    assert "Workforce Intelligence" in btn.cget("text")

    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_frame = app.frames["workforce_intelligence"]
    info = wf_frame.grid_info()
    assert bool(info), "Workforce Intelligence frame must be gridded when selected"


# =========================================================================
# 4. All six analytical views can be selected
# =========================================================================
def test_all_six_analytical_views_can_be_selected(desktop_app):
    """Verify each of the 6 analytical views can be activated."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    expected_views = [
        "overview",
        "attendance",
        "leave",
        "wfh",
        "working_hours",
        "investigations",
    ]

    assert VIEW_KEYS == expected_views
    assert len(wf_view.view_containers) == 6

    for key in expected_views:
        wf_view.select_view(key)
        assert wf_view.active_view == key
        assert key in wf_view.view_containers
        container = wf_view.view_containers[key]
        assert bool(container.grid_info()), f"View container {key} must be gridded when active"


# =========================================================================
# 5. Selected navigation state updates correctly
# =========================================================================
def test_selected_navigation_state_updates_correctly(desktop_app):
    """Verify active tab styling and mutual exclusion of view containers."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    for key in VIEW_KEYS:
        wf_view.select_view(key)

        # 1. Active tab button has accent background
        active_btn = wf_view.tab_buttons[key]
        assert active_btn.cget("fg_color") == ui.COLOR_ACCENT

        # 2. Inactive tab buttons have transparent background
        for other_key, other_btn in wf_view.tab_buttons.items():
            if other_key != key:
                assert other_btn.cget("fg_color") == "transparent"

        # 3. Only the selected view container is gridded
        assert bool(wf_view.view_containers[key].grid_info())
        for other_key, other_container in wf_view.view_containers.items():
            if other_key != key:
                assert not bool(other_container.grid_info()), f"Container {other_key} should not be gridded"


# =========================================================================
# 6. View switching does not trigger workbook reads
# =========================================================================
def test_view_switching_does_not_trigger_workbook_reads(desktop_app):
    """Verify zero file I/O during view switching."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    with patch("openpyxl.load_workbook") as mock_wb, \
         patch("pandas.read_excel") as mock_excel, \
         patch("pandas.read_csv") as mock_csv:

        for key in VIEW_KEYS:
            wf_view.select_view(key)

        assert mock_wb.call_count == 0
        assert mock_excel.call_count == 0
        assert mock_csv.call_count == 0


# =========================================================================
# 7. View switching does not rebuild data foundation or snapshot
# =========================================================================
def test_view_switching_does_not_rebuild_data_foundation_or_snapshot(desktop_app):
    """Verify zero analytical snapshot rebuilding during view switching."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    with patch("storage.snapshot_service.TimeSeriesSnapshotService.prepare_dataset") as mock_prep, \
         patch("workforce_intelligence.load_workforce_data") as mock_load:

        for key in VIEW_KEYS:
            wf_view.select_view(key)

        assert mock_prep.call_count == 0
        assert mock_load.call_count == 0



# =========================================================================
# 8. Repeated navigation does not create duplicate view instances
# =========================================================================
def test_repeated_navigation_does_not_create_duplicate_view_instances(desktop_app):
    """Verify pre-instantiated view containers are reused, retaining Python object identity."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    initial_container_ids = {k: id(wf_view.view_containers[k]) for k in VIEW_KEYS}
    initial_btn_ids = {k: id(wf_view.tab_buttons[k]) for k in VIEW_KEYS}

    # Switch views repeatedly
    for _ in range(3):
        for key in VIEW_KEYS:
            wf_view.select_view(key)

    # Object IDs must remain identical
    current_container_ids = {k: id(wf_view.view_containers[k]) for k in VIEW_KEYS}
    current_btn_ids = {k: id(wf_view.tab_buttons[k]) for k in VIEW_KEYS}

    assert current_container_ids == initial_container_ids
    assert current_btn_ids == initial_btn_ids


# =========================================================================
# 9. No Qt or web framework dependencies introduced
# =========================================================================
def test_no_qt_or_web_framework_dependencies():
    """Verify complete absence of Qt or web server frameworks."""
    forbidden_modules = [
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "flask",
        "fastapi",
        "streamlit",
        "dash",
        "django",
        "tornado",
    ]

    for mod in forbidden_modules:
        assert mod not in sys.modules, f"Forbidden framework '{mod}' detected in sys.modules"


# =========================================================================
# 10. Snapshot state synchronization and existing module compatibility
# =========================================================================
def test_snapshot_state_synchronization_and_legacy_compatibility(desktop_app):
    """Verify snapshot state synchronization in dashboard header and existing module health."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view

    # Initially empty snapshot
    wf_view.sync_snapshot_state(None)
    assert wf_view.lbl_dataset_name.cget("text") == "No dataset loaded"
    assert "Awaiting" in wf_view.lbl_status_text.cget("text")

    # Sync with a synthetic snapshot
    df = pd.DataFrame([{"Employee Number": "E001", "Hours": 8.0}])
    fake_snap = AnalyticalSnapshot(
        key="test_wf_snap_01",
        raw_source="Synthetic_Attendance_Test.xlsx",
        fact_df=df,
        metadata={
            "employee_count": 42,
            "min_date": "2026-09-01",
            "max_date": "2026-09-13",
        },
        metrics={"total_records": 100},
    )

    wf_view.sync_snapshot_state(fake_snap)
    assert wf_view.lbl_dataset_name.cget("text") == "Synthetic_Attendance_Test.xlsx"
    assert "42 employees" in wf_view.lbl_status_text.cget("text")
    assert "2026-09-01 to 2026-09-13" in wf_view.lbl_period.cget("text")
    assert "Clean" in wf_view.lbl_dq_info.cget("text")

    # Verify existing Excel export and Time Series Analysis compatibility
    assert hasattr(desktop_app, "_export_ts_excel")
    assert callable(desktop_app._export_ts_excel)
    assert "analyse_time_series" in desktop_app.frames
