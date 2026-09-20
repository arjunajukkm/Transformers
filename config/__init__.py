"""
config
──────
Transformers 2.0 Configuration Package.
"""

from config.settings import (
    APP_ID,
    APP_NAME,
    APP_TITLE,
    APP_VERSION,
    ASSETS_DIR,
    BASE_DIR,
    CACHE_DIR,
    DEFAULT_WORKFORCE_POLICY,
    ICON_PATH,
    LOCAL_DATA_DIR,
    WINDOW_DEFAULT_SIZE,
    WINDOW_MIN_SIZE,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_ID",
    "APP_TITLE",
    "WINDOW_DEFAULT_SIZE",
    "WINDOW_MIN_SIZE",
    "BASE_DIR",
    "ASSETS_DIR",
    "ICON_PATH",
    "LOCAL_DATA_DIR",
    "CACHE_DIR",
    "DEFAULT_WORKFORCE_POLICY",
]
