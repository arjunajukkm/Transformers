"""
workforce_intelligence/snapshot_bridge.py
────────────────────────────────────────
Thread-safe analytical bridge connecting AnalyticalSnapshot to the
Workforce Intelligence KPI calculation engine.

Provides the decoupled, UI-independent analytical service interface:
- Retrieves active snapshot and canonical foundation without reloading data.
- Bounded LRU cache (default 128 items) for on-demand filtered requests.
- Automatic cache invalidation when the active dataset is replaced.
- Supports background execution without UI or disk blocking.
- Provides benchmarking tools for initial computation vs. cached retrieval.
"""

from collections import OrderedDict
from dataclasses import asdict
from datetime import date
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd

from storage.cache_manager import (
    AnalyticalSnapshot,
    CacheManager,
    snapshot_cache,
    _defensive_copy_dict,
)
from storage.snapshot_service import (
    TimeSeriesSnapshotService,
    snapshot_service as default_snapshot_service,
)
from workforce_intelligence.kpi_engine import (
    EmployeeMonthWFH,
    EmployeePunchDeviation,
    RepeatExceptionDossier,
    _empty_bundle,
    compute_punch_deviations_bu,
    compute_repeated_exceptions,
    compute_wfh_allowance_monthly,
    compute_workforce_intelligence_bundle,
)


def _norm_str(val: Optional[str]) -> Optional[str]:
    """Normalize filter strings to None if empty or 'All'."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("all", "all business units", "all departments", "all managers", "all reporting managers", "all employees", "none", "nan"):
        return None
    return s.lower()


def _norm_emp(val: Optional[str]) -> Optional[str]:
    """Normalize employee filter string to stable employee ID prefix if format is 'EMP001 — Name'."""
    s = _norm_str(val)
    if s is None:
        return None
    if " — " in s:
        return s.split(" — ")[0].strip()
    if " - " in s:
        return s.split(" - ")[0].strip()
    return s


class WorkforceIntelligenceBridge:
    """
    Decoupled analytical service interface for Transformers 2.0 Workforce Intelligence.
    Interacts with TimeSeriesSnapshotService and AnalyticalSnapshot.
    Maintains a thread-safe, bounded LRU cache for workforce KPI requests.
    """

    def __init__(
        self,
        snapshot_service: Optional[TimeSeriesSnapshotService] = None,
        max_cache_size: int = 128,
    ):
        self._service = snapshot_service or default_snapshot_service
        self._max_cache_size = max_cache_size
        self._cache: OrderedDict[Tuple[Any, ...], Dict[str, Any]] = OrderedDict()
        self._last_dataset_id: Optional[str] = None
        self._lock = threading.RLock()

    def _sync_dataset_state(self, snap: Optional[AnalyticalSnapshot]) -> None:
        """Invalidate cached results if the active dataset has changed or been purged."""
        current_id = snap.dataset_id if snap and snap.is_valid() else None
        if current_id != self._last_dataset_id:
            with self._lock:
                self._cache.clear()
                self._last_dataset_id = current_id

    def get_workforce_metrics(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        exception_threshold: int = 3,
        wfh_allowance: float = 3.0,
        late_departure_threshold_mins: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Retrieve comprehensive Workforce Intelligence KPI bundle.
        Uses cached results if available for identical filter parameters.
        Otherwise computes from the active snapshot's shared fact DataFrame.
        """
        snap = self._service.get_active_snapshot()
        if not snap or not snap.is_valid():
            return _empty_bundle(exception_threshold, wfh_allowance)

        self._sync_dataset_state(snap)

        bu_key = _norm_str(business_unit)
        dept_key = _norm_str(department)
        mgr_key = _norm_str(manager)
        emp_key = _norm_emp(employee)
        dr_key = (date_range[0], date_range[1]) if date_range and len(date_range) == 2 else None

        cache_key = (
            bu_key,
            dept_key,
            mgr_key,
            emp_key,
            dr_key,
            int(exception_threshold),
            float(wfh_allowance),
            float(late_departure_threshold_mins),
        )

        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return _defensive_copy_dict(self._cache[cache_key])

        # Compute new bundle using the shared DataFrame (read-only contract)
        foundation = getattr(snap, "workforce_foundation", None)
        bundle = compute_workforce_intelligence_bundle(
            df=snap.fact_df,
            canonical_data=foundation,
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            exception_threshold=exception_threshold,
            wfh_allowance=wfh_allowance,
            late_departure_threshold_mins=late_departure_threshold_mins,
        )

        with self._lock:
            self._cache[cache_key] = bundle
            if len(self._cache) > self._max_cache_size:
                self._cache.popitem(last=False)

        return _defensive_copy_dict(bundle)

    def get_wfh_allowance_audit(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        wfh_allowance: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Retrieve WFH allowance audit records and summary.
        Reuses cached workforce bundle if available.
        """
        bundle = self.get_workforce_metrics(
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            wfh_allowance=wfh_allowance,
        )
        return {
            "summary": bundle.get("wfh_monthly_summary", {}),
            "breakdown": bundle.get("wfh_employee_month_breakdown", []),
            "partially_observed_months": bundle.get("wfh_partially_observed_months", []),
            "total_additional_wfh_days": bundle.get("wfh_total_additional_days", 0.0),
            "employees_exceeding_allowance": bundle.get("wfh_employees_exceeding_allowance", 0),
        }

    def get_punch_deviations(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        deviation_threshold_mins: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Retrieve Business Unit benchmark deviations for employees.
        """
        bundle = self.get_workforce_metrics(
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            late_departure_threshold_mins=deviation_threshold_mins,
        )
        return {
            "bu_benchmarks": bundle.get("bu_benchmarks", {}),
            "deviations": bundle.get("employee_punch_deviations", []),
            "late_arrival_count": bundle.get("late_arrival_employees_count", 0),
            "early_departure_count": bundle.get("early_departure_employees_count", 0),
        }

    def get_repeated_exceptions(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        manager: Optional[str] = None,
        employee: Optional[str] = None,
        date_range: Optional[Tuple[date, date]] = None,
        threshold: int = 3,
    ) -> Dict[str, Any]:
        """
        Retrieve repeated attendance exception dossiers.
        """
        bundle = self.get_workforce_metrics(
            business_unit=business_unit,
            department=department,
            manager=manager,
            employee=employee,
            date_range=date_range,
            exception_threshold=threshold,
        )
        return {
            "threshold": bundle.get("repeated_exception_threshold", threshold),
            "affected_employees_count": bundle.get("repeated_exception_employees_count", 0),
            "affected_rate_pct": bundle.get("repeated_exception_rate_pct", 0.0),
            "dossiers": bundle.get("repeated_exception_dossiers", []),
        }

    def get_filter_cache_stats(self) -> Dict[str, Any]:
        """Return counts and metadata for the internal LRU cache."""
        snap = self._service.get_active_snapshot()
        self._sync_dataset_state(snap)
        with self._lock:
            return {
                "cached_bundles": len(self._cache),
                "max_cache_size": self._max_cache_size,
                "active_dataset_id": self._last_dataset_id,
            }

    def clear_cache(self) -> None:
        """Purge all cached analytical bundles."""
        with self._lock:
            self._cache.clear()

    def benchmark_performance(
        self,
        iterations: int = 5,
    ) -> Dict[str, float]:
        """
        Benchmark initial preparation vs. cached retrieval time.
        Returns average timings in milliseconds.
        """
        snap = self._service.get_active_snapshot()
        if not snap or not snap.is_valid():
            return {"initial_ms": 0.0, "cached_ms": 0.0}

        self.clear_cache()

        # 1. Measure initial calculation time
        t0 = time.perf_counter()
        _ = self.get_workforce_metrics()
        initial_ms = (time.perf_counter() - t0) * 1000.0

        # 2. Measure cached retrieval time over N iterations
        cached_times = []
        for _ in range(iterations):
            t_start = time.perf_counter()
            _ = self.get_workforce_metrics()
            cached_times.append((time.perf_counter() - t_start) * 1000.0)

        avg_cached_ms = sum(cached_times) / len(cached_times) if cached_times else 0.0

        return {
            "initial_ms": round(initial_ms, 2),
            "cached_ms": round(avg_cached_ms, 4),
        }


# Global singleton bridge instance
workforce_bridge = WorkforceIntelligenceBridge()
