import os
import sys
from pathlib import Path

# Ensure Tcl/Tk libraries are located reliably across all test runs
_tcl_p = Path(sys.base_prefix) / "tcl"
if (_tcl_p / "tcl8.6").exists():
    os.environ.setdefault("TCL_LIBRARY", str(_tcl_p / "tcl8.6"))
if (_tcl_p / "tk8.6").exists():
    os.environ.setdefault("TK_LIBRARY", str(_tcl_p / "tk8.6"))
