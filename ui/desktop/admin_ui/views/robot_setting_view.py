from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
                             QGridLayout, QLineEdit, QComboBox, QSlider, QStackedWidget, QAbstractItemView, QScrollArea)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

from components.widgets import create_title_label, ToggleSwitch

class RobotSettingPage(QWidget):
    def __init__(self, test_data_manager):
        super().__init__()
        self.test_data = test_data_manager
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("🤖 로봇 설정 및 관리")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # Dashboard Top
        dash_frame = QFrame()
        dash_frame.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; border: 1px solid #E4E7ED;")
        dash_layout = QHBoxLayout(dash_frame)
        
        metrics = [("총 로봇", "4대", "#303133"), ("정상/대기", "2대", "#67C23A"), 
                   ("충전 중", "1대", "#E6A23C"), ("에러/오프라인", "1대", "#F56C6C")]
        
        for name, val, color in metrics:
            m_layout = QVBoxLayout()
            n_lbl = QLabel(name)
            n_lbl.setStyleSheet("color: #909399; font-weight: bold;")
            n_lbl.setAlignment(Qt.AlignCenter)
            v_lbl = QLabel(val)
            v_lbl.setFont(QFont("Arial", 16, QFont.Bold))
            v_lbl.setStyleSheet(f"color: {color};")
            v_lbl.setAlignment(Qt.AlignCenter)
            m_layout.addWidget(n_lbl)
            m_layout.addWidget(v_lbl)
            dash_layout.addLayout(m_layout)

        main_layout.addWidget(dash_frame)
        main_layout.addSpacing(20)

        # Stacked Content for List vs Config/Test View
        self.content_stack = QStackedWidget()

        # ==========================================
        # 1. List View
        # ==========================================
        self.list_view = QWidget()
        lv_layout = QVBoxLayout(self.list_view)
        lv_layout.setContentsMargins(0, 0, 0, 0)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        add_btn = QPushButton("➕ 새 로봇 추가")
        add_btn.setStyleSheet("background-color: #409EFF; color: white; padding: 8px 15px; border-radius: 4px; font-weight: bold;")
        add_btn.clicked.connect(lambda: self.open_robot_config("새 로봇", "0.0.0.0"))
        btn_layout.addWidget(add_btn)
        
        lv_layout.addLayout(btn_layout)

        table = QTableWidget(4, 5)
        table.setHorizontalHeaderLabels(["ID", "상태", "배터리", "IP 주소", "관리(설정)"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")
        table.setSelectionBehavior(QAbstractItemView.SelectRows)

        mock_robots = [("R1", "이동 중", "73%", "192.168.1.101"),("R2", "대기", "44%", "192.168.1.102"),
                       ("R3", "충전", "80%", "192.168.1.103"),("R4", "에러", "16%", "192.168.1.104")]
        
        for i, (rid, st, bat, ip) in enumerate(mock_robots):
            table.setItem(i, 0, QTableWidgetItem(rid))
            table.setItem(i, 1, QTableWidgetItem(st))
            table.setItem(i, 2, QTableWidgetItem(bat))
            table.setItem(i, 3, QTableWidgetItem(ip))
            edit_btn = QPushButton("설정 및 테스트 열기")
            edit_btn.setStyleSheet("background-color: #ECF5FF; color: #409EFF; border-radius: 3px; border: 1px solid #B3D8FF;")
            edit_btn.clicked.connect(lambda _, r=rid, addr=ip: self.open_robot_config(r, addr))
            table.setCellWidget(i, 4, edit_btn)

        lv_layout.addWidget(table)


        # ==========================================
        # 2. Config & Test View (Specific to a Robot)
        # ==========================================
        self.detail_view = QWidget()
        dv_layout = QVBoxLayout(self.detail_view)
        dv_layout.setContentsMargins(0, 0, 0, 0)
        
        back_btn = QPushButton("◀ 뒤로 (목록으로 돌아가기)")
        back_btn.setStyleSheet("color: #909399; font-weight: bold; border: none; text-align: left; font-size: 14px;")
        back_btn.setFixedWidth(200)
        back_btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        dv_layout.addWidget(back_btn)
        dv_layout.addSpacing(10)

        # Detail Dashboard Title
        self.detail_title = QLabel("로봇 상세 설정")
        self.detail_title.setFont(QFont("Malgun Gothic", 14, QFont.Bold))
        dv_layout.addWidget(self.detail_title)

        # Form Config
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: white; border: 1px solid #E4E7ED; border-radius: 8px;")
        f_layout = QGridLayout(form_frame)
        f_layout.setSpacing(15)
        f_layout.setContentsMargins(20, 20, 20, 20)

        f_layout.addWidget(QLabel("로봇 ID:"), 0, 0)
        self.f_id = QLineEdit()
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

        # Tests Frame
        self.test_frame = QFrame()
        self.test_frame.setStyleSheet("background-color: white; border: 1px solid #E4E7ED; border-radius: 8px;")
        tf_layout = QVBoxLayout(self.test_frame)
        tf_layout.addWidget(self.test_data.create_test_table(["A. 로봇 ↔ 관제", "B. 로봇 → 관제 UDP", "C. 관제 → 로봇 TCP"]))
        
        dv_layout.addWidget(self.test_frame)

        self.content_stack.addWidget(self.list_view)
        self.content_stack.addWidget(self.detail_view)

        main_layout.addWidget(self.content_stack)

    def open_robot_config(self, r_id, ip):
        self.detail_title.setText(f"🤖 {r_id} 개별 설정 및 테스트 환경")
        self.f_id.setText(r_id)
        self.f_ip.setText(ip)
        self.content_stack.setCurrentIndex(1)
