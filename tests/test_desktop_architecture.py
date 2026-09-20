"""
tests/test_desktop_architecture.py
──────────────────────────────────
Unit tests for Transformers 2.0 Desktop Foundation architecture:
- config package (settings, constants, paths)
- storage package (AnalyticalSnapshot, CacheManager)
- ingestion package (facade export validation)
"""

import pandas as pd
import pytest

import config
from storage import AnalyticalSnapshot, CacheManager, snapshot_cache
import ingestion


def test_config_settings():
    assert config.APP_NAME == "Transformers"
    assert "2.0" in config.APP_VERSION
    assert config.WINDOW_DEFAULT_SIZE == "1280x800"
    assert config.BASE_DIR.exists()
    assert config.DEFAULT_WORKFORCE_POLICY["max_daily_quantity"] == 1.0


def test_storage_cache_manager():
    cm = CacheManager()
    assert cm.get_active_snapshot() is None

    df = pd.DataFrame([{"Employee Number": "E001", "Hours": 8.5}])
    snap = AnalyticalSnapshot(
        key="test_key_01",
        raw_source="sample.xlsx",
        fact_df=df,
        metrics={"total": 1},
    )

    assert snap.is_valid()
    assert snap.row_count == 1
    assert snap.metrics["total"] == 1

    cm.set_active_snapshot("test_key_01", snap)
    assert cm.has_snapshot("test_key_01")
    active = cm.get_active_snapshot()
    assert active is not None
    assert active.key == "test_key_01"
    assert active.row_count == 1

    cm.clear()
    assert cm.get_active_snapshot() is None
    assert not cm.has_snapshot("test_key_01")


def test_ingestion_facade_exports():
    assert callable(ingestion.generate_upload_file)
    assert callable(ingestion.generate_okr_upload_file)
    assert callable(ingestion.normalize_okr_weightage)
    assert callable(ingestion.process_absent_management)
    assert callable(ingestion.process_attendance_summary)
