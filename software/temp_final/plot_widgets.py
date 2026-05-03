import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from config import N_CHANNELS, CHANNEL_COLORS, SCAN_ANGLES, ACCENT_COLOR, BG_COLOR, BORDER_COLOR


class ChannelCard(QFrame):
    """
    Compact oscilloscope card for one microphone channel.
    Height is kept small (60 px min) so all 16 cards fit in the scroll area
    without needing to scroll during normal use on a 1080p screen.
    """
    def __init__(self, channel_num: int, color: str):
        super().__init__()
        self.channel_num = channel_num
        self.color       = color
        self.setObjectName("channelCard")
        self._init_ui()

    def _init_ui(self):
        self.setMinimumHeight(60)       # tighter than the old 80 px — fits 16 cards
        self.setMaximumHeight(75)
        self.setStyleSheet(f"""
            QFrame#channelCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e1e2a, stop:1 #252535);
                border: 1px solid {self.color}40;
                border-radius: 6px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # ── Info column ────────────────────────────────────────────────────────
        info = QVBoxLayout()
        info.setSpacing(0)

        ch_label = QLabel(f"CH{self.channel_num + 1:02d}")
        ch_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        ch_label.setStyleSheet(f"color: {self.color};")

        self.val_label = QLabel("0.000")
        self.val_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.val_label.setStyleSheet(f"color: {self.color};")

        info.addWidget(ch_label)
        info.addWidget(self.val_label)
        layout.addLayout(info)

        # ── Mini waveform ──────────────────────────────────────────────────────
        self.plot = pg.PlotWidget()
        self.plot.setBackground(None)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.getPlotItem().hideAxis('left')
        self.plot.getPlotItem().hideAxis('bottom')
        self.plot.setYRange(-1.0, 1.0)

        self.curve = self.plot.plot(pen=pg.mkPen(self.color, width=1.2))
        layout.addWidget(self.plot, stretch=3)

    def update_data(self, data: np.ndarray):
        """data: 1-D float32 array of length BLOCK_SIZE for this channel."""
        peak = float(np.max(np.abs(data)))
        self.val_label.setText(f"{peak:.3f}")
        self.curve.setData(data)


class SpectrumPlot(QFrame):
    """
    SRP-PHAT spatial spectrum: power (Y) vs. scan angle (X).
    Now receives the real normalised spectrum array from DSPWorker.
    """
    def __init__(self):
        super().__init__()
        self.setObjectName("specFrame")
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame#specFrame {{
                background-color: #161620;
                border: 2px solid {BORDER_COLOR};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        title = QLabel("SRP-PHAT SPATIAL SPECTRUM  —  16 ch")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; letter-spacing: 1px;")
        layout.addWidget(title)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(BG_COLOR)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setXRange(-90, 90)
        self.plot_widget.setYRange(0, 1)
        self.plot_widget.setLabel('bottom', 'Angle', units='°')
        self.plot_widget.setLabel('left',   'Normalised Power')

        self.curve = self.plot_widget.plot(
            pen=pg.mkPen("#00d4ff", width=2.0),
            fillLevel=0,
            brush=pg.mkBrush("#00d4ff18"),   # faint fill under the curve
        )

        # Dashed vertical line at the detected peak angle
        self.peak_line = pg.InfiniteLine(
            angle=90,
            pen=pg.mkPen(ACCENT_COLOR, width=2, style=Qt.PenStyle.DashLine),
            label='{value:.0f}°',
            labelOpts={'color': ACCENT_COLOR, 'movable': False},
        )
        self.plot_widget.addItem(self.peak_line)

        layout.addWidget(self.plot_widget)

    def update_spectrum(self, angles, spectrum: np.ndarray, peak_angle: float):
        self.curve.setData(angles, spectrum)
        self.peak_line.setValue(peak_angle)
