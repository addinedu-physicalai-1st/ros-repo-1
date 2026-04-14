import sys
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QGraphicsView, QGraphicsScene, QGraphicsPathItem, QScrollArea, QFrame)
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPainterPath
from PyQt5.QtCore import Qt, QTimer, QPointF

from components.map_items import RobotMapItem
from components.widgets import RobotCard
from utils.config import (MAP_IMG_PATH, COLOR_MOVING, COLOR_WAITING, 
                          COLOR_COLLECT, COLOR_CHARGING)

class MapWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setStyleSheet("background-color: #F4EFE6;")
        
        self.bg_pixmap = QPixmap(MAP_IMG_PATH)
        if self.bg_pixmap.isNull():
            self.bg_pixmap = QPixmap(1000, 1000)
            self.bg_pixmap.fill(QColor("#EAE0D5"))
            
        self.scene.addPixmap(self.bg_pixmap)
        self.setSceneRect(0, 0, self.bg_pixmap.width(), self.bg_pixmap.height())

        self.path_items = []
        self.robots = {}

        self.sim_timer = QTimer(self)
        self.sim_timer.timeout.connect(self.update_simulation)
        self.sim_timer.start(30)

    def add_robot(self, r_id, color, start_pos, path_points):
        robot = RobotMapItem(r_id, color, start_pos)
        robot.set_path(path_points)
        self.scene.addItem(robot)
        self.robots[r_id] = robot
        
        if len(path_points) > 0:
            path = QPainterPath()
            path.moveTo(start_pos)
            for p in path_points:
                path.lineTo(p)
            
            p_item = QGraphicsPathItem(path)
            pen = QPen(color, 3, Qt.DashLine)
            p_item.setPen(pen)
            self.scene.addItem(p_item)
            p_item.setZValue(-1)

    def update_simulation(self):
        for robot in self.robots.values():
            robot.advance_pos()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        
    def fit_view(self): self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


class MapDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.init_mock_data()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        title_lbl = QLabel("전체 2D 맵")
        title_lbl.setFont(QFont("Arial", 14, QFont.Bold))
        left_layout.addWidget(title_lbl)

        self.map_view = MapWidget()
        left_layout.addWidget(self.map_view, 1)



        legend_frame = QFrame()
        legend_frame.setStyleSheet("background-color: white; border-radius: 5px;")
        legend_layout = QHBoxLayout(legend_frame)
        
        legends = [("총 로봇\n4대", "black"), ("이동 중\n1대", COLOR_MOVING.name()), 
                   ("대기\n1대", COLOR_WAITING.name()), ("수거\n1대", COLOR_COLLECT.name()), 
                   ("충전 중\n1대", COLOR_CHARGING.name())]
        for t, c in legends:
            lbl = QLabel(t)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color: {c}; font-weight: bold;")
            legend_layout.addWidget(lbl)
            
        left_layout.addWidget(legend_frame)
        main_layout.addLayout(left_layout, 2)

        right_layout = QVBoxLayout()
        right_title = QLabel("로봇 목록")
        right_title.setFont(QFont("Arial", 14, QFont.Bold))
        right_layout.addWidget(right_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.robots_container = QWidget()
        self.robots_container.setStyleSheet("background: transparent;")
        self.robots_layout = QVBoxLayout(self.robots_container)
        self.robots_layout.setContentsMargins(0, 0, 0, 0)
        self.robots_layout.setSpacing(10)
        self.robots_layout.addStretch()
        
        scroll.setWidget(self.robots_container)
        right_layout.addWidget(scroll)

        main_layout.addLayout(right_layout, 1)

    def add_robot_to_list(self, r_id, status_text, status_color, battery, target):
        card = RobotCard(r_id, status_text, status_color, battery, target)
        self.robots_layout.insertWidget(self.robots_layout.count() - 1, card)

    def init_mock_data(self):
        w = self.map_view.bg_pixmap.width()
        h = self.map_view.bg_pixmap.height()
        p = lambda rx, ry: QPointF(w * rx, h * ry)

        c1 = COLOR_MOVING
        self.add_robot_to_list("R1", "이동", c1, 73, "목표: 테이블 C-3 (호출)")
        p1 = [p(0.2, 0.5), p(0.5, 0.5), p(0.5, 0.2), p(0.6, 0.2)]
        self.map_view.add_robot("R1", c1, p(0.2, 0.8), p1)

        c2 = COLOR_WAITING
        self.add_robot_to_list("R2", "대기", c2, 44, "호출 대기 중\n다음 작업 대기 중")
        p2 = [p(0.5, 0.5), p(0.7, 0.5), p(0.7, 0.7)]
        self.map_view.add_robot("R2", c2, p(0.3, 0.5), p2)

        c3 = COLOR_COLLECT
        self.add_robot_to_list("R3", "수거", c3, 80, "목표: 테이블 A-2 (식기 수거)")
        p3 = [p(0.7, 0.5), p(0.7, 0.3), p(0.8, 0.3)]
        self.map_view.add_robot("R3", c3, p(0.9, 0.5), p3)

        c4 = COLOR_CHARGING
        self.add_robot_to_list("R4", "충전", c4, 16, "충전 중 (충전존)")
        self.map_view.add_robot("R4", c4, p(0.85, 0.85), [])

        QTimer.singleShot(100, self.map_view.fit_view)
