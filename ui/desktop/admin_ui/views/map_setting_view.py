from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

class MapSettingPage(QWidget):
    def __init__(self, test_data_manager):
        super().__init__()
        self.test_data = test_data_manager
        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title_lbl = QLabel("🪑 표심/경로 및 관제 자동 설정")
        title_lbl.setFont(QFont("Malgun Gothic", 18, QFont.Bold))
        main_layout.addWidget(title_lbl)

        # Dashboard
        dash_frame = QFrame()
        dash_frame.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; border: 1px solid #E4E7ED;")
        dash_layout = QHBoxLayout(dash_frame)
        
        self.lbl_table_count = QLabel("12개")
        self.lbl_table_count.setFont(QFont("Arial", 16, QFont.Bold))
        self.lbl_table_count.setStyleSheet("color: #4A88D4;")
        self.lbl_table_count.setAlignment(Qt.AlignCenter)

        metrics = [
            ("서버 상태", QLabel("Online"), "#67C23A"), 
            ("등록된 테이블", self.lbl_table_count, ""), 
            ("경로 모드", QLabel("A* Auto"), "#E6A23C"), 
            ("평균 지연율", QLabel("14ms"), "#909399")
        ]
        
        for name, v_lbl, color in metrics:
            if color:
                v_lbl.setFont(QFont("Arial", 16, QFont.Bold))
                v_lbl.setStyleSheet(f"color: {color};")
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

        # Table Management Header
        header_layout = QHBoxLayout()
        t_lbl = QLabel("▶ 배치(테이블) 관리")
        t_lbl.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        header_layout.addWidget(t_lbl)
        
        header_layout.addStretch()
        btn_add = QPushButton("➕ 테이블 추가")
        btn_add.setStyleSheet("background-color: #67C23A; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold;")
        btn_add.clicked.connect(self.add_table_row)
        header_layout.addWidget(btn_add)
        
        main_layout.addLayout(header_layout)

        # Table list
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["테이블 이름", "수용 인원", "관리"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet("QTableWidget { gridline-color: #E4E7ED; border: 1px solid #E4E7ED; background: white; }")
        
        self.table_counter = 1
        for i in range(12):
            self.add_table_row_data(f"테이블 {self.table_counter}", "4명" if i % 2 == 0 else "6명")

        main_layout.addWidget(self.table)
        
    def add_table_row(self):
        self.add_table_row_data(f"신규 테이블 {self.table_counter}", "4명")

    def add_table_row_data(self, name, cap):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(cap))
        
        del_btn = QPushButton("삭제")
        del_btn.setStyleSheet("color: white; background-color: #F56C6C; border-radius: 3px; padding: 4px;")
        
        # Capture the specific row via lambda parameter
        del_btn.clicked.connect(lambda _, r=row: self.delete_row_by_widget(del_btn))
        
        self.table.setCellWidget(row, 2, del_btn)
        self.table_counter += 1
        self.update_count()

    def delete_row_by_widget(self, btn):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 2) == btn:
                self.table.removeRow(row)
                self.update_count()
                break

    def update_count(self):
        count = self.table.rowCount()
        self.lbl_table_count.setText(f"{count}개")
