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
