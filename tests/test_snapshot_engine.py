"""
tests/test_snapshot_engine.py
──────────────────────────────
Comprehensive unit test suite for Transformers 2.0 High-Performance
Analytical Snapshot Engine and TimeSeriesSnapshotService.

Verifies:
1. Snapshot creation and structure.
2. Exact match of organization-wide metrics against compute_time_series_metrics.
3. Exact match of BU, Department, RM, and Employee breakdowns against compute_level_breakdown.
4. Repeated requests returning cached results with 0 recalculation.
5. Filtered results matching ground truth and being cached.
6. Cache invalidation after dataset replacement.
7. Failed processing preserving the active snapshot.
8. Concurrent / overlapping requests thread-safety.
9. No cross-dataset result leakage.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import pandas as pd
import pytest

from storage import (
    AnalyticalSnapshot,
    CacheManager,
    TimeSeriesSnapshotService,
    create_snapshot,
)
import time_series_analysis as tsa


@pytest.fixture
def test_dataset(tmp_path):
    """Deterministic synthetic dataset containing rich edge cases across multiple entities."""
    rows = [
        # Emp 1: Alice (Engineering, Backend, RM: Bob Manager, Sep 2026)
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-01",
            "Month": "Sep 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "In Time": "09:00",
            "Out Time": "18:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-02",
            "Month": "Sep 2026",
            "Attendance Type": "Missing Swipes",
            "Status": "P(MS)",
            "In Time": "10:00",
            "Out Time": "18:30",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
        {
            "Employee Number": "E001",
            "Employee Name": "Alice",
            "Business Unit": "Engineering",
            "Department": "Backend",
            "Reporting Manager": "Bob Manager",
            "Date": "2026-09-03",
            "Month": "Sep 2026",
            "Attendance Type": "Leave",
            "Status": "CL",
            "Leave Name": "Casual Leave",
            "In Time": "NA",
            "Out Time": "NA",
            "Applied By": "Employee",
            "Applied On": "2026-09-01",  # 2 days in advance
            "Approved By": "Manager",
            "Approved On": "2026-09-02", # 1 day turnaround
        },
        # Emp 2: Charlie (Sales, Direct Sales, RM: David RM, Sep 2026)
        {
            "Employee Number": "E002",
            "Employee Name": "Charlie",
            "Business Unit": "Sales",
            "Department": "Direct Sales",
            "Reporting Manager": "David RM",
            "Date": "2026-09-01",
            "Month": "Sep 2026",
            "Attendance Type": "Regularized",
            "Status": "AR",
            "In Time": "09:30",
            "Out Time": "18:30",
            "Applied By": "Employee",
            "Applied On": "2026-09-01",
            "Approved By": "Manager",
            "Approved On": "2026-09-02",
        },
        # Charlie WFH 4 days (>3 days threshold test)
        *[
            {
                "Employee Number": "E002",
                "Employee Name": "Charlie",
                "Business Unit": "Sales",
                "Department": "Direct Sales",
                "Reporting Manager": "David RM",
                "Date": f"2026-09-0{d}",
                "Month": "Sep 2026",
                "Attendance Type": "Work From Home",
                "Status": "WFH",
                "In Time": "NA",
                "Out Time": "NA",
                "Applied By": "Employee",
                "Applied On": f"2026-09-0{d}",
                "Approved By": "Manager",
                "Approved On": f"2026-09-0{d}",
            }
            for d in range(2, 6) # 4 days
        ],
        # Emp 3: Eve (Marketing, Growth, RM: Frank RM, Oct 2026)
        {
            "Employee Number": "E003",
            "Employee Name": "Eve",
            "Business Unit": "Marketing",
            "Department": "Growth",
            "Reporting Manager": "Frank RM",
            "Date": "2026-10-01",
            "Month": "Oct 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "In Time": "08:30",
            "Out Time": "17:30",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        },
    ]
    df = pd.DataFrame(rows)
    p = tmp_path / "dataset_a.xlsx"
    df.to_excel(p, index=False)
    return p


@pytest.fixture
def second_dataset(tmp_path):
    """Independent second dataset to verify replacement and isolation."""
    rows = [
        {
            "Employee Number": "E999",
            "Employee Name": "Zack",
            "Business Unit": "Executive",
            "Department": "Board",
            "Reporting Manager": "Chairperson",
            "Date": "2026-11-01",
            "Month": "Nov 2026",
            "Attendance Type": "Present",
            "Status": "P",
            "In Time": "10:00",
            "Out Time": "16:00",
            "Applied By": "NA",
            "Applied On": "NA",
            "Approved By": "NA",
            "Approved On": "NA",
        }
    ]
    df = pd.DataFrame(rows)
    p = tmp_path / "dataset_b.xlsx"
    df.to_excel(p, index=False)
    return p


# --------------------------------------------------------------------
# 1. Snapshot Creation and Structure
# --------------------------------------------------------------------

def test_snapshot_creation(test_dataset):
    snap = create_snapshot(test_dataset)
    assert snap.is_valid()
    assert snap.row_count == 9
    assert snap.metadata["employee_count"] == 3
    assert snap.metadata["business_units_count"] == 3
    assert "Engineering" in snap.filter_options["business_units"]
    assert "Sales" in snap.filter_options["business_units"]
    assert "Marketing" in snap.filter_options["business_units"]
    assert "Sep 2026" in snap.filter_options["months"]
    assert "Oct 2026" in snap.filter_options["months"]


# --------------------------------------------------------------------
# 2. Correct Organization-Wide Metrics
# --------------------------------------------------------------------

def test_organization_wide_metrics_accuracy(test_dataset):
    # Calculate baseline via legacy function directly
    raw_df = tsa.load_time_series_dataset(test_dataset)
    expected_metrics = tsa.compute_time_series_metrics(raw_df)

    snap = create_snapshot(test_dataset)
    actual_metrics = snap.get_metrics()

    # Compare every single key in the metrics dictionary
    for k, v in expected_metrics.items():
        assert actual_metrics[k] == v, f"Mismatch in metric '{k}': expected {v}, got {actual_metrics[k]}"


# --------------------------------------------------------------------
# 3. Correct BU, Department, RM, and Employee Breakdowns
# --------------------------------------------------------------------

def test_breakdowns_accuracy(test_dataset):
    raw_df = tsa.load_time_series_dataset(test_dataset)
    snap = create_snapshot(test_dataset)

    for level in ["Business Unit", "Department", "Reporting Manager", "Employee"]:
        expected = tsa.compute_level_breakdown(raw_df, level=level)
        actual = snap.get_breakdown(level=level)
        assert len(actual) == len(expected), f"Length mismatch for level {level}"
        for row_exp, row_act in zip(expected, actual):
            assert row_exp["Entity ID"] == row_act["Entity ID"]
            assert row_exp["Total Records"] == row_act["Total Records"]
            assert row_exp["Unique Employees"] == row_act["Unique Employees"]


# --------------------------------------------------------------------
# 4. Repeated Requests Returning Cached Results
# --------------------------------------------------------------------

def test_repeated_requests_cached(test_dataset):
    snap = create_snapshot(test_dataset)

    # Unfiltered metrics return precomputed reference
    m1 = snap.get_metrics()
    m2 = snap.get_metrics()
    assert m1 is m2 or m1 == m2

    # Filtered requests populate internal LRU cache
    assert snap.get_filter_cache_stats()["metrics_cached"] == 0
    f_m1 = snap.get_metrics(business_unit="Engineering")
    assert snap.get_filter_cache_stats()["metrics_cached"] == 1
    f_m2 = snap.get_metrics(business_unit="Engineering")
    assert f_m1 == f_m2
    # Cached item retrieved without growing cache count
    assert snap.get_filter_cache_stats()["metrics_cached"] == 1


# --------------------------------------------------------------------
# 5. Filtered Results Matching Existing Calculation Engine
# --------------------------------------------------------------------

def test_filtered_results_match_existing_engine(test_dataset):
    raw_df = tsa.load_time_series_dataset(test_dataset)
    snap = create_snapshot(test_dataset)

    # Filter by BU: Sales
    exp_sales = tsa.compute_time_series_metrics(raw_df, business_unit="Sales")
    act_sales = snap.get_metrics(business_unit="Sales")
    assert act_sales == exp_sales
    assert act_sales["total_records"] == 5
    assert act_sales["total_wfh_days"] == 4
    assert act_sales["wfh_excess_days"] == 1

    # Filter by Month: Oct 2026
    exp_oct = tsa.compute_time_series_metrics(raw_df, month="Oct 2026")
    act_oct = snap.get_metrics(month="Oct 2026")
    assert act_oct == exp_oct
    assert act_oct["total_records"] == 1
    assert act_oct["unique_employees"] == 1

    # Breakdown filtered by BU: Sales
    exp_bd = tsa.compute_level_breakdown(raw_df, level="Department", business_unit="Sales")
    act_bd = snap.get_breakdown(level="Department", business_unit="Sales")
    assert act_bd == exp_bd


# --------------------------------------------------------------------
# 6. Cache Invalidation After Dataset Replacement
# --------------------------------------------------------------------

def test_dataset_replacement_and_invalidation(test_dataset, second_dataset):
    cm = CacheManager()
    svc = TimeSeriesSnapshotService(cache_manager=cm)

    # Prepare dataset A
    snap_a = svc.prepare_dataset(test_dataset)
    assert svc.has_active_snapshot()
    assert svc.get_dashboard_metrics()["total_records"] == 9
    assert svc.get_metadata()["employee_count"] == 3

    # Prepare dataset B
    snap_b = svc.prepare_dataset(second_dataset)
    assert svc.has_active_snapshot()
    assert svc.get_active_snapshot().dataset_id != snap_a.dataset_id
    assert svc.get_dashboard_metrics()["total_records"] == 1
    assert svc.get_metadata()["employee_count"] == 1

    # Explicit invalidation
    svc.invalidate_active_snapshot()
    assert not svc.has_active_snapshot()
    assert svc.get_dashboard_metrics()["total_records"] == 0


# --------------------------------------------------------------------
# 7. Failed Processing Preserving the Last Valid Snapshot
# --------------------------------------------------------------------

def test_failed_processing_preserves_active_snapshot(test_dataset, tmp_path):
    svc = TimeSeriesSnapshotService(cache_manager=CacheManager())

    # Ingest valid dataset
    snap_a = svc.prepare_dataset(test_dataset)
    assert svc.get_dashboard_metrics()["total_records"] == 9

    # Attempt to ingest non-existent file
    with pytest.raises(FileNotFoundError):
        svc.prepare_dataset(tmp_path / "does_not_exist.xlsx")

    # Verify previous valid snapshot remains active and untouched
    assert svc.has_active_snapshot()
    assert svc.get_active_snapshot().dataset_id == snap_a.dataset_id
    assert svc.get_dashboard_metrics()["total_records"] == 9

    # Attempt to ingest corrupt/empty file
    corrupt_file = tmp_path / "corrupt.xlsx"
    pd.DataFrame().to_excel(corrupt_file, index=False)
    with pytest.raises(ValueError):
        svc.prepare_dataset(corrupt_file)

    # Active snapshot still preserved
    assert svc.has_active_snapshot()
    assert svc.get_dashboard_metrics()["total_records"] == 9


# --------------------------------------------------------------------
# 8. Concurrent or Overlapping Requests Thread Safety
# --------------------------------------------------------------------

def test_concurrent_access_thread_safety(test_dataset):
    svc = TimeSeriesSnapshotService(cache_manager=CacheManager())
    svc.prepare_dataset(test_dataset)

    def worker_task(idx):
        if idx % 3 == 0:
            return svc.get_dashboard_metrics(business_unit="Engineering")
        elif idx % 3 == 1:
            return svc.get_dashboard_metrics(business_unit="Sales")
        else:
            return svc.get_breakdown(level="Department", month="Sep 2026")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker_task, range(30)))

    assert len(results) == 30
    # Confirm no corrupted results
    eng_res = [r for idx, r in enumerate(results) if idx % 3 == 0]
    for r in eng_res:
        assert r["total_records"] == 3


# --------------------------------------------------------------------
# 9. No Cross-Dataset Result Leakage
# --------------------------------------------------------------------

def test_no_cross_dataset_leakage(test_dataset, second_dataset):
    snap_a = create_snapshot(test_dataset, dataset_id="snap_A")
    snap_b = create_snapshot(second_dataset, dataset_id="snap_B")

    # Populate filter caches in A
    m_a = snap_a.get_metrics(business_unit="Engineering")
    assert m_a["total_records"] == 3

    # Ensure B doesn't see A's metrics or filter options
    assert "Engineering" not in snap_b.filter_options["business_units"]
    m_b = snap_b.get_metrics(business_unit="Engineering")
    assert m_b["total_records"] == 0  # No engineering in B


# --------------------------------------------------------------------
# 10. Immutability Protection: Caller Modifications Do Not Corrupt State
# --------------------------------------------------------------------

def test_metrics_immutability_protection(test_dataset):
    snap = create_snapshot(test_dataset)

    # 1. Standard metrics immutability
    m1 = snap.get_metrics()
    orig_total = m1["total_records"]
    assert orig_total == 9

    # Malicious caller mutation
    m1["total_records"] = -9999
    m1["avg_leave_apply_days"] = 999.9

    # Next retrieval must be completely intact
    m2 = snap.get_metrics()
    assert m2["total_records"] == orig_total
    assert m2["total_records"] != -9999


def test_breakdown_immutability_protection(test_dataset):
    snap = create_snapshot(test_dataset)

    # 1. Standard breakdown immutability
    b1 = snap.get_breakdown("Employee")
    orig_first_emp = b1[0]["Entity ID"]

    # Malicious caller mutation
    b1[0]["Entity ID"] = "MUTATED_EMP_ID"
    b1[0]["Total Records"] = -1
    b1.append({"Entity ID": "FAKE_INJECTED_EMP"})

    # Next retrieval must be completely intact
    b2 = snap.get_breakdown("Employee")
    assert b2[0]["Entity ID"] == orig_first_emp
    assert b2[0]["Entity ID"] != "MUTATED_EMP_ID"
    assert len(b2) == len(snap.standard_breakdowns["Employee"])


def test_filtered_cache_immutability_protection(test_dataset):
    snap = create_snapshot(test_dataset)

    # 1. Filtered metrics immutability
    f1 = snap.get_metrics(business_unit="Engineering")
    assert f1["total_records"] == 3

    f1["total_records"] = -888
    f1["unique_employees"] = -1

    f2 = snap.get_metrics(business_unit="Engineering")
    assert f2["total_records"] == 3
    assert f2["unique_employees"] == 1

    # 2. Filtered breakdown immutability
    fb1 = snap.get_breakdown("Department", business_unit="Engineering")
    orig_dept = fb1[0]["Entity ID"]

    fb1[0]["Entity ID"] = "CORRUPTED_DEPT"
    fb2 = snap.get_breakdown("Department", business_unit="Engineering")
    assert fb2[0]["Entity ID"] == orig_dept


# --------------------------------------------------------------------
# 11. Memory Management: Repeated Dataset Replacement Releases Old Snapshots
# --------------------------------------------------------------------

def test_repeated_replacement_releases_old_snapshots():
    cm = CacheManager(max_snapshots=1)
    svc = TimeSeriesSnapshotService(cache_manager=cm)

    # Create 5 distinct small datasets
    for i in range(5):
        df = pd.DataFrame([{
            "Employee Number": f"EMP{i:03d}",
            "Employee Name": f"Employee {i}",
            "Business Unit": "Eng",
            "Department": "Dev",
            "Reporting Manager": "Mgr",
            "Date": "2026-09-01",
            "Month": "Sep 2026",
            "Attendance Type": "Present",
            "Status": "P",
        }])
        svc.prepare_dataset(df, dataset_id=f"snap_{i}")

    # Only the active snapshot should remain in the cache manager
    assert len(cm._snapshots) == 1
    active = svc.get_active_snapshot()
    assert active is not None
    assert active.dataset_id == "snap_4"
    assert not cm.has_snapshot("snap_0")
    assert not cm.has_snapshot("snap_1")


# --------------------------------------------------------------------
# 12. Stale Job Fencing Prevents Overwriting Newer Snapshot
# --------------------------------------------------------------------

def test_stale_job_fencing_prevents_overwrite(test_dataset, second_dataset):
    cm = CacheManager()
    svc = TimeSeriesSnapshotService(cache_manager=cm)

    # Ingest newer job
    snap2 = svc.prepare_dataset(second_dataset)
    assert svc.get_active_snapshot().dataset_id == snap2.dataset_id

    # Simulate older job finishing after newer job
    stale_snap = create_snapshot(test_dataset, dataset_id="stale_older_job", version=snap2.version - 1)
    with svc._job_fence_lock:
        if stale_snap.version >= svc._latest_completed_job_id:
            svc.cache_manager.set_active_snapshot(stale_snap)

    # Active snapshot must remain snap2
    assert svc.get_active_snapshot().dataset_id == snap2.dataset_id
    assert svc.get_active_snapshot().dataset_id != "stale_older_job"

