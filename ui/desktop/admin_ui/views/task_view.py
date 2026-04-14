from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QGridLayout, QProgressBar, QScrollArea,
                             QLineEdit, QComboBox, QGraphicsOpacityEffect, QMenu)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, QTimer

from utils.config import COLOR_MOVING, COLOR_WAITING, COLOR_COLLECT, COLOR_CHARGING, CARD_STYLE
from utils.scheduler import TaskScheduler, TaskType, TaskStatus
from components.widgets import BatteryWidget

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
        # Custom mapping for charging workflow
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
            # Reset labels for normal task if they were changed
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

class RobotStatusCard(QFrame):
    def __init__(self, robot_id, scheduler, parent=None):
        super().__init__(parent)
        self.robot_id = robot_id
        self.scheduler = scheduler
        self.initUI()
        
    def initUI(self):
        self.setStyleSheet(CARD_STYLE)
        self.layout = QVBoxLayout(self)
        
        # Header: ID + Battery + Collector Badge
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
        
        # Middle: State / Task Info
        self.info_stack = QWidget()
        self.info_layout = QVBoxLayout(self.info_stack)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Active Info
        self.active_widget = QWidget()
        active_lay = QVBoxLayout(self.active_widget)
        active_lay.setContentsMargins(0, 0, 0, 0)
        
        self.type_lbl = QLabel("No Task")
        self.type_lbl.setStyleSheet("background-color: #ECF5FF; color: #409EFF; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;")
        
        self.fsm = FsmIndicator()
        self.est_time_lbl = QLabel("남은 시간: -")
        self.est_time_lbl.setStyleSheet("color: #E6A23C; font-weight: bold; font-size: 11px;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { border: none; background-color: #EBEEF5; border-radius: 4px; } QProgressBar::chunk { background-color: #4A88D4; border-radius: 4px; }")
        
        self.btn_cancel = QPushButton("🛑 작업 강제 취소")
        self.btn_cancel.setStyleSheet("background-color: #FEF0F0; color: #F56C6C; border: 1px solid #FBC4C4; border-radius: 4px; padding: 5px; font-weight: bold;")
        self.btn_cancel.clicked.connect(self.cancel_task)
        
        active_lay.addWidget(self.type_lbl)
        active_lay.addWidget(self.fsm)
        active_lay.addWidget(self.est_time_lbl)
        active_lay.addWidget(self.progress_bar)
        active_lay.addWidget(self.btn_cancel)
        
        # Idle Info
        self.idle_widget = QWidget()
        idle_lay = QVBoxLayout(self.idle_widget)
        self.btn_assign = QPushButton("➕ 새 작업 할당")
        self.btn_assign.setStyleSheet("background-color: #F2F6FC; border: 1px dashed #DCDFE6; border-radius: 6px; padding: 20px; color: #909399; font-weight: bold;")
        self.btn_assign.clicked.connect(self.show_assign_menu)
        idle_lay.addWidget(self.btn_assign)
        
        self.info_layout.addWidget(self.active_widget)
        self.info_layout.addWidget(self.idle_widget)
        
        self.layout.addLayout(header)
        self.layout.addWidget(self.info_stack)
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

    def cancel_task(self):
        self.scheduler.cancel_task_by_robot(self.robot_id)

    def show_assign_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: white; border: 1px solid #DCDFE6; } QMenu::item { padding: 8px 20px; } QMenu::item:selected { background-color: #F5F7FA; }")
        
        pending = self.scheduler.pending_queue
        if not pending:
            action = menu.addAction("대기 중인 작업 없음")
            action.setEnabled(False)
        else:
            for task in pending:
                label = f"[{task.id}] {task.type} (P:{task.priority})"
                action = menu.addAction(label)
                action.triggered.connect(lambda checked, tid=task.id: self.scheduler.manual_assign(tid, self.robot_id))
        
        menu.exec_(self.btn_assign.mapToGlobal(self.btn_assign.rect().bottomLeft()))

    def update_state(self, task, stats):
        battery = stats.get("battery", 0)
        self.battery_ui.setLevel(int(battery))
        
        # Battery Lock / Auto Charge UI
        if task and task.type == TaskType.CHARGE:
            self.setEnabled(True)
            self.active_widget.setVisible(True)
            self.idle_widget.setVisible(False)
            self.type_lbl.setText("🔋 자동 충전 수행 중")
            self.type_lbl.setStyleSheet("background-color: #F0F9EB; color: #67C23A; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;")
            self.btn_cancel.setText("🛑 충전 수동 중단")
            self.opacity_effect.setOpacity(1.0)
            
            # Show Workflow Label
            self.est_time_lbl.setText("워크플로우: [저배터리 감지] → [충전기 복귀] → [충전 중]")
            self.est_time_lbl.setStyleSheet("color: #67C23A; font-size: 9px; font-weight: bold;")
            
            self.fsm.set_status(task.status)
            self.progress_bar.setValue(int(task.progress))
            self.progress_bar.setStyleSheet("QProgressBar { border: none; background-color: #EBEEF5; border-radius: 4px; } QProgressBar::chunk { background-color: #67C23A; border-radius: 4px; }")

        elif battery < 20:
            self.setEnabled(False)
            self.active_widget.setVisible(False)
            self.idle_widget.setVisible(True)
            self.btn_assign.setText("⚠️ 배터리 부족 (충전기로 이동 중...)")
            self.btn_assign.setStyleSheet("background-color: #FEF0F0; color: #F56C6C; border: 1px solid #FBC4C4; border-radius: 6px; padding: 20px;")
            self.opacity_effect.setOpacity(0.8)
        else:
            self.setEnabled(True)
            self.btn_assign.setText("➕ 새 작업 할당")
            self.btn_assign.setStyleSheet("background-color: #F2F6FC; border: 1px dashed #DCDFE6; border-radius: 6px; padding: 20px; color: #909399; font-weight: bold;")
            self.progress_bar.setStyleSheet("QProgressBar { border: none; background-color: #EBEEF5; border-radius: 4px; } QProgressBar::chunk { background-color: #4A88D4; border-radius: 4px; }")

            if task:
                self.opacity_effect.setOpacity(1.0)
                self.active_widget.setVisible(True)
                self.idle_widget.setVisible(False)
                self.type_lbl.setText(task.type)
                self.type_lbl.setStyleSheet("background-color: #ECF5FF; color: #409EFF; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold;")
                self.btn_cancel.setText("🛑 작업 강제 취소")
                self.fsm.set_status(task.status)
                self.progress_bar.setValue(int(task.progress))
                rem = max(0, int(task.est_duration * (1 - task.progress/100)))
                self.est_time_lbl.setText(f"남은 시간: {rem}s")
                self.est_time_lbl.setStyleSheet("color: #E6A23C; font-weight: bold; font-size: 11px;")
                
                is_collector = (self.robot_id == self.scheduler.collector_robot_id and task.type == TaskType.COLLECT)
                self.collector_badge.setVisible(is_collector)
            else:
                self.opacity_effect.setOpacity(0.5)
                self.active_widget.setVisible(False)
                self.idle_widget.setVisible(True)
                self.collector_badge.setVisible(False)

class TaskManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        self.scheduler = TaskScheduler()
        self.scheduler.task_updated.connect(self.update_ui)
        self.initUI()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.simulation_step)
        self.timer.start(1000)
        
        # Initial assignment for demo
        self.scheduler.add_task(TaskType.SERVING, "테이블 3")
        self.scheduler.add_task(TaskType.COLLECT, "테이블 5")

    def initUI(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        # 1. Top Panel: Task Control
        top_panel = QFrame()
        top_layout = QGridLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(15)
        
        task_types = [
            (TaskType.SERVING, "🥘", "서빙 요청", COLOR_MOVING),
            (TaskType.FOLLOW, "👥", "동행 이동", "#9C27B0"),
            (TaskType.GUIDE, "💁", "고객 안내", "#67C23A"),
            (TaskType.COLLECT, "🧺", "식기 수거 (우선)", COLOR_COLLECT)
        ]
        
        for i, (name, icon, desc, color) in enumerate(task_types):
            card = QFrame()
            if isinstance(color, str): color = QColor(color)
            card.setStyleSheet(f"background-color: white; border: 2px solid {color.name()}; border-radius: 12px;")
            c_layout = QVBoxLayout(card)
            
            i_lbl = QLabel(icon)
            i_lbl.setFont(QFont("Arial", 24))
            i_lbl.setAlignment(Qt.AlignCenter)
            
            n_lbl = QLabel(name)
            n_lbl.setFont(QFont("Malgun Gothic", 13, QFont.Bold))
            n_lbl.setAlignment(Qt.AlignCenter)
            n_lbl.setStyleSheet(f"color: {color.name()}; border: none;")
            
            btn = QPushButton("작업 요청")
            btn.setStyleSheet(f"background-color: {color.name()}; color: white; padding: 10px; border-radius: 6px; font-weight: bold;")
            btn.clicked.connect(lambda checked, n=name: self.scheduler.add_task(n))
            
            c_layout.addWidget(i_lbl)
            c_layout.addWidget(n_lbl)
            c_layout.addStretch()
            c_layout.addWidget(btn)
            top_layout.addWidget(card, 0, i)
            
        self.main_layout.addWidget(top_panel)

        # 2. Middle Panel: Monitor & Queue
        mid_panel = QHBoxLayout()
        
        # 2a. Active Monitor (Fixed Robot Cards)
        monitor_frame = QFrame()
        monitor_frame.setStyleSheet(CARD_STYLE)
        monitor_layout = QVBoxLayout(monitor_frame)
        monitor_layout.addWidget(QLabel("⚡ 실시간 로봇 상태 모니터 (Fixed)"))
        
        self.robot_cards = {}
        for rid in ["R1", "R2", "R3"]:
            card = RobotStatusCard(rid, self.scheduler)
            self.robot_cards[rid] = card
            monitor_layout.addWidget(card)
        monitor_layout.addStretch()
        
        mid_panel.addWidget(monitor_frame, 3)
        
        # 2b. Priority Queue
        queue_frame = QFrame()
        queue_frame.setStyleSheet(CARD_STYLE)
        queue_layout = QVBoxLayout(queue_frame)
        queue_layout.addWidget(QLabel("⏳ 대기 중인 작업 (로봇 강제 할당)"))
        
        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["ID", "유형", "로봇 선택", "동작"])
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.queue_table.setStyleSheet("border: none;")
        queue_layout.addWidget(self.queue_table)
        
        mid_panel.addWidget(queue_frame, 3)
        self.main_layout.addLayout(mid_panel, 2)

        # 3. Bottom Panel: History Log
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

    def simulation_step(self):
        self.scheduler.update_progress()
        active_ids = [t.robot_id for t in self.scheduler.active_tasks]
        for rid in ["R1", "R2", "R3"]:
            if rid not in active_ids and self.scheduler.pending_queue:
                self.scheduler.assign_task(rid)

    def manual_assign_handler(self, task_id, combo):
        rid = combo.currentText()
        self.scheduler.manual_assign(task_id, rid)

    def update_ui(self):
        # Update Robot Cards (Fixed Order)
        active_map = {t.robot_id: t for t in self.scheduler.active_tasks}
        for rid, card in self.robot_cards.items():
            task = active_map.get(rid)
            stats = self.scheduler.robot_stats.get(rid, {})
            card.update_state(task, stats)
        
        # Update Queue (Active + Pending)
        all_tasks = self.scheduler.active_tasks + self.scheduler.pending_queue
        self.queue_table.setRowCount(len(all_tasks))
        
        for i, task in enumerate(all_tasks):
            is_active = task in self.scheduler.active_tasks
            
            # ID column
            id_text = f"{task.id}"
            if is_active: id_text = f"▶ {id_text} (진행중)"
            item_id = QTableWidgetItem(id_text)
            if is_active: 
                item_id.setForeground(QColor("#409EFF"))
                item_id.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
            self.queue_table.setItem(i, 0, item_id)
            
            # Type column
            self.queue_table.setItem(i, 1, QTableWidgetItem(f"{task.type} {f'({int(task.progress)}%)' if is_active else f'(~{task.est_duration}s)'}"))
            
            if is_active:
                # Robot column for active
                lbl_bot = QLabel(f"🤖 {task.robot_id}")
                lbl_bot.setAlignment(Qt.AlignCenter)
                lbl_bot.setStyleSheet("color: #409EFF; font-weight: bold;")
                self.queue_table.setCellWidget(i, 2, lbl_bot)
                
                # Action column for active
                btn_cancel = QPushButton("취소")
                btn_cancel.setStyleSheet("background-color: #FEF0F0; color: #F56C6C; border: 1px solid #FBC4C4; border-radius: 4px;")
                btn_cancel.clicked.connect(lambda checked, rid=task.robot_id: self.scheduler.cancel_task_by_robot(rid))
                self.queue_table.setCellWidget(i, 3, btn_cancel)
            else:
                # Robot selection combo for pending
                combo = QComboBox()
                combo.addItems(["R1", "R2", "R3"])
                self.queue_table.setCellWidget(i, 2, combo)
                
                # Assign button for pending
                btn_assign = QPushButton("강제 할당")
                btn_assign.setStyleSheet("background-color: #f0f9eb; color: #67c23a; border: 1px solid #c2e7b0; border-radius: 4px;")
                btn_assign.clicked.connect(lambda checked, tid=task.id, c=combo: self.manual_assign_handler(tid, c))
                self.queue_table.setCellWidget(i, 3, btn_assign)
            
        # Update History
        self.log_table.setRowCount(len(self.scheduler.history))
        for i, task in enumerate(self.scheduler.history):
            data = task.to_list()
            for j, val in enumerate(data):
                item = QTableWidgetItem(val)
                if j == 4:
                    if val == TaskStatus.COMPLETED: item.setForeground(QColor("#67C23A"))
                    elif val == TaskStatus.FAILED: item.setForeground(QColor("#F56C6C"))
                self.log_table.setItem(i, j, item)
