import os
import glob
from PyQt5.QtGui import QColor

# Resolve assets path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMG_DIR = os.path.join(BASE_DIR, "assets", "images")
MAP_IMG_PATH = os.path.join(IMG_DIR, "빈맵.png")

if not os.path.exists(MAP_IMG_PATH):
    png_files = glob.glob(os.path.join(IMG_DIR, "*.png"))
    for f in png_files:
        if "빈맵" in f or "빈맵" in f:
            MAP_IMG_PATH = f
            break
    else:
        if png_files: MAP_IMG_PATH = png_files[0]

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

# Scale factor: pixels per meter used to map ROS pose coordinates onto the
# floor-plan image.  Adjust to match your actual map resolution.
MAP_POSE_SCALE_PX: float = float(os.environ.get("MAP_POSE_SCALE_PX", "50"))
