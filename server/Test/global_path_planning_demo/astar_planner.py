"""Shim — all code now lives in server/lib/path_planning/planner.

This file re-exports everything so that existing demo scripts
continue to work without changes.
"""
import sys
from pathlib import Path

_LIB_DIR = str(Path(__file__).resolve().parents[2] / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from path_planning.planner import *  # noqa: F401,F403
