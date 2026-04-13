from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
                             QGridLayout, QLineEdit, QComboBox, QStackedWidget,
                             QAbstractItemView, QScrollArea, QMessageBox, QDialog,
                             QDialogButtonBox)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

from components.widgets import create_title_label, ToggleSwitch
from utils.api_client import (ApiClient, ApiWorker,
                              CMD_EMERGENCY_STOP, CMD_CANCEL, CMD_RESET, CMD_RETURN_DOCK,
                              ROBOT_STATUS_LABELS)


_CMD_OPTIONS = [
    (CMD_EMERGENCY_STOP, "긴급 정지 (EMERGENCY_STOP)"),
    (CMD_CANCEL,         "작업 취소 (CANCEL)"),
    (CMD_RESET,          "리셋 (RESET)"),
    (CMD_RETURN_DOCK,    "도킹 복귀 (RETURN_DOCK)"),
]


class SendCommandDialog(QDialog):
    """Simple dialog to pick a command type and confirm before sending."""

    def __init__(self, robot_id: str, task_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{robot_id} — 명령 전송")
        self.setFixedWidth(380)
        self.robot_id = robot_id
        self.task_id = task_id

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"로봇 <b>{robot_id}</b>에 명령을 전송합니다."))

        self.combo = QComboBox()
        for _, label in _CMD_OPTIONS:
            self.combo.addItem(label)
        layout.addWidget(self.combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_command(self) -> int:
        return _CMD_OPTIONS[self.combo.currentIndex()][0]


class RobotSettingPage(QWidget):
    def __init__(self, test_data_manager):
        super().__init__()
        self.test_data = test_data_manager
        self._api = ApiClient()
        self._workers: list[ApiWorker] = []
        self._robots: list[dict] = []   # latest robot data from API
        self.initUI()
        self._load_robots()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("🤖 로봇 설정 및 관리")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # Dashboard summary (updated dynamically)
        dash_frame = QFrame()
        dash_frame.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; border: 1px solid #E4E7ED;")
        dash_layout = QHBoxLayout(dash_frame)

        self._summary_labels: dict[str, QLabel] = {}
        for name, key, color in [
            ("총 로봇",       "total",   "#303133"),
            ("정상/대기",     "active",  "#67C23A"),
            ("충전 중",       "charging","#E6A23C"),
            ("에러/오프라인", "error",   "#F56C6C"),
        ]:
            m_layout = QVBoxLayout()
            n_lbl = QLabel(name)
            n_lbl.setStyleSheet("color: #909399; font-weight: bold;")
            n_lbl.setAlignment(Qt.AlignCenter)
            v_lbl = QLabel("—")
            v_lbl.setFont(QFont("Arial", 16, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {color};")
            v_lbl.setAlignment(Qt.AlignCenter)
            m_layout.addWidget(n_lbl)
            m_layout.addWidget(v_lbl)
            dash_layout.addLayout(m_layout)
            self._summary_labels[key] = v_lbl

        main_layout.addWidget(dash_frame)
        main_layout.addSpacing(20)

        # Stacked: list view / detail view
        self.content_stack = QStackedWidget()

        # ── 1. List View ──────────────────────────────────────────────────────
        self.list_view = QWidget()
        lv_layout = QVBoxLayout(self.list_view)
        lv_layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        refresh_btn = QPushButton("🔄 새로 고침")
        refresh_btn.setStyleSheet("background-color: #409EFF; color: white; padding: 8px 15px; border-radius: 4px; font-weight: bold;")
        refresh_btn.clicked.connect(self._load_robots)
        btn_row.addWidget(refresh_btn)
        lv_layout.addLayout(btn_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "상태", "배터리", "IP 주소", "명령 전송", "설정 열기"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lv_layout.addWidget(self.table)

        # Status label when loading / error
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        lv_layout.addWidget(self._status_lbl)

        # ── 2. Detail / Config View ───────────────────────────────────────────
        self.detail_view = QWidget()
        dv_layout = QVBoxLayout(self.detail_view)
        dv_layout.setContentsMargins(0, 0, 0, 0)

        back_btn = QPushButton("◀ 뒤로 (목록으로 돌아가기)")
        back_btn.setStyleSheet("color: #909399; font-weight: bold; border: none; text-align: left; font-size: 14px;")
        back_btn.setFixedWidth(200)
        back_btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        dv_layout.addWidget(back_btn)
        dv_layout.addSpacing(10)

        self.detail_title = QLabel("로봇 상세 설정")
        self.detail_title.setFont(QFont("Malgun Gothic", 14, QFont.Bold))
        dv_layout.addWidget(self.detail_title)

        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: white; border: 1px solid #E4E7ED; border-radius: 8px;")
        f_layout = QGridLayout(form_frame)
        f_layout.setSpacing(15)
        f_layout.setContentsMargins(20, 20, 20, 20)

        f_layout.addWidget(QLabel("로봇 ID:"), 0, 0)
        self.f_id = QLineEdit()
        self.f_id.setReadOnly(True)
        f_layout.addWidget(self.f_id, 0, 1)

        f_layout.addWidget(QLabel("제어 IP 주소:"), 1, 0)
        self.f_ip = QLineEdit()
        f_layout.addWidget(self.f_ip, 1, 1)

        f_layout.addWidget(QLabel("TCP 제어 포트:"), 2, 0)
        self.f_tcp = QLineEdit("9090")
        f_layout.addWidget(self.f_tcp, 2, 1)

        f_layout.addWidget(QLabel("UDP 텔레메트리 포트:"), 3, 0)
        self.f_udp = QLineEdit("9091")
        f_layout.addWidget(self.f_udp, 3, 1)

        f_layout.addWidget(QLabel("자동 재연결 타임아웃 (ms):"), 4, 0)
        self.f_timeout = QLineEdit("3000")
        f_layout.addWidget(self.f_timeout, 4, 1)

        save_btn = QPushButton("설정 저장")
        save_btn.setStyleSheet("background-color: #67C23A; color: white; padding: 10px 20px; border-radius: 4px; font-weight: bold;")
        save_btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        btn_wrapper = QHBoxLayout()
        btn_wrapper.addStretch()
        btn_wrapper.addWidget(save_btn)
        f_layout.addLayout(btn_wrapper, 5, 1)

        dv_layout.addWidget(form_frame)
        dv_layout.addSpacing(20)
        dv_layout.addWidget(QLabel("✅ 이 로봇에 대한 개별 연동 테스트"))

        self.test_frame = QFrame()
        self.test_frame.setStyleSheet("background-color: white; border: 1px solid #E4E7ED; border-radius: 8px;")
        tf_layout = QVBoxLayout(self.test_frame)
        tf_layout.addWidget(self.test_data.create_test_table(["A. 로봇 ↔ 관제", "B. 로봇 → 관제 UDP", "C. 관제 → 로봇 TCP"]))
        dv_layout.addWidget(self.test_frame)

        self.content_stack.addWidget(self.list_view)
        self.content_stack.addWidget(self.detail_view)
        main_layout.addWidget(self.content_stack)

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_robots(self):
        self._status_lbl.setText("로봇 목록 로딩 중...")
        self.table.setRowCount(0)
        w = ApiWorker(self._api.get_robots)
        w.result.connect(self._on_robots_loaded)
        w.error.connect(self._on_load_error)
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _on_load_error(self, msg: str):
        self._status_lbl.setText(f"서버 연결 오류: {msg}")
        self._status_lbl.setStyleSheet("color: #F56C6C; font-style: italic;")

    def _on_robots_loaded(self, data: dict):
        self._robots = data.get("robots", [])
        self._status_lbl.setText(f"총 {len(self._robots)}대 조회됨")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        self._rebuild_table()
        self._update_summary()

    def _update_summary(self):
        total    = len(self._robots)
        charging = sum(1 for r in self._robots if r.get("status") == 4)
        error    = sum(1 for r in self._robots if r.get("status") in (5, 6))
        active   = total - charging - error

        self._summary_labels["total"].setText(f"{total}대")
        self._summary_labels["active"].setText(f"{active}대")
        self._summary_labels["charging"].setText(f"{charging}대")
        self._summary_labels["error"].setText(f"{error}대")

    def _rebuild_table(self):
        self.table.setRowCount(0)
        for robot in self._robots:
            r_id    = robot.get("robot_id", "")
            s_int   = robot.get("status", 0)
            battery = robot.get("battery_last", 0)
            task_id = robot.get("current_task_id", "") or ""
            # IP not returned by API — display placeholder
            ip = "—"

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r_id))
            self.table.setItem(row, 1, QTableWidgetItem(ROBOT_STATUS_LABELS.get(s_int, "알 수 없음")))
            self.table.setItem(row, 2, QTableWidgetItem(f"{battery}%"))
            self.table.setItem(row, 3, QTableWidgetItem(ip))

            cmd_btn = QPushButton("⚡ 명령 전송")
            cmd_btn.setStyleSheet("background-color: #FDF6EC; color: #E6A23C; border-radius: 3px; border: 1px solid #FAECD8; padding: 3px 8px;")
            cmd_btn.clicked.connect(lambda _, rid=r_id, tid=task_id: self._open_command_dialog(rid, tid))
            self.table.setCellWidget(row, 4, cmd_btn)

            edit_btn = QPushButton("설정 및 테스트 열기")
            edit_btn.setStyleSheet("background-color: #ECF5FF; color: #409EFF; border-radius: 3px; border: 1px solid #B3D8FF;")
            edit_btn.clicked.connect(lambda _, rid=r_id, addr=ip: self.open_robot_config(rid, addr))
            self.table.setCellWidget(row, 5, edit_btn)

    # ── command dialog ────────────────────────────────────────────────────────

    def _open_command_dialog(self, robot_id: str, task_id: str):
        dlg = SendCommandDialog(robot_id, task_id, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        cmd = dlg.selected_command()
        w = ApiWorker(self._api.send_command, robot_id, task_id, cmd)
        w.result.connect(lambda _: QMessageBox.information(
            self, "명령 전송", f"{robot_id}에 명령을 전송했습니다."))
        w.error.connect(lambda msg: QMessageBox.warning(
            self, "명령 전송 실패", f"{robot_id}: {msg}"))
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    # ── detail view ───────────────────────────────────────────────────────────

    def open_robot_config(self, r_id: str, ip: str):
        self.detail_title.setText(f"🤖 {r_id} 개별 설정 및 테스트 환경")
        self.f_id.setText(r_id)
        self.f_ip.setText(ip)
        self.content_stack.setCurrentIndex(1)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _discard(self, w: ApiWorker):
        if w in self._workers:
            self._workers.remove(w)
