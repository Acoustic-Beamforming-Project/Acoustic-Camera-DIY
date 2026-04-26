# Acoustic Camera — Software Frontend
# GEMINI.md — Complete Frontend Build Guide

---

## 0. YOUR FIRST TASK: Install Requirements

Before writing any code, run this in the terminal:

```bash
pip install PyQt6 pyqtgraph numpy scipy
```

Verify with:

```python
import PyQt6, pyqtgraph, numpy, scipy
print("All good")
```

If PyQt6 fails on Linux, also run:
```bash
sudo apt install python3-pyqt6
```

---

## 1. Project Overview

This is a **real-time acoustic DOA (Direction of Arrival) visualizer**.

Hardware sends 8-channel raw audio over **UDP/Ethernet** from an STM32F411 + AD7606.
Python receives it, runs **SRP-PHAT beamforming**, and displays results live.

**You are building the Python desktop frontend only.**
The backend (UDP socket + DSP math) runs in background QThreads.
The frontend (PyQt6 GUI) only receives processed results via Qt signals.
The UI thread must NEVER be blocked.

---

## 2. File Structure — Follow This Exactly

```
software/
├── GEMINI.md           <- this file
├── main.py             <- entry point, creates QApplication
├── main_window.py      <- MainWindow class, full layout assembly
├── udp_worker.py       <- UDPWorker(QThread): receives raw UDP packets
├── dsp_worker.py       <- DSPWorker(QThread): runs SRP-PHAT, emits results
├── plot_widgets.py     <- WaveformGrid and SpectrumPlot widget wrappers
├── doa_indicator.py    <- DOAIndicator: angle slider + big number display
├── config.py           <- ALL constants (IP, port, channels, geometry)
└── requirements.txt
```

---

## 3. Config File — Write This First (config.py)

```python
# config.py — single source of truth for all constants

# --- Network ---
UDP_IP      = "0.0.0.0"
UDP_PORT    = 5005
BUFFER_SIZE = 4096        # bytes per UDP packet — adjust to match STM32

# --- Hardware ---
N_CHANNELS     = 8
SAMPLE_RATE    = 48000    # Hz
ADC_BITS       = 16
MIC_SPACING    = 0.05     # meters between microphones (50mm default)
SPEED_OF_SOUND = 343.0    # m/s at room temperature

# --- DSP ---
BLOCK_SIZE    = 256        # samples per processing frame
BANDPASS_LOW  = 300        # Hz — low cutoff (voice range)
BANDPASS_HIGH = 3400       # Hz — high cutoff (voice range)
SCAN_ANGLES   = list(range(-90, 91, 1))   # DOA sweep -90 to +90 degrees

# --- Display ---
PLOT_HISTORY     = 500     # samples shown in scrolling waveform
WAVEFORM_RATE_HZ = 30      # target waveform redraw rate
SPECTRUM_RATE_HZ = 15      # target spectrum redraw rate

# --- Channel Colors (GitHub dark palette, paired by channel) ---
CHANNEL_COLORS = [
    '#1f6feb', '#388bfd',   # Ch1, Ch2 — blue pair
    '#238636', '#2ea043',   # Ch3, Ch4 — green pair
    '#9e6a03', '#d29922',   # Ch5, Ch6 — amber pair
    '#6e7681', '#8b949e',   # Ch7, Ch8 — gray pair
]
```

---

## 4. Threading Architecture — ABSOLUTE RULES

```
MainThread  (PyQt6 UI — NEVER BLOCK THIS THREAD)
├── UDPWorker(QThread)
│     socket.settimeout(1.0) is MANDATORY
│     emits: raw_packet  = pyqtSignal(np.ndarray)
│                          shape: (N_CHANNELS, BLOCK_SIZE), dtype: float32
│
├── DSPWorker(QThread)
│     receives raw_packet from UDPWorker via signal/slot
│     runs: bandpass filter + SRP-PHAT
│     emits: result = pyqtSignal(np.ndarray, float)
│                     np.ndarray = waveform (N_CHANNELS, BLOCK_SIZE)
│                     float      = doa_angle degrees, range -90.0 to +90.0
│
└── MainWindow  (slots connected to DSPWorker.result)
      _on_result(waveform, angle)  -> update 8 curves + DOA display
      _on_udp_error(msg)           -> show QMessageBox
```

### NEVER:
- Call `time.sleep()` in any QThread (use `socket.settimeout` or `self.msleep()`)
- Update any widget from inside a QThread (emit a signal, update in a slot)
- Use `threading.Thread` (always QThread)
- Share mutable data between threads without QMutex
- Use `app.exec_()` — PyQt6 uses `app.exec()`

### ALWAYS:
- Set `socket.settimeout(1.0)` in UDPWorker.run()
- Call `thread.quit(); thread.wait()` in `closeEvent()`
- Use `from PyQt6.xxx import ...` — never PyQt5
- Use full enum paths: `Qt.Orientation.Horizontal` not `Qt.Horizontal`

---

## 5. UDPWorker — Complete Implementation (udp_worker.py)

```python
import socket
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from config import UDP_IP, UDP_PORT, BUFFER_SIZE, N_CHANNELS, BLOCK_SIZE

class UDPWorker(QThread):
    raw_packet = pyqtSignal(np.ndarray)  # shape (N_CHANNELS, BLOCK_SIZE) float32
    error      = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.bind((UDP_IP, UDP_PORT))
        sock.settimeout(1.0)             # CRITICAL: allows clean stop

        while self._running:
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                arr /= 32768.0           # normalize to -1.0 .. +1.0

                # STM32 sends interleaved: [ch0s0, ch1s0,...,ch7s0, ch0s1,...]
                arr = arr.reshape(-1, N_CHANNELS).T  # -> (N_CHANNELS, N_SAMPLES)

                if arr.shape[1] >= BLOCK_SIZE:
                    self.raw_packet.emit(arr[:, :BLOCK_SIZE].copy())

            except socket.timeout:
                continue                 # check _running flag and loop back
            except Exception as e:
                self.error.emit(str(e))
                break

        sock.close()

    def stop(self):
        self._running = False
        self.wait()
```

---

## 6. DSPWorker — Complete Implementation (dsp_worker.py)

```python
import numpy as np
from scipy.signal import butter, sosfilt
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from config import (N_CHANNELS, SAMPLE_RATE, BLOCK_SIZE,
                    BANDPASS_LOW, BANDPASS_HIGH,
                    MIC_SPACING, SPEED_OF_SOUND, SCAN_ANGLES)

class DSPWorker(QThread):
    result = pyqtSignal(np.ndarray, float)  # (waveform, doa_degrees)

    def __init__(self):
        super().__init__()
        self._pending  = None
        self._mutex    = QMutex()
        self._running  = False

        # Pre-compute Butterworth bandpass filter
        self._sos = butter(
            4, [BANDPASS_LOW, BANDPASS_HIGH],
            btype='bandpass', fs=SAMPLE_RATE, output='sos'
        )

        # Pre-compute GCC delays for every mic pair at every scan angle
        self._precompute_delays()

    def _precompute_delays(self):
        angles_rad   = np.deg2rad(SCAN_ANGLES)
        mic_pos      = np.arange(N_CHANNELS) * MIC_SPACING
        self._delays = {}
        for i in range(N_CHANNELS):
            for j in range(i + 1, N_CHANNELS):
                d = (mic_pos[i] - mic_pos[j]) * np.sin(angles_rad)
                self._delays[(i, j)] = (
                    d / SPEED_OF_SOUND * SAMPLE_RATE
                ).astype(int)

    def process(self, data: np.ndarray):
        """Called via signal from UDPWorker — stores latest frame."""
        self._mutex.lock()
        self._pending = data
        self._mutex.unlock()

    def run(self):
        self._running = True
        while self._running:
            self._mutex.lock()
            data          = self._pending
            self._pending = None
            self._mutex.unlock()

            if data is not None:
                filtered = sosfilt(self._sos, data, axis=1).astype(np.float32)
                angle    = self._srp_phat(filtered)
                self.result.emit(data, float(angle))
            else:
                self.msleep(5)

    def _srp_phat(self, data: np.ndarray) -> float:
        n_fft = data.shape[1]
        P = np.zeros(len(SCAN_ANGLES))

        for i in range(N_CHANNELS):
            for j in range(i + 1, N_CHANNELS):
                Xi    = np.fft.rfft(data[i], n=n_fft)
                Xj    = np.fft.rfft(data[j], n=n_fft)
                GCC   = Xi * np.conj(Xj)
                PHAT  = GCC / (np.abs(GCC) + 1e-10)
                gcc_t = np.real(np.fft.irfft(PHAT, n=n_fft))

                delays = self._delays[(i, j)]
                for a_idx, tau in enumerate(delays):
                    P[a_idx] += gcc_t[int(tau) % n_fft]

        return float(SCAN_ANGLES[int(np.argmax(P))])

    def stop(self):
        self._running = False
        self.wait()
```

---

## 7. Main Window Layout Blueprint (main_window.py)

Implement the layout EXACTLY as shown. Widget object names must match.

```
QMainWindow
└── centralWidget (QWidget, objectName="centralWidget")
    └── QVBoxLayout  (spacing=0, margins=0)
        │
        ├── [TOP BAR]  QWidget (objectName="topBar", fixed height 46px)
        │   └── QHBoxLayout (margins: 8px, spacing: 8px)
        │       ├── QLabel "UDP"                   — static label
        │       ├── QLineEdit (objectName="ip_input")    — default "192.168.1.105"
        │       ├── QLabel ":"                     — separator
        │       ├── QLineEdit (objectName="port_input")  — default "5005", maxWidth=60
        │       ├── QPushButton (objectName="btn_connect") — text "Connect"
        │       ├── QPushButton (objectName="btn_stop")    — text "Stop"
        │       ├── QSpacerItem (expanding)
        │       └── QLabel (objectName="lbl_live")        — text "● Live"
        │
        ├── [MAIN BODY]  QSplitter (Horizontal)
        │   │
        │   ├── LEFT PANEL: QWidget (objectName="leftPanel")
        │   │   └── QVBoxLayout (spacing=0, margins=0)
        │   │       └── [8x] QWidget (objectName="chRow_N")
        │   │               └── QHBoxLayout (margins: 4px 2px, spacing=4)
        │   │                   ├── QLabel (objectName="ch_label") — "Ch1".."Ch8"
        │   │                   └── pg.PlotWidget (objectName="wave_N")
        │   │
        │   └── RIGHT PANEL: QWidget (objectName="rightPanel")
        │       └── QVBoxLayout (spacing=0, margins=0)
        │           │
        │           ├── SPECTRUM: pg.PlotWidget (objectName="spectrum_plot")
        │           │   stretch factor = 6
        │           │   X axis: angle -90 to +90 degrees
        │           │   Y axis: SRP-PHAT power (auto range)
        │           │   + pg.InfiniteLine at peak (objectName="peak_line")
        │           │
        │           └── DOA INDICATOR: QWidget (objectName="doaPanel")
        │               stretch factor = 4
        │               └── QVBoxLayout (alignment: center, margins: 12px)
        │                   ├── QLabel (objectName="lbl_doa_title") "Direction of Arrival"
        │                   ├── QLabel (objectName="lbl_angle")     "47°"
        │                   ├── QSlider (objectName="doa_slider")
        │                   │   Horizontal, range 0–180, setValue(90=center)
        │                   │   setEnabled(False) — read-only visual only
        │                   └── QWidget: angle labels row
        │                       QHBoxLayout: "-90°" [spacer] "0°" [spacer] "90°"
        │
        └── [STATUS BAR]  self.statusBar() — QMainWindow built-in
            Updated every 1 second via QTimer
            Format: "Packets/s: N  |  Dropped: N  |  SRP-PHAT · 8ch · 48kHz"
```

### Signal Wiring in __init__:

```python
# Wire workers together and to UI
self._udp.raw_packet.connect(self._dsp.process)
self._dsp.result.connect(self._on_result)
self._udp.error.connect(self._on_udp_error)
self.btn_connect.clicked.connect(self._on_connect)
self.btn_stop.clicked.connect(self._on_stop)
```

### Update Slot:

```python
@pyqtSlot(np.ndarray, float)
def _on_result(self, waveform: np.ndarray, angle: float):
    # 1. Roll and update each channel buffer
    for ch in range(N_CHANNELS):
        n = waveform.shape[1]
        self._buffers[ch] = np.roll(self._buffers[ch], -n)
        self._buffers[ch][-n:] = waveform[ch]
        self._curves[ch].setData(y=self._buffers[ch])   # setData only, never clear()

    # 2. Update spectrum (power vs angle array, shape (181,))
    # self._spectrum_curve.setData(x=SCAN_ANGLES, y=power_array)

    # 3. Update DOA indicator
    self.lbl_angle.setText(f"{angle:.0f}°")
    slider_val = int(np.interp(angle, [-90, 90], [0, 180]))
    self.doa_slider.setValue(slider_val)
    self._peak_line.setValue(angle)
```

---

## 8. PyQtGraph Configuration Rules

### Waveform PlotWidget (create once, update with setData only):

```python
plot = pg.PlotWidget()
plot.setBackground('#0d1117')
plot.setFixedHeight(44)
plot.hideButtons()
plot.getPlotItem().hideAxis('bottom')
plot.getPlotItem().hideAxis('left')
plot.setYRange(-1.0, 1.0, padding=0)
plot.setMouseEnabled(x=False, y=False)
plot.getPlotItem().setContentsMargins(0, 0, 0, 0)

curve = plot.plot(pen=pg.mkPen(CHANNEL_COLORS[ch_index], width=1.2))
# Store curve reference: self._curves.append(curve)
# Update: curve.setData(y=self._buffers[ch])  ← ONLY this, never plot.clear()
```

### Spectrum PlotWidget:

```python
sp = pg.PlotWidget()
sp.setBackground('#0d1117')
sp.setLabel('bottom', 'Angle (°)', **{'color': '#8b949e', 'font-size': '10px'})
sp.setLabel('left',   'Power',     **{'color': '#8b949e', 'font-size': '10px'})
sp.setXRange(-90, 90, padding=0.02)
sp.showGrid(x=True, y=True, alpha=0.12)
sp.getPlotItem().getAxis('bottom').setTextPen('#8b949e')
sp.getPlotItem().getAxis('left').setTextPen('#8b949e')
sp.setMouseEnabled(x=False, y=False)

self._spectrum_curve = sp.plot(
    x=SCAN_ANGLES, y=np.zeros(len(SCAN_ANGLES)),
    pen=pg.mkPen('#1f6feb', width=1.5)
)
self._peak_line = pg.InfiniteLine(
    pos=0, angle=90,
    pen=pg.mkPen('#58a6ff', width=1.0, style=Qt.PenStyle.DashLine),
    label='{value:.0f}°',
    labelOpts={'color': '#58a6ff', 'position': 0.1}
)
sp.addItem(self._peak_line)
```

---

## 9. Complete QSS Stylesheet

```python
QSS = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}

QWidget#topBar {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
    min-height: 46px;
    max-height: 46px;
}

QLineEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 5px;
    color: #58a6ff;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    padding: 4px 10px;
    min-width: 120px;
}
QLineEdit:focus {
    border-color: #388bfd;
    outline: none;
}

QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 5px;
    color: #c9d1d9;
    padding: 5px 14px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
}
QPushButton:pressed {
    background-color: #161b22;
}

QPushButton#btn_connect {
    background-color: #1f6feb;
    border-color: #388bfd;
    color: #ffffff;
    font-weight: 500;
}
QPushButton#btn_connect:hover {
    background-color: #388bfd;
}
QPushButton#btn_connect:disabled {
    background-color: #21262d;
    border-color: #30363d;
    color: #484f58;
}

QPushButton#btn_stop {
    background-color: #21262d;
    border-color: #f85149;
    color: #f85149;
}
QPushButton#btn_stop:hover {
    background-color: #3d1f1f;
}

QLabel#lbl_live {
    color: #3fb950;
    font-size: 11px;
    font-weight: 500;
    padding: 0 8px;
}

QLabel#ch_label {
    color: #484f58;
    font-family: 'Consolas', monospace;
    font-size: 10px;
    min-width: 30px;
    max-width: 30px;
    qproperty-alignment: AlignRight;
}

QLabel#lbl_doa_title {
    color: #484f58;
    font-size: 10px;
    letter-spacing: 1px;
    qproperty-alignment: AlignCenter;
}

QLabel#lbl_angle {
    color: #58a6ff;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 42px;
    font-weight: 500;
    qproperty-alignment: AlignCenter;
    padding: 4px 0;
}

QSlider#doa_slider::groove:horizontal {
    height: 6px;
    background: #21262d;
    border-radius: 3px;
    margin: 0 6px;
}
QSlider#doa_slider::sub-page:horizontal {
    background: #1f6feb;
    border-radius: 3px;
}
QSlider#doa_slider::handle:horizontal {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    background: #58a6ff;
    border: 2px solid #0d1117;
    margin: -5px 0;
}

QWidget#doaPanel {
    background-color: #0d1117;
    border-top: 1px solid #21262d;
}

QWidget#chRow_0, QWidget#chRow_1, QWidget#chRow_2, QWidget#chRow_3,
QWidget#chRow_4, QWidget#chRow_5, QWidget#chRow_6, QWidget#chRow_7 {
    border-bottom: 1px solid #161b22;
}

QSplitter::handle {
    background-color: #21262d;
    width: 1px;
}

QStatusBar {
    background-color: #161b22;
    border-top: 1px solid #30363d;
    color: #8b949e;
    font-size: 11px;
    font-family: 'Consolas', monospace;
}
QStatusBar::item {
    border: none;
}

QMessageBox {
    background-color: #161b22;
    color: #c9d1d9;
}

QScrollBar:vertical {
    background: #0d1117;
    width: 6px;
    border-radius: 3px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
"""
```

Apply with: `self.setStyleSheet(QSS)` inside `MainWindow.__init__`

---

## 10. Entry Point (main.py)

```python
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Segoe UI', 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
```

---

## 11. Requirements File (requirements.txt)

```
PyQt6>=6.5.0
pyqtgraph>=0.13.3
numpy>=1.24.0
scipy>=1.11.0
```

---

## 12. PyQt6 Enum Reference — Always Use Full Path

```python
# CORRECT
Qt.Orientation.Horizontal
Qt.Orientation.Vertical
Qt.AlignmentFlag.AlignCenter
Qt.AlignmentFlag.AlignRight
Qt.PenStyle.DashLine
Qt.PenStyle.SolidLine
QSizePolicy.Policy.Expanding
QSizePolicy.Policy.Fixed
QSizePolicy.Policy.Minimum

# WRONG (PyQt5 style — will crash in PyQt6)
Qt.Horizontal
Qt.AlignCenter
Qt.DashLine
```

---

## 13. What Gemini Must NEVER Do

- Use `PyQt5` — all imports must be `from PyQt6.xxx`
- Use `matplotlib` for any plot — use `pyqtgraph` only
- Use `threading.Thread` — use `QThread` only
- Call `plot.clear()` in the update loop — call `curve.setData()` only
- Use `time.sleep()` — use `socket.settimeout(1.0)` or `self.msleep(N)`
- Update any QWidget from inside a QThread — emit a signal, slot updates UI
- Use `app.exec_()` — PyQt6 uses `app.exec()`
- Use `QDial` for angle display — use `QSlider` + `QLabel` as specified above
- Invent a different file structure — follow Section 2 exactly
- Hardcode IP or port — always read from `config.py`
- Use short enum form like `Qt.Horizontal` — always use full path (Section 12)
- Put DSP math in the UI thread — it belongs in DSPWorker.run() only