from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QGridLayout, QDialog, QDialogButtonBox,
                             QComboBox, QMessageBox, QFormLayout,
                             QProgressBar, QScrollArea, QLineEdit, QGraphicsOpacityEffect, QMenu)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QTimer

import datetime as _dt

from utils.api_client import (ApiClient, ApiWorker,
                              TASK_STATUS_LABELS, TASK_TYPE_LABELS)
from utils.config import COLOR_MOVING, COLOR_WAITING, COLOR_COLLECT, COLOR_CHARGING, CARD_STYLE
from utils.scheduler import TaskScheduler, TaskType, TaskStatus
from components.widgets import BatteryWidget


_STATUS_TO_INT: dict = {
    "PENDING": 1, "IN_PROGRESS": 2, "COMPLETED": 3, "FAILED": 4, "CANCELLED": 5,
}
_TASKTYPE_TO_INT: dict = {
    "KIOSK_TO_TABLE": 1, "TABLE_TO_TOILET": 2, "TABLE_TO_DISPLAY": 3,
    "DISH_PICKUP": 4, "ROBOT_SWAP": 5, "ESCORT_SERVICE": 6, "RETURN_TO_DOCK": 7,
}
_PRIORITY_TO_INT: dict = {
    "LOW": 1, "NORMAL": 2, "HIGH": 3, "CRITICAL": 4,
}


def _status_int(val) -> int:
    """proto enum 문자열('PENDING') 또는 정수(1) 모두 정수로 변환."""
    if isinstance(val, int):
        return val
    return _STATUS_TO_INT.get(str(val), 0)


def _tasktype_int(val) -> int:
    """proto enum 문자열('TABLE_TO_TOILET') 또는 정수(2) 모두 정수로 변환."""
    if isinstance(val, int):
        return val
    return _TASKTYPE_TO_INT.get(str(val), 0)


def _priority_int(val) -> int:
    """proto enum 문자열('HIGH') 또는 정수(3) 모두 정수로 변환."""
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        return _PRIORITY_TO_INT.get(str(val).upper(), 2)


class _RealTask:
    """서버 태스크 dict → RobotStatusCard.update_state() duck-type 어댑터."""
    def __init__(self, task_dict: dict) -> None:
        t_type   = _tasktype_int(task_dict.get("task_type", 0))
        status_i = _status_int(task_dict.get("status", 0))
        dest_id  = task_dict.get("dest_id", "")
        self.task_id  = task_dict.get("task_id", "")
        self.robot_id = task_dict.get("robot_id", "")
        self.type     = f"{TASK_TYPE_LABELS.get(t_type, str(t_type))} → {dest_id}"
        self.progress = {1: 0, 2: 50, 3: 100, 4: 0, 5: 0}.get(status_i, 0)
        self.status   = {
            1: TaskStatus.PENDING,
            2: TaskStatus.MOVING,
            3: TaskStatus.COMPLETED,
            4: TaskStatus.FAILED,
        }.get(status_i, TaskStatus.PENDING)


_TASK_TYPE_OPTIONS = [
    (1, "키오스크→테이블 (KIOSK_TO_TABLE)"),
    (2, "테이블→화장실 (TABLE_TO_TOILET)"),
    (3, "테이블→디스플레이 (TABLE_TO_DISPLAY)"),
    (4, "식기 수거 (DISH_PICKUP)"),
    (5, "로봇 교체 (ROBOT_SWAP)"),
    (6, "안내 서비스 (ESCORT_SERVICE)"),
    (7, "도킹 복귀 (RETURN_TO_DOCK)"),
]

# Maps scheduling TaskType constants to server task_type int for CreateTaskDialog
_TASK_TYPE_MAP = {
    TaskType.COLLECT: 4,
    TaskType.GUIDE:   6,
    TaskType.FOLLOW:  6,
    TaskType.SERVING: 1,
}

_TASK_CARD_INFO = [
    (TaskType.SERVING, "🥘", "서빙 요청",      COLOR_MOVING,   1),
    (TaskType.FOLLOW,  "👥", "동행 이동",      QColor("#9C27B0"), 6),
    (TaskType.GUIDE,   "💁", "고객 안내",      QColor("#67C23A"), 6),
    (TaskType.COLLECT, "🧺", "식기 수거 (우선)", COLOR_COLLECT,  4),
]


# ── CreateTaskDialog ──────────────────────────────────────────────────────────

class CreateTaskDialog(QDialog):
    """Dialog to create a new task via POST /tasks."""

    def __init__(self, task_type_hint: int, places: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("새 작업 지시")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.combo_type = QComboBox()
        for val, label in _TASK_TYPE_OPTIONS:
            self.combo_type.addItem(label, val)
        for i, (val, _) in enumerate(_TASK_TYPE_OPTIONS):
            if val == task_type_hint:
                self.combo_type.setCurrentIndex(i)
                break
        form.addRow("작업 유형:", self.combo_type)

        self.combo_dest = QComboBox()
        if places:
            for p in places:
                self.combo_dest.addItem(p.get("name", p.get("place_id", "")), p.get("place_id", ""))
        else:
            self.combo_dest.addItem("장소 정보 없음", "")
        form.addRow("목적지:", self.combo_dest)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_task_type(self) -> int:
        return self.combo_type.currentData()

    def get_dest_id(self) -> str:
        return self.combo_dest.currentData() or ""


# ── FsmIndicator ─────────────────────────────────────────────────────────────

class FsmIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()

    def initUI(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 5, 0, 5)
        self.layout.setSpacing(5)
        self.steps = ["대기", "이동", "도착", "작업", "완료"]
        self.labels = []
        for s in self.steps:
            lbl = QLabel(s)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #C0C4CC; font-size: 10px; padding: 2px 5px; border: 1px solid #DCDFE6; border-radius: 4px;")
            self.labels.append(lbl)
            self.layout.addWidget(lbl)
            if s != "완료":
                self.layout.addWidget(QLabel("→"))

    def set_status(self, status):
        idx = -1
        if status == TaskStatus.RETURNING_TO_CHARGER:
            self.labels[0].setText("복귀")
            self.labels[1].setText("이동")
            idx = 1
        elif status == TaskStatus.CHARGING:
            self.labels[0].setText("복귀")
            self.labels[1].setText("이동")
            self.labels[2].setText("충전중")
            idx = 2
        else:
            self.labels[0].setText("대기")
            self.labels[1].setText("이동")
            self.labels[2].setText("도착")
            if status == TaskStatus.PENDING: idx = 0
            elif status == TaskStatus.MOVING: idx = 1
            elif status == TaskStatus.ARRIVED: idx = 2
            elif status == TaskStatus.WORKING: idx = 3
            elif status == TaskStatus.COMPLETED: idx = 4

        for i, lbl in enumerate(self.labels):
            if i == idx:
                lbl.setStyleSheet("background-color: #4A88D4; color: white; font-size: 10px; padding: 2px 5px; border-radius: 4px; font-weight: bold;")
            elif i < idx and idx != -1:
                lbl.setStyleSheet("background-color: #E1F3D8; color: #67C23A; font-size: 10px; padding: 2px 5px; border-radius: 4px;")
            else:
                lbl.setStyleSheet("color: #C0C4CC; font-size: 10px; padding: 2px 5px; border: 1px solid #DCDFE6; border-radius: 4px;")


# ── RobotStatusCard ───────────────────────────────────────────────────────────

class RobotStatusCard(QFrame):
    def __init__(self, robot_id, scheduler, api, parent=None):
        super().__init__(parent)
        self.robot_id = robot_id
        self.scheduler = scheduler
        self._api = api
        self._current_task_id: str = ""
        self._workers: list = []
        self.initUI()

    def initUI(self):
        self.setStyleSheet(CARD_STYLE)
        self.layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.id_lbl = QLabel(f"🤖 {self.robot_id}")
        self.id_lbl.setFont(QFont("Malgun Gothic", 12, QFont.Bold))

        self.collector_badge = QLabel("수거 전담")
        self.collector_badge.setStyleSheet("background-color: #F56C6C; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;")
        self.collector_badge.setVisible(False)

        self.battery_ui = BatteryWidget(100)

        header.addWidget(self.id_lbl)
        header.addWidget(self.collector_badge)
        header.addStretch()
        header.addWidget(self.battery_ui)

        self.info_stack = QWidget()
        self.info_layout = QVBoxLayout(self.info_stack)
        self.info_layout.setContentsMargins(0, 0, 0, 0)

        self.active_widget = QWidget()
        active_lay = QVBoxLayout(self.active_widget)
        active_lay.setContentsMargins(0, 0, 0, 0)

        self.task_type_lbl = QLabel("")
        self.task_type_lbl.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
        self.fsm = FsmIndicator()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("QProgressBar { border-radius: 4px; background: #EBEEF5; } QProgressBar::chunk { background: #4A88D4; border-radius: 4px; }")

        self.action_row = QHBoxLayout()
        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setStyleSheet("background: #FEF0F0; color: #F56C6C; border: 1px solid #FBC4C4; border-radius: 4px; padding: 3px 8px;")
        self.btn_cancel.clicked.connect(self.cancel_task)
        self.btn_assign = QPushButton("▼ 수동 할당")
        self.btn_assign.setStyleSheet("background: #f0f9eb; color: #67c23a; border: 1px solid #c2e7b0; border-radius: 4px; padding: 3px 8px;")
        self.btn_assign.clicked.connect(self.show_assign_menu)
        self.action_row.addWidget(self.btn_cancel)
        self.action_row.addWidget(self.btn_assign)

        active_lay.addWidget(self.task_type_lbl)
        active_lay.addWidget(self.fsm)
        active_lay.addWidget(self.progress_bar)
        active_lay.addLayout(self.action_row)

        self.idle_widget = QWidget()
        idle_lay = QVBoxLayout(self.idle_widget)
        idle_lay.setContentsMargins(0, 0, 0, 0)
        idle_lbl = QLabel("대기 중 — 태스크 없음")
        idle_lbl.setStyleSheet("color: #C0C4CC; font-style: italic;")
        idle_lay.addWidget(idle_lbl)

        self.info_layout.addWidget(self.active_widget)
        self.info_layout.addWidget(self.idle_widget)

        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)

        self.layout.addLayout(header)
        self.layout.addWidget(self.info_stack)

    def cancel_task(self):
        if not self._current_task_id:
            return
        reply = QMessageBox.question(
            self, "작업 취소 확인",
            f"로봇 {self.robot_id}의 작업을 취소하고\n대기장소로 복귀시키겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.btn_cancel.setEnabled(False)
        w = ApiWorker(self._api.cancel_task, self._current_task_id)
        w.result.connect(self._on_cancel_done)
        w.error.connect(self._on_cancel_error)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _on_cancel_done(self, data: dict):
        self.btn_cancel.setEnabled(True)
        action = data.get("action", "")
        if action == "cancel_and_return_dock":
            dock = data.get("dock_id", "")
            QMessageBox.information(self, "취소 완료",
                f"작업이 취소되었습니다.\n로봇 {self.robot_id}이(가) 대기장소({dock})로 복귀합니다.")
        else:
            QMessageBox.information(self, "취소 완료", "대기 중 작업이 취소되었습니다.")

    def _on_cancel_error(self, msg: str):
        self.btn_cancel.setEnabled(True)
        QMessageBox.warning(self, "취소 실패", f"작업 취소에 실패했습니다.\n{msg}")

    def show_assign_menu(self):
        menu = QMenu(self)
        pending = self.scheduler.pending_queue
        if not pending:
            menu.addAction("(대기 중인 태스크 없음)").setEnabled(False)
        else:
            for task in pending:
                action = menu.addAction(f"{task.id} — {task.type}")
                action.triggered.connect(lambda checked, tid=task.id: self.scheduler.manual_assign(tid, self.robot_id))
        menu.exec_(self.btn_assign.mapToGlobal(self.btn_assign.rect().bottomLeft()))

    def update_state(self, task, stats):
        battery = stats.get("battery", 100)
        self.battery_ui.setLevel(battery)

        if task:
            self._current_task_id = getattr(task, "task_id", "")
            self.opacity_effect.setOpacity(1.0)
            self.active_widget.setVisible(True)
            self.idle_widget.setVisible(False)
            self.task_type_lbl.setText(f"작업: {task.type}")
            self.fsm.set_status(task.status)
            self.progress_bar.setValue(int(task.progress))
            is_collector = (self.robot_id == self.scheduler.collector_robot_id and task.type == TaskType.COLLECT)
            self.collector_badge.setVisible(is_collector)
            self.btn_cancel.setEnabled(True)
        else:
            self._current_task_id = ""
            self.opacity_effect.setOpacity(0.5)
            self.active_widget.setVisible(False)
            self.idle_widget.setVisible(True)
            self.collector_badge.setVisible(False)


# ── TaskManagementPage ────────────────────────────────────────────────────────

class TaskManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        # Real API client
        self._api = ApiClient()
        self._workers: list[ApiWorker] = []
        self._places: list[dict] = []

        # Mock scheduler (로봇 카드 시그널 연결용으로만 유지)
        self.scheduler = TaskScheduler()

        self._real_inprogress: dict[str, dict] = {}   # robot_id → 진행 중 태스크

        self.initUI()

        # Auto-refresh: 5초마다 서버 태스크 목록 갱신
        self._task_refresh_timer = QTimer(self)
        self._task_refresh_timer.timeout.connect(self._load_tasks)
        self._task_refresh_timer.start(5000)

        # Load real tasks and places from server
        self._load_places_then_tasks()
        # Load active robots for monitor panel
        self._monitor_pending: int = 0
        self._monitor_active: list[str] = []
        self._real_battery: dict[str, int] = {}   # robot_id -> latest real battery %
        self._no_robots_lbl: QLabel | None = None
        self._load_active_robots_for_monitor()

    def initUI(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        # ── 1. Top Panel: Task Creation Buttons ───────────────────────────────
        top_panel = QFrame()
        top_layout = QGridLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)

        for i, (task_type_name, icon, desc, color, task_type_int) in enumerate(_TASK_CARD_INFO):
            card = QFrame()
            if isinstance(color, QColor):
                color_name = color.name()
            else:
                color_name = color
            card.setStyleSheet(f"background-color: white; border: 2px solid {color_name}; border-radius: 12px;")
            c_layout = QVBoxLayout(card)

            i_lbl = QLabel(icon)
            i_lbl.setFont(QFont("Arial", 24))
            i_lbl.setAlignment(Qt.AlignCenter)

            n_lbl = QLabel(desc)
            n_lbl.setFont(QFont("Malgun Gothic", 13, QFont.Bold))
            n_lbl.setAlignment(Qt.AlignCenter)
            n_lbl.setStyleSheet(f"color: {color_name}; border: none;")

            btn = QPushButton("작업 지시")
            btn.setStyleSheet(f"background-color: {color_name}; color: white; padding: 10px; border-radius: 6px; font-weight: bold;")
            btn.clicked.connect(lambda checked, tt=task_type_int: self._open_create_dialog(tt))

            c_layout.addWidget(i_lbl)
            c_layout.addWidget(n_lbl)
            c_layout.addStretch()
            c_layout.addWidget(btn)
            top_layout.addWidget(card, 0, i)

        self.main_layout.addWidget(top_panel)

        # ── 2. Middle Panel: Robot Monitor + Queue ────────────────────────────
        mid_panel = QHBoxLayout()

        # 2a. Robot Status Cards
        monitor_frame = QFrame()
        monitor_frame.setStyleSheet(CARD_STYLE)
        monitor_layout = QVBoxLayout(monitor_frame)

        mon_header = QHBoxLayout()
        mon_title = QLabel("🤖 로봇 상태 모니터")
        mon_title.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        mon_header.addWidget(mon_title)
        mon_header.addStretch()
        self._monitor_refresh_btn = QPushButton("🔄 새로 고침")
        self._monitor_refresh_btn.setStyleSheet(
            "background-color: #409EFF; color: white; padding: 4px 10px; border-radius: 4px;"
        )
        self._monitor_refresh_btn.clicked.connect(self._load_active_robots_for_monitor)
        mon_header.addWidget(self._monitor_refresh_btn)
        monitor_layout.addLayout(mon_header)

        self.robot_cards: dict[str, RobotStatusCard] = {}
        self._monitor_layout = monitor_layout   # card insertion reference
        self._monitor_status_lbl = QLabel("활성 로봇 확인 중...")
        self._monitor_status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        monitor_layout.addWidget(self._monitor_status_lbl)
        monitor_layout.addStretch()
        mid_panel.addWidget(monitor_frame, 2)

        # 2b. Task Queue Table
        queue_frame = QFrame()
        queue_frame.setStyleSheet(CARD_STYLE)
        queue_layout = QVBoxLayout(queue_frame)

        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("📋 태스크 대기열 (대기 중)"))
        queue_header.addStretch()
        queue_layout.addLayout(queue_header)

        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["ID", "유형", "로봇", "액션"])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_table.setStyleSheet("border: none;")
        queue_layout.addWidget(self.queue_table)

        mid_panel.addWidget(queue_frame, 3)
        self.main_layout.addLayout(mid_panel, 2)

        # ── 3. Real Task Table from API ───────────────────────────────────────
        api_frame = QFrame()
        api_frame.setStyleSheet(CARD_STYLE)
        api_layout = QVBoxLayout(api_frame)

        api_header = QHBoxLayout()
        api_title = QLabel("▶ 현재 진행 중인 태스크 (서버)")
        api_title.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        api_header.addWidget(api_title)
        api_header.addStretch()

        refresh_btn = QPushButton("🔄 새로 고침")
        refresh_btn.setStyleSheet("background-color: #409EFF; color: white; padding: 6px 12px; border-radius: 4px; font-weight: bold;")
        refresh_btn.clicked.connect(self._load_tasks)
        api_header.addWidget(refresh_btn)
        api_layout.addLayout(api_header)

        self.task_table = QTableWidget(0, 5)
        self.task_table.setHorizontalHeaderLabels(["작업 ID", "작업 유형", "할당된 로봇", "진행 상태", "관리"])
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")
        api_layout.addWidget(self.task_table)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        api_layout.addWidget(self._status_lbl)

        self.main_layout.addWidget(api_frame, 2)

        # ── 4. Bottom: History Log ─────────────────────────────────────────────
        log_frame = QFrame()
        log_frame.setStyleSheet(CARD_STYLE)
        log_layout = QVBoxLayout(log_frame)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("📜 전체 작업 이력 로그"))
        log_header.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("ID 또는 로봇 검색...")
        self.search_input.setFixedWidth(200)
        log_header.addWidget(self.search_input)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["전체 유형", TaskType.SERVING, TaskType.COLLECT, TaskType.GUIDE, TaskType.FOLLOW])
        log_header.addWidget(self.filter_combo)
        log_layout.addLayout(log_header)

        self.log_table = QTableWidget(0, 7)
        self.log_table.setHorizontalHeaderLabels(["ID", "유형", "요청시간", "로봇", "상태", "수행시간(예상)", "순위"])
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.log_table.setStyleSheet("border: none;")
        log_layout.addWidget(self.log_table)

        self.main_layout.addWidget(log_frame, 2)

    # ── Active robot monitor ──────────────────────────────────────────────────

    def _load_active_robots_for_monitor(self):
        """Fetch DB robot list then keep only those with live pose telemetry."""
        self._monitor_pending = 0
        self._monitor_active = []
        self._monitor_status_lbl.setText("활성 로봇 확인 중...")
        self._monitor_status_lbl.setVisible(True)
        w = ApiWorker(self._api.get_robots)
        w.result.connect(self._on_monitor_robots_loaded)
        w.error.connect(lambda _: self._monitor_status_lbl.setText("로봇 목록 로드 실패"))
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _on_monitor_robots_loaded(self, data: dict):
        all_robots = data.get("robots", [])
        self._monitor_pending = len(all_robots)
        self._monitor_active = []
        if not all_robots:
            self._build_monitor_cards([])
            return
        for robot in all_robots:
            r_id = robot.get("robot_id", "")
            w = ApiWorker(self._api.get_telemetry_pose, r_id)
            w.result.connect(lambda _, rid=r_id: self._on_monitor_pose_done(rid, active=True))
            w.error.connect(lambda _, rid=r_id: self._on_monitor_pose_done(rid, active=False))
            w.finished.connect(lambda: self._discard(w))
            self._workers.append(w)
            w.start()

    def _on_monitor_pose_done(self, r_id: str, active: bool):
        if active:
            self._monitor_active.append(r_id)
        self._monitor_pending -= 1
        if self._monitor_pending <= 0:
            self._build_monitor_cards(self._monitor_active)

    def _build_monitor_cards(self, active_ids: list):
        if self._no_robots_lbl is not None:
            self._no_robots_lbl.deleteLater()
            self._no_robots_lbl = None
        for card in self.robot_cards.values():
            card.deleteLater()
        self.robot_cards.clear()
        self._monitor_status_lbl.setVisible(False)

        # Sync scheduler robot list with real active robots
        self.scheduler.robots = list(active_ids)
        for rid in active_ids:
            if rid not in self.scheduler.robot_stats:
                self.scheduler.robot_stats[rid] = {
                    "battery": 100, "status": "Idle", "is_emergency": False
                }

        # Remove stretch, insert cards, re-add stretch
        stretch_item = self._monitor_layout.takeAt(self._monitor_layout.count() - 1)
        for rid in active_ids:
            card = RobotStatusCard(rid, self.scheduler, self._api)
            self.robot_cards[rid] = card
            self._monitor_layout.addWidget(card)
        if stretch_item:
            self._monitor_layout.addItem(stretch_item)

        if not active_ids:
            self._no_robots_lbl = QLabel("활성 로봇 없음")
            self._no_robots_lbl.setStyleSheet("color: #C0C4CC; font-style: italic;")
            self._monitor_layout.insertWidget(self._monitor_layout.count() - 1, self._no_robots_lbl)

        # (Re)start real battery polling timer
        if hasattr(self, "_battery_timer"):
            self._battery_timer.stop()
        if active_ids:
            self._battery_timer = QTimer(self)
            self._battery_timer.timeout.connect(self._poll_real_battery)
            self._battery_timer.start(5000)
            self._poll_real_battery()

    # ── Real battery polling ──────────────────────────────────────────────────

    def _poll_real_battery(self):
        for r_id in list(self.robot_cards.keys()):
            w = ApiWorker(self._api.get_telemetry_battery, r_id)
            w.result.connect(lambda data, rid=r_id: self._on_battery_data(rid, data))
            w.error.connect(lambda _, rid=r_id: self._on_battery_data(rid, {}))  # 404 → 0%
            w.finished.connect(lambda: self._discard(w))
            self._workers.append(w)
            w.start()

    def _on_battery_data(self, r_id: str, data: dict):
        self._real_battery[r_id] = int(data.get("battery_percent", 0))
        card = self.robot_cards.get(r_id)
        if card is not None:
            card.battery_ui.setLevel(self._real_battery[r_id])

    # ── Real API: data loading ────────────────────────────────────────────────

    def _load_places_then_tasks(self):
        w = ApiWorker(self._api.get_places)
        w.result.connect(self._on_places_loaded)
        w.error.connect(lambda _: self._load_tasks())
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _on_places_loaded(self, data: dict):
        self._places = data.get("places", [])
        self._load_tasks()

    def _load_tasks(self):
        self._status_lbl.setText("태스크 목록 로딩 중...")
        self.task_table.setRowCount(0)
        w = ApiWorker(self._api.get_tasks)
        w.result.connect(self._on_tasks_loaded)
        w.error.connect(self._on_task_error)
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _on_task_error(self, msg: str):
        self._status_lbl.setText(f"서버 오류: {msg}")
        self._status_lbl.setStyleSheet("color: #F56C6C; font-style: italic;")

    def _on_tasks_loaded(self, data: dict):
        tasks = data.get("tasks", [])
        self._status_lbl.setText(f"총 {data.get('total', len(tasks))}건")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        self.task_table.setRowCount(0)

        for task in tasks:
            task_id  = task.get("task_id", "")
            t_type   = _tasktype_int(task.get("task_type", 0))
            robot_id = task.get("robot_id", "") or "미할당"
            status_i = _status_int(task.get("status", 0))
            dest_id  = task.get("dest_id", "")

            row = self.task_table.rowCount()
            self.task_table.insertRow(row)
            self.task_table.setItem(row, 0, QTableWidgetItem(task_id[:8] + "…" if len(task_id) > 8 else task_id))
            self.task_table.setItem(row, 1, QTableWidgetItem(
                f"{TASK_TYPE_LABELS.get(t_type, str(t_type))} → {dest_id}"))
            self.task_table.setItem(row, 2, QTableWidgetItem(robot_id))
            self.task_table.setItem(row, 3, QTableWidgetItem(
                TASK_STATUS_LABELS.get(status_i, str(status_i))))

            cancel_btn = QPushButton("강제 취소")
            cancel_btn.setStyleSheet("background-color: #F56C6C; color: white; padding: 4px 10px; border-radius: 3px;")
            cancel_btn.clicked.connect(lambda _, tid=task_id, rid=robot_id: self._confirm_and_cancel(tid, rid))
            self.task_table.setCellWidget(row, 4, cancel_btn)

        # ── 대기열 테이블: PENDING(1) 태스크 ─────────────────────────
        pending = [t for t in tasks if _status_int(t.get("status", 0)) == 1]
        self.queue_table.setRowCount(len(pending))
        for i, t in enumerate(pending):
            tid   = t.get("task_id", "")
            ttype = _tasktype_int(t.get("task_type", 0))
            dest  = t.get("dest_id", "")
            label = TASK_TYPE_LABELS.get(ttype, str(ttype))
            self.queue_table.setItem(i, 0, QTableWidgetItem(tid[:8] + "…" if len(tid) > 8 else tid))
            self.queue_table.setItem(i, 1, QTableWidgetItem(f"{label} → {dest}"))
            self.queue_table.setItem(i, 2, QTableWidgetItem("미할당"))
            self.queue_table.setItem(i, 3, QTableWidgetItem("—"))

        # ── 이력 로그: COMPLETED(3)/FAILED(4)/CANCELLED(5) 태스크 ───
        done = [t for t in tasks if _status_int(t.get("status", 0)) in (3, 4, 5)]
        self.log_table.setRowCount(len(done))
        for i, t in enumerate(done):
            tid      = t.get("task_id", "")
            ttype    = _tasktype_int(t.get("task_type", 0))
            robot    = t.get("robot_id", "") or "-"
            status_i = _status_int(t.get("status", 0))
            priority = _priority_int(t.get("priority", 2))
            created  = t.get("created_at_ms", 0)
            try:
                t_str = _dt.datetime.fromtimestamp(int(created) / 1000).strftime("%H:%M:%S") if created else "-"
            except Exception:
                t_str = "-"
            label    = TASK_TYPE_LABELS.get(ttype, str(ttype))
            status_s = TASK_STATUS_LABELS.get(status_i, str(status_i))
            prio_s   = "높음" if priority >= 3 else "보통"
            vals = [tid[:8] + "…" if len(tid) > 8 else tid, label, t_str, robot, status_s, "-", prio_s]
            for j, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if j == 4:
                    item.setForeground(QColor("#67C23A") if status_i == 3 else QColor("#F56C6C"))
                self.log_table.setItem(i, j, item)

        # ── 로봇 카드: IN_PROGRESS(2) 태스크 매핑 ────────────────────
        self._real_inprogress = {
            t.get("robot_id"): t
            for t in tasks
            if _status_int(t.get("status", 0)) == 2 and t.get("robot_id")
        }
        self._refresh_robot_cards()

    # ── Real API: task creation ───────────────────────────────────────────────

    def _open_create_dialog(self, task_type_hint: int):
        dlg = CreateTaskDialog(task_type_hint, self._places, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        t_type  = dlg.get_task_type()
        dest_id = dlg.get_dest_id()
        if not dest_id:
            QMessageBox.warning(self, "입력 오류", "유효한 목적지를 선택하세요.")
            return
        w = ApiWorker(self._api.create_task, t_type, dest_id)
        w.result.connect(self._on_task_created)
        w.error.connect(lambda msg: QMessageBox.warning(self, "태스크 생성 실패", msg))
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _on_task_created(self, data: dict):
        task_id = data.get("task_id", "")
        QMessageBox.information(
            self, "태스크 생성 완료",
            f"태스크가 생성되었습니다.\n태스크 ID: {task_id}")
        QTimer.singleShot(500, self._load_tasks)

    def _refresh_robot_cards(self) -> None:
        """실서버 IN_PROGRESS 태스크로 로봇 카드 업데이트."""
        for rid, card in self.robot_cards.items():
            task_dict = self._real_inprogress.get(rid)
            stats = {"battery": self._real_battery.get(rid, 100)}
            task_obj = _RealTask(task_dict) if task_dict else None
            card.update_state(task_obj, stats)

    def update_ui(self):
        self._refresh_robot_cards()

    def _confirm_and_cancel(self, task_id: str, robot_id: str):
        """하단 테이블의 강제 취소 버튼 핸들러."""
        robot_str = f"로봇 {robot_id}" if robot_id and robot_id != "미할당" else "미배정 작업"
        reply = QMessageBox.question(
            self, "강제 취소 확인",
            f"{robot_str}의 작업({task_id[:8]}…)을 취소하겠습니까?\n"
            "진행 중인 경우 로봇이 대기장소로 복귀합니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        w = ApiWorker(self._api.cancel_task, task_id)
        w.result.connect(lambda data: self._on_force_cancel_done(data, robot_id))
        w.error.connect(lambda msg: QMessageBox.warning(self, "취소 실패", f"작업 취소 실패\n{msg}"))
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _on_force_cancel_done(self, data: dict, robot_id: str):
        action = data.get("action", "")
        if action == "cancel_and_return_dock":
            dock = data.get("dock_id", "")
            QMessageBox.information(self, "취소 완료",
                f"작업이 취소되었습니다.\n로봇 {robot_id}이(가) 대기장소({dock})로 복귀합니다.")
        else:
            QMessageBox.information(self, "취소 완료", "작업이 취소되었습니다.")
        QTimer.singleShot(500, self._load_tasks)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _discard(self, w: ApiWorker):
        if w in self._workers:
            self._workers.remove(w)
