"""Shim — all code now lives in server/lib/path_planning/map_data.

This file re-exports everything so that existing demo scripts
(monitor.py, nav2_bridge.py, etc.) continue to work without changes.
"""
import sys
from pathlib import Path

# Ensure server/lib is on sys.path.
_LIB_DIR = str(Path(__file__).resolve().parents[2] / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from path_planning.map_data import *  # noqa: F401,F403

# Override DEFAULT_MAP_PATH to point at the demo's local maps/.
DEFAULT_MAP_PATH = Path(__file__).parent / "maps" / "buffet_sim.yaml"
