from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QMessageBox)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

from utils.api_client import ApiClient, ApiWorker


_ZONE_LABELS: dict[int, str] = {
    0: "미분류",
    1: "테이블",
    2: "주방",
    3: "화장실",
    4: "디스플레이",
    5: "도킹존",
    6: "복도",
}


class MapSettingPage(QWidget):
    def __init__(self, test_data_manager):
        super().__init__()
        self.test_data = test_data_manager
        self._api = ApiClient()
        self._workers: list[ApiWorker] = []
        self._places: list[dict] = []    # latest data from API
        self.initUI()
        self._load_places()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("🪑 표심/경로 및 관제 자동 설정")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # Dashboard metrics
        dash_frame = QFrame()
        dash_frame.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; border: 1px solid #E4E7ED;")
        dash_layout = QHBoxLayout(dash_frame)

        self.lbl_table_count = QLabel("—")
        self.lbl_table_count.setFont(QFont("Arial", 16, QFont.Bold))
        self.lbl_table_count.setStyleSheet("color: #4A88D4;")
        self.lbl_table_count.setAlignment(Qt.AlignCenter)

        self.lbl_server_status = QLabel("—")
        self.lbl_server_status.setFont(QFont("Arial", 16, QFont.Bold))
        self.lbl_server_status.setStyleSheet("color: #67C23A;")
        self.lbl_server_status.setAlignment(Qt.AlignCenter)

        metrics = [
            ("서버 상태",     self.lbl_server_status),
            ("등록된 장소",   self.lbl_table_count),
            ("경로 모드",     QLabel("A* Auto")),
            ("평균 지연율",   QLabel("—")),
        ]
        for name, v_lbl in metrics:
            if v_lbl.font().pointSize() < 14:
                v_lbl.setFont(QFont("Arial", 16, QFont.Bold))
                v_lbl.setStyleSheet("color: #909399;")
                v_lbl.setAlignment(Qt.AlignCenter)
            m_layout = QVBoxLayout()
            n_lbl = QLabel(name)
            n_lbl.setStyleSheet("color: #909399; font-weight: bold;")
            n_lbl.setAlignment(Qt.AlignCenter)
            m_layout.addWidget(n_lbl)
            m_layout.addWidget(v_lbl)
            dash_layout.addLayout(m_layout)

        main_layout.addWidget(dash_frame)
        main_layout.addSpacing(20)

        # Table management header
        header_layout = QHBoxLayout()
        t_lbl = QLabel("▶ 장소(Place) 관리")
        t_lbl.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        header_layout.addWidget(t_lbl)
        header_layout.addStretch()

        refresh_btn = QPushButton("🔄 새로 고침")
        refresh_btn.setStyleSheet("background-color: #409EFF; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold;")
        refresh_btn.clicked.connect(self._load_places)
        header_layout.addWidget(refresh_btn)

        save_btn = QPushButton("💾 변경사항 저장")
        save_btn.setStyleSheet("background-color: #67C23A; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold;")
        save_btn.clicked.connect(self._save_changes)
        header_layout.addWidget(save_btn)

        main_layout.addLayout(header_layout)

        # Places table: name | zone | x | y | active | deactivate
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["이름", "구역", "X (m)", "Y (m)", "활성", "관리"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")

        main_layout.addWidget(self.table)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        main_layout.addWidget(self._status_lbl)

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_places(self):
        self._status_lbl.setText("장소 목록 로딩 중...")
        self.table.setRowCount(0)
        w = ApiWorker(self._api.get_places, active_only=False)
        w.result.connect(self._on_places_loaded)
        w.error.connect(self._on_load_error)
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

        # Also ping health to update server status indicator
        hw = ApiWorker(self._api.health_check)
        hw.result.connect(lambda _: (
            self.lbl_server_status.setText("Online"),
            self.lbl_server_status.setStyleSheet("color: #67C23A; font-size: 16px; font-weight: bold;")))
        hw.error.connect(lambda _: (
            self.lbl_server_status.setText("Offline"),
            self.lbl_server_status.setStyleSheet("color: #F56C6C; font-size: 16px; font-weight: bold;")))
        hw.finished.connect(lambda: self._discard(hw))
        self._workers.append(hw)
        hw.start()

    def _on_load_error(self, msg: str):
        self._status_lbl.setText(f"서버 오류: {msg}")
        self._status_lbl.setStyleSheet("color: #F56C6C; font-style: italic;")
        self.lbl_table_count.setText("—")

    def _on_places_loaded(self, data: dict):
        self._places = data.get("places", [])
        self.lbl_table_count.setText(f"{len(self._places)}개")
        self._status_lbl.setText(f"총 {len(self._places)}개 장소 조회됨")
        self._status_lbl.setStyleSheet("color: #909399; font-style: italic;")
        self._rebuild_table()

    def _rebuild_table(self):
        self.table.setRowCount(0)
        for place in self._places:
            place_id = place.get("place_id", "")
            name     = place.get("name", "")
            zone_i   = place.get("zone", 0)
            x        = place.get("x", 0.0)
            y        = place.get("y", 0.0)
            is_active = place.get("is_active", 1)

            row = self.table.rowCount()
            self.table.insertRow(row)

            # Name — editable
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, place_id)   # store place_id
            self.table.setItem(row, 0, name_item)

            self.table.setItem(row, 1, QTableWidgetItem(_ZONE_LABELS.get(zone_i, str(zone_i))))
            self.table.setItem(row, 2, QTableWidgetItem(f"{x:.2f}" if x is not None else "—"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{y:.2f}" if y is not None else "—"))
            self.table.setItem(row, 4, QTableWidgetItem("✅" if is_active else "❌"))

            if is_active:
                deact_btn = QPushButton("비활성화")
                deact_btn.setStyleSheet("color: white; background-color: #F56C6C; border-radius: 3px; padding: 4px 8px;")
                deact_btn.clicked.connect(lambda _, pid=place_id: self._deactivate_place(pid))
            else:
                deact_btn = QPushButton("활성화")
                deact_btn.setStyleSheet("color: white; background-color: #67C23A; border-radius: 3px; padding: 4px 8px;")
                deact_btn.clicked.connect(lambda _, pid=place_id: self._activate_place(pid))
            self.table.setCellWidget(row, 5, deact_btn)

    # ── save / patch ──────────────────────────────────────────────────────────

    def _save_changes(self):
        """Push any edited names back to the server via PATCH /places/{id}."""
        changes: list[tuple[str, str]] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            place_id = item.data(Qt.UserRole)
            new_name = item.text().strip()
            # Find original name
            orig = next((p for p in self._places if p.get("place_id") == place_id), None)
            if orig and new_name and new_name != orig.get("name", ""):
                changes.append((place_id, new_name))

        if not changes:
            QMessageBox.information(self, "저장", "변경된 내용이 없습니다.")
            return

        self._pending_saves = len(changes)
        self._save_errors: list[str] = []
        for place_id, new_name in changes:
            w = ApiWorker(self._api.patch_place, place_id, {"name": new_name})
            w.result.connect(lambda _: self._on_save_one_done())
            w.error.connect(lambda msg: self._on_save_one_error(msg))
            w.finished.connect(lambda: self._discard(w))
            self._workers.append(w)
            w.start()

    def _on_save_one_done(self):
        self._pending_saves -= 1
        if self._pending_saves <= 0:
            if self._save_errors:
                QMessageBox.warning(self, "저장 오류", "\n".join(self._save_errors))
            else:
                QMessageBox.information(self, "저장 완료", "변경사항이 저장되었습니다.")
            self._load_places()

    def _on_save_one_error(self, msg: str):
        self._save_errors.append(msg)
        self._on_save_one_done()

    def _deactivate_place(self, place_id: str):
        w = ApiWorker(self._api.patch_place, place_id, {"is_active": 0})
        w.result.connect(lambda _: self._load_places())
        w.error.connect(lambda msg: QMessageBox.warning(self, "오류", msg))
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def _activate_place(self, place_id: str):
        w = ApiWorker(self._api.patch_place, place_id, {"is_active": 1})
        w.result.connect(lambda _: self._load_places())
        w.error.connect(lambda msg: QMessageBox.warning(self, "오류", msg))
        w.finished.connect(lambda: self._discard(w))
        self._workers.append(w)
        w.start()

    def update_count(self):
        self.lbl_table_count.setText(f"{self.table.rowCount()}개")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _discard(self, w: ApiWorker):
        if w in self._workers:
            self._workers.remove(w)
