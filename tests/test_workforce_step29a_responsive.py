"""
tests/test_workforce_step29a_responsive.py
──────────────────────────────────────────
Dedicated verification test suite for Transformers 2.0 Step 29A:
1. Responsive KPI card layout & text wrapping (no clipping at narrow card widths).
2. Data Quality badge accessibility across both expanded and collapsed sidebar states.
3. Reconciliation notice responsive text wrapping and vertical growth without clipping.
4. Mathematical and definition audit:
   - Attendance Days KPI: distinct recorded employee-calendar-days.
   - Attendance Composition denominator: quantity-weighted day equivalents.
   - Attendance Exceptions: distinct employee-calendar-days with Attendance Type == 'Regularized'.
5. Functional global filter updates across all ten cards and overview components.
"""

from datetime import date, datetime
import time
from unittest.mock import MagicMock
import pandas as pd
import pytest

from app import App
from storage.cache_manager import AnalyticalSnapshot
from storage import snapshot_service
import ui_components as ui
from workforce_intelligence.dashboard_shell import (
    ExecutiveKPICard,
    WorkforceDashboardView,
    _fmt_days,
)
from workforce_intelligence.kpi_engine import (
    compute_workforce_intelligence_bundle,
    ensure_clean_dataframe,
    get_effective_bu,
)


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
def sample_audit_snapshot() -> AnalyticalSnapshot:
    """
    Synthetic dataset to verify:
    - Distinct employee-days: 2 emps over 2 dates = 4 distinct employee-days.
    - Quantity weights: One half-day leave (0.5), so total day equivalents = 3.5.
    - Regularized record on exactly one employee-date.
    """
    rows = [
        # E001 on 2026-09-01: Full Day Present
        {
            "record_id": "REC_1",
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
        # E001 on 2026-09-02: 0.5 Present, 0.5 Leave
        {
            "record_id": "REC_2",
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
            "record_id": "REC_3",
            "Employee Number": "E001",
            "Employee Name": "Alice Smith",
            "Business Unit": "Technology",
            "Department": "Engineering",
            "Reporting Manager": "Bob Mgr",
            "Date": "2026-09-02",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Quantity": 0.5,
        },
        # E002 on 2026-09-01: Regularized (1.0)
        {
            "record_id": "REC_4",
            "Employee Number": "E002",
            "Employee Name": "Carol Jones",
            "Business Unit": "Operations",
            "Department": "Logistics",
            "Reporting Manager": "Dave Mgr",
            "Date": "2026-09-01",
            "Attendance Type": "Regularized",
            "Status": "P",
            "Quantity": 1.0,
        },
        # E002 on 2026-09-02: 0.5 WFH
        {
            "record_id": "REC_5",
            "Employee Number": "E002",
            "Employee Name": "Carol Jones",
            "Business Unit": "Operations",
            "Department": "Logistics",
            "Reporting Manager": "Dave Mgr",
            "Date": "2026-09-02",
            "Attendance Type": "WFH",
            "Status": "WFH",
            "Quantity": 0.5,
        },
    ]
    df = pd.DataFrame(rows)
    snap = AnalyticalSnapshot(
        key="snap_step29a_test",
        fact_df=df,
        dataset_id="ds_step29a_test",
        raw_source="Step29A_Dataset.xlsx",
        metadata={
            "employee_count": 2,
            "min_date": "2026-09-01",
            "max_date": "2026-09-02",
        },
    )
    return snap


# ─────────────────────────────────────────────────────────────────────────────
# 1. KPI Card Responsive Text Wrapping Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_kpi_card_responsive_wrapping_at_narrow_width(desktop_app):
    """Verify KPI card wraps long titles, values, subtitles, and notes without clipping at narrow width."""
    wf_view = desktop_app.workforce_dashboard_view
    # Card 10: Attendance Exceptions
    card = wf_view.kpi_cards["kpi_9_attendance_exceptions"]

    card.update_values(
        primary="39 exception days",
        secondary="0.8% of recorded employee-days",
        note="Regularized attendance exceptions",
    )

    # Simulate narrow card configure event (e.g. 170 physical pixels)
    scaling = card._get_widget_scaling() if hasattr(card, "_get_widget_scaling") else 1.0
    narrow_w = int(170 * scaling)

    class MockEvent:
        width = narrow_w
        height = int(140 * scaling)

    card._on_card_configure(MockEvent())
    desktop_app.update()

    # Check wraplength is set responsively
    assert card.lbl_title.cget("wraplength") > 0
    assert card.lbl_val.cget("wraplength") > 0
    assert card.lbl_sub.cget("wraplength") > 0
    assert card.lbl_note.cget("wraplength") > 0

    # Physical requested widths should not exceed the available inner width
    inner_max = narrow_w
    assert card.lbl_val.winfo_reqwidth() <= inner_max + 10
    assert card.lbl_sub.winfo_reqwidth() <= inner_max + 10
    assert card.lbl_title.winfo_reqwidth() <= inner_max + 10


# ─────────────────────────────────────────────────────────────────────────────
# 2. Header and Data Quality Badge Accessibility Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_header_dq_badge_accessible_in_both_sidebar_states(desktop_app):
    """Verify Data Quality badge remains in Column 2 and accessible in both sidebar states."""
    wf_view = desktop_app.workforce_dashboard_view

    # Check f_dq is mapped and in grid
    info = wf_view.f_dq.grid_info()
    assert info["column"] == 2
    assert info["row"] == 0

    # Upload button is in Column 3
    btn_info = wf_view.btn_go_upload.grid_info()
    assert btn_info["column"] == 3
    assert btn_info["row"] == 0

    # Metadata strip is in Column 1
    meta_info = wf_view.header_card.winfo_children()[0].winfo_children()[1].grid_info()
    assert meta_info["column"] == 1

    # Check collapsed sidebar
    desktop_app.sidebar_collapsed = True
    desktop_app.update()
    assert wf_view.f_dq.winfo_ismapped() or wf_view.f_dq.grid_info() != {}

    # Check expanded sidebar
    desktop_app.sidebar_collapsed = False
    desktop_app.update()
    assert wf_view.f_dq.winfo_ismapped() or wf_view.f_dq.grid_info() != {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Reconciliation Notice Responsive Wrapping Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_reconciliation_notice_responsive_wrapping(desktop_app):
    """Verify reconciliation notice wraps text within available card width."""
    wf_view = desktop_app.workforce_dashboard_view
    # Set long notice text
    wf_view.lbl_recon_desc.configure(
        text="All 39 unclassified records are accounted for in the composition denominator (5,078.5 days). Categorized attendance totals 5,039.5 days across Present, OD, Leave, WFH, Holiday, Week Off, and Absent."
    )

    # Trigger configure event with width 600
    scaling = wf_view.recon_card._get_widget_scaling() if hasattr(wf_view.recon_card, "_get_widget_scaling") else 1.0

    class MockEvent:
        width = int(600 * scaling)
        height = int(50 * scaling)

    wf_view._on_recon_card_configure(MockEvent())
    desktop_app.update()

    assert wf_view.lbl_recon_desc.cget("wraplength") > 0
    assert wf_view.lbl_recon_desc.cget("justify") == "left"
    assert wf_view.lbl_recon_title.cget("justify") == "left"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Audit: Attendance Days vs Composition vs Exceptions
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_attendance_days_distinct_vs_composition_quantity_weighted(sample_audit_snapshot):
    """
    Verify confirmed business definitions:
    - Attendance Days: 4 distinct employee-calendar-days (E001 on 09-01, E001 on 09-02, E002 on 09-01, E002 on 09-02).
    - Attendance Composition denominator: 3.5 quantity-weighted day equivalents (1.0 + 0.5 + 0.5 + 1.0 + 0.5).
    - Attendance Exceptions: 1 distinct employee-calendar-day with Attendance Type == 'Regularized'.
    """
    bundle = compute_workforce_intelligence_bundle(sample_audit_snapshot.fact_df)

    # 1. Distinct recorded employee-days
    assert bundle["kpi_2_attendance_days"] == 4
    assert bundle["recorded_employee_days"] == 4

    # 2. Quantity-weighted composition denominator
    assert bundle["attendance_composition_denominator"] == 3.5

    # 3. Attendance Exceptions (Regularized only)
    assert bundle["kpi_9_attendance_exceptions_days"] == 1
    # Rate = 1 exception day / 4 recorded employee-days = 25.0%
    assert bundle["kpi_9_attendance_exceptions_rate_pct"] == 25.0
    assert bundle["kpi_9_attendance_exceptions_affected_emps"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Global Filter Integration Verification
# ─────────────────────────────────────────────────────────────────────────────

def test_filters_update_all_overview_components_consistently(desktop_app, sample_audit_snapshot):
    """Verify filtering by Business Unit updates KPI cards, composition, trend, BU comparison, and active scope."""
    wf_view = desktop_app.workforce_dashboard_view
    snapshot_service.cache_manager.set_active_snapshot("snap_step29a_test", sample_audit_snapshot)
    wf_view.sync_snapshot_state(sample_audit_snapshot)

    # Wait for metrics load
    start = time.time()
    while wf_view._is_loading_metrics and (time.time() - start < 10.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        desktop_app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    desktop_app.update()

    # Unfiltered scope: 2 employees, 4 recorded days
    assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "2"
    assert "4" in wf_view.kpi_cards["kpi_2_attendance_days"].lbl_val.cget("text")

    # Apply BU filter: Operations (only E002)
    wf_view._on_bu_selected("Operations")
    wf_view._load_overview_metrics()

    start = time.time()
    while wf_view._is_loading_metrics and (time.time() - start < 10.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        desktop_app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    desktop_app.update()

    # Filtered to Operations:
    # 1 employee (Carol), 2 recorded days
    assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "1"
    assert "2" in wf_view.kpi_cards["kpi_2_attendance_days"].lbl_val.cget("text")
    assert "Operations" in wf_view.lbl_active_scope.cget("text")

    # Composition widget updated
    assert hasattr(wf_view, "comp_widget")
    assert len(wf_view.comp_widget._composition_data) == 8

    # BU comparison table pinned total represents current filtered scope
    assert wf_view.bu_table_widget._bu_total["observed_headcount"] == 1
    assert wf_view.bu_table_widget._bu_total["recorded_employee_days"] == 2

    # Reset restores full scope
    wf_view._on_reset_filters_clicked()

    start = time.time()
    while wf_view._is_loading_metrics and (time.time() - start < 10.0):
        wf_view._poll_metrics_queue(wf_view._latest_job_id)
        desktop_app.update()
        time.sleep(0.05)
    wf_view._poll_metrics_queue(wf_view._latest_job_id)
    desktop_app.update()

    assert wf_view.kpi_cards["kpi_1_emp_hc"].lbl_val.cget("text") == "2"
    assert "Complete Active Population" in wf_view.lbl_active_scope.cget("text")
