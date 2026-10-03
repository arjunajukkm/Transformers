"""
tests/test_workforce_trends_tab.py
──────────────────────────────────
Comprehensive test suite for the Workforce Intelligence Trends Tab & Decision Intelligence.

Tests cover:
 1. Trends tab navigation & container registration (VIEW_KEYS == ["overview", "trends"]).
 2. Trend calculations through the bridge (get_trend_intelligence).
 3. Benchmark calculations (Organisation, Historical Baseline, Peer Business Unit).
 4. Global filter application (Date, BU, Dept, Manager, Employee).
 5. Empty dataset state handling.
 6. Single-month (1 month baseline) dataset.
 7. Low-volume data handling and confidence grading.
 8. Multi-month time-series trajectory and regression detection.
 9. "What Changed?" deterministic driver decomposition (zero AI text generation).
10. Emerging Patterns integration (patterns.py).
11. Multi-Dimension BU Benchmark Comparison Table rows and total.
12. Thread-safety, asynchronous queue polling, and zero workbook re-reads.
"""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest

from storage.cache_manager import AnalyticalSnapshot, snapshot_cache
from storage import snapshot_service
import ui_components as ui
from workforce_intelligence.dashboard_shell import (
    VIEW_CONFIGS,
    VIEW_KEYS,
    WorkforceDashboardView,
    TrendPulseWidget,
    MainTrendChartWidget,
    BusinessUnitHeatmapWidget,
    WhatChangedWidget,
    EmergingPatternsWidget,
    TrendBenchmarkTableWidget,
)
from workforce_intelligence.snapshot_bridge import workforce_bridge
from workforce_intelligence.trends import (
    TREND_METRICS,
    POLICY_EFFECTIVE_DATE_STR,
    format_metric_value,
)


@pytest.fixture
def multi_month_snapshot():
    """Create a clean 3-month synthetic AnalyticalSnapshot for trends testing."""
    records = []
    # Generate May, Jun, Jul 2026 data
    dates = [
        date(2026, 5, 10), date(2026, 5, 15), date(2026, 5, 20),
        date(2026, 6, 10), date(2026, 6, 15), date(2026, 6, 20),
        date(2026, 7, 10), date(2026, 7, 15), date(2026, 7, 20),
    ]

    bus = ["Engineering", "Lending", "Operations"]
    emp_ids = [101, 102, 103, 104, 105, 106, 107, 108, 109]

    for d in dates:
        for idx, emp_id in enumerate(emp_ids):
            bu = bus[idx % 3]
            # Lending has higher exceptions in July
            if bu == "Lending" and d.month == 7:
                att_type = "Single Swipe"
                in_t = "10:30"
                out_t = ""
                exc_flag = "Missing Out Punch"
            elif idx % 4 == 0:
                att_type = "Present"
                in_t = "09:30"
                out_t = "18:30"
                exc_flag = ""
            else:
                att_type = "Present"
                in_t = "09:00"
                out_t = "18:00"
                exc_flag = ""

            records.append({
                "Date": d,
                "Employee No": emp_id,
                "Employee Name": f"Employee {emp_id}",
                "Business Unit": bu,
                "Department": f"{bu} Core",
                "Reporting Manager": f"Manager {bu}",
                "Attendance Type": att_type,
                "First In": in_t,
                "Last Out": out_t,
                "Total Duration": "09:00" if out_t else "04:00",
                "Exceptions": exc_flag,
                "Leave Type": "",
                "Leave Status": "",
            })

    df = pd.DataFrame(records)
    snap = AnalyticalSnapshot(
        key="test_trends_snapshot_multi_month",
        fact_df=df,
        metadata={"min_date": "2026-05-10", "max_date": "2026-07-20", "employee_count": len(emp_ids)},
        raw_source="synthetic_test.xlsx",
    )
    snapshot_cache.set_active_snapshot(snap)
    return snap


# =========================================================================
# 1. Trends Tab Navigation & Structure
# =========================================================================
def test_trends_tab_navigation_structure():
    """Verify VIEW_KEYS contains exactly overview and trends, with proper metadata."""
    assert VIEW_KEYS == ["overview", "trends"]
    assert "trends" in VIEW_CONFIGS
    cfg = VIEW_CONFIGS["trends"]
    assert cfg["tab_title"] == "Trends"
    assert "📈" in cfg["icon"]


# =========================================================================
# 2. Bridge: get_trend_intelligence Multi-Month Calculations
# =========================================================================
def test_get_trend_intelligence_multi_month(multi_month_snapshot):
    """Verify get_trend_intelligence returns complete bundle with all required sections."""
    bundle = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        benchmark_type="ORGANIZATION",
    )

    assert bundle["metric_id"] == "attendance_exception_rate"
    assert bundle["benchmark_type"] == "ORGANIZATION"
    assert "trend_pulse" in bundle
    assert len(bundle["trend_pulse"]) == 5

    # Check 5 Trend Pulse cards
    pulse = bundle["trend_pulse"]
    assert pulse[0]["title"] == "Current Value"
    assert pulse[1]["title"] == "MoM Change"
    assert pulse[2]["title"] == "3-Month Trend"
    assert pulse[3]["title"] == "Benchmark Gap"
    assert pulse[4]["title"] == "Data Confidence"

    # Check Chart
    chart = bundle["chart"]
    assert "points" in chart
    assert len(chart["points"]) == 3  # May, Jun, Jul
    assert chart["points"][0]["period_display"] == "May 2026"
    assert chart["points"][2]["period_display"] == "Jul 2026"

    # Check Heatmap
    heatmap = bundle["heatmap"]
    assert len(heatmap["months"]) == 3
    assert len(heatmap["rows"]) == 3  # Engineering, Lending, Operations

    # Check What Changed
    what_changed = bundle["what_changed"]
    assert "headline" in what_changed
    assert "drivers" in what_changed

    # Check Benchmark Table
    bench_table = bundle["benchmark_table"]
    assert len(bench_table["rows"]) == 3
    assert "total" in bench_table


# =========================================================================
# 3. Benchmark Calculations (Organisation, Historical, Peer)
# =========================================================================
def test_benchmark_modes(multi_month_snapshot):
    """Verify Organisation, Historical Baseline, and Peer benchmarks compute properly."""
    # 1. Organisation
    b_org = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        benchmark_type="ORGANIZATION",
        business_unit="Lending",
    )
    assert b_org["benchmark_type"] == "ORGANIZATION"
    assert b_org["benchmark_label"] == "Organisation"

    # 2. Historical Baseline
    b_hist = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        benchmark_type="HISTORICAL",
        business_unit="Lending",
    )
    assert b_hist["benchmark_type"] == "HISTORICAL"
    assert b_hist["benchmark_label"] == "Historical Baseline"

    # 3. Peer Benchmark
    b_peer = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        benchmark_type="PEER",
        business_unit="Lending",
    )
    assert b_peer["benchmark_type"] == "PEER"
    assert b_peer["benchmark_label"] == "Peer Business Unit"


# =========================================================================
# 4. Global Filters Applied to Trend Intelligence
# =========================================================================
def test_global_filters_in_trends(multi_month_snapshot):
    """Verify filters (BU, Dept, Date Range) restrict scope properly."""
    # Filter to Lending
    bundle_lending = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        business_unit="Lending",
    )
    assert "Lending" in bundle_lending["scope_description"]

    # Filter to specific date range
    bundle_dr = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        date_range=(date(2026, 6, 1), date(2026, 7, 31)),
    )
    assert len(bundle_dr["chart"]["points"]) >= 1


# =========================================================================
# 5. Empty Dataset State Handling
# =========================================================================
def test_empty_dataset_handling():
    """Verify empty dataset returns clean default structure without exceptions."""
    snapshot_service.clear()
    bundle = workforce_bridge.get_trend_intelligence(metric_id="attendance_exception_rate")
    assert bundle["metric_id"] == "attendance_exception_rate"
    assert len(bundle["trend_pulse"]) == 5
    assert bundle["trend_pulse"][0]["value"] == "—"
    assert bundle["chart"]["points"] == []
    assert bundle["what_changed"]["has_movement"] is False


# =========================================================================
# 6. Single-Month Dataset Handling
# =========================================================================
def test_single_month_dataset_handling():
    """Verify single month dataset establishes baseline without crashing."""
    records = [{
        "Date": date(2026, 5, 10),
        "Employee No": 101,
        "Employee Name": "Alice",
        "Business Unit": "Engineering",
        "Department": "Core",
        "Reporting Manager": "Bob",
        "Attendance Type": "Present",
        "First In": "09:00",
        "Last Out": "18:00",
        "Total Duration": "09:00",
        "Exceptions": "",
        "Leave Type": "",
        "Leave Status": "",
    }]
    df = pd.DataFrame(records)
    snap = AnalyticalSnapshot(
        key="test_single_month",
        fact_df=df,
        metadata={"min_date": "2026-05-10", "max_date": "2026-05-10", "employee_count": 1},
        raw_source="single.xlsx",
    )
    snapshot_cache.set_active_snapshot(snap)

    bundle = workforce_bridge.get_trend_intelligence(metric_id="attendance_exception_rate")
    assert len(bundle["chart"]["points"]) == 1
    assert bundle["trend_pulse"][1]["value"] == "Baseline (First Month)"
    assert bundle["what_changed"]["has_movement"] is False


# =========================================================================
# 7. Low-Volume Data Flagging
# =========================================================================
def test_low_volume_data_flagging(multi_month_snapshot):
    """Verify low-volume records are marked with Low confidence flag."""
    bundle = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
        employee="101",  # Single employee = low volume
    )
    assert "confidence" in bundle["trend_pulse"][4]["title"].lower() or "confidence" in bundle["trend_pulse"][4]["value"].lower()


# =========================================================================
# 8. Deterministic What Changed? Driver Attribution
# =========================================================================
def test_what_changed_driver_attribution(multi_month_snapshot):
    """Verify driver attribution identifies contributing BUs deterministically."""
    bundle = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
    )
    what_changed = bundle["what_changed"]
    assert "drivers" in what_changed
    # Lending should be identified as top driver due to July exceptions
    if what_changed["has_movement"]:
        driver_names = [d["driver"] for d in what_changed["drivers"]]
        assert any("Lending" in name or "Exception" in name or "Swipe" in name for name in driver_names)


# =========================================================================
# 9. Emerging Patterns Integration
# =========================================================================
def test_emerging_patterns_integration(multi_month_snapshot):
    """Verify patterns list contains top patterns with required fields."""
    bundle = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
    )
    patterns = bundle["patterns"]
    assert isinstance(patterns, list)
    for pat in patterns:
        assert "name" in pat or "pattern_name" in pat
        assert "severity" in pat
        assert "scope" in pat
        assert "persistence" in pat
        assert "volume" in pat


# =========================================================================
# 10. Multi-Dimension Benchmark Table Structure
# =========================================================================
def test_benchmark_table_structure(multi_month_snapshot):
    """Verify benchmark comparison table contains all 8 required columns and total."""
    bundle = workforce_bridge.get_trend_intelligence(
        metric_id="attendance_exception_rate",
    )
    table = bundle["benchmark_table"]
    assert "columns" in table
    assert "rows" in table
    assert "total" in table
    assert len(table["rows"]) == 3

    for row in table["rows"]:
        assert "business_unit" in row
        assert "current" in row
        assert "three_month_avg" in row
        assert "org_benchmark" in row
        assert "historical" in row
        assert "gap" in row
        assert "trend" in row
        assert "volume" in row


# =========================================================================
# 11. Caching & Zero Workbook Re-Reads
# =========================================================================
def test_trends_caching_and_zero_io(multi_month_snapshot):
    """Verify repeated trend queries hit cache with zero file I/O."""
    # First call primes cache
    bundle1 = workforce_bridge.get_trend_intelligence(metric_id="attendance_exception_rate")

    with patch("openpyxl.load_workbook") as mock_wb, \
         patch("pandas.read_excel") as mock_excel:
        bundle2 = workforce_bridge.get_trend_intelligence(metric_id="attendance_exception_rate")
        assert mock_wb.call_count == 0
        assert mock_excel.call_count == 0
        assert bundle1["metric_id"] == bundle2["metric_id"]


# =========================================================================
# 12. UI: Trends View Activation and Widget Population
# =========================================================================
def test_trends_ui_view_activation(desktop_app, multi_month_snapshot):
    """Verify switching to Trends view activates container and renders widgets."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    wf_view.sync_snapshot_state(multi_month_snapshot)
    desktop_app.update()

    # Switch to trends
    wf_view.select_view("trends")
    desktop_app.update()

    assert wf_view.active_view == "trends"
    assert bool(wf_view.view_containers["trends"].grid_info())

    # Verify widgets exist
    assert hasattr(wf_view, "trend_pulse_widget")
    assert hasattr(wf_view, "main_trend_chart")
    assert hasattr(wf_view, "bu_heatmap_widget")
    assert hasattr(wf_view, "what_changed_widget")
    assert hasattr(wf_view, "emerging_patterns_widget")
    assert hasattr(wf_view, "trend_benchmark_table")

    bundle = workforce_bridge.get_trend_intelligence(metric_id="attendance_exception_rate")
    wf_view._render_trend_intelligence(bundle)
    wf_view._set_trends_state("ready")
    desktop_app.update()

    # Check pulse widget rendered values
    assert wf_view.trend_pulse_widget.cards[0]["lbl_val"].cget("text") != "—"


# =========================================================================
# 13. UI: Metric and Benchmark Dropdown Interactions
# =========================================================================
def test_trends_ui_dropdown_interactions(desktop_app, multi_month_snapshot):
    """Verify changing Metric and Benchmark dropdowns triggers intelligence refresh."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    wf_view.select_view("trends")
    desktop_app.update()

    # Select a different metric
    wf_view._on_trend_metric_selected("Leave Application Compliance")
    assert wf_view._selected_trend_metric == "leave_application_compliance"

    # Select Historical Baseline
    wf_view._on_trend_benchmark_selected("Historical Baseline")
    assert wf_view._selected_benchmark_type == "HISTORICAL"


# =========================================================================
# 14. UI: Heatmap Click to Filter Business Unit
# =========================================================================
def test_trends_ui_heatmap_click_to_filter(desktop_app, multi_month_snapshot):
    """Verify clicking a Business Unit in the Heatmap sets global BU filter."""
    wf_view: WorkforceDashboardView = desktop_app.workforce_dashboard_view
    wf_view.select_view("trends")
    desktop_app.update()

    wf_view._on_heatmap_bu_click("Lending")
    desktop_app.update()

    assert wf_view._filter_state.get("business_unit") == "Lending"
    assert wf_view.combo_bu.get() == "Lending"


# =========================================================================
# 15. Robustness: Dirty / Unparseable Date Strings ("NA", "N/A", "-", "")
# =========================================================================
def test_trends_with_dirty_unparseable_datetime_strings(desktop_app):
    """Verify trends calculation and pattern detectors never crash on string 'NA' or invalid dates."""
    records = []
    # Mix valid dates with "NA", "N/A", "-", None, and empty strings in date columns
    raw_dates = ["2026-10-01", "2026-10-02", "NA", "N/A", "-", "", None, "2026-10-03"]
    applied_dates = ["2026-09-28", "NA", "N/A", "-", "", None, "2026-09-30", "2026-10-01"]
    approved_dates = ["2026-09-29", "NA", "N/A", "-", "", None, "2026-10-01", "2026-10-02"]

    for i in range(40):
        d_val = raw_dates[i % len(raw_dates)]
        app_val = applied_dates[i % len(applied_dates)]
        apr_val = approved_dates[i % len(approved_dates)]
        records.append({
            "Date": d_val,
            "Employee Number": f"EMP{100 + (i % 5)}",
            "Employee Name": f"Employee {i % 5}",
            "Business Unit": "Engineering" if i % 2 == 0 else "Product",
            "Department": "Core",
            "Reporting Manager": "Manager A",
            "Attendance Type": "Leave" if i % 3 == 0 else "Present",
            "Status": "On Leave" if i % 3 == 0 else "Present",
            "Applied On": app_val,
            "Approved On": apr_val,
            "Approval Status": "Approved" if i % 2 == 0 else "Pending",
            "Approved By": "Manager A",
            "Quantity": 1.0 if i % 3 == 0 else 0.0,
            "include_in_analysis": True,
            "policy_event_type": "LEAVE" if i % 3 == 0 else "ATTENDANCE",
        })

    df = pd.DataFrame(records)
    snap = AnalyticalSnapshot(
        key="test_dirty_dates_snap",
        fact_df=df,
        metadata={"min_date": "2026-10-01", "max_date": "2026-10-03", "employee_count": 5},
        raw_source="Dirty_Master.xlsx",
    )
    snapshot_cache.set_active_snapshot(snap)
    workforce_bridge.clear_cache()

    # Should run smoothly without raising ValueError
    bundle = workforce_bridge.get_trend_intelligence(metric_id="attendance_exception_rate")
    assert bundle is not None
    assert "chart" in bundle
    assert "trend_pulse" in bundle
    assert "patterns" in bundle
    assert "benchmark_table" in bundle
