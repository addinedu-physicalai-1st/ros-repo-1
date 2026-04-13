from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QGridLayout)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

class TaskManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("📝 태스크(작업) 통합 관리")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # 4 Core Functions Grid
        task_types = [
            ("🍽 식기 수거 (Collect)", "지정된 테이블에서 다트(트레이)를 수거합니다.", "#4A88D4"),
            ("🔌 충전 복귀 (Charge)", "배터리 부족 로봇을 충전 스테이션으로 보냅니다.", "#E6A23C"),
            ("👥 동행 이동 (Follow)", "작업자를 따라다니며 보조 업무를 수행합니다.", "#9C27B0"),
            ("💁 고객 안내 (Guide)", "목적지(테이블/입구)까지 고객을 에스코트합니다.", "#67C23A")
        ]

        grid_frame = QFrame()
        grid_frame.setStyleSheet("background-color: transparent;")
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(15)

        for i, (name, desc, color) in enumerate(task_types):
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
            
            c_layout.addWidget(n_lbl)
            c_layout.addWidget(d_lbl)
            c_layout.addStretch()
            c_layout.addWidget(btn)
            
            row, col = divmod(i, 2)
            grid_layout.addWidget(card, row, col)

        main_layout.addWidget(grid_frame)
        main_layout.addSpacing(20)

        # Active Tasks Table
        t_lbl = QLabel("▶ 현재 진행 중인 태스크 대기열")
        t_lbl.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        main_layout.addWidget(t_lbl)

        table = QTableWidget(3, 5)
        table.setHorizontalHeaderLabels(["작업 ID", "작업 유형", "할당된 로봇", "진행 상태", "관리"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")

        mock_tasks = [
            ("T-1001", "고객 안내 (테이블 3)", "R1", "안내 이동 중 (60%)"),
            ("T-1002", "충전 복귀", "R2", "대기/이동 중 (10%)"),
            ("T-1003", "식기 수거 (테이블 5)", "R3", "복귀 중 (도킹 대기)")
        ]

        for i, (tid, typ, bot, stat) in enumerate(mock_tasks):
            table.setItem(i, 0, QTableWidgetItem(tid))
            table.setItem(i, 1, QTableWidgetItem(typ))
            table.setItem(i, 2, QTableWidgetItem(bot))
            table.setItem(i, 3, QTableWidgetItem(stat))
            
            cancel_btn = QPushButton("강제 취소")
            cancel_btn.setStyleSheet("background-color: #F56C6C; color: white; padding: 4px 10px; border-radius: 3px;")
            table.setCellWidget(i, 4, cancel_btn)

        main_layout.addWidget(table)
