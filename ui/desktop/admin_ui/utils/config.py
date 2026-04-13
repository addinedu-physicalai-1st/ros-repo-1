import os
import glob
from PyQt5.QtGui import QColor

# Resolve assets path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMG_DIR = os.path.join(BASE_DIR, "assets", "images")
MAP_IMG_PATH = os.path.join(IMG_DIR, "gazebo_map.png")

if not os.path.exists(MAP_IMG_PATH):
    png_files = glob.glob(os.path.join(IMG_DIR, "*.png"))
    if png_files:
        MAP_IMG_PATH = png_files[0]

COLOR_MOVING = QColor("#4A88D4")
COLOR_WAITING = QColor("#999999")
COLOR_COLLECT = QColor("#E06A4E")
COLOR_CHARGING = QColor("#54B254")
COLOR_BG = QColor("#F4EFE6")

CARD_STYLE = """
    QFrame {
        background-color: white;
        border-radius: 10px;
        border: 1px solid #E4E7ED;
    }
"""

# ── Control server connection ─────────────────────────────────────────────────
# Override with environment variables before launching the dashboard.
CONTROL_BASE_URL: str = os.environ.get("CONTROL_BASE_URL", "http://localhost:8000")
ADMIN_API_KEY:    str = os.environ.get("ADMIN_API_KEY", "")

# ── Map coordinate calibration ────────────────────────────────────────────────
# Derived from map4.yaml (nav2 occupancy grid, 0.05 m/px, 10x upscaled to PNG):
#   MAP_POSE_SCALE_PX : pixels per meter  (= 1/resolution * upscale = 20 * 10)
#   MAP_ORIGIN_X/Y    : pixel position of Gazebo world (0, 0) in the image
#                       origin: [-0.285, -1.241] → spawn pixel (57, 72) at 200 px/m
MAP_POSE_SCALE_PX: float = float(os.environ.get("MAP_POSE_SCALE_PX", "200"))
MAP_ORIGIN_X:      float = float(os.environ.get("MAP_ORIGIN_X",      "57"))
MAP_ORIGIN_Y:      float = float(os.environ.get("MAP_ORIGIN_Y",      "72"))
