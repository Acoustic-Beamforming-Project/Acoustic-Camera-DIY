import sys
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QFrame, QScrollArea,
                             QMessageBox, QStatusBar)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QFont
from config import (UDP_IP, UDP_PORT, N_CHANNELS, SAMPLE_RATE,
                    SCAN_ANGLES, BG_COLOR, PANEL_COLOR, LIVE_COLOR, CHANNEL_COLORS,
                    EXPECTED_PKT_SIZE, FRAMES_PER_BATCH)
from udp_worker import UDPWorker
from dsp_worker import DSPWorker
from plot_widgets import ChannelCard, SpectrumPlot
from doa_indicator import DOAIndicator


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DOA Radar System — AD7606 16-ch Acoustic Camera")
        self.setMinimumSize(1400, 900)   # wider to comfortably fit 16 channel cards
        self.setStyleSheet(f"background-color: {BG_COLOR};")

        self._packet_count      = 0   # DSP frames emitted per second
        self._bad_count         = 0
        self._udp_pkt_last      = 0   # last pkt_total snapshot for delta calc
        self._udp_pkt_per_s     = 0   # smoothed pkt/s shown in the status bar
        self._udp_pkt_last_raw  = 0   # updated by _on_pkt_counted each packet
        self._udp = UDPWorker()
        self._dsp = DSPWorker()

        self.init_ui()
        self.setup_connections()

        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(1000)

    # ── Status Bar ────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        """
        Replaces the default QStatusBar with a custom widget row that shows
        individual labeled segments.  Each segment is just a QLabel — updating
        them is a single setText() call, which Qt repaints lazily and cheaply.
        No extra threads, no timers beyond the existing 1 s _status_timer.
        """
        from PyQt6.QtWidgets import QStatusBar
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        bar.setStyleSheet(f"""
            QStatusBar {{
                background: #0d0d0d;
                border-top: 1px solid #2a2a2a;
                padding: 0px 4px;
                color: #555555;
                font-size: 9pt;
            }}
            QStatusBar::item {{ border: none; }}
        """)
        self.setStatusBar(bar)

        def _seg(icon: str, key: str, default: str, accent: str = "#555555"):
            """Return (container QFrame, value QLabel) for one status segment."""
            seg = QFrame()
            seg.setStyleSheet(f"""
                QFrame {{
                    background: #161616;
                    border: 1px solid #2a2a2a;
                    border-radius: 3px;
                    padding: 0px 6px;
                }}
            """)
            h = QHBoxLayout(seg)
            h.setContentsMargins(6, 2, 6, 2)
            h.setSpacing(5)

            icon_lbl = QLabel(icon)
            icon_lbl.setFont(QFont("Segoe UI", 8))
            icon_lbl.setStyleSheet(f"color: {accent}; border: none; background: none;")

            key_lbl = QLabel(key)
            key_lbl.setFont(QFont("Segoe UI", 8))
            key_lbl.setStyleSheet("color: #444444; border: none; background: none;")

            val_lbl = QLabel(default)
            val_lbl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            val_lbl.setStyleSheet(f"color: {accent}; border: none; background: none;")
            val_lbl.setMinimumWidth(52)

            h.addWidget(icon_lbl)
            h.addWidget(key_lbl)
            h.addWidget(val_lbl)
            return seg, val_lbl

        from config import ACCENT_COLOR, LIVE_COLOR

        # PKT/s — most prominent, accent yellow
        pkt_seg,   self._sb_pkt_s    = _seg("▲", "PKT/s",    "—",    ACCENT_COLOR)
        # DSP frames/s — green
        dsp_seg,   self._sb_dsp_s    = _seg("⚙", "DSP/s",    "—",    LIVE_COLOR)
        # Fixed-info segments (never change after connect)
        rate_seg,  self._sb_rate     = _seg("♪", "RATE",     f"{SAMPLE_RATE} Hz", "#38bdf8")
        ch_seg,    self._sb_ch       = _seg("≡", "CH",        f"{N_CHANNELS}",      "#c084fc")
        pkt_b_seg, self._sb_pkt_b   = _seg("□", "PKT",       f"{EXPECTED_PKT_SIZE} B", "#555555")

        for w in (pkt_seg, dsp_seg, rate_seg, ch_seg, pkt_b_seg):
            bar.addWidget(w)

        # Right-side: total packet counter
        tot_seg, self._sb_total = _seg("Σ", "TOTAL",  "0 pkts", "#444444")
        bar.addPermanentWidget(tot_seg)

    # ── UI Construction ────────────────────────────────────────────────────────

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addLayout(self._build_body(), stretch=1)
        self._build_status_bar()

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a25, stop:0.5 #252535, stop:1 #1a1a25);
                border: 2px solid #404060;
                border-radius: 8px;
            }
        """)
        lay = QHBoxLayout(frame)

        title = QLabel("ACOUSTIC DOA RADAR  —  AD7606  |  16 CH  |  ±5 V")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(
            "color: #ffffff; letter-spacing: 2px; "
            "padding: 4px 12px; background-color: #2a2a3a; border-radius: 5px;"
        )
        lay.addWidget(title)
        lay.addStretch()

        # IP / Port inputs
        self.ip_input   = QLineEdit(UDP_IP)
        self.port_input = QLineEdit(str(UDP_PORT))
        _input_style = (
            "background-color: #1a2a35; color: #00ccff; "
            "border: 1px solid #00ccff40; border-radius: 5px; padding: 4px;"
        )
        self.ip_input.setStyleSheet(_input_style)
        self.port_input.setStyleSheet(_input_style)
        self.port_input.setFixedWidth(55)

        lay.addWidget(QLabel("IP:"))
        lay.addWidget(self.ip_input)
        lay.addWidget(QLabel(":"))
        lay.addWidget(self.port_input)

        # Buttons
        self.btn_connect = QPushButton("CONNECT")
        self.btn_connect.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_connect.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #0066dd, stop:1 #004499);
                border: 2px solid #0088ff; border-radius: 6px;
                padding: 6px 18px; color: white;
            }
            QPushButton:hover    { background: #0077ee; }
            QPushButton:disabled { background: #333; border-color: #555; }
        """)
        lay.addWidget(self.btn_connect)

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #3d1f1f; border: 2px solid #f85149; "
            "border-radius: 6px; padding: 6px 18px; color: #f85149; }"
        )
        lay.addWidget(self.btn_stop)

        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet(f"color: {LIVE_COLOR}; font-size: 18px;")
        self.live_dot.setVisible(False)
        lay.addWidget(self.live_dot)

        return frame

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setSpacing(8)

        # ── Left panel: 16 channel cards in a scroll area ──────────────────
        left = QFrame()
        left.setStyleSheet(
            f"background-color: {PANEL_COLOR}; "
            "border: 2px solid #353550; border-radius: 10px;"
        )
        lp = QVBoxLayout(left)
        lp.setContentsMargins(6, 6, 6, 6)
        lp.setSpacing(4)

        ch_title = QLabel(f"CHANNEL MONITORING  ({N_CHANNELS} ch)")
        ch_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        ch_title.setStyleSheet(
            "color: #ffffff; background-color: #202030; "
            "padding: 6px; border-radius: 6px;"
        )
        ch_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp.addWidget(ch_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll_content = QWidget()
        ch_layout = QVBoxLayout(scroll_content)
        ch_layout.setSpacing(3)
        ch_layout.setContentsMargins(2, 2, 2, 2)

        self.channel_cards: list[ChannelCard] = []
        for i in range(N_CHANNELS):
            card = ChannelCard(i, CHANNEL_COLORS[i])
            ch_layout.addWidget(card)
            self.channel_cards.append(card)

        scroll.setWidget(scroll_content)
        lp.addWidget(scroll)
        body.addWidget(left, stretch=3)

        # ── Right panel: spectrum + DOA indicator ───────────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        self.spectrum_plot = SpectrumPlot()
        right.addWidget(self.spectrum_plot, stretch=6)

        self.doa_indicator = DOAIndicator()
        right.addWidget(self.doa_indicator, stretch=4)

        body.addLayout(right, stretch=5)
        return body

    # ── Signal wiring ──────────────────────────────────────────────────────────

    def setup_connections(self):
        self._udp.raw_packet.connect(self._dsp.process)
        self._dsp.result.connect(self._on_result)
        self._udp.error.connect(self._on_udp_error)
        self._udp.pkt_counted.connect(self._on_pkt_counted)
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_stop.clicked.connect(self._on_stop)

    # ── Slots ──────────────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_pkt_counted(self, total: int):
        """Receives the running packet total from UDPWorker — O(1), no work done here."""
        self._udp_pkt_last_raw = total   # _update_status_bar diffs against previous snapshot

    @pyqtSlot(np.ndarray, float, np.ndarray)
    def _on_result(self, waveform: np.ndarray, angle: float, spectrum: np.ndarray):
        """
        Called on every processed DSP frame.
        waveform : (N_CHANNELS, BLOCK_SIZE) float32
        angle    : DOA estimate in degrees
        spectrum : (len(SCAN_ANGLES),) float32, values in [0, 1]
        """
        self._packet_count += 1

        for i in range(N_CHANNELS):
            self.channel_cards[i].update_data(waveform[i])

        self.spectrum_plot.update_spectrum(SCAN_ANGLES, spectrum, angle)
        self.doa_indicator.set_angle(angle)

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
        running = self._udp.isRunning()

        # ── PKT/s: diff the running counter against last snapshot ──────────
        current_total = self._udp_pkt_last_raw
        pkt_delta     = current_total - self._udp_pkt_last
        self._udp_pkt_last = current_total

        # ── DSP frames/s (counted in _on_result) ───────────────────────────
        dsp_fps           = self._packet_count
        self._packet_count = 0

        if running:
            # Colour PKT/s green when healthy (≥ expected ~200 pkt/s from firmware),
            # amber when low, dim when idle.  Threshold is soft — adjust to taste.
            pkt_color = (
                "#39d353" if pkt_delta >= 150 else
                "#facc15" if pkt_delta > 0   else
                "#555555"
            )
            self._sb_pkt_s.setText(f"{pkt_delta}")
            self._sb_pkt_s.setStyleSheet(
                f"color: {pkt_color}; border: none; background: none; font-weight: bold;"
            )
            self._sb_dsp_s.setText(f"{dsp_fps}")
            self._sb_total.setText(f"{current_total:,} pkts")
        else:
            self._sb_pkt_s.setText("—")
            self._sb_dsp_s.setText("—")

    def closeEvent(self, event):
        self._on_stop()
        super().closeEvent(event)