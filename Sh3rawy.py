import sys
import numpy as np
from collections import deque
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
                             QGraphicsDropShadowEffect, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QLinearGradient
import pyqtgraph as pg
import queue
import random

pg.setConfigOption('background', '#1a1a25')
pg.setConfigOption('foreground', '#d0d0d0')
pg.setConfigOptions(antialias=True)

class ChannelGraphWindow(QDialog):
    def __init__(self, channel_num, color, parent=None):
        super().__init__(parent)
        self.channel_num = channel_num
        self.color = color
        self.data_history = deque(maxlen=300)
        for _ in range(300):
            self.data_history.append(0)
        
        self.setWindowTitle(f"Channel {channel_num + 1} - Detailed Analysis")
        self.setMinimumSize(900, 550)
        self.setStyleSheet("""
            QDialog {
                background-color: #15151f;
                border: 2px solid #353550;
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        self.setup_ui()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_graph)
        self.timer.start(40)
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        header = QHBoxLayout()
        
        indicator = QFrame()
        indicator.setFixedSize(16, 16)
        indicator.setStyleSheet(f"""
            background-color: {self.color};
            border-radius: 8px;
            border: 2px solid {self.color};
        """)
        header.addWidget(indicator)
        
        title = QLabel(f"CHANNEL {self.channel_num + 1} ANALYSIS")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet(f"color: {self.color}; letter-spacing: 1px;")
        header.addWidget(title)
        header.addStretch()
        
        self.db_label = QLabel("0.0 dB")
        self.db_label.setFont(QFont("Consolas", 22, QFont.Bold))
        self.db_label.setStyleSheet(f"""
            color: {self.color};
            background-color: #202030;
            padding: 8px 18px;
            border-radius: 8px;
            border: 2px solid {self.color}60;
        """)
        header.addWidget(self.db_label)
        
        layout.addLayout(header)
        
        self.graph = pg.PlotWidget()
        self.graph.setMinimumHeight(350)
        self.graph.setBackground('#1a1a25')
        
        self.graph.setLabel('left', 'Power (dB)', color='#b0b0c0', size='11pt')
        self.graph.setLabel('bottom', 'Samples', color='#b0b0c0', size='11pt')
        
        self.graph.showGrid(x=True, y=True, alpha=0.15)
        self.graph.setYRange(0, 100)
        self.graph.setXRange(0, 300)
        
        left_axis = self.graph.getAxis('left')
        bottom_axis = self.graph.getAxis('bottom')
        left_axis.setPen(pg.mkPen(color='#404055', width=1.5))
        bottom_axis.setPen(pg.mkPen(color='#404055', width=1.5))
        left_axis.setTextPen(pg.mkPen(color='#a0a0b0'))
        bottom_axis.setTextPen(pg.mkPen(color='#a0a0b0'))
        left_axis.setGrid(155)
        bottom_axis.setGrid(155)
        
        self.curve = self.graph.plot(
            pen=pg.mkPen(color=self.color, width=2.5)
        )
        
        fill_color = QColor(self.color)
        fill_color.setAlpha(25)
        self.fill = self.graph.plot(
            pen=None,
            fillBrush=pg.mkBrush(fill_color),
            fillLevel=0
        )
        
        layout.addWidget(self.graph)
        
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)
        
        stats_data = [
            ("PEAK", "#ffd740"),
            ("AVERAGE", "#40c4ff"),
            ("MINIMUM", "#ff5252"),
            ("CURRENT", self.color)
        ]
        
        self.stat_labels = {}
        for name, stat_color in stats_data:
            container = QFrame()
            container.setStyleSheet("""
                background-color: #202030; 
                border-radius: 8px; 
                padding: 10px;
                border: 1px solid #303045;
            """)
            container_layout = QVBoxLayout(container)
            container_layout.setSpacing(4)
            
            stat_title = QLabel(name)
            stat_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
            stat_title.setStyleSheet("color: #707080; letter-spacing: 1px;")
            stat_title.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(stat_title)
            
            stat_value = QLabel("0.0")
            stat_value.setFont(QFont("Consolas", 22, QFont.Bold))
            stat_value.setStyleSheet(f"color: {stat_color}; font-weight: bold;")
            stat_value.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(stat_value)
            
            stats_layout.addWidget(container)
            self.stat_labels[name] = stat_value
        
        layout.addLayout(stats_layout)
        
        buttons = QDialogButtonBox()
        close_btn = buttons.addButton("CLOSE", QDialogButtonBox.RejectRole)
        close_btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        close_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #cc3333, stop:1 #992222);
                border: 2px solid #ff4444;
                border-radius: 8px;
                padding: 10px 35px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dd4444, stop:1 #aa3333);
            }
        """)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def update_graph(self):
        if len(self.data_history) > 0:
            y = np.array(list(self.data_history))
            x = np.arange(len(y))
            
            self.curve.setData(x, y)
            
            fill_y = np.zeros(len(y) + 2)
            fill_y[1:-1] = y
            fill_x = np.arange(len(y) + 2) - 1
            self.fill.setData(fill_x, fill_y)
            
            if len(y) >= 10:
                recent = y[-50:]
                self.stat_labels["PEAK"].setText(f"{np.max(recent):.1f}")
                self.stat_labels["AVERAGE"].setText(f"{np.mean(recent):.1f}")
                self.stat_labels["MINIMUM"].setText(f"{np.min(recent):.1f}")
                self.stat_labels["CURRENT"].setText(f"{y[-1]:.1f}")
            
    def update_value(self, value):
        self.data_history.append(value)
        self.db_label.setText(f"{value:.1f} dB")

class ChannelCard(QFrame):
    def __init__(self, channel_num, color):
        super().__init__()
        self.channel_num = channel_num
        self.color = color
        self.current_value = 0
        self.graph_window = None
        
        self.setup_ui()
        
    def setup_ui(self):
        self.setMinimumHeight(90)
        self.setMinimumWidth(350)
        
        self.setStyleSheet(f"""
            QFrame#channelCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e1e2a, stop:1 #252535);
                border: 2px solid {self.color}50;
                border-radius: 10px;
                padding: 10px;
                margin: 3px;
            }}
            QFrame#channelCard:hover {{
                border: 2px solid {self.color}99;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #252535, stop:1 #2a2a3a);
            }}
        """)
        self.setObjectName("channelCard")
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(self.color).darker(180))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(15)
        
        left_section = QVBoxLayout()
        left_section.setSpacing(5)
        
        header_layout = QHBoxLayout()
        
        indicator = QFrame()
        indicator.setFixedSize(14, 14)
        indicator.setStyleSheet(f"""
            background-color: {self.color};
            border-radius: 7px;
            border: 2px solid {self.color}aa;
        """)
        header_layout.addWidget(indicator)
        
        ch_name = QLabel(f"CH {self.channel_num + 1}")
        ch_name.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ch_name.setStyleSheet(f"color: {self.color}; font-weight: bold; letter-spacing: 1px;")
        header_layout.addWidget(ch_name)
        header_layout.addStretch()
        
        left_section.addLayout(header_layout)
        
        value_bar_layout = QHBoxLayout()
        
        self.db_value_label = QLabel("0.0")
        self.db_value_label.setFont(QFont("Consolas", 30, QFont.Bold))
        self.db_value_label.setStyleSheet(f"""
            color: {self.color};
            font-weight: bold;
            background-color: #1a1a28;
            padding: 5px 15px;
            border-radius: 8px;
            border: 2px solid {self.color}40;
        """)
        value_bar_layout.addWidget(self.db_value_label)
        
        value_bar_layout.addSpacing(5)
        
        self.unit_label = QLabel("dB")
        self.unit_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.unit_label.setStyleSheet("color: #808090; padding-top: 15px;")
        value_bar_layout.addWidget(self.unit_label)
        
        value_bar_layout.addStretch()
        
        left_section.addLayout(value_bar_layout)
        
        self.power_bar_bg = QFrame()
        self.power_bar_bg.setFixedHeight(22)
        self.power_bar_bg.setStyleSheet("""
            background-color: #1a1a28;
            border-radius: 5px;
            border: 1px solid #303040;
        """)
        
        bar_layout = QHBoxLayout(self.power_bar_bg)
        bar_layout.setContentsMargins(2, 2, 2, 2)
        
        self.bar_fill = QFrame()
        self.bar_fill.setFixedWidth(0)
        self.bar_fill.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {self.color}, stop:1 {self.color}66);
            border-radius: 4px;
        """)
        bar_layout.addWidget(self.bar_fill)
        
        left_section.addWidget(self.power_bar_bg)
        main_layout.addLayout(left_section, 2)
        
        right_section = QVBoxLayout()
        right_section.setSpacing(5)
        
        stats_grid = QHBoxLayout()
        stats_grid.setSpacing(8)
        
        peak_container = QFrame()
        peak_container.setStyleSheet("""
            background-color: #1a1a28; 
            border-radius: 6px; 
            padding: 5px 8px;
            border: 1px solid #303040;
        """)
        peak_layout = QVBoxLayout(peak_container)
        peak_layout.setSpacing(1)
        peak_title = QLabel("PEAK")
        peak_title.setFont(QFont("Segoe UI", 7, QFont.Bold))
        peak_title.setStyleSheet("color: #707080; letter-spacing: 1px;")
        peak_title.setAlignment(Qt.AlignCenter)
        peak_layout.addWidget(peak_title)
        self.peak_label = QLabel("0.0")
        self.peak_label.setFont(QFont("Consolas", 13, QFont.Bold))
        self.peak_label.setStyleSheet("color: #ffd740; font-weight: bold;")
        self.peak_label.setAlignment(Qt.AlignCenter)
        peak_layout.addWidget(self.peak_label)
        stats_grid.addWidget(peak_container)
        
        avg_container = QFrame()
        avg_container.setStyleSheet("""
            background-color: #1a1a28; 
            border-radius: 6px; 
            padding: 5px 8px;
            border: 1px solid #303040;
        """)
        avg_layout = QVBoxLayout(avg_container)
        avg_layout.setSpacing(1)
        avg_title = QLabel("AVG")
        avg_title.setFont(QFont("Segoe UI", 7, QFont.Bold))
        avg_title.setStyleSheet("color: #707080; letter-spacing: 1px;")
        avg_title.setAlignment(Qt.AlignCenter)
        avg_layout.addWidget(avg_title)
        self.avg_label = QLabel("0.0")
        self.avg_label.setFont(QFont("Consolas", 13, QFont.Bold))
        self.avg_label.setStyleSheet("color: #40c4ff; font-weight: bold;")
        self.avg_label.setAlignment(Qt.AlignCenter)
        avg_layout.addWidget(self.avg_label)
        stats_grid.addWidget(avg_container)
        
        right_section.addLayout(stats_grid)
        
        self.properties_btn = QPushButton("PROPERTIES")
        self.properties_btn.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.properties_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #353545, stop:1 #252535);
                border: 2px solid {self.color}70;
                border-radius: 6px;
                padding: 6px 12px;
                color: {self.color};
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #454555, stop:1 #353545);
                border: 2px solid {self.color}aa;
            }}
        """)
        self.properties_btn.clicked.connect(self.open_graph_window)
        right_section.addWidget(self.properties_btn)
        
        main_layout.addLayout(right_section)
        
    def open_graph_window(self):
        if self.graph_window is None:
            self.graph_window = ChannelGraphWindow(self.channel_num, self.color, self)
        self.graph_window.update_value(self.current_value)
        self.graph_window.show()
        self.graph_window.raise_()
        self.graph_window.activateWindow()
        
    def update_stats(self, peak, avg):
        self.peak_label.setText(f"{peak:.1f}")
        self.avg_label.setText(f"{avg:.1f}")

class DOADisplay(QFrame):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        self.setStyleSheet("""
            QFrame#doaDisplay {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1a28, stop:1 #252535);
                border: 2px solid #353550;
                border-radius: 12px;
            }
        """)
        self.setObjectName("doaDisplay")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(15)
        
        title = QLabel("DIRECTION OF ARRIVAL")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("color: #ffffff; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        self.doa_value = QLabel("0.0")
        self.doa_value.setFont(QFont("Consolas", 68, QFont.Bold))
        self.doa_value.setStyleSheet("""
            color: #ff3366;
            font-weight: bold;
            padding: 15px;
            background-color: #1a1a28;
            border-radius: 10px;
            border: 2px solid #ff336640;
        """)
        self.doa_value.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.doa_value)
        
        info_layout = QHBoxLayout()
        info_layout.setSpacing(20)
        
        conf_layout = QVBoxLayout()
        conf_title = QLabel("CONFIDENCE")
        conf_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        conf_title.setStyleSheet("color: #707080; letter-spacing: 1px;")
        conf_title.setAlignment(Qt.AlignCenter)
        conf_layout.addWidget(conf_title)
        
        self.conf_value = QLabel("0%")
        self.conf_value.setFont(QFont("Consolas", 26, QFont.Bold))
        self.conf_value.setStyleSheet("color: #00ff88; font-weight: bold;")
        self.conf_value.setAlignment(Qt.AlignCenter)
        conf_layout.addWidget(self.conf_value)
        
        info_layout.addLayout(conf_layout)
        
        snr_layout = QVBoxLayout()
        snr_title = QLabel("SNR")
        snr_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        snr_title.setStyleSheet("color: #707080; letter-spacing: 1px;")
        snr_title.setAlignment(Qt.AlignCenter)
        snr_layout.addWidget(snr_title)
        
        self.snr_value = QLabel("0.0 dB")
        self.snr_value.setFont(QFont("Consolas", 26, QFont.Bold))
        self.snr_value.setStyleSheet("color: #00ccff; font-weight: bold;")
        self.snr_value.setAlignment(Qt.AlignCenter)
        snr_layout.addWidget(self.snr_value)
        
        info_layout.addLayout(snr_layout)
        
        layout.addLayout(info_layout)

class RadarGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DOA Radar System")
        self.setMinimumSize(1500, 900)
        
        self.data_queue = queue.Queue()
        self.udp_ip = "192.168.1.100"
        
        self.channel_stats = {}
        for i in range(8):
            self.channel_stats[f'ch{i}'] = {
                'peak': 0,
                'avg': deque(maxlen=100),
                'current': 0
            }
        
        self.setStyleSheet("background-color: #12121a;")
        
        self.setup_ui()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(40)
        
        self.test_timer = QTimer()
        self.test_timer.timeout.connect(self.generate_realistic_data)
        self.test_timer.start(80)
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(10)
        
        status_bar = self.create_status_bar()
        main_layout.addWidget(status_bar)
        
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        
        channels_panel = self.create_channels_panel()
        content_layout.addWidget(channels_panel, 3)
        
        right_panel = self.create_right_panel()
        content_layout.addWidget(right_panel, 5)
        
        main_layout.addLayout(content_layout)
        
    def create_status_bar(self):
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a25, stop:0.5 #252535, stop:1 #1a1a25);
                border: 2px solid #404060;
                border-radius: 8px;
            }
        """)
        
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 8, 15, 8)
        
        sys_title = QLabel("ACOUSTIC DOA RADAR SYSTEM")
        sys_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        sys_title.setStyleSheet("""
            color: #ffffff;
            letter-spacing: 2px;
            padding: 4px 12px;
            background-color: #2a2a3a;
            border-radius: 5px;
        """)
        layout.addWidget(sys_title)
        
        layout.addStretch()
        
        self.udp_label = QLabel(f"UDP: {self.udp_ip}:5005")
        self.udp_label.setFont(QFont("Consolas", 10, QFont.Bold))
        self.udp_label.setStyleSheet("""
            color: #00ccff;
            background-color: #1a2a35;
            padding: 4px 12px;
            border-radius: 5px;
            border: 1px solid #00ccff40;
        """)
        layout.addWidget(self.udp_label)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color: #505070; max-width: 2px;")
        layout.addWidget(sep)
        
        self.connect_btn = QPushButton("CONNECT")
        self.connect_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0066dd, stop:1 #004499);
                border: 2px solid #0088ff;
                border-radius: 6px;
                padding: 6px 18px;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0077ee, stop:1 #0055aa);
            }
        """)
        layout.addWidget(self.connect_btn)
        
        self.live_dot = QLabel("●")
        self.live_dot.setFont(QFont("Arial", 14, QFont.Bold))
        self.live_dot.setStyleSheet("color: #00ff55;")
        layout.addWidget(self.live_dot)
        
        self.live_text = QLabel("LIVE")
        self.live_text.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.live_text.setStyleSheet("color: #00ff55; letter-spacing: 2px;")
        layout.addWidget(self.live_text)
        
        return bar
        
    def create_channels_panel(self):
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame#chPanel {
                background-color: #161620;
                border: 2px solid #353550;
                border-radius: 10px;
            }
        """)
        panel.setObjectName("chPanel")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        title = QLabel("CHANNEL MONITORING")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("""
            color: #ffffff;
            letter-spacing: 2px;
            padding: 8px;
            background-color: #202030;
            border-radius: 6px;
        """)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: #1a1a28;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #505070;
                border-radius: 5px;
                min-height: 35px;
            }
            QScrollBar::handle:vertical:hover {
                background: #606080;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        ch_layout = QVBoxLayout(scroll_content)
        ch_layout.setSpacing(6)
        
        colors = ['#00e5ff', '#ff5252', '#69f0ae', '#ffd740',
                  '#b388ff', '#ff9100', '#40c4ff', '#ff4081']
        
        self.channel_cards = []
        for i in range(8):
            card = ChannelCard(i, colors[i])
            ch_layout.addWidget(card)
            self.channel_cards.append(card)
        
        ch_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        return panel
        
    def create_right_panel(self):
        panel = QFrame()
        panel.setStyleSheet("background: transparent; border: none;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        spectrum_frame = QFrame()
        spectrum_frame.setStyleSheet("""
            QFrame#specFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1a28, stop:1 #252535);
                border: 2px solid #353550;
                border-radius: 10px;
            }
        """)
        spectrum_frame.setObjectName("specFrame")
        
        spec_layout = QVBoxLayout(spectrum_frame)
        spec_layout.setContentsMargins(15, 12, 15, 12)
        spec_layout.setSpacing(8)
        
        spec_title = QLabel("SRP-PHAT SPECTRUM (Angle vs Power)")
        spec_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        spec_title.setStyleSheet("color: #ffffff; letter-spacing: 1px;")
        spec_layout.addWidget(spec_title)
        
        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setMinimumHeight(350)
        self.spectrum_plot.setBackground('#1a1a25')
        self.spectrum_plot.setLabel('left', 'Power', color='#b0b0c0', size='11pt')
        self.spectrum_plot.setLabel('bottom', 'Angle (degrees)', color='#b0b0c0', size='11pt')
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.15)
        self.spectrum_plot.setXRange(-90, 90)
        self.spectrum_plot.setYRange(0, 1)
        
        for axis_name in ['left', 'bottom']:
            axis = self.spectrum_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(color='#404055', width=1.5))
            axis.setTextPen(pg.mkPen(color='#a0a0b0'))
            axis.setGrid(155)
        
        self.spectrum_curve = self.spectrum_plot.plot(
            pen=pg.mkPen(color='#00d4ff', width=2.5)
        )
        
        fill_color = QColor(0, 212, 255)
        fill_color.setAlpha(25)
        self.spectrum_fill = self.spectrum_plot.plot(
            pen=None,
            fillBrush=pg.mkBrush(fill_color),
            fillLevel=0
        )
        
        self.doa_line = pg.InfiniteLine(
            angle=90,
            pen=pg.mkPen(color='#ff3366', width=2.5, style=Qt.DashLine),
            movable=False
        )
        self.spectrum_plot.addItem(self.doa_line)
        
        self.doa_marker = pg.ScatterPlotItem()
        self.doa_marker.setSize(12)
        self.doa_marker.setBrush(pg.mkBrush('#ff3366'))
        self.doa_marker.setPen(pg.mkPen('#ffffff', width=2))
        self.spectrum_plot.addItem(self.doa_marker)
        
        spec_layout.addWidget(self.spectrum_plot)
        layout.addWidget(spectrum_frame)
        
        self.doa_display = DOADisplay()
        layout.addWidget(self.doa_display)
        
        return panel
        
    def generate_realistic_data(self):
        powers = []
        for i in range(8):
            base = 25 + 10 * np.sin(i * 0.7 + random.random())
            noise = random.gauss(0, 10)
            power = np.clip(base + noise, 0, 100)
            powers.append(power)
        
        angles = np.arange(-90, 91)
        true_doa = random.uniform(-45, 45)
        spectrum = 0.9 * np.exp(-(angles - true_doa)**2 / 80)
        spectrum += 0.03 * np.random.randn(181)
        spectrum = np.clip(spectrum, 0, 1)
        
        data = {
            'channels': powers,
            'spectrum': spectrum,
            'doa': true_doa,
            'angles': angles,
            'confidence': random.uniform(80, 99),
            'snr': random.uniform(10, 22)
        }
        self.data_queue.put(data)
        
    def update_gui(self):
        try:
            data = self.data_queue.get_nowait()
            
            for i, card in enumerate(self.channel_cards):
                power = data['channels'][i]
                
                stats = self.channel_stats[f'ch{i}']
                stats['current'] = power
                stats['avg'].append(power)
                if power > stats['peak']:
                    stats['peak'] = power
                
                card.current_value = power
                card.db_value_label.setText(f"{power:.1f}")
                
                if power >= 75:
                    val_color = '#ff3366'
                elif power >= 50:
                    val_color = '#ffd740'
                elif power >= 25:
                    val_color = '#69f0ae'
                else:
                    val_color = '#40c4ff'
                    
                card.db_value_label.setStyleSheet(f"""
                    color: {val_color};
                    font-size: 30px;
                    font-weight: bold;
                    background-color: #1a1a28;
                    padding: 5px 15px;
                    border-radius: 8px;
                    border: 2px solid {val_color}40;
                """)
                
                bar_width = int(power * 3.4)
                card.bar_fill.setFixedWidth(bar_width)
                
                avg_val = np.mean(stats['avg'])
                card.update_stats(stats['peak'], avg_val)
                
                if card.graph_window is not None and card.graph_window.isVisible():
                    card.graph_window.update_value(power)
                
            angles = np.array(data['angles'])
            spectrum = np.array(data['spectrum'])
            
            self.spectrum_curve.setData(angles, spectrum)
            self.spectrum_fill.setData(angles, spectrum)
            
            doa = data['doa']
            self.doa_display.doa_value.setText(f"{doa:.1f}")
            self.doa_line.setPos(doa)
            
            peak_idx = np.argmax(spectrum)
            self.doa_marker.setData([angles[peak_idx]], [spectrum[peak_idx]])
            
            self.doa_display.conf_value.setText(f"{data['confidence']:.0f}%")
            self.doa_display.snr_value.setText(f"{data['snr']:.1f} dB")
            
            conf = data['confidence']
            if conf > 90:
                doa_color = '#00ff55'
            elif conf > 75:
                doa_color = '#ffd740'
            else:
                doa_color = '#ff3366'
                
            self.doa_display.doa_value.setStyleSheet(f"""
                color: {doa_color};
                font-size: 68px;
                font-weight: bold;
                padding: 15px;
                background-color: #1a1a28;
                border-radius: 10px;
                border: 2px solid {doa_color}40;
            """)
            
        except queue.Empty:
            pass

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = RadarGUI()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()