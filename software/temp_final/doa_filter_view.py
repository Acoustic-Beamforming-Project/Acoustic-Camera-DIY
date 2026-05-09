"""
doa_filter_view.py — Spatial DOA Filter Tab
============================================
A self-contained QWidget that plugs into MainWindow as a new tab.
Receives the same (waveform, angle, spectrum) signal that the dashboard uses.
All filtering happens locally via DOAFilter — no DSP/UDP changes.

Layout
------
  ┌──────────────────────────────────────────────────┬──────────────────┐
  │                                                  │  FILTER CONTROLS │
  │          SRP-PHAT  SPECTRUM  (live)              │  ─────────────── │
  │                                                  │  ● Enable toggle │
  │   raw curve (dim)  +  filtered curve (bright)    │  Center DOA      │
  │   acceptance band shaded in accent color         │  Half-Width      │
  │   two vertical lines mark window edges           │  Rejection dB    │
  │                                                  │  ─────────────── │
  │                                                  │  live readouts   │
  └──────────────────────────────────────────────────┴──────────────────┘

Public API
----------
DOAFilterView.on_result(waveform, angle, spectrum)
    Drop-in slot — same signature as MainWindow._on_result.
    Connect to DSPWorker.result in main_window.py.
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QSlider, QSpinBox, QDoubleSpinBox, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from config import (
    SCAN_ANGLES, ACCENT_COLOR, BG_COLOR, BORDER_COLOR,
    PANEL_COLOR, DIM_COLOR, CARD_COLOR, LIVE_COLOR
)
from doa_filter import DOAFilter


# ── helpers ───────────────────────────────────────────────────────────────────

def _label(text: str, font_size: int = 8, bold: bool = False,
           color: str = DIM_COLOR) -> QLabel:
    lbl = QLabel(text)
    w   = QFont.Weight.Bold if bold else QFont.Weight.Normal
    lbl.setFont(QFont("Segoe UI", font_size, w))
    lbl.setStyleSheet(f"color:{color}; background:none; border:none;")
    return lbl


def _sep() -> QFrame:
    """Thin horizontal rule for the control panel."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color:{BORDER_COLOR};")
    sep.setFixedHeight(1)
    return sep


# ── Control Panel ─────────────────────────────────────────────────────────────

class _ControlPanel(QFrame):
    """
    Vertical strip on the right containing all filter controls.
    Communicates upward by mutating the shared DOAFilter instance directly
    and calling an update callback.
    """

    def __init__(self, filt: DOAFilter, on_change, parent=None):
        super().__init__(parent)
        self._filt      = filt
        self._on_change = on_change
        self._init_ui()

    def _init_ui(self):
        self.setFixedWidth(210)
        self.setStyleSheet(f"""
            QFrame {{
                background: {PANEL_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ── Section title ─────────────────────────────────────────────────────
        title = _label("SPATIAL  FILTER", font_size=9, bold=True, color="#e0e0e0")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:#e0e0e0; background:#202030; border-radius:5px;"
            f" padding:6px; letter-spacing:2px;"
        )
        root.addWidget(title)
        root.addWidget(_sep())

        # ── Enable toggle ─────────────────────────────────────────────────────
        self._btn_enable = QPushButton("⬤  FILTER  ON")
        self._btn_enable.setCheckable(True)
        self._btn_enable.setChecked(True)
        self._btn_enable.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._btn_enable.setFixedHeight(34)
        self._btn_enable.setStyleSheet(self._btn_style(True))
        self._btn_enable.toggled.connect(self._on_toggle)
        root.addWidget(self._btn_enable)

        root.addWidget(_sep())

        # ── Center DOA ────────────────────────────────────────────────────────
        root.addWidget(_label("Center DOA  (degrees)", bold=True, color="#aaaaaa"))

        self._spin_center = QSpinBox()
        self._spin_center.setRange(-90, 90)
        self._spin_center.setValue(int(self._filt.center_deg))
        self._spin_center.setSuffix("°")
        self._spin_center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_center.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self._spin_center.setFixedHeight(40)
        self._spin_center.setStyleSheet(self._spin_style(ACCENT_COLOR))
        self._spin_center.valueChanged.connect(self._on_center)
        root.addWidget(self._spin_center)

        # Angle slider
        self._slider_center = QSlider(Qt.Orientation.Horizontal)
        self._slider_center.setRange(-90, 90)
        self._slider_center.setValue(int(self._filt.center_deg))
        self._slider_center.setStyleSheet(self._slider_style(ACCENT_COLOR))
        self._slider_center.valueChanged.connect(self._on_slider_center)
        root.addWidget(self._slider_center)

        # Quick presets
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        for angle in (-60, -30, 0, 30, 60):
            btn = QPushButton(f"{angle:+d}°")
            btn.setFixedHeight(22)
            btn.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:#1a1a1a; color:{DIM_COLOR};
                    border:1px solid {BORDER_COLOR}; border-radius:3px;
                    padding:0px;
                }}
                QPushButton:hover {{
                    color:{ACCENT_COLOR}; border-color:{ACCENT_COLOR};
                }}
            """)
            btn.clicked.connect(lambda _, a=angle: self._set_center(a))
            preset_row.addWidget(btn)
        root.addLayout(preset_row)

        root.addWidget(_sep())

        # ── Half-Width ────────────────────────────────────────────────────────
        root.addWidget(_label("Accept  ±  Half-Width", bold=True, color="#aaaaaa"))

        self._spin_hw = QDoubleSpinBox()
        self._spin_hw.setRange(1.0, 90.0)
        self._spin_hw.setSingleStep(1.0)
        self._spin_hw.setDecimals(1)
        self._spin_hw.setValue(self._filt.half_width_deg)
        self._spin_hw.setSuffix("°")
        self._spin_hw.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_hw.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self._spin_hw.setFixedHeight(40)
        self._spin_hw.setStyleSheet(self._spin_style("#38bdf8"))
        self._spin_hw.valueChanged.connect(self._on_hw)
        root.addWidget(self._spin_hw)

        self._slider_hw = QSlider(Qt.Orientation.Horizontal)
        self._slider_hw.setRange(10, 900)    # ×10 integer for 1 decimal place
        self._slider_hw.setValue(int(self._filt.half_width_deg * 10))
        self._slider_hw.setStyleSheet(self._slider_style("#38bdf8"))
        self._slider_hw.valueChanged.connect(self._on_slider_hw)
        root.addWidget(self._slider_hw)

        root.addWidget(_sep())

        # ── Rejection floor ───────────────────────────────────────────────────
        root.addWidget(_label("Out-of-Window Floor", bold=True, color="#aaaaaa"))

        self._spin_rej = QSpinBox()
        self._spin_rej.setRange(-80, -6)
        self._spin_rej.setValue(int(self._filt.rejection_db))
        self._spin_rej.setSuffix(" dB")
        self._spin_rej.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_rej.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self._spin_rej.setFixedHeight(36)
        self._spin_rej.setStyleSheet(self._spin_style("#f87171"))
        self._spin_rej.valueChanged.connect(self._on_rejection)
        root.addWidget(self._spin_rej)

        root.addWidget(_sep())

        # ── Live readouts ─────────────────────────────────────────────────────
        root.addWidget(_label("LIVE READOUT", bold=True, color="#555555"))

        self._lbl_raw_peak   = self._readout_pair("Raw peak")
        self._lbl_filt_peak  = self._readout_pair("Filtered peak")
        self._lbl_window     = self._readout_pair("Window")
        for w in (self._lbl_raw_peak[0], self._lbl_filt_peak[0], self._lbl_window[0]):
            root.addWidget(w)

        root.addStretch()

        # ── Reset button ──────────────────────────────────────────────────────
        btn_reset = QPushButton("↺  RESET DEFAULTS")
        btn_reset.setFont(QFont("Segoe UI", 8))
        btn_reset.setFixedHeight(28)
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background:#1a1a1a; color:{DIM_COLOR};
                border:1px solid {BORDER_COLOR}; border-radius:4px;
            }}
            QPushButton:hover {{ color:#e0e0e0; border-color:#555; }}
        """)
        btn_reset.clicked.connect(self._reset)
        root.addWidget(btn_reset)

    # ── Factory helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _btn_style(checked: bool) -> str:
        if checked:
            return (f"QPushButton:checked {{"
                    f" background:#1a2a1a; color:{LIVE_COLOR};"
                    f" border:1px solid {LIVE_COLOR}; border-radius:5px; }}"
                    f" QPushButton {{"
                    f" background:#1a1a1a; color:{DIM_COLOR};"
                    f" border:1px solid {BORDER_COLOR}; border-radius:5px; }}")
        return ""

    @staticmethod
    def _spin_style(color: str) -> str:
        return f"""
            QSpinBox, QDoubleSpinBox {{
                background:{CARD_COLOR}; color:{color};
                border:1px solid {BORDER_COLOR}; border-radius:5px;
                padding:2px 6px;
            }}
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                background:#1e1e1e; border:none; width:16px;
            }}
        """

    @staticmethod
    def _slider_style(color: str) -> str:
        return f"""
            QSlider::groove:horizontal {{
                height:4px; background:{BORDER_COLOR}; border-radius:2px;
            }}
            QSlider::handle:horizontal {{
                background:{color}; width:12px; height:12px;
                margin:-4px 0; border-radius:6px;
            }}
            QSlider::sub-page:horizontal {{
                background:{color}40; border-radius:2px;
            }}
        """

    def _readout_pair(self, label_text: str):
        row = QFrame()
        row.setStyleSheet("background:none; border:none;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        lbl = _label(label_text + ":", color="#444444")
        val = _label("—", color="#666666")
        val.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(lbl)
        h.addStretch()
        h.addWidget(val)
        return row, val

    # ── Slots / helpers ───────────────────────────────────────────────────────

    def _on_toggle(self, checked: bool):
        self._filt.enabled = checked
        self._btn_enable.setText("⬤  FILTER  ON" if checked else "○  FILTER  OFF")
        self._btn_enable.setStyleSheet(self._btn_style(checked))
        self._on_change()

    def _set_center(self, angle: int):
        self._spin_center.setValue(angle)   # triggers _on_center

    def _on_center(self, val: int):
        self._slider_center.blockSignals(True)
        self._slider_center.setValue(val)
        self._slider_center.blockSignals(False)
        self._filt.set_window(val, self._filt.half_width_deg)
        self._on_change()

    def _on_slider_center(self, val: int):
        self._spin_center.blockSignals(True)
        self._spin_center.setValue(val)
        self._spin_center.blockSignals(False)
        self._filt.set_window(val, self._filt.half_width_deg)
        self._on_change()

    def _on_hw(self, val: float):
        self._slider_hw.blockSignals(True)
        self._slider_hw.setValue(int(val * 10))
        self._slider_hw.blockSignals(False)
        self._filt.set_window(self._filt.center_deg, val)
        self._on_change()

    def _on_slider_hw(self, val: int):
        hw = val / 10.0
        self._spin_hw.blockSignals(True)
        self._spin_hw.setValue(hw)
        self._spin_hw.blockSignals(False)
        self._filt.set_window(self._filt.center_deg, hw)
        self._on_change()

    def _on_rejection(self, val: int):
        self._filt.set_rejection_db(float(val))
        self._on_change()

    def _reset(self):
        self._spin_center.setValue(0)
        self._spin_hw.setValue(15.0)
        self._spin_rej.setValue(-40)
        self._btn_enable.setChecked(True)

    # ── Public: update live readout labels ────────────────────────────────────

    def update_readouts(self, raw_peak: float, filt_peak: float):
        c  = self._filt.center_deg
        hw = self._filt.half_width_deg
        self._lbl_raw_peak[1].setText( f"{raw_peak:+.1f}°")
        self._lbl_raw_peak[1].setStyleSheet(f"color:{DIM_COLOR}; font-family:Consolas;")
        self._lbl_filt_peak[1].setText(f"{filt_peak:+.1f}°")
        self._lbl_filt_peak[1].setStyleSheet(f"color:{ACCENT_COLOR}; font-family:Consolas; font-weight:bold;")
        self._lbl_window[1].setText(f"{c:+.0f}° ±{hw:.0f}°")
        self._lbl_window[1].setStyleSheet(f"color:#38bdf8; font-family:Consolas;")


# ── Main Tab Widget ───────────────────────────────────────────────────────────

class DOAFilterView(QWidget):
    """
    The complete DOA-filter tab.  Add to MainWindow with:

        from doa_filter_view import DOAFilterView
        self.doa_filter_view = DOAFilterView()
        self._main_tabs.addTab(self.doa_filter_view, "⊕  DOA FILTER")
        self._dsp.result.connect(self.doa_filter_view.on_result)

    Nothing else changes in main_window.py.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG_COLOR};")

        self._filt = DOAFilter(center_deg=0.0, half_width_deg=15.0,
                               rejection_db=-40.0, enabled=True)
        self._angles = np.array(SCAN_ANGLES, dtype=np.float32)

        # Cache last data so control changes redraw immediately
        self._last_spectrum: np.ndarray | None = None
        self._last_raw_peak: float = 0.0

        self._init_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Left: spectrum plot ───────────────────────────────────────────────
        root.addWidget(self._build_plot_panel(), stretch=1)

        # ── Right: control panel ──────────────────────────────────────────────
        self._ctrl = _ControlPanel(self._filt, self._redraw)
        root.addWidget(self._ctrl)

    def _build_plot_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background:#111111;
                border:1px solid {BORDER_COLOR};
                border-radius:8px;
            }}
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("SRP-PHAT  SPATIAL  SPECTRUM  —  FILTERED")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet("color:#e0e0e0; letter-spacing:1.5px;")
        self._lbl_status = QLabel("FILTER ACTIVE")
        self._lbl_status.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._lbl_status.setStyleSheet(
            f"color:{LIVE_COLOR}; background:#1a2a1a;"
            f" border:1px solid {LIVE_COLOR}; border-radius:3px; padding:2px 8px;"
        )
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._lbl_status)
        lay.addLayout(header)

        # Plot
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#0d0d0d")
        self._plot.showGrid(x=True, y=True, alpha=0.08)
        self._plot.setXRange(-90, 90)
        self._plot.setYRange(0, 1)
        self._plot.setLabel('bottom', 'Angle', units='°',
                            **{'color': '#555555', 'font-size': '9pt'})
        self._plot.setLabel('left', 'Power',
                            **{'color': '#555555', 'font-size': '9pt'})
        self._plot.setMouseEnabled(x=False, y=False)
        for ax in ('bottom', 'left'):
            self._plot.getAxis(ax).setTextPen(pg.mkPen('#555555'))
            self._plot.getAxis(ax).setPen(pg.mkPen(BORDER_COLOR))

        # Acceptance-window shaded region
        self._window_region = pg.LinearRegionItem(
            values=(-15, 15),
            brush=pg.mkBrush(QColor(ACCENT_COLOR.lstrip('#')).rgba() & 0x00FFFFFF | 0x18000000),  # 10% alpha
            movable=False,
        )
        self._window_region.setZValue(-10)
        self._plot.addItem(self._window_region)

        # Window edge lines
        pen_edge = pg.mkPen(ACCENT_COLOR, width=1,
                            style=Qt.PenStyle.DashLine)
        self._line_lo = pg.InfiniteLine(angle=90, pos=-15, pen=pen_edge)
        self._line_hi = pg.InfiniteLine(angle=90, pos= 15, pen=pen_edge)
        self._plot.addItem(self._line_lo)
        self._plot.addItem(self._line_hi)

        # Raw spectrum (dim background)
        self._curve_raw = self._plot.plot(
            pen=pg.mkPen("#2a4a5a", width=1.0),
            name="Raw"
        )

        # Filtered spectrum (bright foreground)
        self._curve_filt = self._plot.plot(
            pen=pg.mkPen("#38bdf8", width=2.0),
            name="Filtered"
        )

        # Filtered peak line
        self._peak_line = pg.InfiniteLine(
            angle=90, pos=0,
            pen=pg.mkPen(ACCENT_COLOR, width=2,
                         style=Qt.PenStyle.SolidLine),
            label='{value:.0f}°',
            labelOpts={'color': ACCENT_COLOR, 'movable': False, 'fill': None},
        )
        self._plot.addItem(self._peak_line)

        lay.addWidget(self._plot)

        # Legend strip
        leg = QHBoxLayout()
        for color, text in (("#2a4a5a", "● Raw SRP-PHAT"),
                             ("#38bdf8", "● Filtered"),
                             (ACCENT_COLOR, "— Filtered peak")):
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color:{color};")
            leg.addWidget(lbl)
        leg.addStretch()
        lay.addLayout(leg)

        return panel

    # ── Internal update ───────────────────────────────────────────────────────

    def _redraw(self):
        """Re-apply filter and refresh all plot elements. Called on new data
        AND whenever a control changes value."""
        if self._last_spectrum is None:
            return

        spec     = self._last_spectrum
        filtered, filt_peak = self._filt.apply(self._angles, spec)

        # Update spectrum curves
        self._curve_raw.setData(self._angles, spec)
        self._curve_filt.setData(self._angles, filtered)
        self._peak_line.setValue(filt_peak)

        # Update shaded window region and edge lines
        lo = self._filt.center_deg - self._filt.half_width_deg
        hi = self._filt.center_deg + self._filt.half_width_deg
        self._window_region.setRegion((lo, hi))
        self._line_lo.setValue(lo)
        self._line_hi.setValue(hi)

        # Status badge
        if self._filt.enabled:
            self._lbl_status.setText("FILTER  ACTIVE")
            self._lbl_status.setStyleSheet(
                f"color:{LIVE_COLOR}; background:#1a2a1a;"
                f" border:1px solid {LIVE_COLOR}; border-radius:3px; padding:2px 8px;"
            )
        else:
            self._lbl_status.setText("FILTER  BYPASSED")
            self._lbl_status.setStyleSheet(
                f"color:{DIM_COLOR}; background:#1a1a1a;"
                f" border:1px solid {BORDER_COLOR}; border-radius:3px; padding:2px 8px;"
            )

        # Control panel readouts
        self._ctrl.update_readouts(self._last_raw_peak, filt_peak)

    # ── Public slot ───────────────────────────────────────────────────────────

    @pyqtSlot(np.ndarray, float, np.ndarray)
    def on_result(self, waveform: np.ndarray, angle: float,
                  spectrum: np.ndarray):
        """
        Same signature as DSPWorker.result.
        Only spectrum and angle are used here; waveform is ignored.
        """
        self._last_spectrum = spectrum
        self._last_raw_peak = angle
        self._redraw()