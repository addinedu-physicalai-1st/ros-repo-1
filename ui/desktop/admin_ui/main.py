import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QStackedWidget, QFrame, QListWidget)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from views.map_view import MapDashboard
from views.robot_setting_view import RobotSettingPage
from views.map_setting_view import MapSettingPage
from views.task_view import TaskManagementPage
from views.record_view import RecordManagementPage
from utils.test_manager import TestDataManager

class UnifiedAdminGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("통합 관제 시스템 - 로봇 및 맵 관리")
        self.resize(1920, 1080)
        self.setStyleSheet("QMainWindow { background-color: #2F3542; }")

        self.test_manager = TestDataManager()

        self.map_app = MapDashboard()
        self.robot_setting = RobotSettingPage(self.test_manager)
        self.map_setting = MapSettingPage(self.test_manager)
        self.task_app = TaskManagementPage()
        self.record_app = RecordManagementPage()

        self.initUI()

    def initUI(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet("background-color: #2F3542; color: white;")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 20, 0, 0)
        
        logo = QLabel("🤖 Smart Admin")
        logo.setFont(QFont("Arial", 18, QFont.Bold))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("color: white; margin-bottom: 20px;")
        side_layout.addWidget(logo)

        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
                outline: none;
            }
            QListWidget::item {
                padding: 18px 25px;
                color: #A4B0BE;
                font-size: 15px;
                font-weight: bold;
            }
            QListWidget::item:selected {
                background-color: #57606F;
                color: white;
                border-left: 4px solid #1E90FF;
            }
            QListWidget::item:hover:!selected {
                background-color: #414A5A;
            }
        """)
        
        # 6 main tabs requested by user
        nav_items = [
            "🗺️ 관제 메인 페이지", 
            "🤖 로봇 개별 환경 설정", 
            "🪑 맵(테이블/경로) 설정", 
            "📝 태스크(작업) 통합 관리",
            "📹 비전 및 녹화 관리 (블랙박스)",
            "🧪 관제 시스템 및 네트워크 테스트"
        ]
        self.nav_list.addItems(nav_items)
        self.nav_list.setCurrentRow(0)
        side_layout.addWidget(self.nav_list)
        
        prof_frame = QFrame()
        prof_frame.setStyleSheet("background-color: #1E272E;")
        p_layout = QVBoxLayout(prof_frame)
        p_layout.addWidget(QLabel("User: Admin\nStatus: Online"))
        side_layout.addWidget(prof_frame)

        main_layout.addWidget(sidebar)

        self.central_stack = QStackedWidget()
        
        # 1. Map Dashboard
        self.central_stack.addWidget(self.map_app)
        
        # 2. Robot Settings
        robot_wrapper = QWidget()
        robot_wrapper.setStyleSheet("background-color: white;")
        r_layout = QVBoxLayout(robot_wrapper)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.addWidget(self.robot_setting)
        self.central_stack.addWidget(robot_wrapper)
        
        # 3. Map Settings
        map_wrapper = QWidget()
        map_wrapper.setStyleSheet("background-color: white;")
        m_layout = QVBoxLayout(map_wrapper)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.addWidget(self.map_setting)
        self.central_stack.addWidget(map_wrapper)

        # 4. Task Management
        task_wrapper = QWidget()
        task_wrapper.setStyleSheet("background-color: white;")
        t_layout = QVBoxLayout(task_wrapper)
        t_layout.setContentsMargins(0, 0, 0, 0)
        t_layout.addWidget(self.task_app)
        self.central_stack.addWidget(task_wrapper)

        # 5. Record / Vision Management
        record_wrapper = QWidget()
        record_wrapper.setStyleSheet("background-color: white;")
        rec_layout = QVBoxLayout(record_wrapper)
        rec_layout.setContentsMargins(0, 0, 0, 0)
        rec_layout.addWidget(self.record_app)
        self.central_stack.addWidget(record_wrapper)

        # 6. Global System / Server Tests
        system_tests_wrapper = QWidget()
        system_tests_wrapper.setStyleSheet("background-color: white;")
        st_layout = QVBoxLayout(system_tests_wrapper)
        st_layout.setContentsMargins(30, 30, 30, 30)
        st_title = QLabel("🧪 관제 시스템 통합 네트워크 모의 테스트")
        st_title.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        st_layout.addWidget(st_title)
        
        system_test_table = self.test_manager.create_test_table(
            ["D. TCP 상태/보고", "E. REST API", "F. 성능/실시간성", "G. 장애/예외(⚠️)"]
        )
        st_layout.addWidget(system_test_table)

        self.central_stack.addWidget(system_tests_wrapper)
        
        main_layout.addWidget(self.central_stack)
        self.nav_list.currentRowChanged.connect(self.central_stack.setCurrentIndex)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Malgun Gothic", 10)
    app.setFont(font)
    window = UnifiedAdminGUI()
    window.showMaximized()
    sys.exit(app.exec_())
