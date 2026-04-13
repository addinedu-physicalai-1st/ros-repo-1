import sys
import math
from PyQt5.QtWidgets import QGraphicsItem
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt5.QtCore import Qt, QPointF, QRectF

QGraphicsObject = QGraphicsItem
if hasattr(sys, 'QGraphicsObject'):
    from PyQt5.QtWidgets import QGraphicsObject

class RobotMapItem(QGraphicsObject):
    def __init__(self, r_id, color, init_pos):
        super().__init__()
        self.r_id = r_id
        self.color = color
        self.setPos(init_pos)
        self.path = []
        self.current_target_idx = 0
        self.speed = 2.0

    def boundingRect(self):
        return QRectF(-30, -30, 60, 60)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw shadow
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawEllipse(-28, -28, 60, 60)
        
        # Outer circle
        painter.setBrush(QBrush(QColor("white")))
        painter.setPen(QPen(self.color, 4))
        painter.drawEllipse(-30, -30, 60, 60)
        
        # Inner circle
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(-24, -24, 48, 48)
        
        # Text
        painter.setPen(QPen(QColor("white")))
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self.r_id)

    def set_path(self, path):
        self.path = path
        self.current_target_idx = 0

    def advance_pos(self):
        if not self.path or self.current_target_idx >= len(self.path):
            return
        
        target = self.path[self.current_target_idx]
        cur = self.pos()
        dx = target.x() - cur.x()
        dy = target.y() - cur.y()
        dist = math.hypot(dx, dy)
        
        if dist < self.speed:
            self.setPos(target)
            self.current_target_idx += 1
            if self.current_target_idx >= len(self.path):
                self.path.reverse()
                self.current_target_idx = 1
        else:
            nx = cur.x() + (dx / dist) * self.speed
            ny = cur.y() + (dy / dist) * self.speed
            self.setPos(QPointF(nx, ny))
