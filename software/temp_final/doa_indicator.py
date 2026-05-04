from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import numpy as np
from config import ACCENT_COLOR, BORDER_COLOR, DIM_COLOR

class DOAIndicator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doaDisplay")
        self._init_ui()

    def _init_ui(self):
        # Flat, no gradient
        self.setStyleSheet(f"""
            QFrame#doaDisplay {{
                background: #111111;
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        # Title — small, spaced, dim
        title = QLabel("DIRECTION OF ARRIVAL")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {DIM_COLOR}; letter-spacing: 3px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Big angle display — no box around it, just the number
        self.doa_value = QLabel("0.0°")
        self.doa_value.setFont(QFont("Consolas", 72, QFont.Weight.Bold))
        self.doa_value.setStyleSheet(f"color: {ACCENT_COLOR};")
        self.doa_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.doa_value)

        # Minimal slider
        self.doa_slider = QSlider(Qt.Orientation.Horizontal)
        self.doa_slider.setRange(0, 180)
        self.doa_slider.setValue(90)
        self.doa_slider.setEnabled(False)
        self.doa_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 2px;
                background: {BORDER_COLOR};
                border-radius: 1px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_COLOR};
                border-radius: 1px;
            }}
            QSlider::handle:horizontal {{
                width: 10px;
                height: 10px;
                border-radius: 5px;
                background: {ACCENT_COLOR};
                margin: -4px 0;
            }}
        """)
        layout.addWidget(self.doa_slider)

        # Angle labels
        labels_layout = QHBoxLayout()
        for txt in ["-90°", "0°", "90°"]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Consolas", 8))
            lbl.setStyleSheet(f"color: {DIM_COLOR};")
            labels_layout.addWidget(lbl)
            if txt != "90°":
                labels_layout.addStretch()
        layout.addLayout(labels_layout)

    def set_angle(self, angle: float):
        self.doa_value.setText(f"{angle:.1f}°")
        slider_val = int(np.interp(angle, [-90, 90], [0, 180]))
        self.doa_slider.setValue(slider_val)
        # No color change — keep it stable, accent color always