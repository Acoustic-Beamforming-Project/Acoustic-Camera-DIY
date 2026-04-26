import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from config import N_CHANNELS, CHANNEL_COLORS, SCAN_ANGLES, ACCENT_COLOR, BG_COLOR, BORDER_COLOR

class ChannelCard(QFrame):
    def __init__(self, channel_num, color):
        super().__init__()
        self.channel_num = channel_num
        self.color = color
        self.setObjectName("channelCard")
        self.init_ui()

    def init_ui(self):
        self.setMinimumHeight(80)
        self.setStyleSheet(f"""
            QFrame#channelCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e1e2a, stop:1 #252535);
                border: 1px solid {self.color}40;
                border-radius: 8px;
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        
        # Info section
        info_layout = QVBoxLayout()
        ch_label = QLabel(f"CH {self.channel_num + 1}")
        ch_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        ch_label.setStyleSheet(f"color: {self.color};")
        
        self.val_label = QLabel("0.0")
        self.val_label.setFont(QFont("Consolas", 24, QFont.Weight.Bold))
        self.val_label.setStyleSheet(f"color: {self.color};")
        
        info_layout.addWidget(ch_label)
        info_layout.addWidget(self.val_label)
        layout.addLayout(info_layout)
        
        # Mini Waveform
        self.plot = pg.PlotWidget()
        self.plot.setBackground(None)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.getPlotItem().hideAxis('left')
        self.plot.getPlotItem().hideAxis('bottom')
        self.plot.setYRange(-1.0, 1.0)
        
        self.curve = self.plot.plot(pen=pg.mkPen(self.color, width=1.5))
        layout.addWidget(self.plot, stretch=2)

    def update_data(self, data: np.ndarray):
        self.val_label.setText(f"{np.max(np.abs(data)):.2f}")
        self.curve.setData(data)

class SpectrumPlot(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("specFrame")
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(f"""
            QFrame#specFrame {{
                background-color: #161620;
                border: 2px solid {BORDER_COLOR};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        
        title = QLabel("SRP-PHAT SPECTRUM")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; letter-spacing: 1px;")
        layout.addWidget(title)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(BG_COLOR)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setXRange(-90, 90)
        self.plot_widget.setYRange(0, 1)
        
        self.curve = self.plot_widget.plot(pen=pg.mkPen("#00d4ff", width=2.5))
        
        # Peak Marker
        self.peak_line = pg.InfiniteLine(
            angle=90,
            pen=pg.mkPen(ACCENT_COLOR, width=2, style=Qt.PenStyle.DashLine)
        )
        self.plot_widget.addItem(self.peak_line)
        
        layout.addWidget(self.plot_widget)

    def update_spectrum(self, angles, spectrum, peak_angle):
        self.curve.setData(angles, spectrum)
        self.peak_line.setValue(peak_angle)
