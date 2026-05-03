import numpy as np
from scipy.signal import butter, sosfilt
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from config import (N_CHANNELS, SAMPLE_RATE, BLOCK_SIZE,
                    BANDPASS_LOW, BANDPASS_HIGH,
                    MIC_SPACING, SPEED_OF_SOUND, SCAN_ANGLES)


class DSPWorker(QThread):
    # Emits: (raw_waveform, doa_degrees, normalised_srp_spectrum)
    # waveform shape : (N_CHANNELS, BLOCK_SIZE) float32
    # spectrum shape : (len(SCAN_ANGLES),)       float32  values in [0, 1]
    result = pyqtSignal(np.ndarray, float, np.ndarray)

    def __init__(self):
        super().__init__()
        self._pending  = None
        self._mutex    = QMutex()
        self._running  = False

        # Pre-compute Butterworth bandpass filter (done once — expensive)
        self._sos = butter(
            4, [BANDPASS_LOW, BANDPASS_HIGH],
            btype='bandpass', fs=SAMPLE_RATE, output='sos'
        )

        # Pre-compute integer sample delays for all mic pairs x all scan angles
        self._precompute_delays()

    def _precompute_delays(self):
        """
        For every unique mic pair (i, j) and every candidate angle, compute the
        expected inter-mic delay in samples (integer).

        With 16 mics there are 16 choose 2 = 120 unique pairs.
        self._delays[(i, j)] is a 181-element int array (one value per scan angle).
        """
        angles_rad = np.deg2rad(SCAN_ANGLES)
        mic_pos    = np.arange(N_CHANNELS) * MIC_SPACING   # [0.0, 0.05, ..., 0.75] m

        self._delays = {}
        for i in range(N_CHANNELS):
            for j in range(i + 1, N_CHANNELS):
                # Path length difference in metres for each candidate angle
                d = (mic_pos[i] - mic_pos[j]) * np.sin(angles_rad)
                # Convert to integer sample delay
                self._delays[(i, j)] = (d / SPEED_OF_SOUND * SAMPLE_RATE).astype(int)

    def process(self, data: np.ndarray):
        """
        Called from UDPWorker via Qt signal — stores the latest frame.
        If a frame is already waiting (DSP is still busy), it is overwritten.
        This intentionally drops stale frames to keep the display real-time.
        """
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
                filtered          = sosfilt(self._sos, data, axis=1).astype(np.float32)
                angle, spectrum   = self._srp_phat(filtered)
                self.result.emit(data, float(angle), spectrum)
            else:
                self.msleep(5)   # nothing pending — sleep 5 ms

    def _srp_phat(self, data: np.ndarray):
        """
        Steered Response Power with PHAse Transform (SRP-PHAT).

        With 16 channels there are 120 mic pairs.  The inner Python loop over
        pairs is the bottleneck; consider replacing with vectorised NumPy or
        moving to a C extension if CPU load becomes an issue.

        Returns:
            angle    (float)           — DOA estimate in degrees [-90, +90]
            spectrum (np.ndarray f32)  — normalised power per scan angle [0, 1]
        """
        n_fft = data.shape[1]   # = BLOCK_SIZE = 256
        P     = np.zeros(len(SCAN_ANGLES), dtype=np.float64)

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

        peak_idx = int(np.argmax(P))
        angle    = float(SCAN_ANGLES[peak_idx])

        # Normalise to [0, 1] for display
        p_min, p_max = P.min(), P.max()
        if p_max - p_min > 1e-10:
            spectrum = ((P - p_min) / (p_max - p_min)).astype(np.float32)
        else:
            spectrum = np.zeros(len(SCAN_ANGLES), dtype=np.float32)

        return angle, spectrum

    def stop(self):
        self._running = False
        self.wait()
