"""
storage/cache_manager.py
────────────────────────
Lightweight, thread-safe in-memory analytical snapshot and cache manager
for Transformers 2.0 desktop workforce analytics.

Implements the high-performance Phase 2A analytical foundation:
"Upload once -> validate and normalize -> build analytical facts ->
calculate standard results -> store a reusable analytical snapshot ->
serve all desktop modules without unnecessary recalculation."
"""

from collections import OrderedDict
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd

import time_series_analysis as tsa


def _normalize_filter_val(val: Optional[str], all_label: str) -> Optional[str]:
    """Normalize a filter string to None if empty or matches an 'All' variant."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("all", all_label.lower(), "none", "nan"):
        return None
    return s


def _canonical_level(level: str) -> str:
    """Resolve level string to canonical breakdown dimension."""
    l_str = str(level).strip().lower()
    if "business unit" in l_str or l_str == "bu":
        return "Business Unit"
    if "department" in l_str or l_str == "dept":
        return "Department"
    if "reporting manager" in l_str or l_str in ("rm", "manager"):
        return "Reporting Manager"
    return "Employee"


def _defensive_copy_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a defensive copy of a dictionary, copying nested dicts or lists if present.
    Protects internally stored snapshot results from caller mutation without full dataset cloning.
    """
    if not d:
        return {}
    res = {}
    for k, v in d.items():
        if isinstance(v, dict):
            res[k] = _defensive_copy_dict(v)
        elif isinstance(v, list):
            res[k] = [x.copy() if isinstance(x, dict) else x for x in v]
        else:
            res[k] = v
    return res


def _defensive_copy_breakdown(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return a defensive copy of a breakdown list of row dictionaries.
    Protects internal table rows from caller mutation.
    """
    if not rows:
        return []
    return [_defensive_copy_dict(row) for row in rows]


class AnalyticalSnapshot:
    """
    Represents a validated, normalized analytical dataset snapshot.
    Precomputes and caches standard organization-wide metrics and multi-level
    breakdowns, with a bounded LRU cache for on-demand filtered requests.
    Returns defensive copies so caller mutations cannot corrupt cached state.
    """

    def __init__(
        self,
        key: Optional[str] = None,
        dataset_id: Optional[str] = None,
        version: int = 1,
        raw_source: str = "",
        fact_df: Optional[pd.DataFrame] = None,
        metrics: Optional[Dict[str, Any]] = None,
        breakdowns: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        filter_options: Optional[Dict[str, List[str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_filter_cache_size: int = 128,
        workforce_foundation: Optional[Any] = None,
    ):
        self.dataset_id = dataset_id or key or f"dataset_v{version}_{int(time.time() * 1000)}"
        self.key = self.dataset_id  # Backward-compatibility alias
        self.version = version
        self.raw_source = raw_source
        self.fact_df = fact_df
        self.workforce_foundation = workforce_foundation
        self.created_at = time.time()
        self.row_count = len(fact_df) if fact_df is not None else 0

        # Precomputed standard results (stored internally)
        self.standard_metrics = metrics or {}
        self.metrics = self.standard_metrics  # Backward-compatibility alias
        self.standard_breakdowns = breakdowns or {}
        self.breakdowns = self.standard_breakdowns  # Backward-compatibility alias

        # Filter options and metadata
        self.filter_options = filter_options or {
            "business_units": [],
            "departments": [],
            "months": [],
        }
        self.metadata = metadata or {}

        # Bounded LRU caches for filtered requests
        self._max_cache_size = max_filter_cache_size
        self._filter_metrics_cache: OrderedDict[Tuple[Optional[str], Optional[str], Optional[str]], Dict[str, Any]] = OrderedDict()
        self._filter_breakdown_cache: OrderedDict[Tuple[str, Optional[str], Optional[str], Optional[str]], List[Dict[str, Any]]] = OrderedDict()
        self._lock = threading.RLock()

    def is_valid(self) -> bool:
        """Returns True if the snapshot contains a non-empty analytical fact DataFrame."""
        return self.fact_df is not None and not self.fact_df.empty

    def get_metrics(
        self,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve organization-wide or filtered dashboard metrics.
        Returns precomputed standard metrics in 0.0ms if unfiltered.
        Caches and retrieves previously computed filter combinations.
        Returns defensive copy to protect internal cache from caller mutation.
        """
        bu = _normalize_filter_val(business_unit, "All Business Units")
        dept = _normalize_filter_val(department, "All Departments")
        m = _normalize_filter_val(month, "All Months")

        # Unfiltered request: return defensive copy of precomputed standard metrics
        if bu is None and dept is None and m is None and self.standard_metrics:
            return _defensive_copy_dict(self.standard_metrics)

        cache_key = (
            bu.lower() if bu else None,
            dept.lower() if dept else None,
            m.lower() if m else None,
        )

        with self._lock:
            if cache_key in self._filter_metrics_cache:
                self._filter_metrics_cache.move_to_end(cache_key)
                return _defensive_copy_dict(self._filter_metrics_cache[cache_key])

        # Calculate using preserved tsa metric calculations
        metrics = tsa.compute_time_series_metrics(
            self.fact_df,
            business_unit=bu,
            department=dept,
            month=m,
        )

        with self._lock:
            self._filter_metrics_cache[cache_key] = metrics
            if len(self._filter_metrics_cache) > self._max_cache_size:
                self._filter_metrics_cache.popitem(last=False)

        return _defensive_copy_dict(metrics)

    def get_breakdown(
        self,
        level: str,
        business_unit: Optional[str] = None,
        department: Optional[str] = None,
        month: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve entity breakdown table for the specified level.
        Returns precomputed standard breakdown in 0.0ms if unfiltered.
        Caches and retrieves previously computed filter combinations.
        Returns defensive copy to protect internal cache from caller mutation.
        """
        canonical_lvl = _canonical_level(level)
        bu = _normalize_filter_val(business_unit, "All Business Units")
        dept = _normalize_filter_val(department, "All Departments")
        m = _normalize_filter_val(month, "All Months")

        # Unfiltered request: return defensive copy of precomputed standard breakdown
        if bu is None and dept is None and m is None and canonical_lvl in self.standard_breakdowns:
            return _defensive_copy_breakdown(self.standard_breakdowns[canonical_lvl])

        cache_key = (
            canonical_lvl,
            bu.lower() if bu else None,
            dept.lower() if dept else None,
            m.lower() if m else None,
        )

        with self._lock:
            if cache_key in self._filter_breakdown_cache:
                self._filter_breakdown_cache.move_to_end(cache_key)
                return _defensive_copy_breakdown(self._filter_breakdown_cache[cache_key])

        # Calculate using preserved tsa breakdown calculations
        breakdown = tsa.compute_level_breakdown(
            self.fact_df,
            level=canonical_lvl,
            business_unit=bu,
            department=dept,
            month=m,
        )

        with self._lock:
            self._filter_breakdown_cache[cache_key] = breakdown
            if len(self._filter_breakdown_cache) > self._max_cache_size:
                self._filter_breakdown_cache.popitem(last=False)

        return _defensive_copy_breakdown(breakdown)

    def get_filter_cache_stats(self) -> Dict[str, int]:
        """Return counts of cached filter combinations."""
        with self._lock:
            return {
                "metrics_cached": len(self._filter_metrics_cache),
                "breakdowns_cached": len(self._filter_breakdown_cache),
            }


class CacheManager:
    """
    Thread-safe analytical snapshot cache manager for the single-user desktop application.
    Retains only the active dataset and releases inactive historical snapshots to
    prevent unbounded memory growth while supporting safe in-progress replacement.
    """

    def __init__(self, cache_dir: Optional[Path] = None, max_snapshots: int = 1):
        self._lock = threading.RLock()
        self._snapshots: OrderedDict[str, AnalyticalSnapshot] = OrderedDict()
        self._active_key: Optional[str] = None
        self._version_counter: int = 0
        self.cache_dir = cache_dir
        self.max_snapshots = max_snapshots

    def next_version(self) -> int:
        """Increment and return monotonically increasing dataset version."""
        with self._lock:
            self._version_counter += 1
            return self._version_counter

    def set_active_snapshot(
        self,
        key_or_snapshot: Union[str, AnalyticalSnapshot],
        snapshot: Optional[AnalyticalSnapshot] = None,
    ):
        """
        Atomically register and activate a snapshot.
        Supports both set_active_snapshot(snap) and set_active_snapshot(key, snap).
        Releases old inactive snapshots to allow immediate garbage collection.
        """
        with self._lock:
            if isinstance(key_or_snapshot, AnalyticalSnapshot):
                actual_snap = key_or_snapshot
                actual_key = actual_snap.dataset_id
            else:
                actual_key = str(key_or_snapshot)
                actual_snap = snapshot

            if actual_snap is None:
                raise ValueError("Snapshot cannot be None.")

            # Replace stored snapshots to free memory from old datasets
            self._snapshots.clear()
            self._snapshots[actual_key] = actual_snap
            self._active_key = actual_key

    def get_active_snapshot(self) -> Optional[AnalyticalSnapshot]:
        """Retrieve the currently active snapshot."""
        with self._lock:
            if self._active_key and self._active_key in self._snapshots:
                return self._snapshots[self._active_key]
            return None

    def get_snapshot(self, key: str) -> Optional[AnalyticalSnapshot]:
        """Retrieve snapshot by key."""
        with self._lock:
            return self._snapshots.get(key)

    def has_snapshot(self, key: str) -> bool:
        """Check if snapshot exists in cache."""
        with self._lock:
            return key in self._snapshots

    def invalidate(self):
        """Deactivate and release active snapshot from cache."""
        with self._lock:
            self._snapshots.clear()
            self._active_key = None

    def clear(self):
        """Purge all cached snapshots and reset state."""
        with self._lock:
            self._snapshots.clear()
            self._active_key = None


# Global singleton instance
snapshot_cache = CacheManager()
