"""
channel_zoom.py — Zoomable single-channel waveform viewer.

Replaces the DOA indicator in the bottom-right panel.
The user picks any channel (1–16) via a small input field;
the selected channel's waveform is rendered in a full pyqtgraph
plot with mouse zoom / pan enabled.
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout,
                             QLabel, QSpinBox, QPushButton)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from config import (N_CHANNELS, CHANNEL_COLORS, ACCENT_COLOR,
                    BORDER_COLOR, DIM_COLOR, CARD_COLOR, BG_COLOR)


class ChannelZoomView(QFrame):
    """
    A panel that shows a zoomable/pannable waveform for one selected channel.

    Public API
    ----------
    update_channel_data(waveform)
        waveform : (N_CHANNELS, BLOCK_SIZE) float32
        Call this every time a new DSP frame arrives (same cadence as the
        channel cards).  Only the currently-selected channel is plotted.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chZoomFrame")
        self._selected_ch = 0          # 0-based index
        self._last_data: np.ndarray | None = None
        self._init_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame#chZoomFrame {{
                background: #111111;
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # ── Header row ────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("CHANNEL ZOOM")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {DIM_COLOR}; letter-spacing: 3px;")

        header.addWidget(title)
        header.addStretch()

        # Channel selector label
        sel_lbl = QLabel("CH:")
        sel_lbl.setFont(QFont("Segoe UI", 9))
        sel_lbl.setStyleSheet(f"color: {DIM_COLOR};")
        header.addWidget(sel_lbl)

        # Spin-box: displays 1-based channel number
        self._spin = QSpinBox()
        self._spin.setRange(1, N_CHANNELS)
        self._spin.setValue(1)
        self._spin.setFixedWidth(52)
        self._spin.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin.setStyleSheet(f"""
            QSpinBox {{
                background: {CARD_COLOR};
                color: {CHANNEL_COLORS[0]};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
                padding: 2px 4px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 14px;
                background: #1e1e1e;
                border: none;
            }}
        """)
        self._spin.valueChanged.connect(self._on_channel_changed)
        header.addWidget(self._spin)

        # Reset zoom button
        self._btn_reset = QPushButton("⊡ RESET")
        self._btn_reset.setFixedHeight(24)
        self._btn_reset.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self._btn_reset.setStyleSheet(f"""
            QPushButton {{
                background: #1e1e1e;
                color: {DIM_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 3px;
                padding: 0px 8px;
            }}
            QPushButton:hover {{
                color: {ACCENT_COLOR};
                border-color: {ACCENT_COLOR};
            }}
        """)
        self._btn_reset.clicked.connect(self._reset_zoom)
        header.addWidget(self._btn_reset)

        root.addLayout(header)

        # ── Plot ──────────────────────────────────────────────────────────────
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#0d0d0d")
        self._plot.showGrid(x=True, y=True, alpha=0.10)
        self._plot.setLabel('bottom', 'Sample', **{'color': '#444444', 'font-size': '8pt'})
        self._plot.setLabel('left',   'Amplitude', **{'color': '#444444', 'font-size': '8pt'})
        self._plot.setYRange(-1.05, 1.05)

        # Enable full mouse interaction — zoom scroll-wheel, pan drag
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.getPlotItem().getViewBox().setMouseMode(
            pg.ViewBox.RectMode   # rubber-band select → zoom; right-drag → pan
        )

        # Style axes
        for ax in ('bottom', 'left'):
            self._plot.getAxis(ax).setTextPen(pg.mkPen('#444444'))
            self._plot.getAxis(ax).setPen(pg.mkPen(BORDER_COLOR))

        # Waveform curve — colored per channel
        self._curve = self._plot.plot(
            pen=pg.mkPen(CHANNEL_COLORS[0], width=1.5)
        )

        # Zero-line
        self._zero_line = pg.InfiniteLine(
            angle=0, pos=0,
            pen=pg.mkPen('#333333', width=1, style=Qt.PenStyle.DashLine)
        )
        self._plot.addItem(self._zero_line)

        root.addWidget(self._plot)

        # ── Info strip ────────────────────────────────────────────────────────
        info_row = QHBoxLayout()
        self._lbl_peak = QLabel("PEAK  —")
        self._lbl_rms  = QLabel("RMS  —")
        for lbl in (self._lbl_peak, self._lbl_rms):
            lbl.setFont(QFont("Consolas", 8))
            lbl.setStyleSheet(f"color: {DIM_COLOR};")
            info_row.addWidget(lbl)
        info_row.addStretch()

        hint = QLabel("scroll=zoom  •  drag=pan  •  right-drag=zoom-box")
        hint.setFont(QFont("Segoe UI", 7))
        hint.setStyleSheet("color: #333333;")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_row.addWidget(hint)

        root.addLayout(info_row)

    # ── Slots / helpers ───────────────────────────────────────────────────────

    def _on_channel_changed(self, value: int):
        """value is 1-based from the spin-box."""
        self._selected_ch = value - 1
        color = CHANNEL_COLORS[self._selected_ch]

        # Re-colour curve and spin-box text
        self._curve.setPen(pg.mkPen(color, width=1.5))
        self._spin.setStyleSheet(f"""
            QSpinBox {{
                background: {CARD_COLOR};
                color: {color};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
                padding: 2px 4px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 14px;
                background: #1e1e1e;
                border: none;
            }}
        """)

        # Redraw with cached data if available
        if self._last_data is not None:
            self._draw(self._last_data[self._selected_ch])

    def _reset_zoom(self):
        self._plot.setYRange(-1.05, 1.05)
        self._plot.enableAutoRange(axis=pg.ViewBox.XAxis)

    def _draw(self, ch_data: np.ndarray):
        self._curve.setData(ch_data)
        peak = float(np.max(np.abs(ch_data)))
        rms  = float(np.sqrt(np.mean(ch_data ** 2)))
        color = CHANNEL_COLORS[self._selected_ch]
        self._lbl_peak.setText(f"PEAK  <span style='color:{color}'>{peak:.4f}</span>")
        self._lbl_rms.setText( f"RMS  <span style='color:{color}'>{rms:.4f}</span>")
        self._lbl_peak.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_rms.setTextFormat(Qt.TextFormat.RichText)

    # ── Public API ────────────────────────────────────────────────────────────

    def update_channel_data(self, waveform: np.ndarray):
        """
        waveform : (N_CHANNELS, BLOCK_SIZE) float32
        Extracts the selected channel and redraws.
        """
        self._last_data = waveform
        self._draw(waveform[self._selected_ch])