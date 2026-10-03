import os
import sys
from pathlib import Path
import pytest

# Ensure Tcl/Tk libraries are located reliably across all test runs
_tcl_p = Path(sys.base_prefix) / "tcl"
if (_tcl_p / "tcl8.6").exists():
    os.environ.setdefault("TCL_LIBRARY", str(_tcl_p / "tcl8.6"))
if (_tcl_p / "tk8.6").exists():
    os.environ.setdefault("TK_LIBRARY", str(_tcl_p / "tk8.6"))


@pytest.fixture(scope="session")
def desktop_app():
    """Headless Desktop App instance shared across test suites to prevent Tkinter re-init conflicts."""
    from app import App
    from storage import snapshot_service
    snapshot_service.clear()
    app = App()
    app.withdraw()
    app.update()

    yield app

    try:
        app.destroy()
    except Exception:
        pass
    snapshot_service.clear()

