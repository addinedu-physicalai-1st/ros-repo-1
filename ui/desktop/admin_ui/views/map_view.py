import math
import sys
from pathlib import Path

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QGraphicsView, QGraphicsScene, QScrollArea, QFrame,
                             QMessageBox, QGraphicsLineItem)
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap, QPen
from PyQt5.QtCore import Qt, QTimer, QPointF

from components.map_items import RobotMapItem, WaypointItem, PathLineItem
from components.widgets import RobotCard
from utils.config import (MAP_IMG_PATH, COLOR_MOVING, COLOR_WAITING,
                          COLOR_COLLECT, COLOR_CHARGING,
                          MAP_POSE_SCALE_PX, MAP_ORIGIN_X, MAP_ORIGIN_Y)
from utils.api_client import (ApiClient, ApiWorker,
                              CMD_CANCEL, CMD_RETURN_DOCK, CMD_EMERGENCY_STOP,
                              ROBOT_STATUS_LABELS, TASK_TYPE_LABELS)


# Map RobotStatus int → display colour
_STATUS_COLORS: dict[int, QColor] = {
    1: COLOR_WAITING,          # IDLE
    2: COLOR_MOVING,           # MOVING
    3: COLOR_MOVING,           # ARRIVED
    4: COLOR_CHARGING,         # CHARGING
    5: QColor("#F56C6C"),      # ERROR
    6: QColor("#909399"),      # OFFLINE
}

# Per-robot fixed colours (same as demo monitor.py)
_ROBOT_COLORS = [
    QColor("#2ca02c"),   # green
    QColor("#d62728"),   # red
    QColor("#9467bd"),   # purple
    QColor("#17becf"),   # cyan
]

# ── Path planning library (optional) ─────────────────────────────────────────
_LIB_DIR = str(Path(__file__).resolve().parents[4] / "server" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
try:
    from path_planning import load_buffet_map, BuffetMap
    _HAS_PATH_PLANNING = True
except ImportError:
    _HAS_PATH_PLANNING = False

import os
_MAP_YAML = os.environ.get("MRTA_MAP_PATH", "")
if not _MAP_YAML:
    # Auto-detect
    _candidates = [
        str(Path(__file__).resolve().parents[4]
            / "server" / "Test" / "global_path_planning_demo"
            / "maps" / "buffet_sim.yaml"),
    ]
    for c in _candidates:
        if os.path.isfile(c):
            _MAP_YAML = c
            break


def _world_to_scene(x: float, y: float) -> QPointF:
    """Convert world metres to scene pixels."""
    return QPointF(
        MAP_ORIGIN_X + x * MAP_POSE_SCALE_PX,
        MAP_ORIGIN_Y - y * MAP_POSE_SCALE_PX,
    )


class MapWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setStyleSheet("background-color: #F4EFE6;")

        self.bg_pixmap = QPixmap(MAP_IMG_PATH)
        if self.bg_pixmap.isNull():
            self.bg_pixmap = QPixmap(1000, 1000)
            self.bg_pixmap.fill(QColor("#EAE0D5"))

        self.scene.addPixmap(self.bg_pixmap)
        self.setSceneRect(0, 0, self.bg_pixmap.width(), self.bg_pixmap.height())
        self.robots: dict[str, RobotMapItem] = {}
        self._robot_color_idx: dict[str, int] = {}
        self._next_color_idx = 0

        # Waypoint graph overlay
        self._buffet_map: BuffetMap | None = None
        self._wp_items: list = []
        self._edge_items: list = []

        self._load_waypoint_graph()

    def _load_waypoint_graph(self) -> None:
        """Load waypoint graph from YAML and draw on scene."""
        if not _HAS_PATH_PLANNING or not _MAP_YAML:
            return
        try:
            self._buffet_map = load_buffet_map(_MAP_YAML)
        except Exception:
            return

        graph = self._buffet_map.graph

        # Draw edges first (behind nodes)
        seen = set()
        for wp_id, neighbors in graph.adjacency.items():
            for nb in neighbors:
                key = (min(wp_id, nb), max(wp_id, nb))
                if key in seen:
                    continue
                seen.add(key)
                a = graph.waypoints[wp_id]
                b = graph.waypoints[nb]
                pa = _world_to_scene(a.x, a.y)
                pb = _world_to_scene(b.x, b.y)
                line = QGraphicsLineItem(pa.x(), pa.y(), pb.x(), pb.y())
                line.setPen(QPen(QColor("#7aa6c2"), 2, Qt.SolidLine))
                line.setOpacity(0.5)
                line.setZValue(1)
                self.scene.addItem(line)
                self._edge_items.append(line)

        # Draw waypoint nodes
        for wp in graph.waypoints.values():
            sp = _world_to_scene(wp.x, wp.y)
            item = WaypointItem(wp.wp_id, sp.x(), sp.y(), label=wp.label or "")
            item.setZValue(2)
            self.scene.addItem(item)
            self._wp_items.append(item)

    def _get_robot_color(self, r_id: str) -> QColor:
        """Assign a fixed color per robot (first seen order)."""
        if r_id not in self._robot_color_idx:
            self._robot_color_idx[r_id] = self._next_color_idx
            self._next_color_idx += 1
        idx = self._robot_color_idx[r_id]
        return _ROBOT_COLORS[idx % len(_ROBOT_COLORS)]

    def add_robot(self, r_id: str, color: QColor, pos: QPointF) -> None:
        robot_color = self._get_robot_color(r_id)
        robot = RobotMapItem(r_id, robot_color, pos)
        robot.setZValue(10)
        self.scene.addItem(robot)
        self.robots[r_id] = robot

    def remove_robot(self, r_id: str) -> None:
        item = self.robots.pop(r_id, None)
        if item is not None:
            self.scene.removeItem(item)

    def update_robot_pos(self, r_id: str, x: float, y: float,
                         yaw: float = 0.0) -> None:
        if r_id not in self.robots:
            return
        sp = _world_to_scene(x, y)
        self.robots[r_id].setPos(sp)
        self.robots[r_id].set_yaw(yaw)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def fit_view(self):
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


class MapDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self._api = ApiClient()
        self._robot_cards: dict[str, RobotCard] = {}
        self._robot_meta: dict[str, dict] = {}
        self._workers: list[ApiWorker] = []

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_all_poses)

        self.initUI()
        self._load_robots()

    # ── UI construction ───────────────────────────────────────────────────────

    def initUI(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Left: map + legend
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel("전체 2D 맵")
        title_lbl.setFont(QFont("Arial", 14, QFont.Bold))
        left_layout.addWidget(title_lbl)

        self.map_view = MapWidget()
        left_layout.addWidget(self.map_view, 1)

        legend_frame = QFrame()
        legend_frame.setStyleSheet("background-color: white; border-radius: 5px;")
        legend_layout = QHBoxLayout(legend_frame)
        for text, color in [
            ("이동 중", COLOR_MOVING.name()),
            ("대기",    COLOR_WAITING.name()),
            ("수거",    COLOR_COLLECT.name()),
            ("충전 중", COLOR_CHARGING.name()),
        ]:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            legend_layout.addWidget(lbl)
        left_layout.addWidget(legend_frame)
        main_layout.addLayout(left_layout, 2)

        # Right: robot list
        right_layout = QVBoxLayout()
        self.right_title = QLabel("로봇 목록 (로딩 중...)")
        self.right_title.setFont(QFont("Arial", 14, QFont.Bold))
        right_layout.addWidget(self.right_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.robots_container = QWidget()
        self.robots_container.setStyleSheet("background: transparent;")
        self.robots_layout = QVBoxLayout(self.robots_container)
        self.robots_layout.setContentsMargins(0, 0, 0, 0)
        self.robots_layout.setSpacing(10)
        self.robots_layout.addStretch()

        scroll.setWidget(self.robots_container)
        right_layout.addWidget(scroll)
        main_layout.addLayout(right_layout, 1)

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_robots(self):
        w = ApiWorker(self._api.get_robots)
        w.result.connect(self._on_robots_loaded)
        w.error.connect(self._on_load_error)
        w.finished.connect(lambda: self._discard_worker(w))
        self._workers.append(w)
        w.start()

    def _on_load_error(self, msg: str):
        self.right_title.setText("로봇 목록 (서버 연결 실패)")
        self.right_title.setStyleSheet("color: #F56C6C;")
        QMessageBox.warning(
            self, "관제 서버 연결 오류",
            f"로봇 목록을 불러올 수 없습니다.\n\n{msg}\n\n"
            "ADMIN_API_KEY 환경변수와 관제 서버 주소를 확인하세요.",
        )

    def _on_robots_loaded(self, data: dict):
        robots = data.get("robots", [])
        self.right_title.setText("로봇 목록 (0대)")
        self.right_title.setStyleSheet("")

        # Clear robot markers and cards (keep waypoint graph overlay)
        for r_id, item in list(self.map_view.robots.items()):
            self.map_view.scene.removeItem(item)
        self.map_view.robots.clear()
        self._robot_cards.clear()
        self._robot_meta.clear()

        while self.robots_layout.count() > 1:
            item = self.robots_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, robot in enumerate(robots):
            r_id     = robot.get("robot_id", f"R{idx + 1}")
            status_i = robot.get("status", 0)
            color    = _STATUS_COLORS.get(status_i, QColor("#999999"))
            s_label  = ROBOT_STATUS_LABELS.get(status_i, "알 수 없음")
            self._robot_meta[r_id] = {**robot, "_color": color, "_s_label": s_label}

        QTimer.singleShot(100, self.map_view.fit_view)
        self._poll_timer.start(2000)

    # ── periodic pose polling ─────────────────────────────────────────────────

    def _poll_all_poses(self):
        for r_id in list(self._robot_meta.keys()):
            w = ApiWorker(self._api.get_telemetry_pose, r_id)
            w.result.connect(lambda data, rid=r_id: self._on_pose_updated(rid, data))
            w.error.connect(lambda _, rid=r_id: self._on_pose_error(rid))
            w.finished.connect(lambda: self._discard_worker(w))
            self._workers.append(w)
            w.start()

        for r_id in list(self._robot_cards.keys()):
            wb = ApiWorker(self._api.get_telemetry_battery, r_id)
            wb.result.connect(lambda data, rid=r_id: self._on_battery_updated(rid, data))
            wb.finished.connect(lambda: self._discard_worker(wb))
            self._workers.append(wb)
            wb.start()

    def _on_pose_updated(self, r_id: str, data: dict):
        pose = data.get("latest_pose", {})
        x = float(pose.get("x", 0.0))
        y = float(pose.get("y", 0.0))
        yaw = float(pose.get("theta", 0.0))

        # First successful pose → add robot to map and card list
        if r_id not in self.map_view.robots:
            meta    = self._robot_meta.get(r_id, {})
            color   = meta.get("_color", QColor("#999999"))
            s_label = meta.get("_s_label", "알 수 없음")
            battery = meta.get("battery_last", 0)
            task_id = meta.get("current_task_id", "") or ""

            self.map_view.add_robot(r_id, color, QPointF(0, 0))

            card = RobotCard(r_id, s_label, color, battery, "태스크: 로딩 중…" if task_id else "태스크: 없음")
            card.btn_stop_imm.clicked.connect(
                lambda _, rid=r_id, tid=task_id: self._send_cmd(rid, tid, CMD_EMERGENCY_STOP))
            card.btn_stop_next.clicked.connect(
                lambda _, rid=r_id, tid=task_id: self._send_cmd(rid, tid, CMD_CANCEL))
            card.btn_charge.clicked.connect(
                lambda _, rid=r_id, tid=task_id: self._send_cmd(rid, tid, CMD_RETURN_DOCK))
            self._robot_cards[r_id] = card
            self.robots_layout.insertWidget(self.robots_layout.count() - 1, card)
            self.right_title.setText(f"로봇 목록 ({len(self._robot_cards)}대)")

            if task_id:
                self._fetch_task_label(r_id, task_id)

        self.map_view.update_robot_pos(r_id, x, y, yaw)

    def _on_pose_error(self, r_id: str):
        removed = False
        if r_id in self.map_view.robots:
            self.map_view.remove_robot(r_id)
            removed = True
        card = self._robot_cards.pop(r_id, None)
        if card is not None:
            card.deleteLater()
            removed = True
        if removed:
            self.right_title.setText(f"로봇 목록 ({len(self._robot_cards)}대)")

    def _on_battery_updated(self, r_id: str, data: dict):
        card = self._robot_cards.get(r_id)
        if card is not None:
            card.battery_ui.setLevel(int(data.get("battery_percent", 0)))

    def _fetch_task_label(self, r_id: str, task_id: str) -> None:
        w = ApiWorker(self._api.get_task, task_id)
        w.result.connect(lambda data, rid=r_id: self._on_task_label_loaded(rid, data))
        w.error.connect(lambda _, rid=r_id: self._set_card_dest(rid, f"태스크: {task_id[:8]}…"))
        w.finished.connect(lambda: self._discard_worker(w))
        self._workers.append(w)
        w.start()

    def _on_task_label_loaded(self, r_id: str, data: dict) -> None:
        task = data.get("task", {})
        t_type  = int(task.get("task_type", 0))
        dest_id = task.get("dest_id", "")
        label   = TASK_TYPE_LABELS.get(t_type, f"유형{t_type}")
        self._set_card_dest(r_id, f"{label} → {dest_id}" if dest_id else label)

    def _set_card_dest(self, r_id: str, text: str) -> None:
        card = self._robot_cards.get(r_id)
        if card is not None:
            card.dest_lbl.setText(text)

    # ── command dispatch ──────────────────────────────────────────────────────

    def _send_cmd(self, robot_id: str, task_id: str, command: int):
        w = ApiWorker(self._api.send_command, robot_id, task_id, command)
        w.result.connect(lambda _: None)
        w.error.connect(lambda msg: QMessageBox.warning(
            self, "명령 전송 실패", f"{robot_id}: {msg}"))
        w.finished.connect(lambda: self._discard_worker(w))
        self._workers.append(w)
        w.start()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _discard_worker(self, w: ApiWorker):
        if w in self._workers:
            self._workers.remove(w)
