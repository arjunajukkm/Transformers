"""
storage/cache_manager.py
────────────────────────
Lightweight, thread-safe in-memory and disk snapshot cache manager
for Transformers 2.0 desktop workforce analytics.

Implements the Phase 2 foundation:
"Upload once -> validate and normalize -> build analytical facts ->
calculate standard results -> store a reusable analytical snapshot ->
serve all desktop modules without unnecessary recalculation."
"""

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd


class AnalyticalSnapshot:
    """Represents a validated, normalized analytical dataset snapshot."""

    def __init__(
        self,
        key: str,
        raw_source: str,
        fact_df: pd.DataFrame,
        metrics: Optional[Dict[str, Any]] = None,
        breakdowns: Optional[Dict[str, Any]] = None,
    ):
        self.key = key
        self.raw_source = raw_source
        self.fact_df = fact_df
        self.metrics = metrics or {}
        self.breakdowns = breakdowns or {}
        self.created_at = time.time()
        self.row_count = len(fact_df) if fact_df is not None else 0

    def is_valid(self) -> bool:
        return self.fact_df is not None and not self.fact_df.empty


class CacheManager:
    """Thread-safe analytical snapshot cache manager."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self._lock = threading.RLock()
        self._memory_cache: Dict[str, AnalyticalSnapshot] = {}
        self._active_key: Optional[str] = None
        self.cache_dir = cache_dir

    def set_active_snapshot(self, key: str, snapshot: AnalyticalSnapshot):
        with self._lock:
            self._memory_cache[key] = snapshot
            self._active_key = key

    def get_active_snapshot(self) -> Optional[AnalyticalSnapshot]:
        with self._lock:
            if self._active_key and self._active_key in self._memory_cache:
                return self._memory_cache[self._active_key]
            return None

    def get_snapshot(self, key: str) -> Optional[AnalyticalSnapshot]:
        with self._lock:
            return self._memory_cache.get(key)

    def has_snapshot(self, key: str) -> bool:
        with self._lock:
            return key in self._memory_cache

    def clear(self):
        with self._lock:
            self._memory_cache.clear()
            self._active_key = None


# Global singleton instance
snapshot_cache = CacheManager()
