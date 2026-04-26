import sys
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QFrame, QScrollArea,
                             QSplitter, QMessageBox, QStatusBar)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QFont
from config import (UDP_IP, UDP_PORT, N_CHANNELS, SAMPLE_RATE, 
                    SCAN_ANGLES, BG_COLOR, PANEL_COLOR, LIVE_COLOR, CHANNEL_COLORS)
from udp_worker import UDPWorker
from dsp_worker import DSPWorker
from plot_widgets import ChannelCard, SpectrumPlot
from doa_indicator import DOAIndicator

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DOA Radar System — Acoustic Camera DIY")
        self.setMinimumSize(1200, 800)
        self.setStyleSheet(f"background-color: {BG_COLOR};")
        
        self._packet_count = 0
        self._udp = UDPWorker()
        self._dsp = DSPWorker()
        
        self.init_ui()
        self.setup_connections()
        
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(1000)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(10)
        
        # --- Top Status Bar (Sh3rawy Style) ---
        status_frame = QFrame()
        status_frame.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a25, stop:0.5 #252535, stop:1 #1a1a25);
                border: 2px solid #404060;
                border-radius: 8px;
            }}
        """)
        sf_layout = QHBoxLayout(status_frame)
        
        sys_title = QLabel("ACOUSTIC DOA RADAR SYSTEM")
        sys_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        sys_title.setStyleSheet("color: #ffffff; letter-spacing: 2px; padding: 4px 12px; background-color: #2a2a3a; border-radius: 5px;")
        sf_layout.addWidget(sys_title)
        sf_layout.addStretch()
        
        self.ip_input = QLineEdit(UDP_IP)
        self.port_input = QLineEdit(str(UDP_PORT))
        for w in [self.ip_input, self.port_input]:
            w.setStyleSheet("background-color: #1a2a35; color: #00ccff; border: 1px solid #00ccff40; border-radius: 5px; padding: 4px;")
        self.port_input.setFixedWidth(50)
        
        sf_layout.addWidget(QLabel("IP:"))
        sf_layout.addWidget(self.ip_input)
        sf_layout.addWidget(QLabel(":"))
        sf_layout.addWidget(self.port_input)
        
        self.btn_connect = QPushButton("CONNECT")
        self.btn_connect.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.btn_connect.setStyleSheet("""
            QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0066dd, stop:1 #004499); border: 2px solid #0088ff; border-radius: 6px; padding: 6px 18px; color: white; }
            QPushButton:hover { background: #0077ee; }
            QPushButton:disabled { background: #333; border-color: #555; }
        """)
        sf_layout.addWidget(self.btn_connect)
        
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("QPushButton { background: #3d1f1f; border: 2px solid #f85149; border-radius: 6px; padding: 6px 18px; color: #f85149; }")
        sf_layout.addWidget(self.btn_stop)
        
        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet(f"color: {LIVE_COLOR}; font-size: 18px;")
        self.live_dot.setVisible(False)
        sf_layout.addWidget(self.live_dot)
        
        main_layout.addWidget(status_frame)
        
        # --- Body ---
        content_layout = QHBoxLayout()
        
        # Left Panel: Channel Monitoring
        left_panel = QFrame()
        left_panel.setStyleSheet(f"background-color: {PANEL_COLOR}; border: 2px solid #353550; border-radius: 10px;")
        lp_layout = QVBoxLayout(left_panel)
        
        title = QLabel("CHANNEL MONITORING")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; background-color: #202030; padding: 8px; border-radius: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_layout.addWidget(title)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll_content = QWidget()
        self.ch_layout = QVBoxLayout(scroll_content)
        
        self.channel_cards = []
        for i in range(N_CHANNELS):
            card = ChannelCard(i, CHANNEL_COLORS[i])
            self.ch_layout.addWidget(card)
            self.channel_cards.append(card)
        
        scroll.setWidget(scroll_content)
        lp_layout.addWidget(scroll)
        content_layout.addWidget(left_panel, 3)
        
        # Right Panel: Spectrum + DOA
        right_panel = QVBoxLayout()
        self.spectrum_plot = SpectrumPlot()
        right_panel.addWidget(self.spectrum_plot, 6)
        
        self.doa_indicator = DOAIndicator()
        right_panel.addWidget(self.doa_indicator, 4)
        
        content_layout.addLayout(right_panel, 5)
        main_layout.addLayout(content_layout)
        
        self.setStatusBar(QStatusBar())

    def setup_connections(self):
        self._udp.raw_packet.connect(self._dsp.process)
        self._dsp.result.connect(self._on_result)
        self._udp.error.connect(self._on_udp_error)
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_stop.clicked.connect(self._on_stop)

    @pyqtSlot(np.ndarray, float)
    def _on_result(self, waveform: np.ndarray, angle: float):
        self._packet_count += 1
        for i in range(N_CHANNELS):
            self.channel_cards[i].update_data(waveform[i])
        
        # Peak angle and spectrum (we'll need spectrum power in the future)
        self.spectrum_plot.update_spectrum(SCAN_ANGLES, np.zeros(len(SCAN_ANGLES)), angle)
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
        if self._udp.isRunning():
            pps = self._packet_count
            self._packet_count = 0
            self.statusBar().showMessage(f"UDP Packets/s: {pps}  |  Sampling Rate: {SAMPLE_RATE} Hz")

    def closeEvent(self, event):
        self._on_stop()
        super().closeEvent(event)
