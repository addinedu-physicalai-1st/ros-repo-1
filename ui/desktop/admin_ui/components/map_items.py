"""Graphics items for the admin dashboard 2D map."""

import math
import re
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
        # Compact badge (digits preferred: "pinky1" → "1")
        m = re.search(r"\d+", r_id)
        self._badge = m.group() if m else r_id[:2].upper()

    # Visual sizing (scene units ≈ pixels at 1.0 zoom)
    R_OUTER = 16    # outer white ring radius
    R_INNER = 13    # colored body radius
    ARROW_TIP = 34  # distance from center to arrow tip
    ARROW_BASE = 8  # distance from center to arrow base (inside body)
    ARROW_HALF = 11 # half-width of arrow base

    def boundingRect(self):
        # Cover arrow tip in any yaw, drop shadow, and name label below body
        return QRectF(-38, -38, 76, 78)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)

        R = self.R_OUTER
        r = self.R_INNER

        # Direction arrow — slim isosceles triangle pointing in yaw direction
        cos_y = math.cos(self.yaw)
        sin_y = -math.sin(self.yaw)  # screen y is flipped
        # Forward and perpendicular unit axes
        fx, fy = cos_y, sin_y
        nx, ny = -sin_y, cos_y  # 90° CCW on screen
        def pt(along, across):
            return QPointF(fx * along + nx * across, fy * along + ny * across)

        tip    = pt(self.ARROW_TIP, 0)
        base_l = pt(self.ARROW_BASE,  self.ARROW_HALF)
        base_r = pt(self.ARROW_BASE, -self.ARROW_HALF)
        arrow = QPolygonF([tip, base_l, base_r])

        # Soft drop shadow under body
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawEllipse(QPointF(1.2, 1.8), R, R)

        # Arrow — opaque fill + dark outline for strong contrast
        arrow_outline = QColor(self.color).darker(160)
        painter.setBrush(QBrush(self.color))
        painter.setPen(QPen(arrow_outline, 1.5))
        painter.drawPolygon(arrow)

        # Outer white ring
        painter.setBrush(QBrush(QColor("white")))
        painter.setPen(QPen(self.color, 2.2))
        painter.drawEllipse(QPointF(0, 0), R, R)

        # Colored inner body
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(0, 0), r, r)

        # Subtle top highlight for a polished look
        highlight = QColor(255, 255, 255, 60)
        painter.setBrush(QBrush(highlight))
        painter.drawEllipse(QPointF(0, -r * 0.35), r * 0.75, r * 0.35)

        # Text layer — counter-rotate so badge + label stay upright
        painter.save()
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if view:
            vt = view.transform()
            rot = math.atan2(vt.m12(), vt.m11())
            if abs(rot) > 0.01:
                painter.rotate(math.degrees(-rot))

        # Compact badge inside the circle
        painter.setPen(QPen(QColor("white")))
        badge_font = QFont()
        badge_font.setPointSize(9)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        painter.drawText(QRectF(-R, -R, R * 2, R * 2), Qt.AlignCenter, self._badge)

        # Full name pill below the body
        label_font = QFont()
        label_font.setPointSize(7)
        label_font.setBold(True)
        painter.setFont(label_font)
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(self.r_id)
        pad_x, pad_h = 6, 13
        pill_w = text_w + pad_x * 2
        pill_rect = QRectF(-pill_w / 2, R + 4, pill_w, pad_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawRoundedRect(pill_rect, 6, 6)
        painter.setPen(QPen(QColor("#333333")))
        painter.drawText(pill_rect, Qt.AlignCenter, self.r_id)

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
        self.editable = False  # Set True in edit mode
        self._hover = False
        # Callback(wp_id) fired on every position change while dragging.
        self.on_moved = None
        self.setPos(x, y)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)

    def itemChange(self, change, value):
        if (change == QGraphicsItem.ItemScenePositionHasChanged
                and self.editable and callable(self.on_moved)):
            try:
                self.on_moved(self.wp_id)
            except Exception:
                pass
        return super().itemChange(change, value)

    def boundingRect(self):
        r = self.RADIUS
        return QRectF(-r - 40, -r - 14, r * 2 + 80, r * 2 + 28)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.RADIUS
        # Edit mode: orange drag handle
        if self.editable:
            handle_r = 14 if self._hover else 10
            painter.setPen(QPen(QColor("#ff7f0e"), 2.5 if self._hover else 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(-handle_r, -handle_r, handle_r * 2, handle_r * 2)
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

    def hoverEnterEvent(self, event):
        if self.editable:
            self._hover = True
            self.update()

    def hoverLeaveEvent(self, event):
        if self.editable:
            self._hover = False
            self.update()

    # Right-click in edit mode → context menu (set by parent widget)
    on_context_menu = None  # callback(wp_id, scene_pos)

    # Shift+click in edit mode → fire on_connect_pick callback
    on_connect_pick = None  # callback(wp_id)

    def mousePressEvent(self, event):
        from PyQt5.QtCore import Qt as _Qt
        if (self.editable and event.button() == _Qt.RightButton
                and callable(self.on_context_menu)):
            try:
                self.on_context_menu(self.wp_id, event.screenPos())
            except Exception:
                pass
            event.accept()
            return
        if (self.editable and event.button() == _Qt.LeftButton
                and (event.modifiers() & _Qt.ShiftModifier)
                and callable(self.on_connect_pick)):
            try:
                self.on_connect_pick(self.wp_id)
            except Exception:
                pass
            event.accept()
            return
        super().mousePressEvent(event)


# ── Edge line ─────────────────────────────────────────────────────────────────

class EdgeLineItem(QGraphicsItem):
    """Edge between two waypoints, right-clickable in edit mode for deletion."""

    HIT_RADIUS = 6.0  # px — fattens the click area beyond the visible line

    def __init__(self, a_id: int, b_id: int,
                 x1: float, y1: float, x2: float, y2: float,
                 parent=None):
        super().__init__(parent)
        self.a_id = a_id
        self.b_id = b_id
        self._x1, self._y1, self._x2, self._y2 = x1, y1, x2, y2
        self.editable = False
        # callback(a_id, b_id, screen_pos) — fired on right-click in edit mode
        self.on_context_menu = None
        self.setAcceptHoverEvents(True)
        self._hover = False

    def boundingRect(self):
        r = self.HIT_RADIUS
        return QRectF(
            min(self._x1, self._x2) - r,
            min(self._y1, self._y2) - r,
            abs(self._x2 - self._x1) + 2 * r,
            abs(self._y2 - self._y1) + 2 * r,
        )

    def shape(self):
        from PyQt5.QtGui import QPainterPath, QPainterPathStroker
        path = QPainterPath()
        path.moveTo(self._x1, self._y1)
        path.lineTo(self._x2, self._y2)
        stroker = QPainterPathStroker()
        stroker.setWidth(self.HIT_RADIUS * 2)
        return stroker.createStroke(path)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#ff7f0e") if (self.editable and self._hover) \
                else QColor("#1f77b4")
        width = 4.0 if (self.editable and self._hover) else 2.5
        opacity = 1.0 if (self.editable and self._hover) else 0.4
        painter.setOpacity(opacity)
        painter.setPen(QPen(color, width))
        painter.drawLine(int(self._x1), int(self._y1),
                         int(self._x2), int(self._y2))

    def hoverEnterEvent(self, event):
        if self.editable:
            self._hover = True
            self.update()

    def hoverLeaveEvent(self, event):
        if self.editable:
            self._hover = False
            self.update()

    def mousePressEvent(self, event):
        from PyQt5.QtCore import Qt as _Qt
        if (self.editable and event.button() == _Qt.RightButton
                and callable(self.on_context_menu)):
            try:
                self.on_context_menu(self.a_id, self.b_id, event.screenPos())
            except Exception:
                pass
            event.accept()
            return
        super().mousePressEvent(event)


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
