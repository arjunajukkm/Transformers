"""
scripts/benchmark_snapshot_engine.py
────────────────────────────────────
Empirical benchmark for Transformers 2.0 Phase 2A Analytical Snapshot Engine.

Measures:
1. Dataset ingestion time.
2. Snapshot preparation time (normalization + precomputing standard KPIs & 4 breakdowns).
3. Organization-wide metrics retrieval (unfiltered).
4. Employee-level breakdown retrieval (unfiltered: precomputed snapshot vs Phase 1 baseline).
5. Repeat retrieval of an already prepared result.
6. First-time filtered calculation.
7. Repeat retrieval of the same filtered result (LRU cache hit).
8. Cache memory usage.

Evaluates against:
- Representative local dataset (11 records)
- Scaled synthetic dataset (1,500 records across 50 employees, 30 days)
"""

import os
import sys
import time
import tracemalloc
from pathlib import Path
import numpy as np
import pandas as pd

# Reconfigure stdout for utf-8 on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from storage import (
    AnalyticalSnapshot,
    CacheManager,
    TimeSeriesSnapshotService,
    create_snapshot,
)
import time_series_analysis as tsa


def generate_synthetic_dataset(num_employees: int = 50, days: int = 30) -> pd.DataFrame:
    """Generate deterministic synthetic attendance dataset for scaled benchmarking."""
    np.random.seed(42)
    emp_ids = [f"EMP{i:03d}" for i in range(1, num_employees + 1)]
    emp_names = [f"Employee {i}" for i in range(1, num_employees + 1)]
    bus = ["Engineering", "Product", "Operations", "Sales", "HR"]
    depts = ["Backend", "Frontend", "QA", "Enterprise Sales", "Talent"]
    rms = [f"Manager {i}" for i in range(1, 10)]

    rows = []
    for day in range(1, days + 1):
        dt_str = f"2026-09-{day:02d}"
        for i in range(num_employees):
            emp_id = emp_ids[i]
            emp_name = emp_names[i]
            bu = bus[i % len(bus)]
            dept = depts[i % len(depts)]
            rm = rms[i % len(rms)]

            rand = np.random.rand()
            if rand < 0.70:
                att_type = "Present"
                status = "P"
                in_time = f"{8 + np.random.randint(0, 2):02d}:{np.random.randint(0, 60):02d}"
                out_time = f"{17 + np.random.randint(0, 2):02d}:{np.random.randint(0, 60):02d}"
                applied_by, applied_on = "NA", "NA"
                approved_by, approved_on = "NA", "NA"
            elif rand < 0.80:
                att_type = "Work From Home"
                status = "WFH"
                in_time, out_time = "NA", "NA"
                applied_by = "Employee"
                applied_on = dt_str
                approved_by = "Manager"
                approved_on = dt_str
            elif rand < 0.90:
                att_type = "Missing Swipes"
                status = "P(MS)"
                in_time = "10:00"
                out_time = "18:30"
                applied_by, applied_on = "NA", "NA"
                approved_by, approved_on = "NA", "NA"
            elif rand < 0.95:
                att_type = "Leave"
                status = "CL"
                in_time, out_time = "NA", "NA"
                applied_by = "Employee"
                applied_on = f"2026-08-{np.random.randint(20, 31):02d}"
                approved_by = "Manager"
                approved_on = f"2026-09-01"
            else:
                att_type = "Regularized"
                status = "AR"
                in_time = "09:30"
                out_time = "18:30"
                applied_by = "Employee"
                applied_on = dt_str
                approved_by = "Manager"
                approved_on = dt_str

            rows.append({
                "Employee Number": emp_id,
                "Employee Name": emp_name,
                "Business Unit": bu,
                "Department": dept,
                "Reporting Manager": rm,
                "Date": dt_str,
                "Month": "Sep 2026",
                "Attendance Type": att_type,
                "Status": status,
                "In Time": in_time,
                "Out Time": out_time,
                "Applied By": applied_by,
                "Applied On": applied_on,
                "Approved By": approved_by,
                "Approved On": approved_on,
            })

    return pd.DataFrame(rows)


def run_benchmark_for_dataset(name: str, df: pd.DataFrame):
    print(f"\n{'=' * 65}")
    print(f"BENCHMARK: {name} ({len(df):,} records, {df['Employee Number'].nunique():,} employees)")
    print(f"{'=' * 65}")

    tracemalloc.start()
    mem_start, _ = tracemalloc.get_traced_memory()

    svc = TimeSeriesSnapshotService(cache_manager=CacheManager())

    # 1. Dataset Ingestion / Normalization Time
    t0 = time.perf_counter()
    normalized_df = tsa.load_time_series_dataset(
        PROJECT_ROOT / "local_data" / "Daily Performance Report 01 Sep 2026 - 13 Sep 2026 - FinBox.xlsx"
        if name == "Local Sample" else df
    ) if name == "Local Sample" else create_snapshot(df).fact_df
    t_ingest = time.perf_counter() - t0
    print(f"1. Ingestion / Normalization Latency:       {t_ingest * 1000:.2f} ms")

    # 2. Snapshot Preparation Time (full end-to-end preparation)
    t0 = time.perf_counter()
    snap = svc.prepare_dataset(df)
    t_snapshot_prep = time.perf_counter() - t0
    print(f"2. Snapshot Preparation Latency:           {t_snapshot_prep * 1000:.2f} ms ({t_snapshot_prep:.4f} s)")

    # 3. Organization-Wide Metrics Retrieval (Unfiltered)
    t0 = time.perf_counter()
    metrics = svc.get_dashboard_metrics()
    t_metrics_unfiltered = time.perf_counter() - t0
    print(f"3. Organization-wide Metrics Retrieval:     {t_metrics_unfiltered * 1000:.4f} ms")

    # 4. Employee-Level Breakdown Retrieval (Unfiltered)
    t0 = time.perf_counter()
    emp_bd = svc.get_breakdown("Employee")
    t_emp_breakdown = time.perf_counter() - t0
    print(f"4. Employee Breakdown Retrieval (Snapshot): {t_emp_breakdown * 1000:.4f} ms")

    # Measure Legacy Phase 1 unoptimized employee breakdown for comparison
    t0 = time.perf_counter()
    legacy_emp_bd = tsa.compute_level_breakdown(snap.fact_df, level="Employee")
    t_legacy_emp = time.perf_counter() - t0
    print(f"   ↳ Legacy Phase 1 Uncached Breakdown:     {t_legacy_emp * 1000:.2f} ms (Speedup: {t_legacy_emp / max(t_emp_breakdown, 1e-9):,.1f}x)")

    # 5. Repeat Retrieval of Already Prepared Result
    t0 = time.perf_counter()
    repeat_metrics = svc.get_dashboard_metrics()
    t_repeat_metrics = time.perf_counter() - t0
    print(f"5. Repeat Metrics Retrieval:                {t_repeat_metrics * 1000:.4f} ms")

    # 6. First-Time Filtered Calculation
    bu_choice = snap.filter_options["business_units"][0] if snap.filter_options["business_units"] else "Engineering"
    t0 = time.perf_counter()
    f_metrics = svc.get_dashboard_metrics(business_unit=bu_choice)
    t_first_filter = time.perf_counter() - t0
    print(f"6. First-Time Filtered Query (BU={bu_choice}): {t_first_filter * 1000:.2f} ms")

    # 7. Repeat Retrieval of the Same Filtered Result (Cache Hit)
    t0 = time.perf_counter()
    repeat_f_metrics = svc.get_dashboard_metrics(business_unit=bu_choice)
    t_repeat_filter = time.perf_counter() - t0
    print(f"7. Repeat Filtered Retrieval (Cache Hit):   {t_repeat_filter * 1000:.4f} ms (Speedup: {t_first_filter / max(t_repeat_filter, 1e-9):,.1f}x)")

    # 8. Memory Usage
    mem_current, mem_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    delta_mb = (mem_current - mem_start) / (1024 * 1024)
    peak_mb = mem_peak / (1024 * 1024)
    print(f"8. Cache Memory Footprint:                  {delta_mb:.2f} MB (Peak: {peak_mb:.2f} MB)")

    return {
        "dataset": name,
        "rows": len(df),
        "t_ingest_ms": t_ingest * 1000,
        "t_prep_ms": t_snapshot_prep * 1000,
        "t_metrics_unfiltered_ms": t_metrics_unfiltered * 1000,
        "t_emp_breakdown_ms": t_emp_breakdown * 1000,
        "t_legacy_emp_ms": t_legacy_emp * 1000,
        "t_repeat_metrics_ms": t_repeat_metrics * 1000,
        "t_first_filter_ms": t_first_filter * 1000,
        "t_repeat_filter_ms": t_repeat_filter * 1000,
        "cache_mem_mb": delta_mb,
    }


def main():
    print("=" * 65)
    print("TRANSFORMERS 2.0 — PHASE 2A BENCHMARK HARNESS")
    print("=" * 65)

    # 1. Local Representative Dataset (11 records)
    sample_file = PROJECT_ROOT / "local_data" / "Daily Performance Report 01 Sep 2026 - 13 Sep 2026 - FinBox.xlsx"
    if sample_file.exists():
        df_local = pd.read_excel(sample_file)
        run_benchmark_for_dataset("Local Sample", df_local)

    # 2. Scaled Synthetic Dataset (1,500 records, 50 employees, 30 days)
    df_scaled = generate_synthetic_dataset(num_employees=50, days=30)
    run_benchmark_for_dataset("Scaled Synthetic (1,500 records)", df_scaled)


if __name__ == "__main__":
    main()
