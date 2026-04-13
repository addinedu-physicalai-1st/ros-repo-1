from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QGridLayout, QDialog, QDialogButtonBox,
                             QComboBox, QMessageBox, QFormLayout)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QTimer

from utils.api_client import (ApiClient, ApiWorker,
                              TASK_STATUS_LABELS, TASK_TYPE_LABELS)


_TASK_TYPE_OPTIONS = [
    (1, "키오스크→테이블 (KIOSK_TO_TABLE)"),
    (2, "테이블→화장실 (TABLE_TO_TOILET)"),
    (3, "테이블→디스플레이 (TABLE_TO_DISPLAY)"),
    (4, "식기 수거 (DISH_PICKUP)"),
    (5, "로봇 교체 (ROBOT_SWAP)"),
    (6, "안내 서비스 (ESCORT_SERVICE)"),
    (7, "도킹 복귀 (RETURN_TO_DOCK)"),
]

_TASK_CARD_INFO = [
    ("🍽 식기 수거 (Collect)",    "지정된 테이블에서 다트(트레이)를 수거합니다.", "#4A88D4", 4),
    ("🔌 충전 복귀 (Charge)",     "배터리 부족 로봇을 충전 스테이션으로 보냅니다.", "#E6A23C", 7),
    ("👥 동행 이동 (Follow)",     "작업자를 따라다니며 보조 업무를 수행합니다.", "#9C27B0", 6),
    ("💁 고객 안내 (Guide)",      "목적지(테이블/입구)까지 고객을 에스코트합니다.", "#67C23A", 6),
]


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
        # Pre-select the hint type
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


class TaskManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        self._api = ApiClient()
        self._workers: list[ApiWorker] = []
        self._places: list[dict] = []   # cached for task creation dialog
        self.initUI()
        self._load_places_then_tasks()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("📝 태스크(작업) 통합 관리")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # Quick-action cards (each opens CreateTaskDialog with a pre-selected type)
        grid_frame = QFrame()
        grid_frame.setStyleSheet("background-color: transparent;")
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(15)

        for i, (name, desc, color, task_type) in enumerate(_TASK_CARD_INFO):
            card = QFrame()
            card.setStyleSheet(f"background-color: white; border: 2px solid {color}; border-radius: 8px;")
            c_layout = QVBoxLayout(card)

            n_lbl = QLabel(name)
            n_lbl.setFont(QFont("Malgun Gothic", 14, QFont.Bold))
            n_lbl.setStyleSheet(f"color: {color}; border: none;")

            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet("color: #606266; border: none;")
            d_lbl.setWordWrap(True)

            btn = QPushButton("작업 지시")
            btn.setStyleSheet(f"background-color: {color}; color: white; padding: 10px; border-radius: 4px; font-weight: bold;")
            btn.clicked.connect(lambda _, tt=task_type: self._open_create_dialog(tt))

            c_layout.addWidget(n_lbl)
            c_layout.addWidget(d_lbl)
            c_layout.addStretch()
            c_layout.addWidget(btn)

            row, col = divmod(i, 2)
            grid_layout.addWidget(card, row, col)

        main_layout.addWidget(grid_frame)
        main_layout.addSpacing(20)

        # Task queue header
        header_row = QHBoxLayout()
        t_lbl = QLabel("▶ 현재 진행 중인 태스크 대기열")
        t_lbl.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        header_row.addWidget(t_lbl)
        header_row.addStretch()

        refresh_btn = QPushButton("🔄 새로 고침")
        refresh_btn.setStyleSheet("background-color: #409EFF; color: white; padding: 6px 12px; border-radius: 4px; font-weight: bold;")
        refresh_btn.clicked.connect(self._load_tasks)
        header_row.addWidget(refresh_btn)
        main_layout.addLayout(header_row)

        # Task table
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
        main_layout.addWidget(self.task_table)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        main_layout.addWidget(self._status_lbl)

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_places_then_tasks(self):
        """Load places first (needed for task creation dialog), then tasks."""
        w = ApiWorker(self._api.get_places)
        w.result.connect(self._on_places_loaded)
        w.error.connect(lambda _: self._load_tasks())  # fallback: load tasks anyway
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
            t_type   = task.get("task_type", 0)
            robot_id = task.get("robot_id", "") or "미할당"
            status_i = task.get("status", 0)
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
            # Cancellation not currently exposed via a dedicated endpoint;
            # show a notice for now
            cancel_btn.clicked.connect(lambda _, tid=task_id: QMessageBox.information(
                self, "알림", f"태스크 {tid[:8]}…\n취소 기능은 로봇 명령 탭에서 CANCEL 명령으로 처리하세요."))
            self.task_table.setCellWidget(row, 4, cancel_btn)

    # ── task creation ─────────────────────────────────────────────────────────

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

    # ── helpers ───────────────────────────────────────────────────────────────

    def _discard(self, w: ApiWorker):
        if w in self._workers:
            self._workers.remove(w)
