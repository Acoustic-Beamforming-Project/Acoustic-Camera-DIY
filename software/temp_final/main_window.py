import sys
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QFrame,
                             QScrollArea, QMessageBox, QStatusBar, QTabWidget)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QFont
from config import (UDP_IP, UDP_PORT, N_CHANNELS, SAMPLE_RATE,
                    SCAN_ANGLES, BG_COLOR, PANEL_COLOR, LIVE_COLOR,
                    CHANNEL_COLORS, EXPECTED_PKT_SIZE, FRAMES_PER_BATCH,
                    ACCENT_COLOR, BORDER_COLOR)
from udp_worker import UDPWorker
from dsp_worker import DSPWorker
from plot_widgets import ChannelCard, SpectrumPlot
from channel_zoom import ChannelZoomView
from camera_overlay import CameraOverlayView
from doa_filter_view import DOAFilterView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DOA Radar System — AD7606 16-ch Acoustic Camera")
        self.setMinimumSize(1400, 900)
        self.setStyleSheet(f"background-color: {BG_COLOR};")

        self._packet_count     = 0
        self._udp_pkt_last     = 0
        self._udp_pkt_last_raw = 0
        self._udp = UDPWorker()
        self._dsp = DSPWorker()

        self.init_ui()
        self.setup_connections()

        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(1000)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        bar.setStyleSheet("""
            QStatusBar {
                background: #0d0d0d;
                border-top: 1px solid #2a2a2a;
                padding: 0 4px;
                color: #555;
                font-size: 9pt;
            }
            QStatusBar::item { border: none; }
        """)
        self.setStatusBar(bar)

        def _seg(icon, key, default, accent="#555555"):
            seg = QFrame()
            seg.setStyleSheet("""
                QFrame {
                    background: #161616; border: 1px solid #2a2a2a;
                    border-radius: 3px; padding: 0 6px;
                }
            """)
            h = QHBoxLayout(seg)
            h.setContentsMargins(6, 2, 6, 2)
            h.setSpacing(5)
            for txt, clr, fnt in (
                (icon,    accent,    QFont("Segoe UI", 8)),
                (key,     "#444444", QFont("Segoe UI", 8)),
            ):
                lbl = QLabel(txt)
                lbl.setFont(fnt)
                lbl.setStyleSheet(f"color:{clr}; border:none; background:none;")
                h.addWidget(lbl)
            val = QLabel(default)
            val.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            val.setStyleSheet(f"color:{accent}; border:none; background:none;")
            val.setMinimumWidth(52)
            h.addWidget(val)
            return seg, val

        pkt_seg,  self._sb_pkt_s = _seg("▲", "PKT/s", "—",    ACCENT_COLOR)
        dsp_seg,  self._sb_dsp_s = _seg("⚙", "DSP/s", "—",    LIVE_COLOR)
        rate_seg, self._sb_rate  = _seg("♪", "RATE",  f"{SAMPLE_RATE} Hz", "#38bdf8")
        ch_seg,   self._sb_ch   = _seg("≡", "CH",    f"{N_CHANNELS}",     "#c084fc")
        pkt_seg2, self._sb_pktb = _seg("□", "PKT",   f"{EXPECTED_PKT_SIZE} B", "#555555")

        for w in (pkt_seg, dsp_seg, rate_seg, ch_seg, pkt_seg2):
            bar.addWidget(w)

        tot_seg, self._sb_total = _seg("Σ", "TOTAL", "0 pkts", "#444444")
        bar.addPermanentWidget(tot_seg)

    # ── UI construction ───────────────────────────────────────────────────────

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)
        root.addWidget(self._build_header())

        # Main tab widget — two full-height tabs
        self._main_tabs = self._build_main_tabs()
        root.addWidget(self._main_tabs, stretch=1)

        self._build_status_bar()

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1a1a25, stop:0.5 #252535, stop:1 #1a1a25);
                border: 2px solid #404060; border-radius: 8px;
            }
        """)
        lay = QHBoxLayout(frame)

        title = QLabel("ACOUSTIC DOA RADAR  —  AD7606  |  16 CH  |  ±5 V")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(
            "color:#fff; letter-spacing:2px; "
            "padding:4px 12px; background:#2a2a3a; border-radius:5px;"
        )
        lay.addWidget(title)
        lay.addStretch()

        self.ip_input   = QLineEdit(UDP_IP)
        self.port_input = QLineEdit(str(UDP_PORT))
        _in = ("background:#1a2a35; color:#00ccff; "
               "border:1px solid #00ccff40; border-radius:5px; padding:4px;")
        self.ip_input.setStyleSheet(_in)
        self.port_input.setStyleSheet(_in)
        self.port_input.setFixedWidth(55)

        for w in (QLabel("IP:"), self.ip_input, QLabel(":"), self.port_input):
            lay.addWidget(w)

        self.btn_connect = QPushButton("CONNECT")
        self.btn_connect.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_connect.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #0066dd, stop:1 #004499);
                border: 2px solid #0088ff; border-radius:6px;
                padding: 6px 18px; color: white;
            }
            QPushButton:hover    { background: #0077ee; }
            QPushButton:disabled { background: #333; border-color: #555; }
        """)
        lay.addWidget(self.btn_connect)

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background:#3d1f1f; border:2px solid #f85149; "
            "border-radius:6px; padding:6px 18px; color:#f85149; }"
        )
        lay.addWidget(self.btn_stop)

        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet(f"color:{LIVE_COLOR}; font-size:18px;")
        self.live_dot.setVisible(False)
        lay.addWidget(self.live_dot)

        return frame

    # ── Main tab widget ───────────────────────────────────────────────────────

    def _build_main_tabs(self) -> QTabWidget:
        """
        Two top-level tabs:
          Tab 0 — RADAR DASHBOARD  (channel cards + spectrum + channel zoom)
          Tab 1 — ACOUSTIC CAMERA  (full-panel CameraOverlayView)
        """
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background: {BG_COLOR};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                border-top-left-radius: 0px;
            }}
            QTabBar::tab {{
                background: #111111;
                color: #555555;
                border: 1px solid {BORDER_COLOR};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 24px;
                font-family: "Segoe UI";
                font-size: 9pt;
                font-weight: bold;
                letter-spacing: 1.5px;
                min-width: 160px;
            }}
            QTabBar::tab:selected {{
                background: {BG_COLOR};
                color: {ACCENT_COLOR};
                border-bottom: 1px solid {BG_COLOR};
            }}
            QTabBar::tab:hover:!selected {{
                background: #1a1a1a;
                color: #888888;
            }}
        """)

        # ── Tab 0: Radar Dashboard ────────────────────────────────────────────
        dashboard = QWidget()
        dashboard.setStyleSheet(f"background:{BG_COLOR};")
        dash_layout = QHBoxLayout(dashboard)
        dash_layout.setContentsMargins(0, 6, 0, 0)
        dash_layout.setSpacing(8)
        dash_layout.addLayout(self._build_channel_panel(), stretch=3)
        dash_layout.addLayout(self._build_right_panel(),   stretch=5)
        tabs.addTab(dashboard, "⊞  RADAR DASHBOARD")

        # ── Tab 1: Acoustic Camera ────────────────────────────────────────────
        self.camera_overlay = CameraOverlayView()
        tabs.addTab(self.camera_overlay, "◉  ACOUSTIC CAMERA")

        # ── Tab 2: DOA Spatial Filter ─────────────────────────────────────────
        self.doa_filter_view = DOAFilterView()
        tabs.addTab(self.doa_filter_view, "⊕  DOA FILTER")


        return tabs

    def _build_channel_panel(self) -> QVBoxLayout:
        """Left column: 16 channel cards in a scroll area."""
        left = QFrame()
        left.setStyleSheet(
            f"background:{PANEL_COLOR}; border:2px solid #353550; border-radius:10px;"
        )
        lp = QVBoxLayout(left)
        lp.setContentsMargins(6, 6, 6, 6)
        lp.setSpacing(4)

        ch_title = QLabel(f"CHANNEL MONITORING  ({N_CHANNELS} ch)")
        ch_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        ch_title.setStyleSheet(
            "color:#fff; background:#202030; padding:6px; border-radius:6px;"
        )
        ch_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp.addWidget(ch_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        content = QWidget()
        ch_lay = QVBoxLayout(content)
        ch_lay.setSpacing(3)
        ch_lay.setContentsMargins(2, 2, 2, 2)

        self.channel_cards: list[ChannelCard] = []
        for i in range(N_CHANNELS):
            card = ChannelCard(i, CHANNEL_COLORS[i])
            ch_lay.addWidget(card)
            self.channel_cards.append(card)

        scroll.setWidget(content)
        lp.addWidget(scroll)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(left)
        return outer

    def _build_right_panel(self) -> QVBoxLayout:
        """Right column: SRP-PHAT spectrum (top) + channel zoom (bottom)."""
        right = QVBoxLayout()
        right.setSpacing(8)
        self.spectrum_plot = SpectrumPlot()
        right.addWidget(self.spectrum_plot, stretch=6)
        self.channel_zoom = ChannelZoomView()
        right.addWidget(self.channel_zoom, stretch=4)
        return right

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def setup_connections(self):
        self._udp.raw_packet.connect(self._dsp.process)
        self._dsp.result.connect(self._on_result)
        self._udp.error.connect(self._on_udp_error)
        self._udp.pkt_counted.connect(self._on_pkt_counted)
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_stop.clicked.connect(self._on_stop)
        self._dsp.result.connect(self.doa_filter_view.on_result)

    # ── Slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_pkt_counted(self, total: int):
        self._udp_pkt_last_raw = total

    @pyqtSlot(np.ndarray, float, np.ndarray)
    def _on_result(self, waveform: np.ndarray, angle: float,
                   spectrum: np.ndarray):
        """
        waveform : (N_CHANNELS, BLOCK_SIZE) float32
        angle    : DOA estimate in degrees
        spectrum : (len(SCAN_ANGLES),) float32, normalised [0, 1]
        """
        self._packet_count += 1

        # Channel cards
        for i in range(N_CHANNELS):
            self.channel_cards[i].update_data(waveform[i])

        # SRP-PHAT spectrum plot
        self.spectrum_plot.update_spectrum(SCAN_ANGLES, spectrum, angle)

        # Channel zoom
        self.channel_zoom.update_channel_data(waveform)

        # Acoustic camera overlay — only stores data, never triggers repaint
        self.camera_overlay.update_overlay(SCAN_ANGLES, spectrum, angle)

    @pyqtSlot(str)
    def _on_udp_error(self, msg: str):
        QMessageBox.critical(self, "UDP Error", msg)
        self._on_stop()

    def _on_connect(self):
        self.btn_connect.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.live_dot.setVisible(True)
        self._udp.start()
        self._dsp.start()

    def _on_stop(self):
        self._udp.stop()
        self._dsp.stop()
        self.btn_connect.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.live_dot.setVisible(False)

    def _update_status_bar(self):
        running       = self._udp.isRunning()
        current_total = self._udp_pkt_last_raw
        pkt_delta     = current_total - self._udp_pkt_last
        self._udp_pkt_last = current_total
        dsp_fps            = self._packet_count
        self._packet_count = 0

        if running:
            pkt_color = (
                "#39d353" if pkt_delta >= 150 else
                "#facc15" if pkt_delta > 0    else
                "#555555"
            )
            self._sb_pkt_s.setText(str(pkt_delta))
            self._sb_pkt_s.setStyleSheet(
                f"color:{pkt_color}; border:none; background:none; font-weight:bold;"
            )
            self._sb_dsp_s.setText(str(dsp_fps))
            self._sb_total.setText(f"{current_total:,} pkts")
        else:
            self._sb_pkt_s.setText("—")
            self._sb_dsp_s.setText("—")

    def closeEvent(self, event):
        self._on_stop()
        self.camera_overlay.stop_camera()
        super().closeEvent(event)