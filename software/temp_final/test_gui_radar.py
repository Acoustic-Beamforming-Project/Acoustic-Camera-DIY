"""
test_gui_radar.py — Synthetic data test for the 16-channel AD7606 UI.

Simulates a sound source sweeping from -60° to +60° and back.
No hardware or UDP socket is required — data is injected directly
into the DSP worker's input slot, bypassing UDPWorker entirely.

Run with:
    python test_gui_radar.py
"""

import sys
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, pyqtSlot, QObject, pyqtSignal
from main_window import MainWindow
from config import N_CHANNELS, BLOCK_SIZE, SCAN_ANGLES


class MockDataGenerator(QObject):
    """
    Generates synthetic 16-channel audio that mimics a sound source
    at a known angle, using per-channel phase offsets to simulate
    the propagation delay across the microphone array.
    """
    raw_packet = pyqtSignal(np.ndarray)   # shape (N_CHANNELS, BLOCK_SIZE) float32

    def __init__(self):
        super().__init__()
        self.timer        = QTimer()
        self.timer.timeout.connect(self._generate)
        self.phase        = 0.0
        self.target_angle = 0.0
        self._angle_step  = 1.5   # degrees per tick

    def start(self):
        self.timer.start(30)   # ~33 fps

    def _generate(self):
        # Sweep the simulated source angle back and forth
        self.target_angle += self._angle_step
        if abs(self.target_angle) > 60.0:
            self._angle_step *= -1

        self.phase += 0.08

        t = np.linspace(0, BLOCK_SIZE / 48000, BLOCK_SIZE, endpoint=False)

        # Phase offset per channel proportional to sin(angle).
        # This is a simplified spatial delay — enough to drive SRP-PHAT.
        delay_offset = np.sin(np.deg2rad(self.target_angle)) * 6.0

        data = np.zeros((N_CHANNELS, BLOCK_SIZE), dtype=np.float32)
        for i in range(N_CHANNELS):
            phase_i = self.phase + i * delay_offset
            sig   = 0.4 * np.sin(2 * np.pi * 1000 * t + phase_i)
            noise = 0.04 * np.random.normal(size=BLOCK_SIZE)
            data[i] = (sig + noise).astype(np.float32)

        self.raw_packet.emit(data)


class TestRadarWindow(MainWindow):
    """
    MainWindow subclass that wires the mock generator instead of real UDP.
    The mock signal bypasses UDPWorker and feeds DSPWorker directly.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RADAR UI TEST — Simulated {N_CHANNELS}-ch Data")
        self.mock_angles = np.array(SCAN_ANGLES, dtype=np.float32)

    @pyqtSlot(np.ndarray)
    def inject_mock_data(self, data: np.ndarray):
        """Feed synthetic waveform straight into the DSP worker."""
        self._dsp.process(data)


def main():
    app = QApplication(sys.argv)
    window = TestRadarWindow()

    generator = MockDataGenerator()

    # Wire generator -> DSP (skips UDP entirely)
    generator.raw_packet.connect(window.inject_mock_data)

    # Start DSP worker (no UDP worker needed for the test)
    window._dsp.start()

    window.show()
    generator.start()

    print(f"Radar UI test running — {N_CHANNELS} channels, synthetic sweep ±60°")
    print("Close the window to exit.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
