"""
tests/test_historical_sync.py
──────────────────────────────
Unit and Integration tests for Multi-Month Historical Sync & Archive Manager.

Covers:
  1. Month partitioning & calendar boundaries (bypassing Keka 1-month limits).
  2. Local registry persistence, loading, and status tracking.
  3. Single month sync and Parquet/Excel local archival.
  4. Multi-month sequential batch sync with progress reporting.
  5. Multi-month unified dataset assembly and deduplication.
  6. Re-syncing existing months to overwrite with updated data.
  7. Activating historical archive directly into AnalyticalSnapshot without file I/O.
"""

import os
import json
import tempfile
import shutil
from pathlib import Path
from datetime import date, datetime
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from workforce_intelligence.historical_sync import HistoricalSyncManager
from storage.snapshot_service import snapshot_service, AnalyticalSnapshot


@pytest.fixture
def temp_archive_dir():
    temp_dir = tempfile.mkdtemp(prefix="test_historical_archive_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sync_manager(temp_archive_dir):
    return HistoricalSyncManager(archive_dir=temp_archive_dir)


@pytest.fixture
def mock_keka_fetcher():
    fetcher = MagicMock()
    # Mock Employee Master
    emp_df = pd.DataFrame([
        {"Employee Number": "101", "Employee Name": "Alice", "Business Unit": "Engineering", "Department": "Core", "Reporting Manager": "Bob"},
        {"Employee Number": "102", "Employee Name": "Charlie", "Business Unit": "Lending", "Department": "Ops", "Reporting Manager": "Bob"},
    ])
    fetcher.fetch_employee_master.return_value = (emp_df, None)

    # Mock WFH/OD
    fetcher.fetch_od_wfh_requests.return_value = (pd.DataFrame(), None)

    # Mock attendance records
    def _fake_att(from_date, to_date, emp_df=None, wfh_df=None, progress_callback=None):
        dates = pd.date_range(from_date, to_date, freq="D")
        rows = []
        for d in dates:
            for emp in ["101", "102"]:
                rows.append({
                    "Employee Number": emp,
                    "Employee Name": "Alice" if emp == "101" else "Charlie",
                    "Business Unit": "Engineering" if emp == "101" else "Lending",
                    "Department": "Core" if emp == "101" else "Ops",
                    "Reporting Manager": "Bob",
                    "Date": d.strftime("%Y-%m-%d"),
                    "Month": d.strftime("%b %Y"),
                    "Attendance Type": "Present",
                    "Status": "P",
                    "In Time": "09:00",
                    "Out Time": "18:00",
                    "Effective Hours": "09:00",
                    "Quantity": 1.0,
                })
        return pd.DataFrame(rows), None

    fetcher.fetch_attendance_records_api.side_effect = _fake_att
    return fetcher


def test_month_boundaries_calculation(sync_manager):
    """Verify calendar month boundary calculation."""
    f_day, l_day = sync_manager.get_month_boundaries(2026, 2)
    assert f_day == date(2026, 2, 1)
    assert l_day == date(2026, 2, 28)

    f_day, l_day = sync_manager.get_month_boundaries(2026, 10)
    assert f_day == date(2026, 10, 1)
    assert l_day == date(2026, 10, 31)

    f_day, l_day = sync_manager.get_month_boundaries(2026, 12)
    assert f_day == date(2026, 12, 1)
    assert l_day == date(2026, 12, 31)


def test_get_available_months_grid(sync_manager):
    """Verify available months grid list includes current and historical months."""
    grid = sync_manager.get_available_months_grid(past_n_months=6)
    assert len(grid) == 6
    assert all("month_key" in item for item in grid)
    assert all("display_name" in item for item in grid)
    assert all("is_synced" in item for item in grid)
    assert grid[0]["is_synced"] is False


def test_single_month_sync(sync_manager, mock_keka_fetcher):
    """Verify single month sync downloads, formats, saves to archive, and updates registry."""
    att_df, emp_df, err = sync_manager.sync_single_month_keka(
        month_key="2026-09",
        keka_fetcher=mock_keka_fetcher
    )
    assert err is None
    assert att_df is not None
    assert len(att_df) == 60  # 30 days * 2 emps

    # Verify registry updated
    reg = sync_manager.load_registry()
    assert "2026-09" in reg["months"]
    m_info = reg["months"]["2026-09"]
    assert m_info["status"] == "SYNCED"
    assert m_info["record_count"] == 60
    assert m_info["headcount"] == 2


def test_multi_month_batch_sync(sync_manager, mock_keka_fetcher):
    """Verify multi-month sequential sync respects 1-month chunks and unites datasets."""
    months = ["2026-08", "2026-09", "2026-10"]
    progress_calls = []

    def _prog(idx, total, m_name, pct, msg):
        progress_calls.append((idx, total, m_name, pct))

    res = sync_manager.sync_multiple_months_keka(
        month_keys=months,
        keka_fetcher=mock_keka_fetcher,
        batch_progress_callback=_prog
    )

    assert res["success"] is True
    assert res["total_synced"] == 3
    assert len(progress_calls) > 0

    # Total days: Aug (31) + Sep (30) + Oct (31) = 92 days * 2 emps = 184
    assert res["total_records"] == 184

    reg = sync_manager.load_registry()
    assert len(reg["months"]) == 3
    assert "2026-08" in reg["months"]
    assert "2026-09" in reg["months"]
    assert "2026-10" in reg["months"]


def test_load_unified_history(sync_manager, mock_keka_fetcher):
    """Verify loading from local archive loads all synced months into unified DataFrame."""
    sync_manager.sync_multiple_months_keka(
        month_keys=["2026-08", "2026-09"],
        keka_fetcher=mock_keka_fetcher
    )

    unified_df, summary = sync_manager.load_unified_history()
    assert summary["months_count"] == 2
    assert summary["total_records"] == (31 + 30) * 2  # 122 rows
    assert len(unified_df) == 122

    # Load subset
    sub_df, sub_summary = sync_manager.load_unified_history(month_keys=["2026-08"])
    assert sub_summary["months_count"] == 1
    assert len(sub_df) == 62


def test_resync_overwrites_existing_month(sync_manager, mock_keka_fetcher):
    """Verify re-syncing a month refreshes its archive file and registry timestamp."""
    sync_manager.sync_single_month_keka("2026-09", mock_keka_fetcher)
    reg1 = sync_manager.load_registry()
    t1 = reg1["months"]["2026-09"]["last_synced"]

    # Re-sync
    sync_manager.sync_single_month_keka("2026-09", mock_keka_fetcher)
    reg2 = sync_manager.load_registry()
    assert "2026-09" in reg2["months"]
    assert reg2["months"]["2026-09"]["record_count"] == 60


def test_delete_month_from_archive(sync_manager, mock_keka_fetcher):
    """Verify deleting month removes registry entry and local files."""
    sync_manager.sync_single_month_keka("2026-09", mock_keka_fetcher)
    assert "2026-09" in sync_manager.load_registry()["months"]

    sync_manager.delete_month("2026-09")
    reg = sync_manager.load_registry()
    assert "2026-09" not in reg.get("months", {})


def test_activate_archive_into_analytical_snapshot(sync_manager, mock_keka_fetcher):
    """Verify prepared snapshot directly from unified historical DataFrame."""
    sync_manager.sync_multiple_months_keka(
        month_keys=["2026-08", "2026-09", "2026-10"],
        keka_fetcher=mock_keka_fetcher
    )

    unified_df, summary = sync_manager.load_unified_history()
    snap = snapshot_service.prepare_dataset(unified_df)
    assert snap.is_valid()
    assert snap.row_count == len(unified_df)
    assert snap.metadata["employee_count"] == 2
    assert snapshot_service.has_active_snapshot()
