import sys
import numpy as np
import serial
import serial.tools.list_ports
import socket
import json
import threading
import os
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QComboBox, 
                             QLineEdit, QPushButton, QScrollArea, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QGraphicsDropShadowEffect,
                             QTabWidget, QGroupBox, QProgressBar, QMessageBox,
                             QFileDialog, QLayout, QGraphicsBlurEffect,
                             QCheckBox, QListWidget, QListWidgetItem, QTextEdit,
                             QInputDialog, QDialog, QDoubleSpinBox, QSpinBox,
                             QFormLayout, QSizePolicy)
from PyQt5.QtCore import (QPropertyAnimation, QEasingCurve, Qt, QTimer, 
                          QParallelAnimationGroup, QThread, pyqtSignal)
import pyqtgraph as pg
import pandas as pd
from datetime import datetime
from scipy.fft import fft, fftfreq
from scipy.signal import butter, filtfilt, iirnotch
import pickle
import matplotlib
matplotlib.use('Qt5Agg')  # Use Qt5 backend for PyQt5 integration
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# =====================================================================
# AI IMPORT - Import Keras model from AI.py
# =====================================================================
try:
    import tensorflow as tf
    from tensorflow import keras
    from sklearn.preprocessing import StandardScaler
    import joblib
    AI_AVAILABLE = True
    print("✅ TensorFlow/Keras available for AI model")
except ImportError as e:
    AI_AVAILABLE = False
    print(f"❌ TensorFlow/Keras not available: {e}")

# =====================================================================
# FILTER SETTINGS DIALOG - Separate window for filter configuration
# =====================================================================
class FilterSettingsDialog(QDialog):
    """Dialog window for configuring Notch and Bandpass filters."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter Settings")
        self.setFixedSize(400, 350)
        
        layout = QVBoxLayout(self)
        
        # Notch Filter Settings
        notch_group = QGroupBox("Notch Filter (Power Line Interference)")
        notch_layout = QFormLayout(notch_group)
        
        self.notch_enabled = QCheckBox("Enable Notch Filter")
        self.notch_enabled.setChecked(True)
        
        self.notch_freq = QDoubleSpinBox()
        self.notch_freq.setRange(10.0, 100.0)
        self.notch_freq.setValue(50.0)  # 50 Hz for power line interference
        self.notch_freq.setSuffix(" Hz")
        self.notch_freq.setSingleStep(1.0)
        
        self.notch_q = QDoubleSpinBox()
        self.notch_q.setRange(10.0, 100.0)
        self.notch_q.setValue(30.0)  # Quality factor
        self.notch_q.setSingleStep(5.0)
        
        notch_layout.addRow("Enable:", self.notch_enabled)
        notch_layout.addRow("Frequency:", self.notch_freq)
        notch_layout.addRow("Quality Factor (Q):", self.notch_q)
        
        # Bandpass Filter Settings
        bandpass_group = QGroupBox("Bandpass Filter (EMG Signals)")
        bandpass_layout = QFormLayout(bandpass_group)
        
        self.bandpass_enabled = QCheckBox("Enable Bandpass Filter")
        self.bandpass_enabled.setChecked(True)
        
        self.lowcut_freq = QDoubleSpinBox()
        self.lowcut_freq.setRange(10.0, 200.0)
        self.lowcut_freq.setValue(20.0)
        self.lowcut_freq.setSuffix(" Hz")
        self.lowcut_freq.setSingleStep(5.0)
        
        self.highcut_freq = QDoubleSpinBox()
        self.highcut_freq.setRange(50.0, 1000.0)
        self.highcut_freq.setValue(500.0)
        self.highcut_freq.setSuffix(" Hz")
        self.highcut_freq.setSingleStep(10.0)
        
        self.filter_order = QSpinBox()
        self.filter_order.setRange(2, 8)
        self.filter_order.setValue(4)
        
        bandpass_layout.addRow("Enable:", self.bandpass_enabled)
        bandpass_layout.addRow("Low Cutoff:", self.lowcut_freq)
        bandpass_layout.addRow("High Cutoff:", self.highcut_freq)
        bandpass_layout.addRow("Filter Order:", self.filter_order)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.reset_btn = QPushButton("Reset to Default")
        self.close_btn = QPushButton("Close")
        
        button_layout.addWidget(self.apply_btn)
        button_layout.addWidget(self.reset_btn)
        button_layout.addWidget(self.close_btn)
        
        # Add all to main layout
        layout.addWidget(notch_group)
        layout.addWidget(bandpass_group)
        layout.addLayout(button_layout)
        
        # Connect signals
        self.apply_btn.clicked.connect(self.apply_settings)
        self.reset_btn.clicked.connect(self.reset_to_default)
        self.close_btn.clicked.connect(self.close)
        
    def apply_settings(self):
        """Apply filter settings and close dialog."""
        self.accept()
        
    def reset_to_default(self):
        """Reset all settings to default values."""
        self.notch_enabled.setChecked(True)
        self.notch_freq.setValue(50.0)
        self.notch_q.setValue(30.0)
        
        self.bandpass_enabled.setChecked(True)
        self.lowcut_freq.setValue(20.0)
        self.highcut_freq.setValue(500.0)
        self.filter_order.setValue(4)
        
    def get_settings(self):
        """Get current filter settings as a dictionary."""
        return {
            'notch': {
                'enabled': self.notch_enabled.isChecked(),
                'frequency': self.notch_freq.value(),
                'q': self.notch_q.value()
            },
            'bandpass': {
                'enabled': self.bandpass_enabled.isChecked(),
                'lowcut': self.lowcut_freq.value(),
                'highcut': self.highcut_freq.value(),
                'order': self.filter_order.value()
            }
        }

# =====================================================================
# SERIAL READER THREAD - Reads data without blocking GUI
# =====================================================================
class SerialReaderThread(QThread):
    """
    Dedicated thread for continuous serial port reading.
    Updated for STM32 6-byte packet format (3 ch × 2 bytes, little endian).
    """
    
    data_received = pyqtSignal(list)  # Signal: batch of [adc0, adc1, adc2, timer]
    connection_status = pyqtSignal(bool, str)  # Signal: (connected: bool, message: str)
    
    def __init__(self, port, baudrate=115200):
        """
        Initialize serial reader thread.
        
        Args:
            port (str): COM port name (e.g., 'COM3')
            baudrate (int): Baud rate for serial communication
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.running = False
        self.retry_count = 0
        self.max_buffer_size = 1000
        
        # STM32 packet configuration - FIXED: 6 bytes total (2 bytes per channel)
        # STM32 sends: [ch0_low, ch0_high, ch1_low, ch1_high, ch2_low, ch2_high]
        self.PACKET_SIZE = 6  # Fixed: 6 bytes for 3 channels × 2 bytes each
        self.sample_time = 0.001  # 1ms sample time (adjust based on STM32 timer)
        self.current_time = 0.0
        
        # Buffer for packet synchronization
        self.rx_buffer = bytearray()
        self.packets_received = 0  # Counter for successful packets
        self.debug_mode = True  # Enable debug output
        
        # Batch buffering to reduce GUI overhead
        self.batch = []
        self.batch_size = 10  # Smaller batch size for faster updates
        
    def run(self):
        """
        Main thread execution loop.
        Continuously reads from serial port and emits data.
        """
        self.running = True
        
        while self.running:
            try:
                # Connect if not connected
                if self.ser is None or not self.ser.is_open:
                    if not self.connect_serial():
                        self.msleep(1000)  # Wait before retry
                        continue
                
                # Read data if available
                if self.ser and self.ser.is_open:
                    # Read available bytes
                    available = self.ser.in_waiting
                    if available > 0:
                        # Read all available bytes
                        new_data = self.ser.read(available)
                        self.rx_buffer.extend(new_data)
                        
                        # Try to find valid packet in buffer (fixed 6-byte, little endian)
                        while len(self.rx_buffer) >= self.PACKET_SIZE:
                            packet = self.rx_buffer[:self.PACKET_SIZE]
                            
                            # Debug: show first packet
                            if self.packets_received == 0 and self.debug_mode:
                                hex_data = ' '.join(f'{b:02X}' for b in packet)
                                print(f"First packet received: {hex_data}")
                            
                            try:
                                # Extract ADC values (little endian - STM32 default)
                                adc0_raw = (packet[1] << 8) | packet[0]   # Channel 0
                                adc1_raw = (packet[3] << 8) | packet[2]   # Channel 1
                                adc2_raw = (packet[5] << 8) | packet[4]   # Channel 2
                                
                                # Mask to 12 bits (STM32 ADC is 12-bit)
                                adc0 = adc0_raw & 0x0FFF
                                adc1 = adc1_raw & 0x0FFF
                                adc2 = adc2_raw & 0x0FFF
                                
                                # Validate ADC ranges (0-4095 for 12-bit ADC)
                                if self.validate_adc_data(adc0, adc1, adc2):
                                    self.current_time += self.sample_time
                                    
                                    # Debug output for first few packets
                                    if self.packets_received < 3 and self.debug_mode:
                                        print(f"Valid packet {self.packets_received + 1}: "
                                              f"ADC=[{adc0}, {adc1}, {adc2}]")
                                    
                                    # Append to batch; emit every batch_size samples
                                    self.batch.append([adc0, adc1, adc2, self.current_time])
                                    if len(self.batch) >= self.batch_size:
                                        self.data_received.emit(self.batch)
                                        self.batch = []
                                    
                                    self.rx_buffer = self.rx_buffer[self.PACKET_SIZE:]
                                    self.retry_count = 0
                                    self.packets_received += 1
                                    continue
                                else:
                                    print(f"Invalid ADC values: [{adc0}, {adc1}, {adc2}]")
                                    self.rx_buffer = self.rx_buffer[1:]  # Skip 1 byte
                                    self.retry_count += 1
                            except Exception as e:
                                print(f"Packet parsing error: {e}")
                                self.rx_buffer = self.rx_buffer[1:]  # Skip 1 byte
                                self.retry_count += 1
                            
                            # Check if we need to clear buffer (too many retries)
                            if self.retry_count > 100:
                                self.rx_buffer.clear()
                                self.retry_count = 0
                                print("Buffer cleared due to too many retries")
                                break
                
                # Small sleep to prevent CPU overuse
                self.msleep(1)  # 1ms delay for CPU efficiency
                
            except Exception as e:
                print(f"Serial thread error: {e}")
                self.connection_status.emit(False, str(e))
                if self.ser and self.ser.is_open:
                    self.ser.close()
                self.ser = None
                self.msleep(1000)  # Wait before retry
    
    def connect_serial(self):
        """
        Establish serial connection to the specified port.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.01,  # Short timeout for non-blocking read
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            print(f"✅ Serial connected to {self.port}")
            self.connection_status.emit(True, f"Connected to {self.port}")
            self.retry_count = 0
            return True
        except Exception as e:
            self.retry_count += 1
            if self.retry_count % 10 == 0:  # Print every 10 retries
                print(f"❌ Failed to connect to {self.port}: {e}")
            return False
    
    def validate_adc_data(self, adc0, adc1, adc2):
        """
        Validate ADC data ranges (12-bit ADC: 0-4095).
        
        Args:
            adc0, adc1, adc2: ADC values
            
        Returns:
            bool: True if data is within valid ranges
        """
        try:
            # ADC values typically 0-4095 for 12-bit ADC
            # Also reject if all zeros (might be sync issue)
            if not (0 <= adc0 <= 4095 and 0 <= adc1 <= 4095 and 0 <= adc2 <= 4095):
                return False
            
            # Reject if all zeros (probably bad data)
            if adc0 == 0 and adc1 == 0 and adc2 == 0:
                return False
                
            return True
        except:
            return False
    
    def stop(self):
        """
        Safely stop the serial reading thread.
        """
        self.running = False
        # Flush any remaining samples in batch before closing
        if self.batch:
            self.data_received.emit(self.batch)
            self.batch = []
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.wait(1000)  # Wait up to 1 second for thread to finish

# =====================================================================
# SIGNAL PROCESSOR - Filters and processes EMG signals
# =====================================================================
class SignalProcessor:
    """
    Handles signal filtering and processing for EMG signals.
    Implements Notch filter for power line interference and Bandpass filter for EMG.
    """
    
    def __init__(self, sampling_rate=1000.0):
        """
        Initialize signal processor.
        
        Args:
            sampling_rate: Sampling rate in Hz
        """
        self.sampling_rate = sampling_rate
        self.filtered_signals = {
            'ch1': [],
            'ch2': [], 
            'ch3': []
        }
        self.raw_signals = {
            'ch1': [],
            'ch2': [],
            'ch3': []
        }
        self.buffer_size = 1000  # Store last N samples
        
        # Default filter parameters
        self.notch_enabled = True
        self.notch_freq = 50.0    # Hz (power line frequency)
        self.notch_q = 30.0       # Quality factor
        
        self.bandpass_enabled = True
        self.lowcut = 20.0        # Hz
        self.highcut = 500.0      # Hz
        self.order = 4            # Filter order
        
        # Initialize filter coefficients
        self.init_filters()
        
    def init_filters(self):
        """Initialize Notch and Bandpass filter coefficients."""
        # Notch filter
        if self.notch_enabled:
            nyquist = 0.5 * self.sampling_rate
            # Ensure normalized frequency is < 1 (strictly less than Nyquist)
            notch_freq_norm = min(self.notch_freq / nyquist, 0.99)
            self.b_notch, self.a_notch = iirnotch(notch_freq_norm, self.notch_q)
        
        # Bandpass filter
        if self.bandpass_enabled:
            # Use fs parameter to pass frequencies in Hz directly
            # Ensure highcut is strictly less than Nyquist
            nyquist = 0.5 * self.sampling_rate
            highcut_safe = min(self.highcut, nyquist * 0.99)
            
            # Design Butterworth bandpass filter with fs parameter
            self.b_bandpass, self.a_bandpass = butter(
                self.order, 
                [self.lowcut, highcut_safe], 
                btype='band',
                fs=self.sampling_rate
            )
        
        print(f"✅ Filters initialized: Notch={self.notch_enabled} ({self.notch_freq}Hz), "
              f"Bandpass={self.bandpass_enabled} ({self.lowcut}-{self.highcut}Hz)")
    
    def update_filters(self, settings):
        """
        Update filter parameters.
        
        Args:
            settings: Dictionary with filter settings
        """
        self.notch_enabled = settings['notch']['enabled']
        self.notch_freq = settings['notch']['frequency']
        self.notch_q = settings['notch']['q']
        
        self.bandpass_enabled = settings['bandpass']['enabled']
        self.lowcut = settings['bandpass']['lowcut']
        self.highcut = settings['bandpass']['highcut']
        self.order = settings['bandpass']['order']
        
        # Reinitialize filters with new parameters
        self.init_filters()
    
    def apply_notch_filter(self, signal_channel):
        """
        Apply Notch filter to remove power line interference.
        
        Args:
            signal_channel: List of signal values
            
        Returns:
            list: Filtered signal
        """
        if not self.notch_enabled or len(signal_channel) < 10:
            return signal_channel
        
        try:
            signal_array = np.array(signal_channel, dtype=float)
            filtered = filtfilt(self.b_notch, self.a_notch, signal_array)
            return filtered.tolist()
        except:
            return signal_channel
    
    def apply_bandpass_filter(self, signal_channel):
        """
        Apply Bandpass filter for EMG frequency range.
        
        Args:
            signal_channel: List of signal values
            
        Returns:
            list: Filtered signal
        """
        if not self.bandpass_enabled or len(signal_channel) < self.order * 3:
            return signal_channel
        
        try:
            signal_array = np.array(signal_channel, dtype=float)
            filtered = filtfilt(self.b_bandpass, self.a_bandpass, signal_array)
            return filtered.tolist()
        except:
            return signal_channel
    
    def apply_all_filters(self, signal_channel):
        """
        Apply both Notch and Bandpass filters.
        
        Args:
            signal_channel: List of signal values
            
        Returns:
            list: Filtered signal
        """
        if len(signal_channel) < 10:
            return signal_channel
        
        filtered = signal_channel.copy()
        
        # Apply Notch filter
        if self.notch_enabled:
            filtered = self.apply_notch_filter(filtered)
        
        # Apply Bandpass filter
        if self.bandpass_enabled:
            filtered = self.apply_bandpass_filter(filtered)
        
        return filtered
    
    def add_sample(self, adc0, adc1, adc2):
        """
        Add new ADC samples and apply filtering.
        
        Args:
            adc0, adc1, adc2: Raw ADC values from STM32, 0-4095
        """
        # Store raw ADC signals directly
        self.raw_signals['ch1'].append(float(adc0))
        self.raw_signals['ch2'].append(float(adc1))
        self.raw_signals['ch3'].append(float(adc2))
        
        # Limit buffer size
        for ch in ['ch1', 'ch2', 'ch3']:
            if len(self.raw_signals[ch]) > self.buffer_size:
                self.raw_signals[ch] = self.raw_signals[ch][-self.buffer_size:]
        
        # Apply filtering when enough samples are available
        if len(self.raw_signals['ch1']) >= 50:  # Reduced from 100 for faster response
            self.filtered_signals['ch1'] = self.apply_all_filters(self.raw_signals['ch1'])
            self.filtered_signals['ch2'] = self.apply_all_filters(self.raw_signals['ch2'])
            self.filtered_signals['ch3'] = self.apply_all_filters(self.raw_signals['ch3'])
    
    def get_latest_filtered(self, channel='ch1', num_samples=200):
        """
        Get latest filtered samples.
        
        Args:
            channel: Channel name
            num_samples: Number of samples to return
            
        Returns:
            list: Latest filtered samples
        """
        if channel in self.filtered_signals and self.filtered_signals[channel]:
            return self.filtered_signals[channel][-num_samples:]
        return []
    
    def get_latest_raw(self, channel='ch1', num_samples=200):
        """
        Get latest raw samples.
        
        Args:
            channel: Channel name
            num_samples: Number of samples to return
            
        Returns:
            list: Latest raw samples
        """
        if channel in self.raw_signals and self.raw_signals[channel]:
            return self.raw_signals[channel][-num_samples:]
        return []

# =====================================================================
# FEATURE CALCULATOR THREAD - Calculates features in background
# =====================================================================
class FeatureCalculator(QThread):
    """
    Background thread for calculating EMG signal features.
    Uses filtered signals for feature extraction.
    """
    
    features_calculated = pyqtSignal(dict)
    
    def __init__(self, signal_processor):
        """Initialize feature calculator with window parameters."""
        super().__init__()
        self.signal_processor = signal_processor
        self.sampling_rate = 1000.0  # Assuming 1kHz sampling rate
        self.window_size = int(200 / 1000 * self.sampling_rate)  # 200ms window
        self.step_size = int(50 / 1000 * self.sampling_rate)     # 50ms step
        self.running = False
        
    def calculate_features(self, channel_data):
        """
        Calculate time and frequency domain features from EMG data.
        
        Args:
            channel_data: List of signal data for one channel
            
        Returns:
            dict: Calculated features for the channel
        """
        if len(channel_data) < 10:
            return {}
        
        # Convert to numpy array
        data_array = np.array(channel_data, dtype=float)
        
        features = {}
        
        # Time Domain Features
        mav = np.mean(np.abs(data_array))  # Mean Absolute Value
        rms = np.sqrt(np.mean(np.square(data_array)))  # Root Mean Square
        var_feat = np.var(data_array)  # Variance
        zc = np.sum(np.diff(np.sign(data_array)) != 0)  # Zero Crossing
        wl = np.sum(np.abs(np.diff(data_array)))  # Waveform Length
        
        # Slope Sign Change
        diff1 = np.diff(data_array)
        ssc = np.sum((diff1[:-1] * diff1[1:]) < 0)
        
        # Frequency Domain Features (if enough data)
        if len(data_array) > 10:
            n = len(data_array)
            fft_vals = fft(data_array)
            fft_freqs = fftfreq(n, 1/self.sampling_rate)
            
            # Positive frequencies only
            positive_freqs = fft_freqs[:n//2]
            positive_fft = np.abs(fft_vals[:n//2])
            
            if len(positive_freqs) > 0 and np.sum(positive_fft) > 0:
                # Mean Frequency
                mean_freq = np.sum(positive_freqs * positive_fft) / np.sum(positive_fft)
                
                # Median Frequency
                cumulative_sum = np.cumsum(positive_fft)
                if cumulative_sum[-1] > 0:
                    median_freq_idx = np.where(cumulative_sum >= cumulative_sum[-1]/2)[0]
                    median_freq = positive_freqs[median_freq_idx[0]] if len(median_freq_idx) > 0 else 0
                else:
                    median_freq = 0
                
                # Peak Frequency
                if len(positive_fft) > 0:
                    peak_freq_idx = np.argmax(positive_fft)
                    peak_freq = positive_freqs[peak_freq_idx]
                else:
                    peak_freq = 0
                
                # Power Calculations
                total_power = np.sum(positive_fft**2)
                band_mask = (positive_freqs >= 20) & (positive_freqs <= 500)
                band_power = np.sum(positive_fft[band_mask]**2) if np.any(band_mask) else 0
            else:
                mean_freq = median_freq = peak_freq = total_power = band_power = 0
        else:
            mean_freq = median_freq = peak_freq = total_power = band_power = 0
        
        # Store features
        features['MAV'] = float(mav)
        features['RMS'] = float(rms)
        features['VAR'] = float(var_feat)
        features['ZC'] = float(zc)
        features['SSC'] = float(ssc)
        features['WL'] = float(wl)
        features['meanFreq'] = float(mean_freq)
        features['medianFreq'] = float(median_freq)
        features['peakFreq'] = float(peak_freq)
        features['totalPower'] = float(total_power)
        features['bandPower'] = float(band_power)
        
        return features
    
    def run(self):
        """
        Main feature calculation loop.
        Calculates features from filtered signals every 200ms and saves them.
        """
        self.running = True
        while self.running:
            # Get latest filtered data (200ms window)
            ch1_data = self.signal_processor.get_latest_filtered('ch1', self.window_size)
            ch2_data = self.signal_processor.get_latest_filtered('ch2', self.window_size)
            ch3_data = self.signal_processor.get_latest_filtered('ch3', self.window_size)
            
            # Ensure we have enough data (at least 200 samples for 200ms at 1kHz)
            if len(ch1_data) >= self.window_size:
                features = {}
                
                # Calculate features for each channel from filtered signals
                for i, (channel_name, channel_data) in enumerate([
                    ('ch1', ch1_data), ('ch2', ch2_data), ('ch3', ch3_data)
                ]):
                    channel_features = self.calculate_features(channel_data)
                    for key, value in channel_features.items():
                        features[f'{channel_name}_{key}'] = value
                
                # Calculate average features across channels
                for feature_name in ['MAV', 'RMS', 'VAR', 'ZC', 'SSC', 'WL', 
                                    'meanFreq', 'medianFreq', 'peakFreq', 
                                    'totalPower', 'bandPower']:
                    values = []
                    for ch in ['ch1', 'ch2', 'ch3']:
                        key = f'{ch}_{feature_name}'
                        if key in features:
                            values.append(features[key])
                    if values:
                        features[f'avg_{feature_name}'] = float(np.mean(values))
                
                # Add metadata
                features['timestamp'] = datetime.now().isoformat()
                features['window_samples'] = len(ch1_data)
                features['window_duration_ms'] = 200.0  # 200ms window
                
                # Emit features if calculated (this will trigger automatic saving)
                if features:
                    self.features_calculated.emit(features)
            
            # Wait for next calculation period - 200ms interval
            self.msleep(200)  # Calculate features every 200ms
    
    def stop(self):
        """Stop the feature calculation thread."""
        self.running = False

# =====================================================================
# MATLAB CONNECTOR - TCP Communication with MATLAB
# =====================================================================
class MATLABConnector:
    """
    Handles TCP/IP communication with MATLAB for data streaming.
    Sends EMG and sensor data to MATLAB for additional processing.
    """
    
    def __init__(self):
        """Initialize MATLAB connector with default settings."""
        self.socket = None
        self.is_connected = False
        self.host = 'localhost'
        self.port = 12345
        
    def connect_to_matlab(self):
        """
        Establish TCP connection to MATLAB server.
        
        Returns:
            bool: True if connection successful
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.is_connected = True
            print("✅ Connected to MATLAB successfully")
            return True
        except Exception as e:
            print(f"❌ MATLAB Connection Error: {e}")
            self.is_connected = False
            return False
            
    def disconnect_matlab(self):
        """Close MATLAB connection."""
        if self.socket:
            self.socket.close()
            self.is_connected = False
            print("MATLAB Disconnected")
            
    def send_to_matlab(self, ch1_data, ch2_data, ch3_data, timer_data, sensor_data):
        """
        Send data packet to MATLAB via TCP.
        
        Args:
            ch1_data, ch2_data, ch3_data: EMG channel data
            timer_data: Timer values
            sensor_data: Accelerometer and gyroscope data
            
        Returns:
            bool: True if send successful
        """
        if not self.is_connected:
            return False
            
        try:
            # Create data packet
            data_packet = {
                'timestamp': datetime.now().isoformat(),
                'ch1': ch1_data[-100:],  # Last 100 points
                'ch2': ch2_data[-100:],
                'ch3': ch3_data[-100:],
                'timer': timer_data[-100:],
                'sensors': {
                    'accel_x': sensor_data[0],
                    'accel_y': sensor_data[1],
                    'accel_z': sensor_data[2],
                    'gyro_x': sensor_data[3],
                    'gyro_y': sensor_data[4],
                    'gyro_z': sensor_data[5]
                },
                'sampling_rate': 1000.0
            }
            
            # Send as JSON
            message = json.dumps(data_packet) + '\n'
            self.socket.send(message.encode())
            return True
        except Exception as e:
            print(f"MATLAB Send Error: {e}")
            self.is_connected = False
            return False

# =====================================================================
# SPLASH SCREEN - Application startup animation
# =====================================================================
class BioLinkSplash(QWidget):
    """
    Animated splash screen displayed during application startup.
    Provides visual feedback while main window loads.
    """
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        
        self.setupUI()
        self.setupAnimations()
        
    def setupUI(self):
        """Initialize splash screen UI components."""
        # Main container
        self.container = QFrame(self)
        self.container.setObjectName("splashContainer")
        self.container.setStyleSheet("""
            #splashContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0C0C0C, stop:0.5 #151515, stop:1 #0C0C0C);
                border-radius: 20px;
                border: 2px solid #00D4FF;
            }
        """)
        
        self.blur_effect = QGraphicsBlurEffect()
        self.blur_effect.setBlurRadius(0.0)
        self.container.setGraphicsEffect(self.blur_effect)

        layout = QVBoxLayout(self.container)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(30)
        
        # Title
        self.title_label = QLabel("BIO LINK")
        self.title_label.setObjectName("splashTitle")
        self.title_label.setStyleSheet("""
            #splashTitle {
                color: #00D4FF;
                font-size: 72px;
                font-weight: bold;
                font-family: 'Segoe UI';
            }
        """)
        self.title_label.setAlignment(Qt.AlignCenter)
        
        # Subtitle
        self.subtitle_label = QLabel("STM32 EMG + MATLAB System")
        self.subtitle_label.setObjectName("splashSubtitle")
        self.subtitle_label.setStyleSheet("""
            #splashSubtitle {
                color: #BFBFBF;
                font-size: 18px;
                font-weight: 300;
                font-family: 'Segoe UI';
            }
        """)
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        
        # Loading bar
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 100)
        self.loading_bar.setValue(0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(6)
        self.loading_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1A1A1A;
                border-radius: 3px;
                border: 1px solid #333;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #00FFC4);
                border-radius: 3px;
            }
        """)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.loading_bar)
        
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.container)
        main_layout.setAlignment(Qt.AlignCenter)
        
    def setupAnimations(self):
        """Configure splash screen animations."""
        # Fade in animation
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(800)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Loading bar animation
        self.loading_animation = QPropertyAnimation(self.loading_bar, b"value")
        self.loading_animation.setDuration(2500)
        self.loading_animation.setStartValue(0)
        self.loading_animation.setEndValue(100)
        self.loading_animation.setEasingCurve(QEasingCurve.InOutQuad)
        
    def startAnimations(self):
        """Start all splash screen animations."""
        self.fade_animation.start()
        self.loading_animation.start()
        self.startGlowAnimation()
        self.loading_animation.finished.connect(self.transitionToMainWindow)
        
    def startGlowAnimation(self):
        """Start border glow effect animation."""
        self.glow_timer = QTimer()
        self.glow_timer.timeout.connect(self.updateGlow)
        self.glow_timer.start(50)
        self.glow_phase = 0
        
    def updateGlow(self):
        """Update border glow intensity."""
        self.glow_phase += 0.1
        glow_intensity = (np.sin(self.glow_phase) + 1) * 0.3 + 0.4 
        new_style = f"""
            #splashContainer {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0C0C0C, stop:0.5 #151515, stop:1 #0C0C0C);
                border-radius: 20px;
                border: 2px solid rgba(0, 212, 255, {glow_intensity});
            }}
        """
        self.container.setStyleSheet(new_style)

    def transitionToMainWindow(self):
        """Transition from splash screen to main window."""
        self.glow_timer.stop() 
        self.anim_blur = QPropertyAnimation(self.blur_effect, b"blurRadius")
        self.anim_blur.setDuration(700)
        self.anim_blur.setStartValue(0.0)
        self.anim_blur.setEndValue(25.0)
        self.anim_blur.setEasingCurve(QEasingCurve.InCubic)

        self.anim_fade = QPropertyAnimation(self, b"windowOpacity")
        self.anim_fade.setDuration(700)
        self.anim_fade.setStartValue(1.0)
        self.anim_fade.setEndValue(0.0)
        self.anim_fade.setEasingCurve(QEasingCurve.InCubic)
        
        self.anim_group = QParallelAnimationGroup()
        self.anim_group.addAnimation(self.anim_blur)
        self.anim_group.addAnimation(self.anim_fade)
        
        self.anim_group.finished.connect(self.showMainWindow)
        self.anim_group.start(QPropertyAnimation.DeleteWhenStopped)
    
    def showMainWindow(self):
        """Show main window and close splash."""
        self.main_window.show() 
        self.main_window.activateWindow()
        self.main_window.raise_()
        self.close()

# =====================================================================
# CIRCULAR GAUGE WIDGET - Visual display for gyroscope data
# =====================================================================
class GaugeWidget(QtWidgets.QWidget):
    """
    Circular gauge widget for displaying gyroscope values.
    Includes checkbox for enabling/disabling individual axes.
    """
    
    def __init__(self, label="Gauge"):
        super().__init__()
        self.value = 0
        self.label = label
        self.is_active = True
        self.setMinimumSize(100, 120)
        
        # Add checkbox for control
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self.toggle_active)
        self.checkbox.setStyleSheet("""
            QCheckBox {
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)

    def setValue(self, v):
        """
        Set gauge value.
        
        Args:
            v: Value to display (degrees)
        """
        if self.is_active:
            try:
                self.value = float(v)
            except:
                self.value = 0
        else:
            self.value = 0
        self.update()

    def toggle_active(self, state):
        """
        Toggle gauge active state.
        
        Args:
            state: Checkbox state
        """
        self.is_active = (state == Qt.Checked)
        self.update()

    def paintEvent(self, event):
        """Paint gauge with current value."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(10,10,-10,-10)

        # Determine color based on state
        if self.is_active:
            gauge_color = QtGui.QColor("#00D4FF")
        else:
            gauge_color = QtGui.QColor("#666666")

        # Draw background
        grad = QtGui.QConicalGradient(rect.center(), -90)
        grad.setColorAt(0.0, QtGui.QColor("#181818"))
        grad.setColorAt(1.0, QtGui.QColor("#222222"))
        painter.setBrush(QtGui.QBrush(grad))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(rect)

        # Draw value arc
        pen = QtGui.QPen(gauge_color, 6)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(pen)
        
        angle = int((self.value % 360) * 16)
        start_angle = 90 * 16
        painter.drawArc(rect, start_angle, -angle)

        # Draw text
        painter.setPen(gauge_color if self.is_active else QtGui.QColor("#888888"))
        painter.setFont(QtGui.QFont("Segoe UI Semibold", 10))
        numeric_text = f"{int(self.value)}°"
        painter.drawText(self.rect().adjusted(0,20,0,-20), QtCore.Qt.AlignCenter, numeric_text)

        painter.setFont(QtGui.QFont("Segoe UI", 8))
        painter.setPen(gauge_color if self.is_active else QtGui.QColor("#888888"))
        painter.drawText(self.rect().adjusted(0,60,0,-4), QtCore.Qt.AlignCenter, self.label)
        
        # Draw checkbox
        checkbox_rect = QtCore.QRect(rect.left() + 5, rect.top() + 5, 20, 20)
        self.checkbox.setGeometry(checkbox_rect)
        
    def resizeEvent(self, event):
        """Handle widget resize."""
        super().resizeEvent(event)
        rect = self.rect().adjusted(10,10,-10,-10)
        checkbox_rect = QtCore.QRect(rect.left() + 5, rect.top() + 5, 20, 20)
        self.checkbox.setGeometry(checkbox_rect)

# =====================================================================
# AXIS BAR WIDGET - Progress bar for accelerometer data
# =====================================================================
class AxisBar(QtWidgets.QWidget):
    """
    Progress bar widget for displaying accelerometer axis values.
    Includes checkbox for enabling/disabling individual axes.
    """
    
    def __init__(self, label="Axis", value=0):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        self.base_label_text = label
        self.label = QtWidgets.QLabel(f"{label}: {value} g")
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 20)  # Range from 0 to 2g (10 units per g)
        self.bar.setValue(value * 10)  # Convert g to bar units
        
        # Add checkbox for control
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self.toggle_bar)
        
        top_layout = QHBoxLayout()
        top_layout.addWidget(self.label)
        top_layout.addWidget(self.checkbox)
        
        layout.addLayout(top_layout)
        layout.addWidget(self.bar)

        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.bar.setTextVisible(False)
        self.label.setObjectName("axisLabel")
        
        self.is_active = True

    def toggle_bar(self, state):
        """
        Toggle bar active state.
        
        Args:
            state: Checkbox state
        """
        self.is_active = (state == Qt.Checked)
        if not self.is_active:
            self.bar.setValue(0)
            self.label.setText(f"{self.base_label_text}: 0 g (Disabled)")

    def setValue(self, val):
        """
        Set bar value.
        
        Args:
            val: Value to display in g units
        """
        if self.is_active:
            try: 
                vi = float(val)
            except: 
                vi = 0
            
            # Convert g to bar units (0-2g maps to 0-20)
            display = max(0, min(20, int(abs(vi) * 10)))
            self.bar.setValue(display)
            self.label.setText(f"{self.base_label_text}: {vi:.2f} g")
        else:
            self.bar.setValue(0)

# =====================================================================
# SIGNAL PLOT WIDGET - Real-time EMG signal plotting
# =====================================================================
class SignalPlot(pg.PlotWidget):
    """
    PyQtGraph widget for real-time EMG signal visualization.
    Displays scrolling waveform with configurable buffer length.
    """
    
    def __init__(self, title, show_filtered=True):
        super().__init__()
        self.setTitle(title, color="#FFFFFF", size="11pt")
        self.showGrid(x=True, y=True, alpha=0.3)
        
        # Set background gradient
        gradient = QtGui.QLinearGradient(0, 0, 0, 1)
        gradient.setCoordinateMode(QtGui.QGradient.ObjectBoundingMode)
        gradient.setColorAt(0.0, QtGui.QColor(25, 25, 25)) 
        gradient.setColorAt(1.0, QtGui.QColor(12, 12, 12)) 
        brush = QtGui.QBrush(gradient)
        self.setBackground(brush)
        
        # Style axes
        self.getAxis("bottom").setPen(pg.mkPen(color="#666", width=1))
        self.getAxis("left").setPen(pg.mkPen(color="#666", width=1))
        
        # Set Y-axis range for 12-bit ADC (0-4095)
        self.setYRange(0, 4095, padding=0.1)
        self.setLabel('left', 'ADC Value', color='#FFFFFF')
        self.setLabel('bottom', 'Sample', color='#FFFFFF')

        # Create plot curves
        self.curve_raw = self.plot(pen=pg.mkPen("#00D4FF", width=1.5))
        self.curve_filtered = self.plot(pen=pg.mkPen("#FF00FF", width=1.5))
        
        self.buffer_len = 200  # Reduced for faster response
        self.data_raw = [0.0] * self.buffer_len
        self.data_filtered = [0.0] * self.buffer_len
        self.show_filtered = show_filtered
        
        # Hide filtered line initially if show_filtered is False
        if not self.show_filtered:
            self.curve_filtered.setData([], [], _callSync='off')

    def set_show_filtered(self, show):
        """
        Show or hide the filtered signal line.
        
        Args:
            show (bool): True to show filtered line, False to hide it
        """
        self.show_filtered = show
        if not show:
            # Clear the filtered line data to hide it
            self.curve_filtered.setData([], [], _callSync='off')

    def updateData(self, val_raw, val_filtered=None):
        """
        Update plot with new data value or batch of values.
        
        Args:
            val_raw: New raw ADC value(s) - can be single value or list (0-4095 for 12-bit ADC)
            val_filtered: New filtered value(s) - can be single value or list (optional)
        """
        try:
            # Handle batch updates for better performance
            if isinstance(val_raw, (list, np.ndarray)):
                # Batch update - append multiple values at once
                num_new = len(val_raw)
                if num_new > 0:
                    # Convert to float array
                    raw_vals = [float(v) if v is not None else 0.0 for v in val_raw]
                    # Keep buffer size constant, append new values
                    self.data_raw = self.data_raw[num_new:] + raw_vals
                else:
                    return
            elif val_raw is not None:
                # Single value update
                raw_val = float(val_raw)
                self.data_raw = self.data_raw[1:] + [raw_val]
            else:
                self.data_raw = self.data_raw[1:] + [0.0]
            
            # Handle filtered data
            if isinstance(val_filtered, (list, np.ndarray)):
                # Batch update for filtered
                num_new = len(val_filtered)
                if num_new > 0:
                    filtered_vals = [float(v) if v is not None else 0.0 for v in val_filtered]
                    self.data_filtered = self.data_filtered[num_new:] + filtered_vals
            elif val_filtered is not None:
                # Single filtered value
                filtered_val = float(val_filtered)
                self.data_filtered = self.data_filtered[1:] + [filtered_val]
            else:
                # If no filtered value, use raw value
                if isinstance(val_raw, (list, np.ndarray)):
                    # Use raw values for filtered if no filtered provided
                    self.data_filtered = self.data_raw.copy()
                elif val_raw is not None:
                    self.data_filtered = self.data_filtered[1:] + [float(val_raw)]
                else:
                    self.data_filtered = self.data_filtered[1:] + [0.0]
                
        except Exception as e:
            print(f"updateData error: {e}")
            self.data_raw = self.data_raw[1:] + [0.0]
            self.data_filtered = self.data_filtered[1:] + [0.0]
        
        # Update curves efficiently - only update if data changed
        self.curve_raw.setData(self.data_raw, _callSync='off')
        if self.show_filtered:
            self.curve_filtered.setData(self.data_filtered, _callSync='off')

# =====================================================================
# MATPLOTLIB PLOT WINDOW - Three-channel plotting with matplotlib
# =====================================================================
class MatplotlibPlotWindow(QWidget):
    """
    Separate window for three-channel plotting using matplotlib.
    Provides calibrated display with real-time updates.
    """
    
    def __init__(self, parent=None, signal_processor=None, main_window=None):
        super().__init__(parent)
        self.setWindowTitle("Three-Channel Signal Plot (Matplotlib)")
        self.setGeometry(100, 100, 1200, 800)
        
        self.signal_processor = signal_processor
        self.main_window = main_window  # Reference to main window to check if data is running
        self.is_running = False
        self.show_filtered = False  # Hide filtered lines by default
        
        # Create matplotlib figure with 3 subplots
        self.figure = Figure(figsize=(12, 8), facecolor='#1a1a1a')
        self.canvas = FigureCanvas(self.figure)
        self.figure.patch.set_facecolor('#1a1a1a')
        
        # Create 3 subplots (one for each channel)
        self.ax1 = self.figure.add_subplot(311)
        self.ax2 = self.figure.add_subplot(312)
        self.ax3 = self.figure.add_subplot(313)
        
        # Style the plots
        for ax in [self.ax1, self.ax2, self.ax3]:
            ax.set_facecolor('#0d0d0d')
            ax.grid(True, alpha=0.3, color='#666666')
            ax.spines['bottom'].set_color('#666666')
            ax.spines['top'].set_color('#666666')
            ax.spines['right'].set_color('#666666')
            ax.spines['left'].set_color('#666666')
            ax.tick_params(colors='#FFFFFF', labelsize=9)
            ax.set_ylim(0, 4095)  # ADC range
        
        # Set labels and titles
        self.ax1.set_title('Channel 1 - Raw Signal', color='#FFFFFF', fontsize=11, fontweight='bold')
        self.ax1.set_ylabel('ADC Value', color='#FFFFFF', fontsize=10)
        self.ax1.set_xlabel('Sample Index', color='#FFFFFF', fontsize=10)
        
        self.ax2.set_title('Channel 2 - Raw Signal', color='#FFFFFF', fontsize=11, fontweight='bold')
        self.ax2.set_ylabel('ADC Value', color='#FFFFFF', fontsize=10)
        self.ax2.set_xlabel('Sample Index', color='#FFFFFF', fontsize=10)
        
        self.ax3.set_title('Channel 3 - Raw Signal', color='#FFFFFF', fontsize=11, fontweight='bold')
        self.ax3.set_ylabel('ADC Value', color='#FFFFFF', fontsize=10)
        self.ax3.set_xlabel('Sample Index', color='#FFFFFF', fontsize=10)
        
        # Initialize plot lines
        self.line1, = self.ax1.plot([], [], color='#00D4FF', linewidth=1.5, label='Raw')
        self.line2, = self.ax2.plot([], [], color='#00FF88', linewidth=1.5, label='Raw')
        self.line3, = self.ax3.plot([], [], color='#FF6B00', linewidth=1.5, label='Raw')
        
        # Add filtered signal lines (initially hidden)
        self.line1_filt, = self.ax1.plot([], [], color='#FF00FF', linewidth=1.5, linestyle='--', label='Filtered', alpha=0.8, visible=False)
        self.line2_filt, = self.ax2.plot([], [], color='#FF00FF', linewidth=1.5, linestyle='--', label='Filtered', alpha=0.8, visible=False)
        self.line3_filt, = self.ax3.plot([], [], color='#FF00FF', linewidth=1.5, linestyle='--', label='Filtered', alpha=0.8, visible=False)
        
        # Add legends
        self.ax1.legend(loc='upper right', facecolor='#2a2a2a', edgecolor='#666666', labelcolor='#FFFFFF')
        self.ax2.legend(loc='upper right', facecolor='#2a2a2a', edgecolor='#666666', labelcolor='#FFFFFF')
        self.ax3.legend(loc='upper right', facecolor='#2a2a2a', edgecolor='#666666', labelcolor='#FFFFFF')
        
        # Adjust layout
        self.figure.tight_layout(pad=2.0)
        
        # Create layout
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(self.canvas)
        
        # Status label
        self.status_label = QLabel("Status: Waiting for serial data...")
        self.status_label.setStyleSheet("color: #FFAA00; font-size: 9pt; padding: 5px; font-weight: bold;")
        
        # Control buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Plotting")
        self.stop_btn = QPushButton("⏸ Stop Plotting")
        self.clear_btn = QPushButton("Clear Data")
        
        self.start_btn.clicked.connect(self.start_plotting)
        self.stop_btn.clicked.connect(self.stop_plotting)
        self.clear_btn.clicked.connect(self.clear_data)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.clear_btn)
        
        layout.addWidget(self.status_label)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # Update timer for real-time plotting
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_plots)
        self.update_interval_ms = 50  # 20 Hz update rate for smooth plotting
        
        # Apply dark theme styling
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 10pt;
                color: #FFFFFF;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border: 1px solid #00D4FF;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
        """)
    
    def start_plotting(self):
        """Start real-time plotting."""
        self.is_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.update_timer.start(self.update_interval_ms)
        print("Matplotlib plotting started")
    
    def stop_plotting(self):
        """Stop real-time plotting."""
        self.is_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.update_timer.stop()
        print("Matplotlib plotting stopped")
    
    def set_show_filtered(self, show):
        """
        Show or hide the filtered signal lines.
        
        Args:
            show (bool): True to show filtered lines, False to hide them
        """
        self.show_filtered = show
        if not show:
            # Hide filtered lines
            self.line1_filt.set_visible(False)
            self.line2_filt.set_visible(False)
            self.line3_filt.set_visible(False)
            self.canvas.draw_idle()
    
    def clear_data(self):
        """Clear all plot data."""
        # Update plot lines with empty data
        self.line1.set_data([], [])
        self.line2.set_data([], [])
        self.line3.set_data([], [])
        self.line1_filt.set_data([], [])
        self.line2_filt.set_data([], [])
        self.line3_filt.set_data([], [])
        self.canvas.draw_idle()
        print("Plot data cleared")
    
    def update_plots(self):
        """Update the three-channel plots with latest data."""
        # Check if main window is running and has data (connected to serial)
        if self.main_window and not self.main_window.is_running:
            self.status_label.setText("Status: ⚠️ Serial not running - Start data acquisition first")
            self.status_label.setStyleSheet("color: #FFAA00; font-size: 9pt; padding: 5px; font-weight: bold;")
            return
        
        # Check if this window's plotting is enabled
        if not self.is_running or not self.signal_processor:
            self.status_label.setText("Status: ⏸ Plotting paused - Click 'Start Plotting'")
            self.status_label.setStyleSheet("color: #FFAA00; font-size: 9pt; padding: 5px; font-weight: bold;")
            return
        
        try:
            # Check if we have data from serial input
            if 'ch1' not in self.signal_processor.raw_signals or len(self.signal_processor.raw_signals['ch1']) == 0:
                return
            
            # Get latest data from signal processor
            window_size = min(200, len(self.signal_processor.raw_signals['ch1']))
            if window_size > 0:
                # Get raw signals
                raw_ch1 = self.signal_processor.get_latest_raw('ch1', window_size)
                raw_ch2 = self.signal_processor.get_latest_raw('ch2', window_size)
                raw_ch3 = self.signal_processor.get_latest_raw('ch3', window_size)
                
                # Ensure we have valid data
                if not raw_ch1 or len(raw_ch1) == 0:
                    return
                
                # Get filtered signals
                filtered_ch1 = self.signal_processor.get_latest_filtered('ch1', window_size)
                filtered_ch2 = self.signal_processor.get_latest_filtered('ch2', window_size)
                filtered_ch3 = self.signal_processor.get_latest_filtered('ch3', window_size)
                
                # Create time axis
                time_axis = list(range(len(raw_ch1)))
                
                # Update plot data
                self.line1.set_data(time_axis, raw_ch1)
                self.line2.set_data(time_axis, raw_ch2)
                self.line3.set_data(time_axis, raw_ch3)
                
                # Update filtered lines - only if lengths match and show_filtered is True
                if self.show_filtered:
                    if filtered_ch1 and len(filtered_ch1) == len(raw_ch1):
                        self.line1_filt.set_data(time_axis, filtered_ch1)
                        self.line1_filt.set_visible(True)
                    if filtered_ch2 and len(filtered_ch2) == len(raw_ch2):
                        self.line2_filt.set_data(time_axis, filtered_ch2)
                        self.line2_filt.set_visible(True)
                    if filtered_ch3 and len(filtered_ch3) == len(raw_ch3):
                        self.line3_filt.set_data(time_axis, filtered_ch3)
                        self.line3_filt.set_visible(True)
                else:
                    # Hide filtered lines
                    self.line1_filt.set_visible(False)
                    self.line2_filt.set_visible(False)
                    self.line3_filt.set_visible(False)
                
                # Update axis limits for better visualization
                for ax in [self.ax1, self.ax2, self.ax3]:
                    if len(time_axis) > 0:
                        ax.set_xlim(0, max(time_axis) if max(time_axis) > 0 else 100)
                    ax.set_ylim(0, 4095)
                
                # Update status to show connection
                self.status_label.setText("Status: ✅ Connected to serial - Plotting active")
                self.status_label.setStyleSheet("color: #00FF00; font-size: 9pt; padding: 5px; font-weight: bold;")
                
                # Redraw canvas efficiently
                self.canvas.draw_idle()
            else:
                self.status_label.setText("Status: ⚠️ No data available yet")
                self.status_label.setStyleSheet("color: #FFAA00; font-size: 9pt; padding: 5px; font-weight: bold;")
                
        except Exception as e:
            print(f"Matplotlib plot update error: {e}")
            self.status_label.setText(f"Status: ❌ Error: {str(e)}")
            self.status_label.setStyleSheet("color: #FF4444; font-size: 9pt; padding: 5px; font-weight: bold;")
    
    def closeEvent(self, event):
        """Handle window close event."""
        self.stop_plotting()
        # Reset button text in main window if it exists
        if self.main_window and hasattr(self.main_window, 'matplotlib_plot_btn'):
            self.main_window.matplotlib_plot_btn.setText("📊 Open Matplotlib Plot Window")
            self.main_window.matplotlib_window = None
        event.accept()

# =====================================================================
# KERAS AI MODEL - Using TensorFlow/Keras model for gesture recognition
# =====================================================================
class KerasAIModel:
    """
    Keras AI model for EMG gesture recognition.
    Automatically loads model and scaler from files in the same folder.
    """
    
    def __init__(self):
        self.model = None
        self.scaler = None
        self.is_loaded = False
        self.class_names = {0: "Movement 1 - Hand Grip", 
                           1: "Movement 2 - Finger Extension",
                           2: "Movement 3 - Wrist Lift",
                           3: "Movement 4 - Wrist Lower",
                           4: "Movement 5 - Internal Rotation",
                           5: "Movement 6 - External Rotation",
                           6: "Movement 7 - Relaxation"}
        
    def load_model_from_folder(self):
        """
        Automatically load Keras model and scaler from files in the same folder.
        Looks for: emg_model.keras, emg_scaler.pkl
        
        Returns:
            bool: True if both model and scaler loaded successfully
        """
        try:
            if not AI_AVAILABLE:
                print("❌ TensorFlow/Keras not available")
                return False
            
            # Check for model and scaler files
            model_file = "emg_model.keras"
            scaler_file = "emg_scaler.pkl"
            
            if not os.path.exists(model_file):
                print(f"❌ Model file not found: {model_file}")
                return False
            
            if not os.path.exists(scaler_file):
                print(f"❌ Scaler file not found: {scaler_file}")
                return False
            
            # Load Keras model
            print(f"Loading Keras model from: {model_file}")
            self.model = tf.keras.models.load_model(model_file)
            print(f"✅ Model loaded successfully: {self.model.summary()}")
            
            # Load scaler
            print(f"Loading scaler from: {scaler_file}")
            self.scaler = joblib.load(scaler_file)
            print("✅ Scaler loaded successfully")
            
            self.is_loaded = True
            return True
            
        except Exception as e:
            print(f"❌ Error loading model: {e}")
            import traceback
            traceback.print_exc()
            self.is_loaded = False
            return False
    
    def prepare_features(self, features_dict):
        """
        Prepare features from dictionary to match model input format.
        
        Args:
            features_dict: Dictionary of calculated features
            
        Returns:
            numpy array: Prepared features for model prediction
        """
        if not features_dict:
            return None
        
        # Define expected feature order (33 features as in AI.py)
        # This should match the training data format
        expected_features = [
            'ch1_MAV', 'ch1_RMS', 'ch1_VAR', 'ch1_ZC', 'ch1_SSC', 'ch1_WL',
            'ch1_meanFreq', 'ch1_medianFreq', 'ch1_peakFreq', 'ch1_totalPower', 'ch1_bandPower',
            'ch2_MAV', 'ch2_RMS', 'ch2_VAR', 'ch2_ZC', 'ch2_SSC', 'ch2_WL',
            'ch2_meanFreq', 'ch2_medianFreq', 'ch2_peakFreq', 'ch2_totalPower', 'ch2_bandPower',
            'ch3_MAV', 'ch3_RMS', 'ch3_VAR', 'ch3_ZC', 'ch3_SSC', 'ch3_WL',
            'ch3_meanFreq', 'ch3_medianFreq', 'ch3_peakFreq', 'ch3_totalPower', 'ch3_bandPower'
        ]
        
        # Try to extract features in the expected order
        feature_vector = []
        for feature_name in expected_features:
            if feature_name in features_dict:
                feature_vector.append(float(features_dict[feature_name]))
            else:
                # Try to find similar feature names
                found = False
                for key in features_dict.keys():
                    if feature_name.replace('ch1_', '').replace('ch2_', '').replace('ch3_', '') in key:
                        feature_vector.append(float(features_dict[key]))
                        found = True
                        break
                if not found:
                    # Use average value or zero
                    feature_vector.append(0.0)
        
        return np.array(feature_vector).reshape(1, -1)
    
    def predict(self, features):
        """
        Predict gesture using Keras model.
        
        Args:
            features: Dictionary of calculated features or numpy array
            
        Returns:
            tuple: (prediction_label, confidence, prediction_index)
        """
        if not self.is_loaded or self.model is None or self.scaler is None:
            return None, 0, -1
        
        try:
            # Prepare features
            if isinstance(features, dict):
                features_array = self.prepare_features(features)
            elif isinstance(features, np.ndarray):
                features_array = features.reshape(1, -1)
            else:
                print("Invalid features format")
                return None, 0, -1
            
            if features_array is None or features_array.size == 0:
                return None, 0, -1
            
            # Scale features using the same scaler used in training
            features_scaled = self.scaler.transform(features_array)
            
            # Make prediction
            predictions = self.model.predict(features_scaled, verbose=0)
            prediction_idx = np.argmax(predictions[0])
            confidence = float(predictions[0][prediction_idx]) * 100
            
            # Get prediction label
            if prediction_idx in self.class_names:
                prediction_label = self.class_names[prediction_idx]
            else:
                prediction_label = f"Movement {prediction_idx + 1}"
            
            return prediction_label, confidence, prediction_idx
            
        except Exception as e:
            print(f"Prediction error: {e}")
            import traceback
            traceback.print_exc()
            return None, 0, -1

# =====================================================================
# AI TRAINING PANEL - Interface for model training and testing
# =====================================================================
class AITrainingPanel(QGroupBox):
    """
    Panel for AI model training and testing.
    Provides interface for recording training data and real-time testing.
    """
    
    def __init__(self, main_window):
        super().__init__("AI Training & Testing Panel")
        self.main_window = main_window
        
        # Initialize Keras AI model
        self.ai_model = KerasAIModel()
        
        # Try to automatically load model on startup
        if AI_AVAILABLE:
            self.auto_load_model()
        else:
            print("⚠️ AI features disabled - TensorFlow not available")
        
        # Training data storage
        self.training_features = []  # List of features for training
        self.training_labels = []    # List of labels for training
        self.recorded_features = []  # Temporary storage for features during recording
        self.recorded_samples = 0
        self.is_recording = False
        
        # Test mode storage
        self.is_testing = False
        
        layout = QVBoxLayout(self)
        
        # Create tabs
        tabs = QTabWidget()
        self.train_tab = QWidget()
        self.test_tab = QWidget()
        
        tabs.addTab(self.train_tab, "Training Mode")
        tabs.addTab(self.test_tab, "Test Mode")
        tabs.setObjectName("aiTabs")
        
        # Setup tabs
        self.setup_training_tab()
        self.setup_test_tab()
        
        layout.addWidget(tabs)
    
    def auto_load_model(self):
        """Automatically load model on startup."""
        if self.ai_model.load_model_from_folder():
            print("✅ AI model loaded automatically from folder")
        else:
            print("⚠️ Could not auto-load AI model")
    
    def setup_training_tab(self):
        """Setup training interface with movement selection and recording."""
        train_layout = QVBoxLayout(self.train_tab)
        train_layout.setSpacing(15)
        
        # Movement selection
        movement_box = QGroupBox("Training Movement")
        movement_lay = QVBoxLayout(movement_box)
        
        movement_row = QHBoxLayout()
        movement_row.addWidget(QLabel("Select Movement:"))
        
        self.movement_combo = QComboBox()
        self.movement_combo.addItems([
            "Movement 1 - Hand Grip",
            "Movement 2 - Finger Extension", 
            "Movement 3 - Wrist Lift",
            "Movement 4 - Wrist Lower",
            "Movement 5 - Internal Rotation",
            "Movement 6 - External Rotation",
            "Movement 7 - Relaxation"
        ])
        
        self.add_movement_btn = QPushButton("Add New Movement")
        self.add_movement_btn.clicked.connect(self.add_new_movement)
        
        movement_row.addWidget(self.movement_combo, 2)
        movement_row.addWidget(self.add_movement_btn, 1)
        movement_lay.addLayout(movement_row)
        
        # Movement description
        self.movement_desc = QLineEdit()
        self.movement_desc.setPlaceholderText("Movement description (optional)")
        movement_lay.addWidget(QLabel("Movement Description:"))
        movement_lay.addWidget(self.movement_desc)
        
        train_layout.addWidget(movement_box)
        
        # Data recording
        record_box = QGroupBox("Training Data Recording")
        record_lay = QVBoxLayout(record_box)
        
        info_label = QLabel("Filtered signals (Notch + Bandpass) used for feature calculation")
        info_label.setStyleSheet("color: #00D4FF; font-weight: bold; padding: 5px;")
        record_lay.addWidget(info_label)
        
        # Recording controls
        btn_layout = QHBoxLayout()
        self.start_record_btn = QPushButton("▶ Start Recording")
        self.stop_record_btn = QPushButton("⏹ Stop Recording")
        self.stop_record_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_record_btn)
        btn_layout.addWidget(self.stop_record_btn)
        record_lay.addLayout(btn_layout)
        
        # Sample counter
        self.sample_counter = QLabel("Recorded Samples: 0")
        record_lay.addWidget(self.sample_counter)
        
        train_layout.addWidget(record_box)
        
        # Features display
        features_box = QGroupBox("Automatically Calculated Features")
        features_lay = QVBoxLayout(features_box)
        
        self.features_display = QTextEdit()
        self.features_display.setReadOnly(True)
        self.features_display.setMaximumHeight(150)
        self.features_display.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A;
                color: #00FFC4;
                font-family: 'Consolas';
                font-size: 9pt;
                border: 1px solid #333;
                border-radius: 5px;
            }
        """)
        features_lay.addWidget(self.features_display)
        
        # Add features button
        self.add_features_btn = QPushButton("➕ Add Features for Training")
        self.add_features_btn.setEnabled(False)
        features_lay.addWidget(self.add_features_btn, 0, Qt.AlignRight)
        
        train_layout.addWidget(features_box)
        
        # Training log
        log_box = QGroupBox("Training Data Log")
        log_lay = QVBoxLayout(log_box)
        
        self.training_log = QListWidget()
        self.training_log.setMaximumHeight(100)
        log_lay.addWidget(self.training_log)
        
        # Data management
        manage_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("Clear Log")
        self.export_train_btn = QPushButton("Export Training Data")
        self.export_ai_btn = QPushButton("📤 Export AI Training Data")
        
        manage_layout.addWidget(self.clear_log_btn)
        manage_layout.addWidget(self.export_train_btn)
        manage_layout.addWidget(self.export_ai_btn)
        log_lay.addLayout(manage_layout)
        
        train_layout.addWidget(log_box)
        
        # Connect signals
        self.start_record_btn.clicked.connect(self.start_training_recording)
        self.stop_record_btn.clicked.connect(self.stop_training_recording)
        self.add_features_btn.clicked.connect(self.add_features_to_training)
        self.clear_log_btn.clicked.connect(self.clear_training_log)
        self.export_train_btn.clicked.connect(self.export_training_data)
        self.export_ai_btn.clicked.connect(self.export_ai_training_data)
        
    def setup_test_tab(self):
        """Setup testing interface with automatic model loading and real-time recognition."""
        test_layout = QVBoxLayout(self.test_tab)
        test_layout.setSpacing(15)
        
        # Model status
        model_status_box = QGroupBox("AI Model Status")
        model_status_lay = QVBoxLayout(model_status_box)
        
        self.model_status = QLabel("Model Status: Checking...")
        self.model_status.setStyleSheet("color: #FFAA00; font-weight: bold;")
        
        # Auto-load button
        self.auto_load_btn = QPushButton("🔄 Auto-Load Model")
        self.auto_load_btn.clicked.connect(self.auto_load_model_manual)
        
        model_status_lay.addWidget(self.model_status)
        model_status_lay.addWidget(self.auto_load_btn)
        
        test_layout.addWidget(model_status_box)
        
        # Test info
        info_box = QGroupBox("AI Test Mode")
        info_lay = QVBoxLayout(info_box)
        
        info_label = QLabel("In test mode, filtered signals are analyzed in real-time using Keras AI model.\n"
                           "Model files (emg_model.keras and emg_scaler.pkl) must be in the same folder.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #00FFC4; padding: 10px;")
        info_lay.addWidget(info_label)
        
        test_layout.addWidget(info_box)
        
        # Control buttons
        control_box = QGroupBox("Test Control")
        control_lay = QVBoxLayout(control_box)
        
        # Test start/stop buttons
        test_btn_layout = QHBoxLayout()
        self.start_test_btn = QPushButton("▶ Start Testing")
        self.stop_test_btn = QPushButton("⏹ Stop Testing")
        self.stop_test_btn.setEnabled(False)
        
        test_btn_layout.addWidget(self.start_test_btn)
        test_btn_layout.addWidget(self.stop_test_btn)
        control_lay.addLayout(test_btn_layout)
        
        test_layout.addWidget(control_box)
        
        # Results display
        result_box = QGroupBox("AI Recognition Results")
        result_lay = QVBoxLayout(result_box)
        
        self.prediction_label = QLabel("Recognized Movement: ---")
        self.prediction_label.setStyleSheet("""
            QLabel {
                font-size: 20pt;
                font-weight: bold;
                color: #00D4FF;
                padding: 15px;
                border: 2px solid #00D4FF;
                border-radius: 10px;
                background-color: rgba(0, 212, 255, 0.1);
                text-align: center;
            }
        """)
        self.prediction_label.setAlignment(Qt.AlignCenter)
        result_lay.addWidget(self.prediction_label)
        
        # Confidence display
        self.confidence_label = QLabel("Confidence: ---")
        self.confidence_label.setStyleSheet("""
            QLabel {
                font-size: 14pt;
                font-weight: bold;
                color: #00FFC4;
                padding: 10px;
                text-align: center;
            }
        """)
        self.confidence_label.setAlignment(Qt.AlignCenter)
        result_lay.addWidget(self.confidence_label)
        
        # Features details
        self.test_features_display = QTextEdit()
        self.test_features_display.setReadOnly(True)
        self.test_features_display.setMaximumHeight(120)
        self.test_features_display.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A;
                color: #00FFC4;
                font-family: 'Consolas';
                font-size: 9pt;
                border: 1px solid #333;
                border-radius: 5px;
            }
        """)
        result_lay.addWidget(QLabel("Calculated Features:"))
        result_lay.addWidget(self.test_features_display)
        
        test_layout.addWidget(result_box)
        
        # Test log
        test_log_box = QGroupBox("Test Log")
        test_log_lay = QVBoxLayout(test_log_box)
        
        self.test_log = QListWidget()
        self.test_log.setMaximumHeight(100)
        test_log_lay.addWidget(self.test_log)
        
        # Clear log button
        self.clear_test_log_btn = QPushButton("Clear Test Log")
        test_log_lay.addWidget(self.clear_test_log_btn)
        
        test_layout.addWidget(test_log_box)
        
        # Connect signals
        self.start_test_btn.clicked.connect(self.start_test_mode)
        self.stop_test_btn.clicked.connect(self.stop_test_mode)
        self.clear_test_log_btn.clicked.connect(self.clear_test_log)
        
        # Update model status
        self.update_model_status()
    
    # =====================================================================
    # MODEL MANAGEMENT METHODS
    # =====================================================================
    
    def auto_load_model_manual(self):
        """Manually trigger model auto-loading."""
        if not AI_AVAILABLE:
            QMessageBox.warning(self, "AI Not Available", 
                              "TensorFlow/Keras is not available.\n"
                              "Please install: pip install tensorflow")
            return
        
        if self.ai_model.load_model_from_folder():
            self.update_model_status()
            QMessageBox.information(self, "Model Loaded", 
                                  "✅ AI model loaded successfully!\n\n"
                                  "Model: emg_model.keras\n"
                                  "Scaler: emg_scaler.pkl")
        else:
            QMessageBox.warning(self, "Load Failed", 
                              "❌ Could not load AI model.\n\n"
                              "Required files:\n"
                              "1. emg_model.keras (Keras model)\n"
                              "2. emg_scaler.pkl (Scaler)\n\n"
                              "Make sure both files are in the same folder as the application.")
    
    def update_model_status(self):
        """Update model status display."""
        if self.ai_model.is_loaded:
            self.model_status.setText("Model Status: ✅ Loaded (Keras)")
            self.model_status.setStyleSheet("color: #00FF00; font-weight: bold;")
            self.start_test_btn.setEnabled(True)
        else:
            self.model_status.setText("Model Status: ❌ Not Loaded")
            self.model_status.setStyleSheet("color: #FF4444; font-weight: bold;")
            self.start_test_btn.setEnabled(False)
    
    # =====================================================================
    # TRAINING METHODS
    # =====================================================================
    
    def add_new_movement(self):
        """Add a new movement type to the list."""
        movement_name, ok = QInputDialog.getText(
            self, "Add New Movement", "Enter movement name:"
        )
        
        if ok and movement_name:
            # Add to combo box
            self.movement_combo.addItem(f"Custom - {movement_name}")
            # Select the new movement
            self.movement_combo.setCurrentIndex(self.movement_combo.count() - 1)
            QMessageBox.information(self, "Movement Added", 
                                   f"Added new movement: {movement_name}")
    
    def start_training_recording(self):
        """Start recording training data."""
        if not self.main_window.is_running:
            QMessageBox.warning(self, "Not Running", 
                              "Please start data acquisition first!")
            return
        
        # Clear previous recorded features
        self.recorded_features = []
        self.recorded_samples = 0
        
        # Get selected movement label
        selected_text = self.movement_combo.currentText()
        # Extract just the movement name
        if " - " in selected_text:
            movement_label = selected_text.split(" - ")[1]
        else:
            movement_label = selected_text
        
        # Start recording
        self.is_recording = True
        
        # Enable feature calculation
        self.add_features_btn.setEnabled(True)
        
        # Update UI
        self.start_record_btn.setEnabled(False)
        self.stop_record_btn.setEnabled(True)
        self.sample_counter.setText(f"Recording: {movement_label}")
        
        print(f"Started recording for movement: {movement_label}")
    
    def stop_training_recording(self):
        """Stop recording training data."""
        self.is_recording = False
        self.start_record_btn.setEnabled(True)
        self.stop_record_btn.setEnabled(False)
        
        if self.recorded_samples > 0:
            self.sample_counter.setText(f"Recorded Samples: {self.recorded_samples}")
        else:
            self.sample_counter.setText(f"Recorded Samples: 0")
        
        print(f"Stopped recording. Total samples: {self.recorded_samples}")
    
    def update_features_display(self, features):
        """Update features display and store features if recording."""
        if not features:
            return
        
        # Display features
        features_text = ""
        for key, value in features.items():
            if key not in ['timestamp', 'window_samples']:
                features_text += f"{key}: {value:.3f}\n"
        
        self.features_display.setText(features_text)
        
        # Store features if recording
        if self.is_recording:
            # Create a copy of features
            features_copy = features.copy()
            
            # Get movement label
            selected_text = self.movement_combo.currentText()
            if " - " in selected_text:
                movement_label = selected_text.split(" - ")[1]
            else:
                movement_label = selected_text
            
            # Add movement label to features
            features_copy['movement_label'] = movement_label
            
            # Store features
            self.recorded_features.append(features_copy)
            self.recorded_samples += 1
            
            # Update counter
            self.sample_counter.setText(f"Recording: {movement_label} - Samples: {self.recorded_samples}")
    
    def add_features_to_training(self):
        """Add recorded features to training dataset."""
        if not self.recorded_features:
            QMessageBox.warning(self, "No Features", "No features recorded yet. Start recording first!")
            return
        
        # Get movement label
        selected_text = self.movement_combo.currentText()
        if " - " in selected_text:
            movement_label = selected_text.split(" - ")[1]
        else:
            movement_label = selected_text
        
        # Add all recorded features to training data
        for features in self.recorded_features:
            # Remove movement_label from features before adding to training
            features_copy = features.copy()
            if 'movement_label' in features_copy:
                del features_copy['movement_label']
            
            self.training_features.append(features_copy)
            self.training_labels.append(movement_label)
        
        # Update log
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_item = f"[{timestamp}] {movement_label}: {len(self.recorded_features)} feature sets added"
        self.training_log.addItem(log_item)
        
        # Scroll to bottom
        self.training_log.scrollToBottom()
        
        # Clear recorded features for next recording
        self.recorded_features = []
        self.recorded_samples = 0
        
        # Update UI
        self.add_features_btn.setEnabled(False)
        self.sample_counter.setText(f"Added {len(self.training_labels)} samples total")
        
        print(f"Added {len(self.recorded_features)} feature sets to training for {movement_label}")
    
    def clear_training_log(self):
        """Clear training log and data."""
        reply = QMessageBox.question(
            self, "Clear Log", 
            "Are you sure you want to clear all training data?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.training_log.clear()
            self.training_features = []
            self.training_labels = []
            self.recorded_features = []
            self.recorded_samples = 0
            self.sample_counter.setText("Recorded Samples: 0")
            print("Training data cleared")
    
    def export_training_data(self):
        """Export training data to CSV file."""
        if not self.training_features:
            QMessageBox.warning(self, "No Data", "No training data to export")
            return
        
        try:
            # Create DataFrame
            data = []
            for features, label in zip(self.training_features, self.training_labels):
                row = features.copy()
                row['label'] = label
                data.append(row)
            
            df = pd.DataFrame(data)
            
            # Get save filename
            default_name = f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            file, _ = QFileDialog.getSaveFileName(
                self, "Save Training Data", default_name, "CSV (*.csv)"
            )
            
            if file:
                df.to_csv(file, index=False)
                QMessageBox.information(self, "Exported", 
                                      f"Training data exported to:\n{file}")
                print(f"Training data exported to {file}")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export data:\n{str(e)}")
    
    def export_ai_training_data(self):
        """Export AI training data with movement number to Excel."""
        if not self.training_features:
            QMessageBox.warning(self, "No Data", "No AI training data to export")
            return
        
        try:
            # Create DataFrame with movement numbers
            data = []
            movement_counter = {}
            
            for features, label in zip(self.training_features, self.training_labels):
                row = features.copy()
                row['movement_label'] = label
                
                # Add movement number
                if label not in movement_counter:
                    movement_counter[label] = 1
                else:
                    movement_counter[label] += 1
                
                # Extract movement number from label if it contains a number
                import re
                match = re.search(r'(\d+)', label)
                if match:
                    movement_number = int(match.group(1))
                else:
                    # Assign a number based on order in dictionary
                    movement_number = list(movement_counter.keys()).index(label) + 1
                
                row['movement_number'] = movement_number
                row['sample_number'] = movement_counter[label]
                
                data.append(row)
            
            df = pd.DataFrame(data)
            
            # Reorder columns to have movement info first
            cols = ['movement_number', 'movement_label', 'sample_number', 'timestamp']
            other_cols = [c for c in df.columns if c not in cols]
            df = df[cols + other_cols]
            
            # Get save filename
            default_name = f"ai_training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            file, _ = QFileDialog.getSaveFileName(
                self, "Export AI Training Data", default_name, 
                "Excel (*.xlsx);;CSV (*.csv)"
            )
            
            if not file:
                return
            
            # Save based on file extension
            if file.endswith('.csv'):
                df.to_csv(file, index=False)
            else:
                df.to_excel(file, index=False, engine='openpyxl')
            
            QMessageBox.information(
                self, "Exported", 
                f"✅ Exported {len(self.training_features)} AI training samples to:\n{file}\n\n"
                f"Movement numbers added for each sample."
            )
            print(f"✅ Exported {len(self.training_features)} AI training samples to {file}")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export AI training data:\n{str(e)}")
            print(f"❌ Error exporting AI training data: {e}")
    
    # =====================================================================
    # TESTING METHODS
    # =====================================================================
    
    def start_test_mode(self):
        """Start real-time testing mode."""
        if not self.ai_model.is_loaded:
            QMessageBox.warning(self, "Model Not Loaded", 
                              "Please load the AI model first!")
            return
        
        if not self.main_window.is_running:
            QMessageBox.warning(self, "Not Running", 
                              "Please start data acquisition first!")
            return
        
        self.is_testing = True
        
        # Set main window to test mode
        self.main_window.is_test_mode = True
        
        # Update UI
        self.start_test_btn.setEnabled(False)
        self.stop_test_btn.setEnabled(True)
        
        print("Started AI testing mode")
    
    def stop_test_mode(self):
        """Stop testing mode."""
        self.is_testing = False
        self.main_window.is_test_mode = False
        
        # Update UI
        self.start_test_btn.setEnabled(True)
        self.stop_test_btn.setEnabled(False)
        
        print("Stopped AI testing mode")
    
    def update_test_prediction(self, features):
        """
        Update test prediction display with new features.
        
        Args:
            features: Dictionary of calculated features
        """
        if not self.is_testing or not self.ai_model.is_loaded:
            return
        
        try:
            # Make prediction using Keras model
            prediction_label, confidence, prediction_idx = self.ai_model.predict(features)
            
            if prediction_label:
                # Update prediction display
                self.prediction_label.setText(f"Movement: {prediction_label}")
                self.confidence_label.setText(f"Confidence: {confidence:.1f}%")
                
                # Color code based on confidence
                if confidence > 80:
                    color = "#00FF00"  # Green
                elif confidence > 60:
                    color = "#FFFF00"  # Yellow
                else:
                    color = "#FF4444"  # Red
                
                self.confidence_label.setStyleSheet(f"""
                    QLabel {{
                        font-size: 14pt;
                        font-weight: bold;
                        color: {color};
                        padding: 10px;
                        text-align: center;
                    }}
                """)
                
                # Update test features display
                features_text = ""
                for key, value in features.items():
                    if key not in ['timestamp', 'window_samples']:
                        features_text += f"{key}: {value:.3f}\n"
                
                self.test_features_display.setText(features_text)
                
                # Log prediction
                timestamp = datetime.now().strftime("%H:%M:%S")
                log_item = f"[{timestamp}] {prediction_label} ({confidence:.1f}%)"
                self.test_log.addItem(log_item)
                self.test_log.scrollToBottom()
        
        except Exception as e:
            print(f"AI prediction error: {e}")
    
    def clear_test_log(self):
        """Clear test log."""
        self.test_log.clear()
        self.prediction_label.setText("Recognized Movement: ---")
        self.confidence_label.setText("Confidence: ---")
        self.confidence_label.setStyleSheet("""
            QLabel {
                font-size: 14pt;
                font-weight: bold;
                color: #00FFC4;
                padding: 10px;
                text-align: center;
            }
        """)
        self.test_features_display.clear()
        print("Test log cleared")

# =====================================================================
# MAIN APPLICATION WINDOW - Primary interface
# =====================================================================
class MainWindow(QtWidgets.QWidget):
    """
    Main application window coordinating all components.
    Manages serial communication, data processing, and UI updates.
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("⚡ STM EMG Monitor + AI System")
        self.setStyleSheet(self.loadStyle())

        # Signal processing
        self.signal_processor = SignalProcessor(sampling_rate=1000.0)  # 1kHz sampling rate
        
        # Serial communication
        self.serial_thread = None  # Thread for serial reading
        self.is_running = False    # Application running state
        self.is_test_mode = False  # AI test mode state
        
        # Data buffers
        self.data_buffer = []      # Buffer for received data
        self.max_buffer_size = 1000
        self.timer_buffer = []     # Buffer for timer values
        self.sensor_buffer = []    # Buffer for sensor data [ax, ay, az, gx, gy, gz]
        
        # External connections
        self.matlab_connector = MATLABConnector()
        self.matplotlib_window = None  # Reference to matplotlib plotting window
        
        # Feature calculation
        self.feature_calculator = FeatureCalculator(self.signal_processor)
        self.feature_calculator.features_calculated.connect(self.on_features_calculated)
        
        # Feature storage - automatically saved every 200ms
        self.saved_features = []  # List to store all calculated features
        self.auto_save_features = True  # Enable automatic saving

        # Recording variables
        self.recorded_segments = []
        self.is_segment_recording = False
        self.current_segment_label = ""
        self.current_segment_data = {
            "timestamps": [],
            "ch1": [],
            "ch2": [],
            "ch3": [],
            "timer": [],
            "sensors": []
        }
        
        # Initialize UI and timers
        self.initUI()
        self.setupTimer()
        
    def initUI(self):
        """Initialize main window user interface."""
        mainLayout = QGridLayout(self)
        mainLayout.setSpacing(15)
        mainLayout.setContentsMargins(15, 15, 15, 15)

        # Left Column: Signal Plots
        plotLayout = QVBoxLayout()
        plotLayout.setSpacing(10)
        
        self.ch1 = SignalPlot("Channel 1 - Raw (Blue) & Filtered (Pink)", show_filtered=False)
        self.ch2 = SignalPlot("Channel 2 - Raw (Blue) & Filtered (Pink)", show_filtered=False)
        self.ch3 = SignalPlot("Channel 3 - Raw (Blue) & Filtered (Pink)", show_filtered=False)
        
        # Set size policies for plots
        for plot in [self.ch1, self.ch2, self.ch3]:
            plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            plot.setMinimumHeight(200)
        
        plotLayout.addWidget(self.ch1, 1)
        plotLayout.addWidget(self.ch2, 1)
        plotLayout.addWidget(self.ch3, 1)
        
        mainLayout.addLayout(plotLayout, 0, 0)

        # Right Column: Control Tabs
        self.controlTabs = QTabWidget()
        self.controlTabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
        # --- TAB 1: Monitor Controls ---
        monitorTabWidget = QWidget()
        monitorTabLayout = QVBoxLayout(monitorTabWidget)
        monitorTabLayout.setSpacing(15)
        monitorTabLayout.setContentsMargins(5, 10, 5, 5)
        
        # Create scroll area for controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        # Container for scroll content
        scrollContent = QWidget()
        scrollLayout = QVBoxLayout(scrollContent)
        scrollLayout.setSpacing(15)
        scrollLayout.setContentsMargins(5, 5, 5, 5)

        # Signal Processing Card
        filter_box = QGroupBox("SIGNAL PROCESSING")
        filter_box.setStyleSheet("""
            QGroupBox {
                color: #00D4FF;
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
            }
        """)
        filterLayout = QVBoxLayout(filter_box)
        
        filter_info = QLabel("✓ Notch Filter: Remove power line interference\n✓ Bandpass Filter: EMG frequency range")
        filter_info.setStyleSheet("color: #BFBFBF; font-size: 9pt; padding: 5px;")
        filterLayout.addWidget(filter_info)
        
        # Filter settings button
        self.filter_settings_btn = QPushButton("⚙️ Configure Filters")
        self.filter_settings_btn.clicked.connect(self.open_filter_settings)
        filterLayout.addWidget(self.filter_settings_btn)
        
        # Filter status display
        self.filter_status = QLabel("Status: Notch (50Hz) + Bandpass (20-500Hz)")
        self.filter_status.setStyleSheet("color: #00FFC4; font-size: 9pt; padding: 5px;")
        filterLayout.addWidget(self.filter_status)
        
        scrollLayout.addWidget(filter_box)

        # MATLAB Connection Card
        matlab_group = QGroupBox("MATLAB CONNECTION")
        matlab_group.setStyleSheet(filter_box.styleSheet())
        matlab_layout = QVBoxLayout(matlab_group)
        
        self.matlab_connect_btn = QPushButton("🔗 Connect to MATLAB")
        self.matlab_disconnect_btn = QPushButton("🔌 Disconnect MATLAB")
        self.matlab_status = QLabel("Status: Disconnected")
        self.matlab_status.setStyleSheet("color: #FF4444; font-weight: bold;")
        
        matlab_layout.addWidget(self.matlab_connect_btn)
        matlab_layout.addWidget(self.matlab_disconnect_btn)
        matlab_layout.addWidget(self.matlab_status)
        
        scrollLayout.addWidget(matlab_group)

        # Matplotlib Plotting Window Card
        matplotlib_group = QGroupBox("MATPLOTLIB PLOTTING")
        matplotlib_group.setStyleSheet(filter_box.styleSheet())
        matplotlib_layout = QVBoxLayout(matplotlib_group)
        
        matplotlib_info = QLabel("✓ Three-channel calibrated plotting\n✓ Real-time signal visualization")
        matplotlib_info.setStyleSheet("color: #BFBFBF; font-size: 9pt; padding: 5px;")
        matplotlib_layout.addWidget(matplotlib_info)
        
        self.matplotlib_plot_btn = QPushButton("📊 Open Matplotlib Plot Window")
        matplotlib_layout.addWidget(self.matplotlib_plot_btn)
        
        scrollLayout.addWidget(matplotlib_group)

        # Gyroscope Control Card
        gyro_group = QGroupBox("GYROSCOPE CONTROL")
        gyro_group.setStyleSheet(filter_box.styleSheet())
        gyroLayout = QVBoxLayout(gyro_group)
        
        control_info = QLabel("✓ Use Checkboxes to enable/disable axes")
        control_info.setStyleSheet("color: #BFBFBF; font-size: 9pt; padding: 5px;")
        gyroLayout.addWidget(control_info)
        
        # Gyroscope gauges
        gauges_layout = QHBoxLayout()
        gauges_layout.setSpacing(10)
        self.gx = GaugeWidget("X Gyro")
        self.gy = GaugeWidget("Y Gyro")
        self.gz = GaugeWidget("Z Gyro")
        
        # Set fixed size for gauges
        for gauge in [self.gx, self.gy, self.gz]:
            gauge.setFixedSize(100, 120)
            
        gauges_layout.addWidget(self.gx)
        gauges_layout.addWidget(self.gy)
        gauges_layout.addWidget(self.gz)
        gyroLayout.addLayout(gauges_layout)
        
        scrollLayout.addWidget(gyro_group)

        # Accelerometer Control Card
        axis_group = QGroupBox("ACCELEROMETER CONTROL")
        axis_group.setStyleSheet(filter_box.styleSheet())
        axisLayout = QVBoxLayout(axis_group)
        
        axis_info = QLabel("✓ Use Checkboxes to enable/disable axes")
        axis_info.setStyleSheet("color: #BFBFBF; font-size: 9pt; padding: 5px;")
        axisLayout.addWidget(axis_info)
        
        axisLayout.setSpacing(8)
        self.x_axis = AxisBar("X Axis", 0)
        self.y_axis = AxisBar("Y Axis", 0)
        self.z_axis = AxisBar("Z Axis", 0)
        axisLayout.addWidget(self.x_axis)
        axisLayout.addWidget(self.y_axis)
        axisLayout.addWidget(self.z_axis)
        
        scrollLayout.addWidget(axis_group)

        # Connection Control Card
        connection_group = QGroupBox("CONNECTION")
        connection_group.setStyleSheet(filter_box.styleSheet())
        btnLayout = QGridLayout(connection_group)
        btnLayout.setSpacing(10)
        
        self.startBtn = QPushButton("▶ Start")
        self.stopBtn = QPushButton("⏸ Stop")
        self.saveBtn = QPushButton("💾 Save Excel")
        self.exportBtn = QPushButton("📤 Export Training")
        self.exportFeaturesBtn = QPushButton("📊 Export Features (200ms)")
        self.portBox = QComboBox()
        self.refresh_usb_ports()
        
        # Features status label
        self.features_status = QLabel("Saved Features: 0 (every 200ms)")
        self.features_status.setStyleSheet("color: #00FFC4; font-size: 9pt; padding: 5px;")
        
        btnLayout.addWidget(QLabel("Port:"), 0, 0)
        btnLayout.addWidget(self.portBox, 0, 1)
        btnLayout.addWidget(self.startBtn, 1, 0)
        btnLayout.addWidget(self.stopBtn, 1, 1)
        btnLayout.addWidget(self.saveBtn, 2, 0, 1, 2)
        btnLayout.addWidget(self.exportBtn, 3, 0, 1, 2)
        btnLayout.addWidget(self.exportFeaturesBtn, 4, 0, 1, 2)
        btnLayout.addWidget(self.features_status, 5, 0, 1, 2)
        
        scrollLayout.addWidget(connection_group)
        scrollLayout.addStretch(1)
        
        # Set scroll content
        scroll.setWidget(scrollContent)
        monitorTabLayout.addWidget(scroll)

        # --- TAB 2: AI Training & Testing ---
        self.aiTab = AITrainingPanel(self)

        self.controlTabs.addTab(monitorTabWidget, "Monitor Controls")
        self.controlTabs.addTab(self.aiTab, "AI Section")
        
        mainLayout.addWidget(self.controlTabs, 0, 1)
        
        # Set column stretch ratios
        mainLayout.setColumnStretch(0, 3)  # Plots take 3 parts
        mainLayout.setColumnStretch(1, 1)  # Controls take 1 part
        
        # Set minimum sizes
        self.setMinimumSize(1200, 700)
        self.controlTabs.setMinimumWidth(350)

        # Connect signals
        self.startBtn.clicked.connect(self.startData)
        self.stopBtn.clicked.connect(self.stopData)
        self.saveBtn.clicked.connect(self.saveData)
        self.exportBtn.clicked.connect(self.export_training_data)
        self.exportFeaturesBtn.clicked.connect(self.export_saved_features)
        self.matlab_connect_btn.clicked.connect(self.connect_matlab)
        self.matlab_disconnect_btn.clicked.connect(self.disconnect_matlab)
        self.matplotlib_plot_btn.clicked.connect(self.open_matplotlib_window)
    
    # =====================================================================
    # SERIAL COMMUNICATION METHODS
    # =====================================================================
    
    def refresh_usb_ports(self):
        """
        Auto-detect available USB virtual COM ports and populate the combo box.
        Falls back to common COM names if nothing is detected.
        """
        ports = [p.device for p in serial.tools.list_ports.comports() 
                 if 'USB' in p.description.upper()]
        
        # If no USB-tagged ports, include all detected ports as fallback
        if not ports:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        
        self.portBox.clear()
        if ports:
            self.portBox.addItems(ports)
        else:
            self.portBox.addItems(["COM1","COM2","COM3","COM4", "COM5", "COM6", "COM7", "COM8"])
        
        if self.portBox.count() > 0:
            self.portBox.setCurrentIndex(0)
    
    def startData(self):
        """
        Start serial data acquisition in separate thread.
        This prevents GUI freezing during continuous data reading.
        """
        # Refresh ports before starting to ensure we pick the active USB CDC port
        self.refresh_usb_ports()
        port = self.portBox.currentText()
        
        # Create and configure serial thread
        self.serial_thread = SerialReaderThread(port)
        self.serial_thread.data_received.connect(self.process_serial_data)
        self.serial_thread.connection_status.connect(self.update_connection_status)
        self.serial_thread.start()
        
        # Start feature calculator
        self.feature_calculator.start()
        
        # Update application state
        self.is_running = True
        self.startBtn.setEnabled(False)
        self.stopBtn.setEnabled(True)
        
        # Start GUI update timer (separate from data acquisition)
        self.timer.start(self.timer_interval_ms)
        
        # Auto-start matplotlib plotting if window is open
        if self.matplotlib_window and self.matplotlib_window.isVisible():
            self.matplotlib_window.start_plotting()
        
        print("✅ Started serial reading thread")
    
    def stopData(self):
        """
        Stop all data acquisition and processing threads.
        """
        # Stop recording if active
        if hasattr(self, 'is_segment_recording') and self.is_segment_recording:
            self.stop_segment_recording()
            
        # Update application state
        self.is_running = False
        self.is_test_mode = False
        self.timer.stop()
        
        # Stop serial thread
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        
        # Stop feature calculator
        self.feature_calculator.stop()
        
        # Stop matplotlib plotting if window is open
        if self.matplotlib_window and self.matplotlib_window.isVisible():
            self.matplotlib_window.stop_plotting()
        
        # Update UI
        self.startBtn.setEnabled(True)
        self.stopBtn.setEnabled(False)
        
        # Update features status
        if hasattr(self, 'features_status'):
            self.features_status.setText(f"Saved Features: {len(self.saved_features)} (every 200ms)")
        
        print(f"Timer Stopped, Serial Disconnected. Total features saved: {len(self.saved_features)}")
    
    def process_serial_data(self, data):
        """
        Process data received from serial thread.
        This runs in the GUI thread when data is available.
        
        Args:
            data: Either a single sample [adc0, adc1, adc2, timer]
                  or a list of such samples.
        """
        # Normalize to a list of samples
        samples = data if (isinstance(data, list) and data and isinstance(data[0], (list, tuple))) else [data]
        
        for sample in samples:
            if not sample or len(sample) < 4:
                continue
            
            # Extract REAL ADC data directly from STM32 (no modification)
            adc0, adc1, adc2, timer_val = sample[0], sample[1], sample[2], sample[3]
            
            # Sensor data not available from STM32, use default zeros
            sensor_data = [0, 0, 0, 0, 0, 0]  # [ax, ay, az, gx, gy, gz] - not available
            
            # Store REAL data with timestamp
            data_with_time = {
                'timestamp': datetime.now(),
                'adc0': int(adc0),  # Ensure integer (REAL ADC value)
                'adc1': int(adc1),  # Ensure integer (REAL ADC value)
                'adc2': int(adc2),  # Ensure integer (REAL ADC value)
                'timer': timer_val,
                'sensors': sensor_data
            }
            
            # Add to buffers
            self.data_buffer.append(data_with_time)
            self.timer_buffer.append(timer_val)
            self.sensor_buffer.append(sensor_data)
            
            # Limit buffer sizes
            if len(self.data_buffer) > self.max_buffer_size:
                self.data_buffer = self.data_buffer[-self.max_buffer_size:]
            if len(self.timer_buffer) > self.max_buffer_size:
                self.timer_buffer = self.timer_buffer[-self.max_buffer_size:]
            if len(self.sensor_buffer) > self.max_buffer_size:
                self.sensor_buffer = self.sensor_buffer[-self.max_buffer_size:]
            
            # Process REAL signal with filter (passes REAL ADC values to processor)
            self.signal_processor.add_sample(adc0, adc1, adc2)
    
    def update_connection_status(self, connected, message):
        """
        Update connection status display.
        
        Args:
            connected: Connection state
            message: Status message
        """
        if connected:
            print(f"✅ {message}")
        else:
            print(f"❌ {message}")
    
    # =====================================================================
    # GUI UPDATE METHODS
    # =====================================================================
    
    def setupTimer(self):
        """
        Setup GUI update timer.
        This timer updates plots and displays, not for data acquisition.
        """
        self.timer = QTimer()
        self.timer.timeout.connect(self.updateGUI)
        self.timer_interval_ms = 50  # 20 Hz update rate for smoother plotting
    
    def updateGUI(self):
        """
        Update GUI components with latest data.
        Called by timer at regular intervals.
        Optimized for batch updates for smoother real-time plotting.
        """
        if not self.is_running or len(self.data_buffer) < 5:
            self.updatePlotsWithZeros()
            return
        
        try:
            # Get latest data from buffer for sensor display
            latest = self.data_buffer[-1]
            timer_val = latest['timer']
            sensor_data = latest['sensors']
            
            # Get batch of recent data for smoother plotting (last 10-20 samples)
            batch_size = min(20, len(self.data_buffer))
            recent_data = self.data_buffer[-batch_size:]
            
            # Extract raw ADC values in batch
            raw_ch1_batch = [d['adc0'] for d in recent_data]
            raw_ch2_batch = [d['adc1'] for d in recent_data]
            raw_ch3_batch = [d['adc2'] for d in recent_data]
            
            # Get filtered signals in batch for smoother display
            filtered_ch1 = self.signal_processor.get_latest_filtered('ch1', batch_size)
            filtered_ch2 = self.signal_processor.get_latest_filtered('ch2', batch_size)
            filtered_ch3 = self.signal_processor.get_latest_filtered('ch3', batch_size)
            
            # Get matching filtered values for the batch
            if filtered_ch1 and len(filtered_ch1) >= batch_size:
                filtered_ch1_batch = filtered_ch1[-batch_size:]
            elif filtered_ch1 and len(filtered_ch1) > 0:
                filtered_ch1_batch = filtered_ch1[-len(filtered_ch1):] + [filtered_ch1[-1]] * (batch_size - len(filtered_ch1))
            else:
                filtered_ch1_batch = raw_ch1_batch.copy()
            
            if filtered_ch2 and len(filtered_ch2) >= batch_size:
                filtered_ch2_batch = filtered_ch2[-batch_size:]
            elif filtered_ch2 and len(filtered_ch2) > 0:
                filtered_ch2_batch = filtered_ch2[-len(filtered_ch2):] + [filtered_ch2[-1]] * (batch_size - len(filtered_ch2))
            else:
                filtered_ch2_batch = raw_ch2_batch.copy()
            
            if filtered_ch3 and len(filtered_ch3) >= batch_size:
                filtered_ch3_batch = filtered_ch3[-batch_size:]
            elif filtered_ch3 and len(filtered_ch3) > 0:
                filtered_ch3_batch = filtered_ch3[-len(filtered_ch3):] + [filtered_ch3[-1]] * (batch_size - len(filtered_ch3))
            else:
                filtered_ch3_batch = raw_ch3_batch.copy()
            
            # Update plots with batch data for smoother, faster rendering
            self.ch1.updateData(raw_ch1_batch, filtered_ch1_batch)
            self.ch2.updateData(raw_ch2_batch, filtered_ch2_batch)
            self.ch3.updateData(raw_ch3_batch, filtered_ch3_batch)
            
            # Update sensor displays
            self.updateSensors(sensor_data)
            
            # Send to MATLAB if connected
            if self.matlab_connector.is_connected:
                self.matlab_connector.send_to_matlab(
                    self.signal_processor.raw_signals['ch1'],
                    self.signal_processor.raw_signals['ch2'],
                    self.signal_processor.raw_signals['ch3'],
                    self.timer_buffer,
                    sensor_data
                )
                
        except Exception as e:
            print(f"GUI update error: {e}")
            self.updatePlotsWithZeros()
    
    def updateSensors(self, sensor_data):
        """
        Update sensor display widgets with new values.
        
        Args:
            sensor_data: List [ax, ay, az, gx, gy, gz]
        """
        try:
            if len(sensor_data) >= 6:
                ax, ay, az, gx, gy, gz = sensor_data
                
                # Update gyroscope gauges
                self.gx.setValue(gx)
                self.gy.setValue(gy)
                self.gz.setValue(gz)
                
                # Update accelerometer bars
                self.x_axis.setValue(ax)
                self.y_axis.setValue(ay)
                self.z_axis.setValue(az)
                
        except Exception as e:
            print(f"Sensor update error: {e}")
    
    def updatePlotsWithZeros(self):
        """Display zero values on all plots when no data is available."""
        # Use real zero values (not random) when no data
        self.ch1.updateData(0, 0)
        self.ch2.updateData(0, 0)
        self.ch3.updateData(0, 0)
    
    # =====================================================================
    # FILTER CONTROL METHODS
    # =====================================================================
    
    def open_filter_settings(self):
        """Open filter settings dialog."""
        dialog = FilterSettingsDialog(self)
        
        # Show dialog and wait for user input
        if dialog.exec_() == QDialog.Accepted:
            # Get settings from dialog
            settings = dialog.get_settings()
            
            # Update signal processor
            self.signal_processor.update_filters(settings)
            
            # Show/hide filtered lines based on whether any filter is enabled
            any_filter_enabled = settings['notch']['enabled'] or settings['bandpass']['enabled']
            self.ch1.set_show_filtered(any_filter_enabled)
            self.ch2.set_show_filtered(any_filter_enabled)
            self.ch3.set_show_filtered(any_filter_enabled)
            
            # Also update matplotlib window if it exists
            if self.matplotlib_window and self.matplotlib_window.isVisible():
                self.matplotlib_window.set_show_filtered(any_filter_enabled)
            
            # Update status display
            notch_status = "Enabled" if settings['notch']['enabled'] else "Disabled"
            bandpass_status = "Enabled" if settings['bandpass']['enabled'] else "Disabled"
            
            status_text = f"Status: Notch {notch_status} ({settings['notch']['frequency']}Hz) "
            status_text += f"+ Bandpass {bandpass_status} "
            status_text += f"({settings['bandpass']['lowcut']}-{settings['bandpass']['highcut']}Hz)"
            
            self.filter_status.setText(status_text)
            
            print(f"✅ Filters updated: {status_text}")
    
    # =====================================================================
    # FEATURE PROCESSING METHODS
    # =====================================================================
    
    def on_features_calculated(self, features):
        """
        Handle calculated features from feature calculator thread.
        Automatically saves features every 200ms from filtered signals.
        
        Args:
            features: Dictionary of calculated features
        """
        # Automatically save features every 200ms (calculated from filtered signals)
        if self.auto_save_features and features:
            # Create a copy to avoid reference issues
            features_copy = features.copy()
            self.saved_features.append(features_copy)
            
            # Update features status label
            if hasattr(self, 'features_status'):
                self.features_status.setText(f"Saved Features: {len(self.saved_features)} (every 200ms)")
            
            print(f"✅ Features saved at {features.get('timestamp', 'N/A')} - Window: {features.get('window_samples', 0)} samples")
        
        # Send features to AI tab for display and recording
        if hasattr(self, 'aiTab'):
            self.aiTab.update_features_display(features)
            
            # In test mode, send features to model
            if self.is_test_mode:
                self.aiTab.update_test_prediction(features)
    
    # =====================================================================
    # MATLAB CONNECTION METHODS
    # =====================================================================
    
    def connect_matlab(self):
        """Establish connection to MATLAB."""
        if self.matlab_connector.connect_to_matlab():
            self.matlab_status.setText("Status: Connected ✅")
            self.matlab_status.setStyleSheet("color: #00FF00; font-weight: bold;")
            QMessageBox.information(self, "MATLAB", "Connected to MATLAB successfully!")
        else:
            self.matlab_status.setText("Status: Connection Failed ❌")
            self.matlab_status.setStyleSheet("color: #FF4444; font-weight: bold;")
            QMessageBox.warning(self, "MATLAB", 
                              "Failed to connect to MATLAB!\nMake sure MATLAB server is running.")
    
    def disconnect_matlab(self):
        """Disconnect from MATLAB."""
        self.matlab_connector.disconnect_matlab()
        self.matlab_status.setText("Status: Disconnected")
        self.matlab_status.setStyleSheet("color: #FF4444; font-weight: bold;")
    
    def open_matplotlib_window(self):
        """Toggle matplotlib three-channel plotting window (open/close)."""
        if self.matplotlib_window is None or not self.matplotlib_window.isVisible():
            # Create new window if it doesn't exist or was closed
            self.matplotlib_window = MatplotlibPlotWindow(self, self.signal_processor, self)
            # Set filtered line visibility based on current filter state
            any_filter_enabled = (self.signal_processor.notch_enabled or 
                                 self.signal_processor.bandpass_enabled)
            self.matplotlib_window.set_show_filtered(any_filter_enabled)
            self.matplotlib_window.show()
            # Auto-start plotting if main window is already running
            if self.is_running:
                self.matplotlib_window.start_plotting()
            # Update button text
            self.matplotlib_plot_btn.setText("📊 Close Matplotlib Plot Window")
            print("Matplotlib plotting window opened")
        else:
            # Toggle: Close the window if it's already open
            self.matplotlib_window.stop_plotting()
            self.matplotlib_window.close()
            self.matplotlib_window = None
            # Update button text
            self.matplotlib_plot_btn.setText("📊 Open Matplotlib Plot Window")
            print("Matplotlib plotting window closed")
    
    # =====================================================================
    # UI HELPER METHODS
    # =====================================================================
    
    def showEvent(self, event):
        """Fade the window in when shown."""
        self.setWindowOpacity(0.0)
        super().showEvent(event)
        
        # Create fade animation
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(500)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.start(QPropertyAnimation.DeleteWhenStopped)
    
    # =====================================================================
    # DATA MANAGEMENT METHODS
    # =====================================================================
    
    def export_training_data(self):
        """Export all recorded training segments to organized files."""
        if not self.recorded_segments:
            QMessageBox.warning(self, "No Data", "No movements have been recorded yet")
            return
        
        try:
            # Create folder for data
            folder_name = f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.makedirs(folder_name, exist_ok=True)
            
            # Save all segments
            all_data = []
            for segment in self.recorded_segments:
                label = segment["label"]
                data = segment["data"]
                
                for i in range(len(data["ch1"])):
                    timestamp = data["timestamps"][i] if i < len(data["timestamps"]) else datetime.now()
                    sensor_data = data["sensors"][i] if i < len(data["sensors"]) else [0, 0, 0, 0, 0, 0]
                    
                    row = {
                        "timestamp": timestamp,
                        "label": label,
                        "channel_1": data["ch1"][i] if i < len(data["ch1"]) else 0,
                        "channel_2": data["ch2"][i] if i < len(data["ch2"]) else 0,
                        "channel_3": data["ch3"][i] if i < len(data["ch3"]) else 0,
                        "timer": data["timer"][i] if i < len(data["timer"]) else 0,
                        "accel_x": sensor_data[0],
                        "accel_y": sensor_data[1],
                        "accel_z": sensor_data[2],
                        "gyro_x": sensor_data[3],
                        "gyro_y": sensor_data[4],
                        "gyro_z": sensor_data[5]
                    }
                    all_data.append(row)
            
            # Save as Excel
            df = pd.DataFrame(all_data)
            excel_file = f"{folder_name}/all_training_data.xlsx"
            df.to_excel(excel_file, index=False)
            
            # Save summary
            summary = []
            for i, segment in enumerate(self.recorded_segments):
                summary.append({
                    "segment_id": i+1,
                    "label": segment["label"],
                    "samples": segment["sample_count"],
                    "timestamp": segment["timestamp"],
                    "duration_seconds": segment["sample_count"] * 0.001,  # 1ms per sample
                    "sampling_rate_hz": 1000.0
                })
            
            summary_df = pd.DataFrame(summary)
            summary_file = f"{folder_name}/segments_summary.xlsx"
            summary_df.to_excel(summary_file, index=False)
            
            QMessageBox.information(self, "Exported", 
                                   f"Saved {len(self.recorded_segments)} segments to folder:\n{folder_name}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export data:\n{str(e)}")
    
    def saveData(self):
        """Save current plot data to Excel file."""
        try:
            # Collect current data
            data_length = min(len(self.ch1.data_raw), 200)
            
            # Get filtered data
            filtered_ch1 = self.signal_processor.get_latest_filtered('ch1', data_length)
            filtered_ch2 = self.signal_processor.get_latest_filtered('ch2', data_length)
            filtered_ch3 = self.signal_processor.get_latest_filtered('ch3', data_length)
            
            # Ensure all arrays have same length
            min_len = min(len(filtered_ch1), len(filtered_ch2), len(filtered_ch3), data_length)
            
            timestamps = [datetime.now() for _ in range(min_len)]
            timer_vals = self.timer_buffer[-min_len:] if self.timer_buffer else [0.0] * min_len
            
            # Get latest sensor data
            sensor_data = []
            if self.sensor_buffer:
                for i in range(min_len):
                    idx = min(i, len(self.sensor_buffer)-1)
                    sensor_data.append(self.sensor_buffer[idx])
            
            df = pd.DataFrame({
                "timestamp": timestamps,
                "timer": timer_vals[:min_len],
                "channel_1_raw": self.ch1.data_raw[-min_len:],
                "channel_1_filtered": filtered_ch1[:min_len],
                "channel_2_raw": self.ch2.data_raw[-min_len:],
                "channel_2_filtered": filtered_ch2[:min_len],
                "channel_3_raw": self.ch3.data_raw[-min_len:],
                "channel_3_filtered": filtered_ch3[:min_len]
            })
            
            # Add sensor data if available
            if sensor_data:
                for i, col in enumerate(['accel_x', 'accel_y', 'accel_z', 'gyro_x', 'gyro_y', 'gyro_z']):
                    col_data = [sensor[i] for sensor in sensor_data[:min_len]]
                    df[col] = col_data
            
            # Get save filename
            default_name = f"emg_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            file, _ = QFileDialog.getSaveFileName(self, "Save File", default_name, "Excel (*.xlsx)")
            if not file:
                return
            
            # Save to Excel
            df.to_excel(file, index=False, engine='openpyxl')
            QMessageBox.information(self, "Saved", f"Data saved successfully to:\n{file}")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save data:\n{str(e)}")
    
    def export_saved_features(self):
        """Export all automatically saved features (calculated every 200ms) to CSV/Excel."""
        if not self.saved_features:
            QMessageBox.warning(self, "No Features", "No features have been saved yet.\nFeatures are saved every 200ms when data acquisition is running.")
            return
        
        try:
            # Convert saved features to DataFrame
            df = pd.DataFrame(self.saved_features)
            
            # Get save filename
            default_name = f"features_200ms_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            file, _ = QFileDialog.getSaveFileName(
                self, "Export Saved Features", default_name, 
                "Excel (*.xlsx);;CSV (*.csv)"
            )
            
            if not file:
                return
            
            # Save based on file extension
            if file.endswith('.csv'):
                df.to_csv(file, index=False)
            else:
                df.to_excel(file, index=False, engine='openpyxl')
            
            QMessageBox.information(
                self, "Exported", 
                f"✅ Exported {len(self.saved_features)} feature sets to:\n{file}\n\n"
                f"Features calculated every 200ms from filtered signals."
            )
            print(f"✅ Exported {len(self.saved_features)} feature sets to {file}")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export features:\n{str(e)}")
            print(f"❌ Error exporting features: {e}")
    
    def clear_saved_features(self):
        """Clear all saved features."""
        count = len(self.saved_features)
        self.saved_features = []
        print(f"Cleared {count} saved feature sets")
    
    # =====================================================================
    # STYLING
    # =====================================================================
    
    def loadStyle(self):
        """
        Load application stylesheet.
        
        Returns:
            str: CSS stylesheet string
        """
        return """
        /* === Main Window === */
        QWidget { 
            background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, 
                                            stop:0 #0C0C0C, stop:1 #151515);
            color: #EAEAEA; 
            font-family: 'Segoe UI'; 
            font-size: 10pt; 
        }
        
        /* === GroupBox === */
        QGroupBox {
            color: #00D4FF;
            font-weight: 600;
            font-size: 11pt;
            border: 1px solid #444;
            border-radius: 8px;
            margin-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px 0 5px;
            left: 10px;
        }
        
        /* === Tabs === */
        QTabWidget::pane {
            border-top: 2px solid #333;
        }
        QTabBar::tab {
            background: #1A1A1A;
            border: 1px solid #333;
            padding: 10px 15px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            color: #AAA;
            font-weight: bold;
        }
        QTabBar::tab:selected {
            background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, 
                                            stop:0 #0C0C0C, stop:1 #151515);
            color: #00D4FF;
            border-bottom-color: #151515;
        }
        
        /* === Buttons === */
        QPushButton { 
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1F1F1F, stop:1 #292929);
            border: 1px solid #00D4FF; 
            padding: 7px 15px; 
            border-radius: 6px; 
            color: #EAEAEA; 
            font-weight: 500;
            text-align: center;
        }
        QPushButton:hover { 
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00BFFF, stop:1 #007FFF); 
            color: #000; 
            font-weight: bold; 
        }
        QPushButton:pressed { 
            background-color: #008CFF; 
            color: #000; 
        }
        QPushButton:disabled {
            background-color: #1A1A1A;
            border: 1px solid #444;
            color: #666;
        }
        
        /* === ComboBox === */
        QComboBox { 
            background-color: #1E1E1E; 
            color: #FFFFFF; 
            border: 1px solid #00D4FF; 
            border-radius: 4px; 
            padding: 5px; 
            min-width: 80px; 
        }
        QComboBox:hover { border-color: #0099FF; }
        QComboBox::drop-down { border: none; }
        QComboBox QAbstractItemView {
            background-color: #2D2D2D;
            border: 1px solid #00D4FF;
            selection-background-color: #00AFFF;
        }
        
        /* === LineEdit === */
        QLineEdit {
            background-color: #1E1E1E;
            color: #FFFFFF;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 5px;
        }
        QLineEdit:focus {
            border-color: #00D4FF;
        }
        
        /* === Checkboxes === */
        QCheckBox {
            color: #BFBFBF;
            spacing: 5px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #444;
            border-radius: 3px;
            background-color: #2A2A2A;
        }
        QCheckBox::indicator:checked {
            background-color: #00D4FF;
            border: 1px solid #00D4FF;
        }
        QCheckBox::indicator:hover {
            border: 1px solid #00BFFF;
        }
        
        /* === Text Edit === */
        QTextEdit {
            background-color: #1A1A1A;
            color: #FFFFFF;
            border: 1px solid #444;
            border-radius: 5px;
            padding: 5px;
        }
        
        /* === List Widget === */
        QListWidget {
            background-color: #1A1A1A;
            color: #FFFFFF;
            border: 1px solid #444;
            border-radius: 5px;
            padding: 5px;
        }
        QListWidget::item {
            padding: 3px;
            border-bottom: 1px solid #333;
        }
        QListWidget::item:selected {
            background-color: #00D4FF;
            color: #000;
        }
        
        /* === Progress Bar === */
        QProgressBar {
            background-color: #1A1A1A;
            border: 1px solid #333;
            border-radius: 4px;
            text-align: center;
            color: #FFF;
        }
        QProgressBar::chunk {
            background-color: #00D4FF;
            border-radius: 4px;
        }
        
        /* === ScrollBar === */
        QScrollBar:vertical {
            border: none;
            background: #191919;
            width: 12px;
            margin: 10px 0 10px 0;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #333;
            min-height: 20px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical:hover { background: #444; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        /* === Inner AI Tabs === */
        QTabWidget#aiTabs::pane { border: none; }
        QTabWidget#aiTabs QTabBar::tab {
            background: #222;
            border: 1px solid #333;
            padding: 8px 15px;
            color: #AAA;
        }
        QTabWidget#aiTabs QTabBar::tab:selected {
            background: #333;
            color: #00D4FF;
            border-bottom-color: #333;
        }
        """

# =====================================================================
# APPLICATION ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    """
    Main application entry point.
    Initializes QApplication, shows splash screen, and starts main window.
    """
    # Create application instance
    app = QtWidgets.QApplication(sys.argv)
    
    # Set default font
    font = QtGui.QFont("Calibri", 10)
    app.setFont(font)
    
    # Create main window
    win = MainWindow()
    win.resize(1500, 900)
    
    # Create and show splash screen
    splash = BioLinkSplash(win)
    splash.resize(600, 400)
    
    # Center splash screen
    try:
        screen_geometry = QApplication.primaryScreen().geometry()
        splash_x = (screen_geometry.width() - splash.width()) // 2
        splash_y = (screen_geometry.height() - splash.height()) // 2
        splash.move(splash_x, splash_y)
    except Exception as e:
        print(f"Could not center splash screen: {e}")

    # Start splash animations
    splash.show()
    splash.startAnimations()
    
    # Start application event loop
    sys.exit(app.exec_())