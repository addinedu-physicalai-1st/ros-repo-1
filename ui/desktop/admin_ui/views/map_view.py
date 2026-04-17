import math
import sys
from pathlib import Path
from typing import Optional, Tuple

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QGraphicsView, QGraphicsScene, QScrollArea, QFrame,
                             QMessageBox, QGraphicsLineItem, QGraphicsItem,
                             QMenu, QAction, QInputDialog, QPushButton)
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap, QPen
from PyQt5.QtCore import Qt, QTimer, QPointF, pyqtSignal

from components.map_items import RobotMapItem, WaypointItem, PathLineItem
from components.widgets import RobotCard
from utils.config import (MAP_IMG_PATH, COLOR_MOVING, COLOR_WAITING,
                          COLOR_COLLECT, COLOR_CHARGING,
                          MAP_POSE_SCALE_PX, MAP_ORIGIN_X, MAP_ORIGIN_Y,
                          MAP_ROTATED_CCW90)
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
    """Convert world metres to scene pixels (original map coordinates)."""
    return QPointF(
        MAP_ORIGIN_X + x * MAP_POSE_SCALE_PX,
        MAP_ORIGIN_Y - y * MAP_POSE_SCALE_PX,
    )


def _scene_to_world(sx: float, sy: float) -> Tuple[float, float]:
    """Convert scene pixels to world metres."""
    wx = (sx - MAP_ORIGIN_X) / MAP_POSE_SCALE_PX
    wy = (MAP_ORIGIN_Y - sy) / MAP_POSE_SCALE_PX
    return wx, wy


class MapWidget(QGraphicsView):
    # Signal: (waypoint_label, world_x, world_y)
    waypoint_clicked = pyqtSignal(str, float, float)
    # Signal: emitted when waypoints are saved in edit mode
    waypoints_saved = pyqtSignal()

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

        # Rotate view CCW 90° so physical space matches screen layout
        if MAP_ROTATED_CCW90:
            self.rotate(-90)

        self.robots: dict[str, RobotMapItem] = {}
        self._robot_color_idx: dict[str, int] = {}
        self._next_color_idx = 0

        # Waypoint graph overlay
        self._buffet_map: BuffetMap | None = None
        self._wp_items: list = []
        self._edge_items: list = []

        # Per-robot planned path line items
        self._path_items: dict[str, PathLineItem] = {}

        # Edit mode state
        self._edit_mode = False
        self._dragging_wp: Optional[WaypointItem] = None

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

        # Create planned path line item
        path_item = PathLineItem([], robot_color, dashed=True, opacity=0.7, width=3)
        path_item.setZValue(3)
        self.scene.addItem(path_item)
        self._path_items[r_id] = path_item

    def remove_robot(self, r_id: str) -> None:
        item = self.robots.pop(r_id, None)
        if item is not None:
            self.scene.removeItem(item)
        path = self._path_items.pop(r_id, None)
        if path is not None:
            self.scene.removeItem(path)

    def update_robot_pos(self, r_id: str, x: float, y: float,
                         yaw: float = 0.0) -> None:
        if r_id not in self.robots:
            return
        sp = _world_to_scene(x, y)
        self.robots[r_id].setPos(sp)
        self.robots[r_id].set_yaw(yaw)

    def set_planned_path(self, r_id: str, world_points: list) -> None:
        """Show a planned path for a robot. *world_points* is [(x,y), ...]."""
        path_item = self._path_items.get(r_id)
        if not path_item:
            return
        scene_pts = [_world_to_scene(x, y) for x, y in world_points]
        color = self._get_robot_color(r_id)
        # Remove and re-add to force Qt scene repaint
        self.scene.removeItem(path_item)
        path_item.set_points(scene_pts, color)
        self.scene.addItem(path_item)

    def clear_planned_path(self, r_id: str) -> None:
        """Clear a robot's planned path."""
        path_item = self._path_items.get(r_id)
        if path_item:
            self.scene.removeItem(path_item)
            path_item.set_points([])
            self.scene.addItem(path_item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def fit_view(self):
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    # ── Edit mode ──────────────────────────────────────────────────────

    def toggle_edit_mode(self) -> bool:
        """Toggle edit mode. Returns new state."""
        self._edit_mode = not self._edit_mode
        for item in self._wp_items:
            item.editable = self._edit_mode
            if self._edit_mode:
                item.setFlag(QGraphicsItem.ItemIsMovable, True)
                item.setCursor(Qt.OpenHandCursor)
            else:
                item.setFlag(QGraphicsItem.ItemIsMovable, False)
                item.unsetCursor()
            item.update()
        if not self._edit_mode:
            # Rebuild edges from new positions
            self._rebuild_edges()
        return self._edit_mode

    def _rebuild_edges(self) -> None:
        """Remove old edge lines and redraw from current wp positions."""
        for edge in self._edge_items:
            self.scene.removeItem(edge)
        self._edge_items.clear()

        if not self._buffet_map:
            return
        graph = self._buffet_map.graph
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

    def save_waypoints(self) -> bool:
        """Write current waypoint positions back to the map YAML."""
        if not self._buffet_map:
            return False
        graph = self._buffet_map.graph
        # Update graph waypoints from scene positions
        for item in self._wp_items:
            wp = graph.waypoints.get(item.wp_id)
            if wp:
                sx, sy = item.pos().x(), item.pos().y()
                wx, wy = _scene_to_world(sx, sy)
                from path_planning.map_data import Waypoint
                graph.waypoints[item.wp_id] = Waypoint(
                    wp_id=wp.wp_id, x=wx, y=wy,
                    label=wp.label, yaw=wp.yaw,
                )
        # Rebuild edges and save
        self._buffet_map._rebuild_edges()
        try:
            self._buffet_map.save_to_yaml()
            self._rebuild_edges()
            return True
        except Exception:
            return False

    def mouseReleaseEvent(self, event):
        """After dragging a waypoint, update graph position."""
        super().mouseReleaseEvent(event)
        if self._edit_mode and self._buffet_map:
            for item in self._wp_items:
                wp = self._buffet_map.graph.waypoints.get(item.wp_id)
                if wp:
                    sx, sy = item.pos().x(), item.pos().y()
                    wx, wy = _scene_to_world(sx, sy)
                    from path_planning.map_data import Waypoint
                    self._buffet_map.graph.waypoints[item.wp_id] = Waypoint(
                        wp_id=wp.wp_id, x=wx, y=wy,
                        label=wp.label, yaw=wp.yaw,
                    )
            self._rebuild_edges()

    def mouseDoubleClickEvent(self, event):
        """Double-click on map → find nearest waypoint → emit signal."""
        if self._edit_mode:
            return  # No navigation in edit mode
        if not self._buffet_map:
            return super().mouseDoubleClickEvent(event)

        scene_pos = self.mapToScene(event.pos())
        wx, wy = _scene_to_world(scene_pos.x(), scene_pos.y())

        # Find nearest waypoint
        graph = self._buffet_map.graph
        best_wp, best_d = None, math.inf
        for wp in graph.waypoints.values():
            d = math.hypot(wp.x - wx, wp.y - wy)
            if d < best_d:
                best_d = d
                best_wp = wp

        # Snap threshold (in metres)
        max_snap = max(0.15, self._buffet_map.width_m * 0.08)
        if best_wp and best_d <= max_snap:
            label = best_wp.label or f"({best_wp.x:.2f},{best_wp.y:.2f})"
            self.waypoint_clicked.emit(label, best_wp.x, best_wp.y)
        else:
            super().mouseDoubleClickEvent(event)


class MapDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self._api = ApiClient()
        self._robot_cards: dict[str, RobotCard] = {}
        self._robot_meta: dict[str, dict] = {}
        self._workers: list[ApiWorker] = []

        # Path planning state per robot
        # goal_wp_id → target waypoint id (None = no active goal)
        self._robot_goals: dict[str, tuple[int, str]] = {}  # r_id → (wp_id, label)
        # Cached planned waypoint IDs per robot (for reserved_paths)
        self._robot_planned_wps: dict[str, list[int]] = {}
        # Waypoint visit index per robot (tracks remaining path)
        self._robot_wp_idx: dict[str, int] = {}
        # Latest known world pose per robot
        self._robot_poses: dict[str, tuple[float, float]] = {}

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
        self.map_view.waypoint_clicked.connect(self._on_waypoint_clicked)
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

        # Edit / Save buttons
        self.btn_edit = QPushButton("편집 모드")
        self.btn_edit.setStyleSheet(
            "QPushButton { padding: 4px 12px; font-weight: bold; }"
            "QPushButton:checked { background-color: #ff7f0e; color: white; }"
        )
        self.btn_edit.setCheckable(True)
        self.btn_edit.clicked.connect(self._toggle_edit_mode)
        legend_layout.addWidget(self.btn_edit)

        self.btn_save = QPushButton("저장")
        self.btn_save.setStyleSheet("padding: 4px 12px; font-weight: bold;")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_waypoints)
        legend_layout.addWidget(self.btn_save)

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

        # Also poll robot status to clear path when IDLE/ARRIVED
        wr = ApiWorker(self._api.get_robots)
        wr.result.connect(self._on_robots_status_polled)
        wr.finished.connect(lambda: self._discard_worker(wr))
        self._workers.append(wr)
        wr.start()

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
        self._robot_poses[r_id] = (x, y)

        # Track waypoint visitation (advance index when near next wp)
        wps = self._robot_planned_wps.get(r_id, [])
        idx = self._robot_wp_idx.get(r_id, 0)
        bm = self.map_view._buffet_map
        if wps and idx < len(wps) and bm:
            wp = bm.graph.waypoints.get(wps[idx])
            if wp and math.hypot(x - wp.x, y - wp.y) <= 0.12:
                self._robot_wp_idx[r_id] = idx + 1

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

    def _toggle_edit_mode(self) -> None:
        editing = self.map_view.toggle_edit_mode()
        self.btn_edit.setChecked(editing)
        self.btn_save.setEnabled(editing)
        if editing:
            self.btn_edit.setText("편집 중")
        else:
            self.btn_edit.setText("편집 모드")

    def _save_waypoints(self) -> None:
        if self.map_view.save_waypoints():
            QMessageBox.information(self, "저장 완료", "웨이포인트가 저장되었습니다.")
        else:
            QMessageBox.warning(self, "저장 실패", "맵 파일 저장에 실패했습니다.")

    def _on_robots_status_polled(self, data: dict):
        for robot in data.get("robots", []):
            r_id = robot.get("robot_id", "")
            status = robot.get("status", "")
            # Track which robots are MOVING (protect their goals)
            if status == "MOVING" and r_id:
                self._robot_was_moving = getattr(self, "_robot_was_moving", set())
                self._robot_was_moving.add(r_id)
            # Clear goal ONLY if robot was MOVING and is now IDLE (= arrived)
            if status in ("IDLE", "CHARGING") and r_id:
                was_moving = getattr(self, "_robot_was_moving", set())
                if r_id in was_moving and r_id in self._robot_goals:
                    self._robot_goals.pop(r_id, None)
                    self._robot_planned_wps.pop(r_id, None)
                    self._robot_wp_idx.pop(r_id, None)
                    self.map_view.clear_planned_path(r_id)
                    was_moving.discard(r_id)

        # Replan paths for robots with active goals
        remaining_goals = list(self._robot_goals.keys())
        if remaining_goals:
            print(f"[poll] goals={remaining_goals}", file=sys.stderr, flush=True)
            try:
                self._replan_all_paths()
            except Exception as e:
                import traceback
                traceback.print_exc()

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

    # ── waypoint click → task creation ──────────────────────────────────────

    def _on_waypoint_clicked(self, label: str, wx: float, wy: float) -> None:
        """Double-click on a waypoint → select robot → create task + assign."""
        # Get available (IDLE) robots
        idle_robots = []
        for r_id, meta in self._robot_meta.items():
            if r_id in self.map_view.robots:
                idle_robots.append(r_id)

        if not idle_robots:
            QMessageBox.information(self, "로봇 없음", "연결된 로봇이 없습니다.")
            return

        # Find matching place_id for this waypoint label
        # Map waypoint labels to place_ids
        _LABEL_TO_PLACE = {
            "Kitchen": "KITCHEN",
            "Entrance": "KIOSK_1",
            "Charging": "WAIT_A",
            "Return": "EXIT_DINE",
            "Table-N": "TBL_01",
            "Table-S": "TBL_02",
        }
        dest_id = _LABEL_TO_PLACE.get(label, "")

        if not dest_id:
            QMessageBox.information(
                self, "목적지 미설정",
                f"'{label}' 웨이포인트에 매핑된 place가 없습니다.",
            )
            return

        # Select robot
        if len(idle_robots) == 1:
            robot_id = idle_robots[0]
        else:
            robot_id, ok = QInputDialog.getItem(
                self, "로봇 선택",
                f"'{label}'(으)로 보낼 로봇을 선택하세요:",
                idle_robots, 0, False,
            )
            if not ok:
                return

        # Find goal waypoint ID
        graph = self.map_view._buffet_map.graph if self.map_view._buffet_map else None
        goal_wp_id = None
        if graph:
            best_d = math.inf
            for wp in graph.waypoints.values():
                d = math.hypot(wp.x - wx, wp.y - wy)
                if d < best_d:
                    best_d = d
                    goal_wp_id = wp.wp_id

        # Ensure robot pose is cached (fetch synchronously if needed)
        if robot_id not in self._robot_poses:
            try:
                pose_data = self._api.get_telemetry_pose(robot_id)
                pose = pose_data.get("latest_pose", {})
                self._robot_poses[robot_id] = (
                    float(pose.get("x", 0)), float(pose.get("y", 0)),
                )
            except Exception:
                pass

        # Register goal and replan immediately
        if goal_wp_id is not None:
            self._robot_goals[robot_id] = (goal_wp_id, label)
            import sys
            print(f"[click] {robot_id} goal=wp#{goal_wp_id} ({label}), "
                  f"pose={self._robot_poses.get(robot_id)}",
                  file=sys.stderr, flush=True)
            try:
                self._replan_all_paths()
            except Exception:
                import traceback
                traceback.print_exc()

        # Create task + assign
        self._create_and_assign_task(dest_id, label, robot_id)

    def _create_and_assign_task(self, dest_id: str, label: str,
                                robot_id: str) -> None:
        """Create a MOVE_TO task and assign it to the selected robot."""

        def _do_create():
            result = self._api.create_task(
                task_type=2,  # TABLE_TO_TOILET (generic MOVE_TO)
                dest_id=dest_id,
                requester_id="admin",
                priority=2,
            )
            task_id = result.get("task_id", "")
            if task_id:
                self._api.assign_task(task_id, robot_id)
            return result

        w = ApiWorker(_do_create)
        w.result.connect(
            lambda data: self._on_task_dispatched(robot_id, label, data))
        w.error.connect(lambda msg: QMessageBox.warning(
            self, "태스크 생성 실패", f"{msg}"))
        w.finished.connect(lambda: self._discard_worker(w))
        self._workers.append(w)
        w.start()

    def _replan_all_paths(self) -> None:
        """Recompute paths for all robots with active goals.

        Called periodically from the poll timer. Implements the
        demo monitor's dynamic replanning logic:
        - Each robot's path is computed from its CURRENT position
        - Other robots' planned paths are passed as reserved_paths
        - If a path is blocked, the robot waits (path cleared)
        - When the blocking robot moves away, the path opens up
        """
        bm = self.map_view._buffet_map
        if not bm or not _HAS_PATH_PLANNING:
            return

        from path_planning import plan_path, plan_path_from_point, DynamicObstacle

        graph = bm.graph
        # Sort: robots already moving get priority (plan first)
        sorted_ids = sorted(
            self._robot_goals.keys(),
            key=lambda rid: 0 if rid in self._robot_planned_wps else 1,
        )

        new_plans: dict[str, list[int]] = {}

        for r_id in sorted_ids:
            goal_info = self._robot_goals.get(r_id)
            if not goal_info:
                continue
            goal_wp_id, label = goal_info

            pose = self._robot_poses.get(r_id)
            if not pose:
                continue
            rwx, rwy = pose

            # Check if arrived
            goal_wp = graph.waypoints.get(goal_wp_id)
            if goal_wp and math.hypot(rwx - goal_wp.x, rwy - goal_wp.y) < 0.12:
                self._robot_goals.pop(r_id, None)
                self._robot_planned_wps.pop(r_id, None)
                self._robot_wp_idx.pop(r_id, None)
                self.map_view.clear_planned_path(r_id)
                continue

            # Current robot's nearest waypoint (exclude from reservation)
            current_wp = None
            nearest_d = math.inf
            for wp in graph.waypoints.values():
                d = math.hypot(wp.x - rwx, wp.y - rwy)
                if d < nearest_d:
                    nearest_d = d
                    current_wp = wp.wp_id

            # Dynamic obstacles: all OTHER robots with goals (not self)
            dyn_obs = []
            for other_id, other_pose in self._robot_poses.items():
                if other_id != r_id and other_id in self._robot_goals:
                    dyn_obs.append(DynamicObstacle(
                        obs_id=hash(other_id) & 0xFFFF,
                        x=other_pose[0], y=other_pose[1],
                        radius=0.12, label=other_id,
                    ))

            # Reserved paths: other robots' remaining waypoints
            reserved = []
            for other_id in self._robot_goals:
                if other_id == r_id:
                    continue
                other_wps = new_plans.get(other_id,
                             self._robot_planned_wps.get(other_id, []))
                if not other_wps:
                    continue
                other_idx = self._robot_wp_idx.get(other_id, 0)
                remaining = [w for w in other_wps[other_idx:]
                             if w != current_wp]
                if remaining:
                    reserved.append(remaining)

            # Always snap to nearest waypoint for wp→wp planning
            # (avoids diagonal free-start segments)
            try:
                best_start_wp, best_start_d = None, math.inf
                for wp in graph.waypoints.values():
                    d = math.hypot(wp.x - rwx, wp.y - rwy)
                    if d < best_start_d:
                        best_start_d = d
                        best_start_wp = wp.wp_id

                if best_start_wp is not None and best_start_wp != goal_wp_id:
                    path_wps, cost = plan_path(
                        bm, best_start_wp, goal_wp_id,
                        dynamic_obstacles=dyn_obs if dyn_obs else None,
                        reserved_paths=reserved if reserved else None,
                    )
                    plan_waypoints = path_wps if path_wps else None
                else:
                    plan_waypoints = None
            except Exception as e:
                print(f"[replan] {r_id} error: {e}",
                      file=sys.stderr, flush=True)
                plan_waypoints = None

            if plan_waypoints:
                new_plans[r_id] = list(plan_waypoints)
                self._robot_wp_idx[r_id] = 0
                # Path display: waypoints ONLY (no robot pos → no diagonal)
                points = []
                for wp_id in plan_waypoints:
                    wp = graph.waypoints[wp_id]
                    points.append((wp.x, wp.y))
                print(f"[replan] {r_id} → {label}: {len(plan_waypoints)} wps",
                      file=sys.stderr, flush=True)
                self.map_view.set_planned_path(r_id, points)
            else:
                new_plans[r_id] = []
                print(f"[replan] {r_id} → {label}: BLOCKED",
                      file=sys.stderr, flush=True)
                self.map_view.clear_planned_path(r_id)

        self._robot_planned_wps = new_plans

    def _on_task_dispatched(self, robot_id: str, label: str, data: dict):
        task_id = data.get("task_id", "?")
        card = self._robot_cards.get(robot_id)
        if card:
            card.dest_lbl.setText(f"→ {label}")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _discard_worker(self, w: ApiWorker):
        if w in self._workers:
            self._workers.remove(w)
