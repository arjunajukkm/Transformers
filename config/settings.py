"""
config/settings.py
──────────────────
Central application configuration for Transformers 2.0 Desktop Application.
Manages application metadata, runtime constants, UI geometry, and paths.
"""

from pathlib import Path
import sys

# Application Metadata
APP_NAME = "Transformers"
APP_VERSION = "2.0.0-phase1"
APP_ID = "moshpit.transformers.2.0"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"

# Window Dimensions & Geometry
WINDOW_DEFAULT_SIZE = "1280x800"
WINDOW_MIN_SIZE = (1024, 700)

# Paths Configuration
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = BASE_DIR
ICON_PATH = BASE_DIR / "icon.ico"
LOCAL_DATA_DIR = BASE_DIR / "local_data"
CACHE_DIR = BASE_DIR / ".cache"

# Ensure local directories exist if needed
CACHE_DIR.mkdir(exist_ok=True)

# Analytical Defaults
DEFAULT_WORKFORCE_POLICY = {
    "standard_daily_hours": 9.0,
    "wfh_monthly_threshold": 3,
    "max_daily_quantity": 1.0,
}
