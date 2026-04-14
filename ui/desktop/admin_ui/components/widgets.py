from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPixmap
from PyQt5.QtCore import Qt

from utils.config import COLOR_CHARGING, CARD_STYLE

class ToggleSwitch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 26)
        self._checked = False
        self._thumb_pos = 2

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def isChecked(self):
        return self._checked

    def setChecked(self, state):
        self._checked = state
        self._thumb_pos = 26 if self._checked else 2
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background track
        painter.setPen(Qt.NoPen)
        bg_color = QColor("#4A88D4") if self._checked else QColor("#DCDFE6")
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(0, 0, 50, 26, 13, 13)

        # Thumb
        painter.setBrush(QBrush(QColor("white")))
        painter.drawEllipse(self._thumb_pos, 2, 22, 22)


class BatteryWidget(QWidget):
    def __init__(self, level, parent=None):
        super().__init__(parent)
        self.level = level
        self.initUI()

    def initUI(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(24, 16)
        self.update_icon()
        
        self.level_label = QLabel(f"{self.level}%")
        font = QFont()
        font.setBold(True)
        self.level_label.setFont(font)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.level_label)

    def setLevel(self, level):
        self.level = level
        self.level_label.setText(f"{self.level}%")
        self.update_icon()

    def update_icon(self):
        pixmap = QPixmap(24, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(QPen(Qt.black, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, 20, 14, 2, 2)
        painter.setBrush(Qt.black)
        painter.drawRect(21, 5, 2, 6)

        if self.level > 50:
            color = COLOR_CHARGING
        elif self.level > 20:
            color = QColor("#E6A23C")
        else:
            color = QColor("#F56C6C")
        
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        fill_width = int(18 * (self.level / 100.0))
        if fill_width > 0:
            painter.drawRoundedRect(2, 2, fill_width, 12, 1, 1)

        painter.end()
        self.icon_label.setPixmap(pixmap)


class RobotCard(QFrame):
    def __init__(self, r_id, status_text, status_color, battery_level, dest_text, parent=None):
        super().__init__(parent)
        self.r_id = r_id
        self.status_color = status_color
        self.initUI(status_text, battery_level, dest_text)

    def initUI(self, status_text, battery_level, dest_text):
        self.setStyleSheet(CARD_STYLE)
        self.setContentsMargins(10, 10, 10, 10)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        top_layout = QHBoxLayout()
        id_lbl = QLabel(self.r_id)
        id_lbl.setFixedSize(30, 30)
        id_lbl.setAlignment(Qt.AlignCenter)
        id_lbl.setStyleSheet(f"background-color: {self.status_color.name()}; color: white; border-radius: 15px; font-weight: bold;")
        
        status_lbl = QLabel(status_text)
        status_lbl.setStyleSheet(f"color: {self.status_color.name()}; font-weight: bold; border: 1px solid {self.status_color.name()}; border-radius: 5px; padding: 2px 5px;")
        
        self.battery_ui = BatteryWidget(battery_level)
        
        top_layout.addWidget(id_lbl)
        top_layout.addWidget(status_lbl)
        top_layout.addStretch()
        top_layout.addWidget(self.battery_ui)
        
        self.dest_lbl = QLabel(dest_text)
        dest_font = QFont()
        dest_font.setPointSize(11)
        dest_font.setBold(True)
        self.dest_lbl.setFont(dest_font)

        self.btn_toggle_actions = QPushButton("⚡ 액션")
        self.btn_toggle_actions.setStyleSheet("QPushButton { background-color: #f0f0f0; border-radius: 5px; padding: 5px; font-weight: bold; } QPushButton:hover { background-color: #e0e0e0; }")
        self.btn_toggle_actions.clicked.connect(self.toggle_actions)

        self.actions_frame = QFrame()
        actions_layout = QHBoxLayout(self.actions_frame)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        
        btn_stop_imm = QPushButton("❌ 즉시 멈춤")
        btn_stop_imm.setStyleSheet("background-color: #FDE2E2; color: #F56C6C; border-radius: 5px; padding: 5px; font-weight: bold;")
        btn_stop_next = QPushButton("⏸ 다음 멈춤")
        btn_stop_next.setStyleSheet("background-color: #FAECD8; color: #E6A23C; border-radius: 5px; padding: 5px; font-weight: bold;")
        btn_charge = QPushButton("🔌 충전하기")
        btn_charge.setStyleSheet("background-color: #E1F3D8; color: #67C23A; border-radius: 5px; padding: 5px; font-weight: bold;")

        actions_layout.addWidget(btn_stop_imm)
        actions_layout.addWidget(btn_stop_next)
        actions_layout.addWidget(btn_charge)
        self.actions_frame.setVisible(False)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.dest_lbl)
        main_layout.addWidget(self.btn_toggle_actions)
        main_layout.addWidget(self.actions_frame)

    def toggle_actions(self):
        visible = self.actions_frame.isVisible()
        self.actions_frame.setVisible(not visible)
        self.btn_toggle_actions.setText("숨기기 ▲" if visible else "⚡ 액션")

def create_card_frame():
    frame = QFrame()
    frame.setStyleSheet(CARD_STYLE)
    frame.setContentsMargins(20, 20, 20, 20)
    return frame

def create_title_label(text):
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(14)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setStyleSheet("color: #303133;")
    return lbl
