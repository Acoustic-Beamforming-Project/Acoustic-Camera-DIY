import sys
import numpy as np
import random
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, pyqtSlot, QObject, pyqtSignal
from main_window import MainWindow
from config import N_CHANNELS, BLOCK_SIZE, SCAN_ANGLES

class MockDataGenerator(QObject):
    """Generates synthetic multi-channel audio and SRP-PHAT spectrum data."""
    raw_packet = pyqtSignal(np.ndarray)  # Simulated UDP packet
    
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.timer.timeout.connect(self.generate)
        self.phase = 0
        self.target_angle = 0
        self._angle_step = 2

    def start(self):
        self.timer.start(30)  # ~33 FPS

    def generate(self):
        # 1. Create a simulated sound source (sine wave + noise)
        t = np.linspace(0, 0.01, BLOCK_SIZE)
        self.phase += 0.1
        
        # Moving target angle for the "Radar" feel
        self.target_angle += self._angle_step
        if abs(self.target_angle) > 60:
            self._angle_step *= -1
            
        data = np.zeros((N_CHANNELS, BLOCK_SIZE), dtype=np.float32)
        
        # Add some signal to each channel with a slight delay offset based on angle
        delay_offset = (np.sin(np.deg2rad(self.target_angle)) * 5)
        
        for i in range(N_CHANNELS):
            # Simulated signal + noise
            sig = 0.3 * np.sin(2 * np.pi * 1000 * t + self.phase + (i * delay_offset))
            noise = 0.05 * np.random.normal(size=BLOCK_SIZE)
            data[i] = sig + noise

        self.raw_packet.emit(data)

class TestRadarWindow(MainWindow):
    """Modified MainWindow that accepts mocked results directly for testing."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RADAR UI TEST - Simulated Data")
        
        # Override the spectrum plot update to show simulated power levels
        self.mock_angles = np.array(SCAN_ANGLES)
        
    @pyqtSlot(np.ndarray)
    def inject_mock_data(self, data: np.ndarray):
        """Mock the DSP process results."""
        # Calculate a fake SRP-PHAT spectrum based on the 'target_angle'
        # In a real scenario, this comes from DSPWorker
        target = getattr(self, 'target_angle_ref', 0)
        spectrum = np.exp(-0.5 * ((self.mock_angles - target) / 10)**2) 
        spectrum += 0.1 * np.random.random(len(SCAN_ANGLES)) # Noise floor
        spectrum /= (np.max(spectrum) + 1e-6) # Normalize
        
        # Update UI using existing logic
        self._on_result(data, float(target))
        self.spectrum_plot.update_spectrum(self.mock_angles, spectrum, target)

def main():
    app = QApplication(sys.argv)
    window = TestRadarWindow()
    
    generator = MockDataGenerator()
    
    # Wire generator directly to the test window's injection slot
    generator.raw_packet.connect(window.inject_mock_data)
    
    # Update the internal target angle reference for the mock spectrum
    def update_angle():
        window.target_angle_ref = generator.target_angle
        
    generator.timer.timeout.connect(update_angle)
    
    window.show()
    generator.start()
    
    print("Starting Radar UI Test with synthetic data...")
    print("Close the window to exit.")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
