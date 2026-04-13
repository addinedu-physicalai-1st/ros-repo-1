from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QGridLayout)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QTimer
import datetime

class RecordManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("📹 비전 및 녹화 관리 (블랙박스)")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # 1. Realtime Feeds (Mock)
        feeds_layout = QHBoxLayout()
        for r_id in ["R1", "R3"]:
            cam_frame = QFrame()
            cam_frame.setStyleSheet("background-color: black; border-radius: 8px;")
            cam_frame.setMinimumHeight(250)
            c_layout = QVBoxLayout(cam_frame)
            lbl = QLabel(f"🔴 Live Feed Active: {r_id} Front Camera\n[ 192.168.1.10{r_id[1]} ]")
            lbl.setStyleSheet("color: white; font-weight: bold;")
            lbl.setAlignment(Qt.AlignCenter)
            c_layout.addWidget(lbl)
            feeds_layout.addWidget(cam_frame)
        
        main_layout.addLayout(feeds_layout)
        main_layout.addSpacing(20)

        # 2. Emergency Active Recording Panel (Hidden by Default)
        self.emg_frame = QFrame()
        self.emg_frame.setStyleSheet("background-color: #FEF0F0; border: 2px solid #F56C6C; border-radius: 8px;")
        self.emg_frame.setVisible(False)
        emg_layout = QHBoxLayout(self.emg_frame)
        
        self.emg_lbl = QLabel("🚨 충돌 이벤트 감지됨! (R2) - 사고 1분 전 시점부터 녹화를 진행 중입니다...")
        self.emg_lbl.setFont(QFont("Malgun Gothic", 14, QFont.Bold))
        self.emg_lbl.setStyleSheet("color: #F56C6C;")
        emg_layout.addWidget(self.emg_lbl)
        
        emg_layout.addStretch()
        
        self.btn_resolve = QPushButton("해결 (Release)")
        self.btn_resolve.setStyleSheet("background-color: #F56C6C; color: white; padding: 10px 20px; border-radius: 4px; font-weight: bold; font-size: 14px;")
        self.btn_resolve.clicked.connect(self.resolve_emergency)
        emg_layout.addWidget(self.btn_resolve)
        
        main_layout.addWidget(self.emg_frame)

        # 3. Archive List
        header_layout = QHBoxLayout()
        t_lbl = QLabel("▶ 과거 이벤트 녹화 영상 목록")
        t_lbl.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        header_layout.addWidget(t_lbl)
        
        header_layout.addStretch()
        
        # Test Trigger Button
        btn_trigger = QPushButton("💥 충돌 이벤트 발생 테스트")
        btn_trigger.setStyleSheet("background-color: #E6A23C; color: white; padding: 6px 15px; border-radius: 4px; font-weight: bold;")
        btn_trigger.clicked.connect(self.trigger_emergency)
        header_layout.addWidget(btn_trigger)

        main_layout.addLayout(header_layout)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["이벤트 발생 시간", "로봇 ID", "이벤트 유형", "녹화 구간", "영상 재생"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")

        # Init Mock records
        self.add_record("2026-04-12 11:30:22", "R1", "충돌 회피 비상정지", "-1m ~ +30s", False)
        self.add_record("2026-04-12 14:05:10", "R4", "네트워크 10초 이상 단절", "-1m ~ +10s", False)

        main_layout.addWidget(self.table)

        self.recording_start_time = None

    def trigger_emergency(self):
        self.emg_frame.setVisible(True)
        now = datetime.datetime.now()
        self.recording_start_time = now - datetime.timedelta(minutes=1)
        
        # Flashing effect
        self.flash_state = True
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.flash_label)
        self.flash_timer.start(500)

    def flash_label(self):
        self.flash_state = not self.flash_state
        if self.flash_state:
            self.emg_lbl.setStyleSheet("color: #F56C6C;")
        else:
            self.emg_lbl.setStyleSheet("color: black;")

    def resolve_emergency(self):
        self.flash_timer.stop()
        self.emg_frame.setVisible(False)
        self.emg_lbl.setStyleSheet("color: #F56C6C;")
        
        if self.recording_start_time:
            now = datetime.datetime.now()
            start_str = self.recording_start_time.strftime("%H:%M:%S")
            end_str = now.strftime("%H:%M:%S")
            time_str = now.strftime("%Y-%m-%d %H:%M:%S")
            
            self.add_record(time_str, "R2", "운영자 해결(Release)된 충돌", f"{start_str} ~ {end_str}", True)
            self.recording_start_time = None

    def add_record(self, time_val, rid, event_type, range_val, highlight):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        self.table.setItem(row, 0, QTableWidgetItem(time_val))
        self.table.setItem(row, 1, QTableWidgetItem(rid))
        self.table.setItem(row, 2, QTableWidgetItem(event_type))
        self.table.setItem(row, 3, QTableWidgetItem(range_val))
        
        play_btn = QPushButton("▶ 보기")
        play_btn.setStyleSheet("background-color: #4A88D4; color: white; border-radius: 3px; padding: 4px;")
        self.table.setCellWidget(row, 4, play_btn)
        
        if highlight:
            for i in range(4):
                item = self.table.item(row, i)
                item.setBackground(QColor("#ECF5FF"))
