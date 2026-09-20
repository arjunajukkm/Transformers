"""
scripts/benchmark_data_foundation_memory.py
───────────────────────────────────────────
Performance and Memory Benchmark for Transformers 2.0 — Phase 3A:
Unified Workforce Data Foundation attached to AnalyticalSnapshot.

Measures:
 1. Comparable snapshot preparation times: Phase 2B baseline vs. Phase 3A integrated.
 2. Memory measurements distinguishing:
    - Ingested DataFrame deep memory (fact_df.memory_usage(deep=True))
    - Active snapshot object-graph deep memory (deep_getsizeof(snapshot))
    - Total Python process Working Set memory (RSS) via Windows kernel API
 3. Investigation of raw_dataframe memory ownership and reference sharing.
 4. Retrieval latencies for dashboard metrics and breakdowns.
 5. Scaled 5,000-record dataset observed performance and scaling ratios.
"""

import ctypes
from ctypes import wintypes
from dataclasses import is_dataclass
import gc
import os
from pathlib import Path
import sys
import time
from typing import Any, Set

import numpy as np
import pandas as pd

# Set up project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from storage import snapshot_service
from storage.cache_manager import AnalyticalSnapshot
from workforce_intelligence.data_foundation import CanonicalWorkforceData
import time_series_analysis as tsa


# ─────────────────────────────────────────────────────────────────────────────
# Windows Process Memory Measurement (RSS) via ctypes
# ─────────────────────────────────────────────────────────────────────────────
class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t),
    ]


def get_process_working_set_mb() -> float:
    """Retrieve actual process Working Set (RSS) in Megabytes via Windows API."""
    try:
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def deep_getsizeof(obj: Any, seen: Set[int] = None) -> int:
    """Recursively calculate deep memory footprint of an in-memory Python object."""
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)

    size = sys.getsizeof(obj, 0)

    if isinstance(obj, pd.DataFrame):
        return int(obj.memory_usage(deep=True).sum())
    elif isinstance(obj, pd.Series):
        return int(obj.memory_usage(deep=True))
    elif isinstance(obj, dict):
        size += sum(deep_getsizeof(k, seen) + deep_getsizeof(v, seen) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set, frozenset)):
        size += sum(deep_getsizeof(i, seen) for i in obj)
    elif is_dataclass(obj):
        for field_name in obj.__dataclass_fields__:
            val = getattr(obj, field_name)
            size += deep_getsizeof(val, seen)
    elif hasattr(obj, "__dict__"):
        size += deep_getsizeof(obj.__dict__, seen)

    return size


def generate_synthetic_dataset(file_path: Path, num_employees: int = 50, num_days: int = 30):
    """Generates synthetic workforce dataset with given dimensions."""
    np.random.seed(42)
    emp_ids = [f"EMP{i:03d}" for i in range(1, num_employees + 1)]
    emp_names = [f"Employee {i}" for i in range(1, num_employees + 1)]
    bus = ["Engineering", "Product", "Operations", "Sales", "HR"]
    depts = ["Backend", "Frontend", "QA", "Enterprise Sales", "Talent"]
    rms = [f"Manager {i}" for i in range(1, 10)]
    dates = pd.date_range("2026-09-01", periods=num_days)

    synth_rows = []
    for d in dates:
        d_str = d.strftime("%Y-%m-%d")
        for i in range(num_employees):
            emp_id = emp_ids[i]
            emp_name = emp_names[i]
            bu = bus[i % len(bus)]
            dept = depts[i % len(depts)]
            rm = rms[i % len(rms)]

            rnd = np.random.rand()
            if rnd < 0.80:
                att_type = "Present"
                status = "P"
                in_time = "09:15"
                out_time = "18:45"
                leave_name = "-"
                app_by, app_on, appr_by, appr_on = "NA", "NA", "NA", "NA"
            elif rnd < 0.90:
                att_type = "Work From Home"
                status = "WFH"
                in_time = "NA"
                out_time = "NA"
                leave_name = "-"
                app_by, app_on, appr_by, appr_on = "Employee", d_str, "Manager", d_str
            elif rnd < 0.95:
                att_type = "Leave"
                status = "CL"
                in_time = "NA"
                out_time = "NA"
                leave_name = "Casual Leave"
                app_by, app_on, appr_by, appr_on = "Employee", d_str, "Manager", d_str
            else:
                att_type = "Regularized"
                status = "AR"
                in_time = "09:30"
                out_time = "18:30"
                leave_name = "-"
                app_by, app_on, appr_by, appr_on = "Employee", d_str, "Manager", d_str

            synth_rows.append({
                "Employee Number": emp_id,
                "Employee Name": emp_name,
                "Business Unit": bu,
                "Department": dept,
                "Reporting Manager": rm,
                "Date": d_str,
                "Month": d.strftime("%b %Y"),
                "Attendance Type": att_type,
                "Status": status,
                "In Time": in_time,
                "Out Time": out_time,
                "Leave Name": leave_name,
                "Quantity": 1.0,
                "Applied By": app_by,
                "Applied On": app_on,
                "Approved By": appr_by,
                "Approved On": appr_on,
            })

    df = pd.DataFrame(synth_rows)
    df.to_excel(file_path, index=False)
    return file_path, len(df), num_employees


def run_benchmark():
    print("=" * 78)
    print("TRANSFORMERS 2.0 — STEP 12: DATA ACCURACY, PERFORMANCE & INTEGRITY BENCHMARK")
    print("=" * 78)

    data_dir = PROJECT_ROOT / "local_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bench_file_1500 = data_dir / "benchmark_1500_records.xlsx"
    bench_file_5000 = data_dir / "benchmark_5000_records.xlsx"

    print("\n[Step 1] Verifying benchmark datasets...")
    if not bench_file_1500.exists():
        generate_synthetic_dataset(bench_file_1500, num_employees=50, num_days=30)
    print(f"  ✓ Standard dataset: {bench_file_1500.name} (1,500 rows, 50 employees)")

    if not bench_file_5000.exists():
        generate_synthetic_dataset(bench_file_5000, num_employees=100, num_days=50)
    print(f"  ✓ Scaled dataset:   {bench_file_5000.name} (5,000 rows, 100 employees)")

    # ─────────────────────────────────────────────────────────────────────────
    # Benchmark 1: Comparable Standard 1,500-Record Dataset Analysis
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 78)
    print("TEST 1: Standard 1,500-Record Dataset Stage-by-Stage Performance")
    print("-" * 78)

    gc.collect()
    rss_before_1500 = get_process_working_set_mb()

    # Stage 1: Excel read & normalization (load_time_series_dataset)
    t0 = time.perf_counter()
    fact_df = tsa.load_time_series_dataset(str(bench_file_1500))
    t_stage1_load = time.perf_counter() - t0

    # Stage 2: Filter options & period extraction
    t0 = time.perf_counter()
    bus = sorted([str(x) for x in fact_df["_bu"].dropna().unique() if str(x).strip() not in ("", "nan", "None")])
    depts = sorted([str(x) for x in fact_df["_dept"].dropna().unique() if str(x).strip() not in ("", "nan", "None")])
    rms = sorted([str(x) for x in fact_df["_rm"].dropna().unique() if str(x).strip() not in ("", "nan", "None", "Unknown")])
    months = sorted([str(x) for x in fact_df["_month_clean"].dropna().unique() if str(x).strip() not in ("", "nan", "None")])
    t_stage2_meta = time.perf_counter() - t0

    # Stage 3: Time Series standard metrics computation
    t0 = time.perf_counter()
    metrics = tsa.compute_time_series_metrics(fact_df)
    t_stage3_metrics = time.perf_counter() - t0

    # Stage 4: 4-Level drilldown breakdowns (BU, Dept, Manager, Employee)
    t0 = time.perf_counter()
    bk_bu = tsa.compute_level_breakdown(fact_df, level="Business Unit")
    bk_dept = tsa.compute_level_breakdown(fact_df, level="Department")
    bk_rm = tsa.compute_level_breakdown(fact_df, level="Reporting Manager")
    bk_emp = tsa.compute_level_breakdown(fact_df, level="Employee")
    t_stage4_breakdowns = time.perf_counter() - t0

    # Phase 2B equivalent total (Stages 1-4 without data foundation)
    t_phase2b_equivalent = t_stage1_load + t_stage2_meta + t_stage3_metrics + t_stage4_breakdowns

    # Stage 5: Canonical Workforce Data Foundation Construction
    t0 = time.perf_counter()
    foundation_obj = CanonicalWorkforceData.from_dataframe(fact_df, source_file_name=str(bench_file_1500))
    t_stage5_foundation = time.perf_counter() - t0

    # Phase 3A total (Stages 1-5 integrated)
    t_phase3a_total = t_phase2b_equivalent + t_stage5_foundation

    # End-to-end active snapshot via service
    snapshot_service.clear()
    gc.collect()
    t0 = time.perf_counter()
    snapshot = snapshot_service.prepare_dataset(str(bench_file_1500))
    t_service_prepare = time.perf_counter() - t0

    rss_after_1500 = get_process_working_set_mb()

    # Memory measurements
    mem_fact_df = fact_df.memory_usage(deep=True).sum()
    mem_snapshot_complete = deep_getsizeof(snapshot)
    mem_foundation_alone = deep_getsizeof(snapshot.workforce_foundation)

    print(f"\n1. Stage-by-Stage Processing Latencies (1,500 records):")
    print(f"   • Stage 1: Excel read & normalization (single disk read): {t_stage1_load*1000:.1f} ms ({t_stage1_load:.4f}s)")
    print(f"   • Stage 2: Dimension & filter options extraction:       {t_stage2_meta*1000:.1f} ms ({t_stage2_meta:.4f}s)")
    print(f"   • Stage 3: Organization-wide standard KPI metrics:      {t_stage3_metrics*1000:.1f} ms ({t_stage3_metrics:.4f}s)")
    print(f"   • Stage 4: 4 Level breakdowns (BU, Dept, RM, Emp):      {t_stage4_breakdowns*1000:.1f} ms ({t_stage4_breakdowns:.4f}s)")
    print(f"   ----------------------------------------------------------------------")
    print(f"   • Phase 2B Baseline Equivalent (Stages 1-4):            {t_phase2b_equivalent*1000:.1f} ms ({t_phase2b_equivalent:.4f}s)")
    print(f"   • Stage 5: Canonical Data Foundation (optimized):       {t_stage5_foundation*1000:.1f} ms ({t_stage5_foundation:.4f}s)")
    print(f"   ----------------------------------------------------------------------")
    print(f"   • Phase 3A End-to-End Pipeline (Stages 1-5):            {t_phase3a_total*1000:.1f} ms ({t_phase3a_total:.4f}s)")
    print(f"   • snapshot_service.prepare_dataset() measured:          {t_service_prepare*1000:.1f} ms ({t_service_prepare:.4f}s)")

    print(f"\n2. Memory Measurements (1,500 records):")
    print(f"   • Ingested DataFrame deep memory (fact_df):             {mem_fact_df / 1024:.1f} KB ({mem_fact_df / (1024*1024):.2f} MB)")
    print(f"   • Active AnalyticalSnapshot object graph:               {mem_snapshot_complete / 1024:.1f} KB ({mem_snapshot_complete / (1024*1024):.2f} MB)")
    print(f"   • Canonical Foundation alone (entities + indexes):      {mem_foundation_alone / 1024:.1f} KB ({mem_foundation_alone / (1024*1024):.2f} MB)")
    print(f"   • Python Process Working Set (RSS):                     {rss_after_1500:.2f} MB (delta: +{rss_after_1500 - rss_before_1500:.2f} MB)")

    # Shared DataFrame check
    is_shared = (snapshot.fact_df is snapshot.workforce_foundation.raw_dataframe)
    print(f"\n3. Shared DataFrame Safety & Reference Check:")
    print(f"   • snapshot.fact_df is foundation.raw_dataframe:         {is_shared} (id: {id(snapshot.fact_df)})")
    print(f"   • Unnecessary duplicate copy avoided:                   {'YES — Zero duplicated memory' if is_shared else 'NO'}")

    # Retrieval times
    t0 = time.perf_counter()
    m_val = snapshot_service.get_dashboard_metrics()
    t_get_metrics = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    bk_val = snapshot_service.get_breakdown("Employee")
    t_get_breakdown = (time.perf_counter() - t0) * 1000

    print(f"\n4. Dashboard Retrieval Times:")
    print(f"   • get_dashboard_metrics():                              {t_get_metrics:.4f} ms")
    print(f"   • get_breakdown('Employee'):                            {t_get_breakdown:.4f} ms")

    # ─────────────────────────────────────────────────────────────────────────
    # Benchmark 2: Scaled 5,000-Record Dataset
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 78)
    print("TEST 2: Scaled 5,000-Record Dataset Observed Performance")
    print("-" * 78)

    snapshot_service.clear()
    gc.collect()
    rss_before_5k = get_process_working_set_mb()

    t0 = time.perf_counter()
    snapshot_5k = snapshot_service.prepare_dataset(str(bench_file_5000))
    t_prep_5k = time.perf_counter() - t0

    rss_after_5k = get_process_working_set_mb()

    mem_df_5k = snapshot_5k.fact_df.memory_usage(deep=True).sum()
    mem_snapshot_5k = deep_getsizeof(snapshot_5k)
    wf_5k = snapshot_5k.workforce_foundation
    mem_wf_5k = deep_getsizeof(wf_5k)

    print(f"   • Total Snapshot Preparation (5,000 records):           {t_prep_5k:.4f}s ({t_prep_5k*1000:.1f} ms)")
    print(f"   • Ingested DataFrame deep memory:                       {mem_df_5k / 1024:.1f} KB ({mem_df_5k / (1024*1024):.2f} MB)")
    print(f"   • Active AnalyticalSnapshot object graph:               {mem_snapshot_5k / 1024:.1f} KB ({mem_snapshot_5k / (1024*1024):.2f} MB)")
    print(f"   • Canonical Foundation alone (entities + indexes):      {mem_wf_5k / 1024:.1f} KB ({mem_wf_5k / (1024*1024):.2f} MB)")
    print(f"   • Python Process Working Set (RSS):                     {rss_after_5k:.2f} MB (delta: +{rss_after_5k - rss_before_5k:.2f} MB)")
    print(f"   • Entities Generated:")
    print(f"     - Employees:          {len(wf_5k.employees)}")
    print(f"     - Attendance Records: {len(wf_5k.attendance_records)}")
    print(f"     - Workforce Requests: {len(wf_5k.requests)}")
    print(f"     - Employee Day Facts: {len(wf_5k.employee_day_facts)}")

    ratio_rows = 5000 / 1500
    ratio_time = t_prep_5k / t_service_prepare
    ratio_mem = mem_snapshot_5k / mem_snapshot_complete
    print(f"\n5. Observed Scaling Ratio (5,000 records vs 1,500 records):")
    print(f"   • Dataset size increase:                                {ratio_rows:.2f}x (3.33x records)")
    print(f"   • Observed preparation time ratio:                      {ratio_time:.2f}x")
    print(f"   • Observed snapshot deep-memory ratio:                  {ratio_mem:.2f}x")
    print(f"   • Note: Measurements reflect observed scaling between the two test points.")

    snapshot_service.clear()
    print("\n" + "=" * 78)
    print("BENCHMARK COMPLETED SUCCESSFULLY")
    print("=" * 78)


if __name__ == "__main__":
    run_benchmark()
