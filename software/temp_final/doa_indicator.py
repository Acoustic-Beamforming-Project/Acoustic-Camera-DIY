from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import numpy as np
from config import ACCENT_COLOR, BORDER_COLOR

class DOAIndicator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doaDisplay")
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame#doaDisplay {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1a28, stop:1 #252535);
                border: 2px solid {BORDER_COLOR};
                border-radius: 12px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)
        
        title = QLabel("DIRECTION OF ARRIVAL")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        self.doa_value = QLabel("0.0")
        self.doa_value.setFont(QFont("Consolas", 68, QFont.Weight.Bold))
        self.doa_value.setStyleSheet(f"""
            color: {ACCENT_COLOR};
            background-color: #1a1a28;
            padding: 15px;
            border-radius: 10px;
            border: 2px solid {ACCENT_COLOR}40;
        """)
        self.doa_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.doa_value)
        
        # Keep the slider as requested
        self.doa_slider = QSlider(Qt.Orientation.Horizontal)
        self.doa_slider.setObjectName("doa_slider")
        self.doa_slider.setRange(0, 180)
        self.doa_slider.setValue(90)
        self.doa_slider.setEnabled(False)
        self.doa_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: #21262d;
                border_radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_COLOR};
                border_radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                background: #58a6ff;
                border: 2px solid #0d1117;
                margin: -5px 0;
            }}
        """)
        layout.addWidget(self.doa_slider)

        # Labels for slider
        labels_layout = QHBoxLayout()
        for txt in ["-90°", "0°", "90°"]:
            lbl = QLabel(txt)
            lbl.setStyleSheet("color: #707080; font-weight: bold;")
            labels_layout.addWidget(lbl)
            if txt != "90°": labels_layout.addStretch()
        layout.addLayout(labels_layout)

    def set_angle(self, angle: float):
        self.doa_value.setText(f"{angle:.1f}")
        slider_val = int(np.interp(angle, [-90, 90], [0, 180]))
        self.doa_slider.setValue(slider_val)
        
        # Dynamic color based on "confidence" (simplified as angle range for now)
        color = ACCENT_COLOR if abs(angle) < 45 else "#ffd740"
        self.doa_value.setStyleSheet(f"""
            color: {color};
            font-size: 68px;
            font-weight: bold;
            background-color: #1a1a28;
            padding: 15px;
            border-radius: 10px;
            border: 2px solid {color}40;
        """)
