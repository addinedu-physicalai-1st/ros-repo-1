"""Graphics items for the admin dashboard 2D map."""

import math
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsLineItem
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPolygonF
from PyQt5.QtCore import Qt, QPointF, QRectF


# Use QGraphicsItem as the base — it's available in all PyQt5 builds.
QGraphicsObject = QGraphicsItem


# ── Robot marker ──────────────────────────────────────────────────────────────

class RobotMapItem(QGraphicsObject):
    """Circular robot marker with ID label and optional yaw arrow."""

    def __init__(self, r_id, color, init_pos):
        super().__init__()
        self.r_id = r_id
        self.color = color
        self.setPos(init_pos)
        self.yaw = 0.0  # radians, 0 = east
        self.path = []
        self.current_target_idx = 0
        self.speed = 2.0

    def boundingRect(self):
        return QRectF(-35, -35, 70, 70)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        # Shadow
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

        # Yaw arrow
        arrow_len = 32
        dx = math.cos(self.yaw) * arrow_len
        dy = -math.sin(self.yaw) * arrow_len
        painter.setPen(QPen(QColor("white"), 3))
        painter.drawLine(QPointF(0, 0), QPointF(dx, dy))
        head_len = 10
        angle = math.atan2(dy, dx)
        p1 = QPointF(
            dx - head_len * math.cos(angle - 0.4),
            dy - head_len * math.sin(angle - 0.4),
        )
        p2 = QPointF(
            dx - head_len * math.cos(angle + 0.4),
            dy - head_len * math.sin(angle + 0.4),
        )
        painter.setBrush(QBrush(QColor("white")))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(dx, dy), p1, p2]))

        # Text (counter-rotate to stay upright if view is rotated)
        painter.save()
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if view:
            vt = view.transform()
            # Extract rotation angle and counter-rotate
            rot = math.atan2(vt.m12(), vt.m11())
            if abs(rot) > 0.01:
                painter.rotate(math.degrees(-rot))
        painter.setPen(QPen(QColor("white")))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(-30, -30, 60, 60), Qt.AlignCenter, self.r_id)
        painter.restore()

    def set_yaw(self, yaw: float) -> None:
        """Set orientation in radians (ROS convention: 0=east, CCW+)."""
        self.yaw = yaw
        self.update()

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
        else:
            nx = cur.x() + (dx / dist) * self.speed
            ny = cur.y() + (dy / dist) * self.speed
            self.setPos(QPointF(nx, ny))


# ── Waypoint node ─────────────────────────────────────────────────────────────

class WaypointItem(QGraphicsItem):
    """Small circle representing a waypoint on the map."""

    RADIUS = 6

    def __init__(self, wp_id: int, x: float, y: float,
                 label: str = "", parent=None):
        super().__init__(parent)
        self.wp_id = wp_id
        self.label = label
        self.setPos(x, y)

    def boundingRect(self):
        r = self.RADIUS
        return QRectF(-r - 40, -r - 14, r * 2 + 80, r * 2 + 28)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.RADIUS
        # Node circle
        painter.setPen(QPen(QColor("#1f77b4"), 1.5))
        painter.setBrush(QBrush(QColor("#1f77b4")))
        painter.drawEllipse(-r, -r, r * 2, r * 2)
        # Label (counter-rotate to stay upright)
        if self.label:
            painter.save()
            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view:
                vt = view.transform()
                rot = math.atan2(vt.m12(), vt.m11())
                if abs(rot) > 0.01:
                    painter.rotate(math.degrees(-rot))
            painter.setPen(QPen(QColor("#555555")))
            font = QFont()
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(
                QRectF(-40, -r - 14, 80, 14),
                Qt.AlignCenter, self.label,
            )
            painter.restore()


# ── Path line ─────────────────────────────────────────────────────────────────

class PathLineItem(QGraphicsItem):
    """Line showing a path (list of scene-coordinate points)."""

    def __init__(self, points: list, color: QColor, dashed: bool = False,
                 opacity: float = 0.4, width: float = 2.5, parent=None):
        super().__init__(parent)
        self._points = points
        self._color = color
        self._dashed = dashed
        self._opacity = opacity
        self._width = width
        self._rect = QRectF()
        self._compute_rect()

    def _compute_rect(self):
        if not self._points:
            self._rect = QRectF()
            return
        xs = [p.x() for p in self._points]
        ys = [p.y() for p in self._points]
        self._rect = QRectF(
            min(xs) - 5, min(ys) - 5,
            max(xs) - min(xs) + 10, max(ys) - min(ys) + 10,
        )

    def set_points(self, points: list, color: QColor = None):
        self.prepareGeometryChange()
        self._points = points
        if color:
            self._color = color
        self._compute_rect()
        self.update()

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget):
        if len(self._points) < 2:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._opacity)
        pen = QPen(self._color, self._width)
        pen.setStyle(Qt.DashLine if self._dashed else Qt.SolidLine)
        painter.setPen(pen)
        for i in range(len(self._points) - 1):
            painter.drawLine(self._points[i], self._points[i + 1])
