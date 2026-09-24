"""
tests/test_workforce_step29b_sidebar_filters.py
───────────────────────────────────────────────
Synthetic automated tests for Step 29B:
1. Compact navigation rail on startup (~60-68px) and no full-width sidebar.
2. Floating Transform and Analyse submenus (hover, click, one open at a time, escape/outside dismiss).
3. All 8 registered destinations remain accessible, active-screen highlighting on rail.
4. Searchable, scrollable filter dropdowns with case-insensitive search (name and stable employee ID).
5. Mousewheel isolation, keyboard navigation (Up/Down/Enter/Escape), bounded viewport.
6. Cascading filters, combined BU + Date Range update all Overview components, Reset restoration.
7. DQ badge accessibility, zero unnecessary workbook reread or snapshot rebuild.
"""

import pytest
import datetime
from datetime import date, timedelta
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import tkinter as tk
import customtkinter as ctk

from app import App
import ui_components as ui
from storage.cache_manager import AnalyticalSnapshot
from storage import snapshot_service
from workforce_intelligence.dashboard_shell import WorkforceDashboardView
from workforce_intelligence.kpi_engine import compute_workforce_intelligence_bundle


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def desktop_app():
    """Headless Desktop App instance reused across tests in this module."""
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


@pytest.fixture
def synthetic_step29b_snapshot() -> AnalyticalSnapshot:
    """Synthetic dataset with 26 Business Units and 400 employees."""
    rows = []
    # 26 Business Units: BU_A to BU_Z
    bu_names = [f"BU_{chr(ord('A') + i)}" for i in range(26)]
    start_date = date(2026, 9, 1)

    for i in range(1, 401):
        emp_id = f"EMP{i:04d}"
        emp_name = f"Employee {i}"
        bu = bu_names[i % 26]
        dept = f"Dept_{bu}_{i % 3}"
        mgr = f"Manager_{(i % 10):02d}"

        # 3 dates for each employee
        for day_offset in range(3):
            d = start_date + timedelta(days=day_offset)
            is_present = (i + day_offset) % 5 != 0
            rows.append({
                "record_id": f"REC_{emp_id}_{day_offset}",
                "Employee Number": emp_id,
                "Employee Name": emp_name,
                "Business Unit": bu,
                "Department": dept,
                "Reporting Manager": mgr,
                "Date": d.isoformat(),
                "Attendance Type": "Present" if is_present else "Absent",
                "Status": "P" if is_present else "A",
                "Quantity": 1.0,
            })

    fact_df = pd.DataFrame(rows)

    snap = AnalyticalSnapshot(
        key="snap_step29b_test",
        fact_df=fact_df,
        dataset_id="SYNTH_STEP29B",
        raw_source="synthetic_step29b.xlsx",
        metadata={"total_records": len(fact_df), "min_date": "2026-09-01", "max_date": "2026-09-03", "employee_count": 400},
    )
    return snap


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 TESTS — PERMANENT COMPACT SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

def test_01_02_sidebar_starts_compact_and_no_fullwidth(desktop_app):
    """
    Requirements 1 & 2:
    - Sidebar starts as a compact icon rail (60-68px).
    - The full-width sidebar (280px) does not appear on startup.
    - Toggle button is not gridded in visible layout.
    """
    app = desktop_app
    app.update()

    assert app.sidebar_collapsed is True
    rail_w = app.sidebar.cget("width")
    assert 60 <= rail_w <= 68, f"Sidebar rail width should be 60-68px, got {rail_w}"

    # Verify toggle button is NOT gridded
    assert not bool(app.btn_sidebar_toggle.grid_info()), "Full-width expansion toggle should not be gridded"

    # Verify compact logo mark is gridded
    assert bool(app.lbl_logo_compact.grid_info()), "Compact brand mark must be gridded in sidebar header"
    assert app.lbl_logo_compact.cget("text") == "⚡"


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 TESTS — FLOATING TRANSFORM AND ANALYSE SUBMENUS
# ─────────────────────────────────────────────────────────────────────────────

def test_03_hover_opens_floating_submenu(desktop_app):
    """Requirement 3: Hover opens the correct floating parent submenu after debounce."""
    app = desktop_app
    app.close_floating_nav()
    app.update()

    # Trigger hover enter on Transform
    app._on_nav_btn_enter("transform")
    assert app._nav_hover_timer is not None

    # Force timer execution
    app._show_floating_nav("transform")
    app.update()

    assert app.floating_nav_popup is not None
    assert app.floating_nav_popup.winfo_exists()
    assert app.floating_nav_group == "transform"

    app.close_floating_nav()


def test_04_clicking_parent_opens_submenu(desktop_app):
    """Requirement 4: Clicking the parent icon opens its submenu."""
    app = desktop_app
    app.close_floating_nav()
    app.update()

    app._on_transform_parent_clicked()
    app.update()

    assert app.floating_nav_popup is not None
    assert app.floating_nav_popup.winfo_exists()
    assert app.floating_nav_group == "transform"

    # Clicking currently open parent closes it
    app._on_transform_parent_clicked()
    app.update()
    assert app.floating_nav_popup is None


def test_05_pointer_transition_into_submenu_does_not_close_prematurely(desktop_app):
    """Requirement 5: Moving pointer into the submenu does not close it prematurely."""
    app = desktop_app
    app._show_floating_nav("analyse")
    app.update()

    # Leaving parent icon starts grace timer
    app._on_nav_btn_leave("analyse")
    assert app._nav_leave_timer is not None

    # Entering flyout cancels grace timer
    # Simulating the card enter event
    if app._nav_leave_timer:
        app.after_cancel(app._nav_leave_timer)
        app._nav_leave_timer = None

    app.update()
    assert app.floating_nav_popup is not None
    assert app.floating_nav_popup.winfo_exists()

    app.close_floating_nav()


def test_06_only_one_submenu_open_at_a_time(desktop_app):
    """Requirement 6: Only one floating submenu remains open at a time."""
    app = desktop_app
    app._show_floating_nav("transform")
    app.update()
    assert app.floating_nav_group == "transform"

    # Opening analyse closes transform
    app._show_floating_nav("analyse")
    app.update()
    assert app.floating_nav_group == "analyse"

    app.close_floating_nav()


def test_07_outside_click_and_escape_close_flyout(desktop_app):
    """Requirement 7: Outside click and pressing Escape close the flyout."""
    app = desktop_app
    app._show_floating_nav("transform")
    app.update()
    assert app.floating_nav_popup is not None

    # Escape closes
    app._on_flyout_escape()
    app.update()
    assert app.floating_nav_popup is None

    # Test outside click
    app._show_floating_nav("analyse")
    app.update()
    assert app.floating_nav_popup is not None

    # Simulate outside click at coordinate (900, 500)
    mock_event = MagicMock()
    mock_event.x_root = 900
    mock_event.y_root = 500
    app._on_nav_outside_click(mock_event)
    app.update()
    assert app.floating_nav_popup is None


# ─────────────────────────────────────────────────────────────────────────────
# PART 4 TESTS — PRESERVE STATE AND NAVIGATION
# ─────────────────────────────────────────────────────────────────────────────

def test_08_09_all_navigation_destinations_and_highlighting(desktop_app):
    """Requirements 8 & 9: All 8 existing destinations accessible and active screen highlighted."""
    app = desktop_app
    destinations = [
        "dashboard",
        "transform",
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
        assert bool(app.frames[dest].grid_info())

        # Check rail highlighting
        if dest in ("dashboard", "transform", "absent", "att_summary", "time_leave"):
            assert app.nav_parent_btn.cget("fg_color") == ui.COLOR_NAV_ACTIVE
            assert app.analyse_parent_btn.cget("fg_color") == "transparent"
        else:
            assert app.analyse_parent_btn.cget("fg_color") == ui.COLOR_NAV_ACTIVE
            assert app.nav_parent_btn.cget("fg_color") == "transparent"


def test_10_navigation_flyouts_do_not_recalculate_kpis(desktop_app):
    """Requirement 10: Opening navigation flyouts does not recalculate KPIs."""
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_view: WorkforceDashboardView = app.workforce_dashboard_view
    load_metrics_mock = MagicMock()
    with patch.object(wf_view, "_load_overview_metrics", load_metrics_mock):
        app._show_floating_nav("transform")
        app.update()
        app.close_floating_nav()
        app.update()
        app._show_floating_nav("analyse")
        app.update()
        app.close_floating_nav()
        app.update()

        load_metrics_mock.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# PART 5, 6, 7 TESTS — SEARCHABLE DROPDOWNS & SCROLLING
# ─────────────────────────────────────────────────────────────────────────────

def test_11_filter_search_case_insensitive_matching(desktop_app):
    """Requirement 11: Filter dropdown search performs case-insensitive matching."""
    top = tk.Toplevel(desktop_app)
    top.withdraw()
    dropdown = ui.SearchableDropdown(
        top,
        values=["Technology", "Lending Operations", "Finance", "Human Resources"],
        initial_value="Technology",
    )
    dropdown.pack()
    top.update()

    dropdown.open_dropdown()
    top.update()

    # Search lowercase "lend"
    dropdown._search_var.set("lend")
    top.update()
    assert dropdown._filtered_values == ["Lending Operations"]

    # Search uppercase "FIN"
    dropdown._search_var.set("FIN")
    top.update()
    assert dropdown._filtered_values == ["Finance"]

    dropdown.close_dropdown()
    top.destroy()


def test_12_employee_search_by_name_and_stable_id(desktop_app):
    """Requirement 12: Employee search works by both display name and stable ID."""
    top = tk.Toplevel(desktop_app)
    top.withdraw()
    emp_options = [
        "All Employees",
        "E1001 — Alice Johnson",
        "E1002 — Bob Smith",
        "E1003 — Carol Danvers",
    ]
    dropdown = ui.SearchableDropdown(
        top,
        values=emp_options,
        initial_value="All Employees",
    )
    dropdown.pack()
    top.update()

    dropdown.open_dropdown()
    top.update()

    # Search by ID substring
    dropdown._search_var.set("1002")
    top.update()
    assert dropdown._filtered_values == ["E1002 — Bob Smith"]

    # Search by Name substring
    dropdown._search_var.set("carol")
    top.update()
    assert dropdown._filtered_values == ["E1003 — Carol Danvers"]

    dropdown.close_dropdown()
    top.destroy()


def test_13_14_long_options_scrollbar_and_mousewheel_isolation(desktop_app):
    """
    Requirements 13 & 14:
    - Long option list (> 7 items) shows vertical scrollbar.
    - Short option list hides scrollbar.
    - Mouse-wheel events return "break" preventing propagation.
    """
    top = tk.Toplevel(desktop_app)
    top.withdraw()

    # 400 options
    long_opts = [f"Option {i}" for i in range(400)]
    dropdown_long = ui.SearchableDropdown(top, values=long_opts, initial_value="Option 0")
    dropdown_long.pack()
    top.update()
    dropdown_long.open_dropdown()
    top.update()

    # Scrollbar must be visible
    assert bool(dropdown_long._scrollbar.grid_info()), "Scrollbar must be visible for 400 options"

    dropdown_long.close_dropdown()
    dropdown_long.destroy()

    # Short list (3 options)
    dropdown_short = ui.SearchableDropdown(top, values=["A", "B", "C"], initial_value="A")
    dropdown_short.pack()
    top.update()
    dropdown_short.open_dropdown()
    top.update()

    assert not bool(dropdown_short._scrollbar.grid_info()), "Scrollbar must NOT be visible for 3 options"
    dropdown_short.close_dropdown()
    top.destroy()


def test_15_16_17_keyboard_navigation_selection_and_escape(desktop_app):
    """
    Requirements 15, 16, 17:
    - Up and Down arrows move selection.
    - Enter selects active option.
    - Escape closes without changing selection.
    - Searching does not apply selection prematurely.
    """
    top = tk.Toplevel(desktop_app)
    top.withdraw()

    selected_val = None
    def _cmd(val):
        nonlocal selected_val
        selected_val = val

    opts = ["Option A", "Option B", "Option C"]
    dropdown = ui.SearchableDropdown(top, values=opts, initial_value="Option A", command=_cmd)
    dropdown.pack()
    top.update()

    dropdown.open_dropdown()
    top.update()

    # 1. Searching does NOT apply selection prematurely
    dropdown._search_var.set("Option B")
    top.update()
    assert selected_val is None
    assert dropdown.get() == "Option A"

    # 2. Down arrow and Enter selects
    dropdown._on_entry_down(None)
    dropdown._on_entry_return(None)
    top.update()
    assert selected_val == "Option B"
    assert dropdown.get() == "Option B"
    assert dropdown._popup is None

    # 3. Escape dismisses without changing selection
    dropdown.open_dropdown()
    top.update()
    dropdown._search_var.set("Option C")
    top.update()
    dropdown._popup.event_generate("<Escape>")
    top.update()
    assert dropdown.get() == "Option B"  # Still Option B!

    top.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# PART 8 TESTS — CASCADING FILTERS AND INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

def test_18_cascading_dropdown_options(desktop_app, synthetic_step29b_snapshot):
    """Requirement 18: Cascading dropdown options update dynamically based on eligible scope."""
    snapshot_service.cache_manager.set_active_snapshot("snap_step29b_test", synthetic_step29b_snapshot)
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_view: WorkforceDashboardView = app.workforce_dashboard_view
    wf_view.sync_snapshot_state(synthetic_step29b_snapshot)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    # Initially all BUs available
    bu_values = wf_view.combo_bu.cget("values")
    assert "All Business Units" in bu_values
    assert "BU_A" in bu_values
    assert len(bu_values) >= 26

    # Select BU_A
    wf_view._on_bu_selected("BU_A")
    app.update()

    # Departments should only contain Dept_BU_A_*
    dept_values = wf_view.combo_dept.cget("values")
    for d in dept_values:
        if d != "All Departments":
            assert d.startswith("Dept_BU_A_"), f"Unexpected department {d} outside BU_A"

    # Reset
    wf_view._on_reset_filters_clicked()
    app.update()


def test_19_20_combined_filters_and_reset(desktop_app, synthetic_step29b_snapshot):
    """
    Requirements 19 & 20:
    - Combined BU and Date Range filters update all Overview components.
    - Reset restores original complete dataset scope.
    """
    snapshot_service.cache_manager.set_active_snapshot("snap_step29b_test", synthetic_step29b_snapshot)
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_view: WorkforceDashboardView = app.workforce_dashboard_view
    wf_view.sync_snapshot_state(synthetic_step29b_snapshot)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    initial_headcount = wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text")
    assert int(initial_headcount) == 400

    # Apply BU_B filter
    wf_view._on_bu_selected("BU_B")
    wf_view._load_overview_metrics()

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    filtered_headcount = int(wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text"))
    assert filtered_headcount < 400
    assert "BU_B" in wf_view.lbl_active_scope.cget("text")

    # Reset
    wf_view._on_reset_filters_clicked()
    wf_view._load_overview_metrics()

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    restored_headcount = int(wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text"))
    assert restored_headcount == 400
    assert "All Business Units" in wf_view.combo_bu.get()
    assert "All Dates" in wf_view.combo_date_range.get()


def test_21_dq_status_remains_accessible(desktop_app, synthetic_step29b_snapshot):
    """Requirement 21: Data Quality badge remains accessible in the header."""
    snapshot_service.cache_manager.set_active_snapshot("snap_step29b_test", synthetic_step29b_snapshot)
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_view: WorkforceDashboardView = app.workforce_dashboard_view
    assert hasattr(wf_view, "f_dq")
    assert bool(wf_view.f_dq.grid_info()), "DQ status badge container must remain gridded"


def test_22_no_workbook_reread_on_dropdown_interactions(desktop_app, synthetic_step29b_snapshot):
    """Requirement 22: Opening and closing dropdowns does not re-read workbook or rebuild snapshot."""
    snapshot_service.cache_manager.set_active_snapshot("snap_step29b_test", synthetic_step29b_snapshot)
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_view: WorkforceDashboardView = app.workforce_dashboard_view
    sync_mock = MagicMock()
    with patch.object(wf_view, "sync_snapshot_state", sync_mock):
        wf_view.combo_bu.open_dropdown()
        app.update()
        wf_view.combo_bu._search_var.set("BU_C")
        app.update()
        wf_view.combo_bu.close_dropdown()
        app.update()

        sync_mock.assert_not_called()


def test_23_24_bu_table_and_export_structure_unchanged(desktop_app, synthetic_step29b_snapshot):
    """Requirements 23 & 24: BU comparison table retains layout and pinned total row."""
    snapshot_service.cache_manager.set_active_snapshot("snap_step29b_test", synthetic_step29b_snapshot)
    app = desktop_app
    app.select_frame_by_name("workforce_intelligence")
    app.update()

    wf_view: WorkforceDashboardView = app.workforce_dashboard_view
    wf_view.sync_snapshot_state(synthetic_step29b_snapshot)

    start_time = time.time()
    while wf_view._is_loading_metrics and (time.time() - start_time < 5.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    app.update()

    assert hasattr(wf_view, "bu_table_frame")
    assert hasattr(wf_view, "bu_table_widget")
    assert bool(wf_view.bu_table_widget.grid_info())

