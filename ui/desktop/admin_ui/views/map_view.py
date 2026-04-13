from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QGraphicsView, QGraphicsScene, QScrollArea, QFrame,
                             QMessageBox)
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt5.QtCore import Qt, QTimer, QPointF

from components.map_items import RobotMapItem
from components.widgets import RobotCard
from utils.config import (MAP_IMG_PATH, COLOR_MOVING, COLOR_WAITING,
                          COLOR_COLLECT, COLOR_CHARGING,
                          MAP_POSE_SCALE_PX, MAP_ORIGIN_X, MAP_ORIGIN_Y)
from utils.api_client import (ApiClient, ApiWorker,
                              CMD_CANCEL, CMD_RETURN_DOCK, CMD_EMERGENCY_STOP,
                              ROBOT_STATUS_LABELS)


# Map RobotStatus int → display colour
_STATUS_COLORS: dict[int, QColor] = {
    1: COLOR_WAITING,          # IDLE
    2: COLOR_MOVING,           # MOVING
    3: COLOR_MOVING,           # ARRIVED
    4: COLOR_CHARGING,         # CHARGING
    5: QColor("#F56C6C"),      # ERROR
    6: QColor("#909399"),      # OFFLINE
}


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

    def add_robot(self, r_id: str, color: QColor, pos: QPointF) -> None:
        robot = RobotMapItem(r_id, color, pos)
        self.scene.addItem(robot)
        self.robots[r_id] = robot

    def update_robot_pos(self, r_id: str, x: float, y: float) -> None:
        """Move a robot marker using ROS /odom pose coordinates (metres).

        Coordinate mapping (derived from map4.yaml, 10x upscaled):
            scene_x = MAP_ORIGIN_X + x * MAP_POSE_SCALE_PX
            scene_y = MAP_ORIGIN_Y - y * MAP_POSE_SCALE_PX  (screen y inverted)

        Override via env-vars MAP_ORIGIN_X, MAP_ORIGIN_Y, MAP_POSE_SCALE_PX
        if the map or spawn position changes.
        """
        if r_id not in self.robots:
            return
        cx = MAP_ORIGIN_X + x * MAP_POSE_SCALE_PX
        cy = MAP_ORIGIN_Y - y * MAP_POSE_SCALE_PX
        self.robots[r_id].setPos(QPointF(cx, cy))

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
        self._robot_meta: dict[str, dict] = {}   # robot_id → latest robot dict
        self._workers: list[ApiWorker] = []       # keep references alive

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
        count = len(robots)
        self.right_title.setText(f"로봇 목록 ({count}대)")
        self.right_title.setStyleSheet("")

        # Clear map scene (re-add background) and robot list
        self.map_view.scene.clear()
        self.map_view.scene.addPixmap(self.map_view.bg_pixmap)
        self.map_view.robots.clear()
        self._robot_cards.clear()
        self._robot_meta.clear()

        while self.robots_layout.count() > 1:
            item = self.robots_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        w_img = self.map_view.bg_pixmap.width()
        h_img = self.map_view.bg_pixmap.height()

        for idx, robot in enumerate(robots):
            r_id      = robot.get("robot_id", f"R{idx + 1}")
            status_i  = robot.get("status", 0)
            battery   = robot.get("battery_last", 0)
            task_id   = robot.get("current_task_id", "") or ""
            color     = _STATUS_COLORS.get(status_i, QColor("#999999"))
            s_label   = ROBOT_STATUS_LABELS.get(status_i, "알 수 없음")

            self._robot_meta[r_id] = robot

            # Spread robots across the map horizontally
            fx = 0.2 + (idx / max(count - 1, 1)) * 0.6 if count > 1 else 0.5
            pos = QPointF(w_img * fx, h_img * 0.5)
            self.map_view.add_robot(r_id, color, pos)

            card = RobotCard(r_id, s_label, color, battery, f"태스크: {task_id or '없음'}")
            self._robot_cards[r_id] = card

            # Wire up command buttons
            card.btn_stop_imm.clicked.connect(
                lambda _, rid=r_id, tid=task_id: self._send_cmd(rid, tid, CMD_EMERGENCY_STOP))
            card.btn_stop_next.clicked.connect(
                lambda _, rid=r_id, tid=task_id: self._send_cmd(rid, tid, CMD_CANCEL))
            card.btn_charge.clicked.connect(
                lambda _, rid=r_id, tid=task_id: self._send_cmd(rid, tid, CMD_RETURN_DOCK))

            self.robots_layout.insertWidget(self.robots_layout.count() - 1, card)

        QTimer.singleShot(100, self.map_view.fit_view)
        # Start polling telemetry every 2 seconds
        self._poll_timer.start(2000)

    # ── periodic pose polling ─────────────────────────────────────────────────

    def _poll_all_poses(self):
        for r_id in list(self.map_view.robots.keys()):
            w = ApiWorker(self._api.get_telemetry_pose, r_id)
            w.result.connect(lambda data, rid=r_id: self._on_pose_updated(rid, data))
            # 404 is expected for robots that have never sent telemetry — ignore
            w.finished.connect(lambda: self._discard_worker(w))
            self._workers.append(w)
            w.start()

    def _on_pose_updated(self, r_id: str, data: dict):
        pose = data.get("latest_pose", {})
        x = float(pose.get("x", 0.0))
        y = float(pose.get("y", 0.0))
        self.map_view.update_robot_pos(r_id, x, y)

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
