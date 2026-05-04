import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from config import N_CHANNELS, CHANNEL_COLORS, SCAN_ANGLES, ACCENT_COLOR, BG_COLOR, BORDER_COLOR, CARD_COLOR, DIM_COLOR


class ChannelCard(QFrame):
    def __init__(self, channel_num: int, color: str):
        super().__init__()
        self.channel_num = channel_num
        self.color       = color
        self.setObjectName("channelCard")
        self._init_ui()

    def _init_ui(self):
        self.setMinimumHeight(60)
        self.setMaximumHeight(72)
        # Flat card — no gradient, single background, thin left accent border
        self.setStyleSheet(f"""
            QFrame#channelCard {{
                background: {CARD_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-left: 2px solid {self.color};
                border-radius: 4px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 8, 4)
        layout.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(1)

        ch_label = QLabel(f"CH{self.channel_num + 1:02d}")
        ch_label.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        ch_label.setStyleSheet(f"color: {self.color}; letter-spacing: 1px;")

        self.val_label = QLabel("0.000")
        self.val_label.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self.val_label.setStyleSheet("color: #e0e0e0;")  # value in neutral white, not channel color

        info.addWidget(ch_label)
        info.addWidget(self.val_label)
        layout.addLayout(info)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(None)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.getPlotItem().hideAxis('left')
        self.plot.getPlotItem().hideAxis('bottom')
        self.plot.setYRange(-1.0, 1.0)
        self.plot.getPlotItem().getViewBox().setBorder(None)

        self.curve = self.plot.plot(pen=pg.mkPen(self.color, width=1.0))
        layout.addWidget(self.plot, stretch=3)

    def update_data(self, data: np.ndarray):
        peak = float(np.max(np.abs(data)))
        self.val_label.setText(f"{peak:.3f}")
        self.curve.setData(data)


class SpectrumPlot(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("specFrame")
        self._init_ui()

    def _init_ui(self):
        # Flat panel — no gradient, just a border
        self.setStyleSheet(f"""
            QFrame#specFrame {{
                background: #111111;
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header row: title left, subtle tag right
        header = QHBoxLayout()
        title = QLabel("SRP-PHAT SPATIAL SPECTRUM")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #e0e0e0; letter-spacing: 1.5px;")

        ch_tag = QLabel("16 CH")
        ch_tag.setFont(QFont("Segoe UI", 8))
        ch_tag.setStyleSheet(f"color: {DIM_COLOR};")
        ch_tag.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header.addWidget(title)
        header.addWidget(ch_tag)
        layout.addLayout(header)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#111111")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.08)  # even more subtle grid
        self.plot_widget.setXRange(-90, 90)
        self.plot_widget.setYRange(0, 1)
        self.plot_widget.setLabel('bottom', 'Angle', units='°',
                                  **{'color': '#555555', 'font-size': '9pt'})
        self.plot_widget.setLabel('left', 'Power',
                                  **{'color': '#555555', 'font-size': '9pt'})

        # Style axis ticks
        for ax in ('bottom', 'left'):
            self.plot_widget.getAxis(ax).setTextPen(pg.mkPen('#555555'))
            self.plot_widget.getAxis(ax).setPen(pg.mkPen(BORDER_COLOR))

        # Spectrum curve — thin cyan, no fill
        self.curve = self.plot_widget.plot(
            pen=pg.mkPen("#38bdf8", width=1.5),
        )

        # Peak line — accent color, dashed
        self.peak_line = pg.InfiniteLine(
            angle=90,
            pen=pg.mkPen(ACCENT_COLOR, width=1.5, style=Qt.PenStyle.DashLine),
            label='{value:.0f}°',
            labelOpts={'color': ACCENT_COLOR, 'movable': False, 'fill': None},
        )
        self.plot_widget.addItem(self.peak_line)
        layout.addWidget(self.plot_widget)

    def update_spectrum(self, angles, spectrum: np.ndarray, peak_angle: float):
        self.curve.setData(angles, spectrum)
        self.peak_line.setValue(peak_angle)