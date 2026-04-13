from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QStackedWidget, QFrame, 
                             QScrollArea, QSlider, QComboBox, QLineEdit, 
                             QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
                             QGridLayout, QAbstractItemView)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from components.widgets import ToggleSwitch, create_card_frame, create_title_label

class RobotSettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cont_layout = QVBoxLayout(container)
        cont_layout.setSpacing(20)

        robots = [
            ("R1", "Moving", "#4A88D4", 73),
            ("R2", "Idle", "#999999", 44),
            ("R3", "Charging", "#54B254", 80),
            ("R4", "Error", "#F56C6C", 16)
        ]

        for r_id, status, color, battery in robots:
            card = create_card_frame()
            card_layout = QVBoxLayout(card)

            header_layout = QHBoxLayout()
            id_lbl = QLabel(f"로봇 {r_id}")
            font = QFont()
            font.setPointSize(12)
            font.setBold(True)
            id_lbl.setFont(font)

            status_lbl = QLabel(status)
            status_lbl.setStyleSheet(f"color: white; background-color: {color}; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
            
            bat_lbl = QLabel(f"배터리: {battery}%")
            bat_lbl.setStyleSheet("color: #606266; font-weight: bold;")

            header_layout.addWidget(id_lbl)
            header_layout.addWidget(status_lbl)
            header_layout.addStretch()
            header_layout.addWidget(bat_lbl)

            controls_layout = QGridLayout()
            controls_layout.setSpacing(15)

            controls_layout.addWidget(QLabel("기본 속도"), 0, 0)
            spd_slider = QSlider(Qt.Horizontal)
            spd_slider.setRange(1, 100)
            spd_slider.setValue(50)
            controls_layout.addWidget(spd_slider, 0, 1)

            controls_layout.addWidget(QLabel("자동 충전 복귀 기준(%)"), 1, 0)
            chg_slider = QSlider(Qt.Horizontal)
            chg_slider.setRange(10, 50)
            chg_slider.setValue(20)
            controls_layout.addWidget(chg_slider, 1, 1)

            controls_layout.addWidget(QLabel("충돌 회피 기능"), 2, 0)
            toggle_coll = ToggleSwitch()
            toggle_coll.setChecked(True)
            controls_layout.addWidget(toggle_coll, 2, 1, Qt.AlignLeft)

            btns_layout = QHBoxLayout()
            btn_restart = QPushButton("🔄 재시작")
            btn_reset = QPushButton("⚠️ 초기화")
            btn_restart.setStyleSheet("background-color: #E6A23C; color: white; padding: 6px 15px; border-radius: 4px; font-weight: bold;")
            btn_reset.setStyleSheet("background-color: #F56C6C; color: white; padding: 6px 15px; border-radius: 4px; font-weight: bold;")
            
            btns_layout.addStretch()
            btns_layout.addWidget(btn_restart)
            btns_layout.addWidget(btn_reset)

            card_layout.addLayout(header_layout)
            card_layout.addSpacing(10)
            card_layout.addLayout(controls_layout)
            card_layout.addSpacing(10)
            card_layout.addLayout(btns_layout)

            cont_layout.addWidget(card)

        cont_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)


class NetworkSettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        card = create_card_frame()
        c_layout = QGridLayout(card)
        c_layout.setSpacing(20)

        c_layout.addWidget(create_title_label("네트워크 및 서버 설정"), 0, 0, 1, 2)

        c_layout.addWidget(QLabel("연결 방식:"), 1, 0)
        combo = QComboBox()
        combo.addItems(["TCP", "UDP"])
        combo.setFixedHeight(35)
        c_layout.addWidget(combo, 1, 1)

        c_layout.addWidget(QLabel("IP 주소:"), 2, 0)
        ip_edit = QLineEdit("192.168.1.100")
        ip_edit.setFixedHeight(35)
        c_layout.addWidget(ip_edit, 2, 1)

        c_layout.addWidget(QLabel("Port:"), 3, 0)
        port_edit = QLineEdit("9090")
        port_edit.setFixedHeight(35)
        c_layout.addWidget(port_edit, 3, 1)

        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("현재 상태:"))
        status_lbl = QLabel("● Connected")
        status_lbl.setStyleSheet("color: #67C23A; font-weight: bold;")
        status_layout.addWidget(status_lbl)
        status_layout.addStretch()
        
        c_layout.addLayout(status_layout, 4, 0, 1, 2)

        ping_btn = QPushButton("통신 테스트 (Ping)")
        ping_btn.setStyleSheet("background-color: #4A88D4; color: white; padding: 8px; border-radius: 4px;")
        
        ping_res_lbl = QLabel("지연시간: 12ms | 패킷 손실률: 0%")
        ping_res_lbl.setStyleSheet("color: #606266;")
        
        c_layout.addWidget(ping_btn, 5, 0)
        c_layout.addWidget(ping_res_lbl, 5, 1)

        c_layout.addWidget(QLabel("네트워크 연결 로그:"), 6, 0, 1, 2)
        log_edit = QTextEdit()
        log_edit.setReadOnly(True)
        log_edit.setText("[14:02:11] Connected to 192.168.1.100:9090\n[14:15:30] Ping test ok (12ms)")
        log_edit.setStyleSheet("background-color: #F8F9FA; border: 1px solid #E4E7ED; border-radius: 4px;")
        c_layout.addWidget(log_edit, 7, 0, 1, 2)

        layout.addWidget(card)
        layout.addStretch()


class TableSettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        card = create_card_frame()
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(15)

        header_layout = QHBoxLayout()
        header_layout.addWidget(create_title_label("배치 테이블 목록 (총 12개)"))
        header_layout.addStretch()
        
        add_btn = QPushButton("➕ 테이블 추가")
        add_btn.setStyleSheet("background-color: #67C23A; color: white; padding: 8px 15px; border-radius: 4px; font-weight: bold;")
        header_layout.addWidget(add_btn)
        
        c_layout.addLayout(header_layout)

        table = QTableWidget(12, 3)
        table.setHorizontalHeaderLabels(["테이블 이름", "수용 인원", "관리"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; border-radius: 4px; }")

        for i in range(12):
            cap = 4 if i % 2 == 0 else 6
            name_item = QTableWidgetItem(f"{cap}인 테이블 {i+1}")
            cap_item = QTableWidgetItem(f"{cap}명")
            
            table.setItem(i, 0, name_item)
            table.setItem(i, 1, cap_item)

            del_btn = QPushButton("삭제")
            del_btn.setStyleSheet("color: white; background-color: #F56C6C; border-radius: 3px; padding: 4px;")
            table.setCellWidget(i, 2, del_btn)

        c_layout.addWidget(table)
        layout.addWidget(card)


class PathSettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        card = create_card_frame()
        c_layout = QGridLayout(card)
        c_layout.setSpacing(25)

        c_layout.addWidget(create_title_label("경로 알고리즘 및 주행 설정"), 0, 0, 1, 2)

        c_layout.addWidget(QLabel("경로 알고리즘:"), 1, 0)
        algo_combo = QComboBox()
        algo_combo.addItems(["A* Algorithm", "Dijkstra", "DWA"])
        algo_combo.setFixedHeight(35)
        c_layout.addWidget(algo_combo, 1, 1)

        c_layout.addWidget(QLabel("장애물 회피(동적):"), 2, 0)
        toggle_obs = ToggleSwitch()
        toggle_obs.setChecked(True)
        c_layout.addWidget(toggle_obs, 2, 1, Qt.AlignLeft)

        c_layout.addWidget(QLabel("최대 주행 속도 제한:"), 3, 0)
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setRange(10, 100)
        speed_slider.setValue(80)
        c_layout.addWidget(speed_slider, 3, 1)

        c_layout.addWidget(QLabel("실시간 경로 재계산:"), 4, 0)
        toggle_live = ToggleSwitch()
        toggle_live.setChecked(True)
        c_layout.addWidget(toggle_live, 4, 1, Qt.AlignLeft)

        layout.addWidget(card)
        layout.addStretch()


class SystemSettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        card = create_card_frame()
        c_layout = QGridLayout(card)
        c_layout.setSpacing(25)

        c_layout.addWidget(create_title_label("시스템 통합 환경"), 0, 0, 1, 2)

        stat_layout = QHBoxLayout()
        stat_layout.addWidget(QLabel("시스템 상태:"))
        stat_lbl = QLabel("Online")
        stat_lbl.setStyleSheet("color: white; background-color: #67C23A; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        stat_layout.addWidget(stat_lbl)
        stat_layout.addStretch()
        c_layout.addLayout(stat_layout, 1, 0, 1, 2)

        settings = [
            ("자동 업데이트", True),
            ("로그 히스토리 영구 저장", False),
            ("다크 모드 강제 적용", False),
        ]

        row = 2
        for title, default in settings:
            c_layout.addWidget(QLabel(title), row, 0)
            tog = ToggleSwitch()
            tog.setChecked(default)
            c_layout.addWidget(tog, row, 1, Qt.AlignLeft)
            row += 1

        layout.addWidget(card)
        layout.addStretch()

class SettingsDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: white; border-bottom: 1px solid #DCDFE6;")
        top_bar.setFixedHeight(70)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(30, 0, 30, 0)
        
        title_lbl = QLabel("⚙️ 설정 및 연결")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        top_layout.addWidget(title_lbl)
        top_layout.addStretch()
        
        user_lbl = QLabel("Admin Profile ▼")
        user_lbl.setStyleSheet("color: #606266; font-weight: bold;")
        top_layout.addWidget(user_lbl)

        main_layout.addWidget(top_bar)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(250)
        sidebar.setStyleSheet("QFrame { background-color: white; border-right: 1px solid #DCDFE6; }")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 20, 0, 0)
        side_layout.setSpacing(0)

        self.menu_list = QListWidget()
        self.menu_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
                outline: none;
            }
            QListWidget::item {
                padding: 15px 30px;
                color: #606266;
                font-size: 14px;
                font-weight: bold;
            }
            QListWidget::item:selected {
                background-color: #ECF5FF;
                color: #409EFF;
                border-right: 3px solid #409EFF;
            }
            QListWidget::item:hover:!selected {
                background-color: #F5F7FA;
            }
        """)

        categories = [
            "🤖 로봇 관리",
            "🌐 네트워크 설정",
            "🪑 배치 관리",
            "🛣 경로 및 주행 설정",
            "🎛 시스템 설정"
        ]
        self.menu_list.addItems(categories)
        self.menu_list.setCurrentRow(0)

        side_layout.addWidget(self.menu_list)
        content_layout.addWidget(sidebar)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(30, 30, 30, 30)

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(RobotSettingsPage())
        self.stacked_widget.addWidget(NetworkSettingsPage())
        self.stacked_widget.addWidget(TableSettingsPage())
        self.stacked_widget.addWidget(PathSettingsPage())
        self.stacked_widget.addWidget(SystemSettingsPage())

        right_layout.addWidget(self.stacked_widget)
        content_layout.addWidget(right_container)

        main_layout.addLayout(content_layout)
        self.menu_list.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
