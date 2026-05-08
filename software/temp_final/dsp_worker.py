import numpy as np
from scipy.signal import butter, sosfilt
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from config import (N_CHANNELS, SAMPLE_RATE, BLOCK_SIZE,
                    BANDPASS_LOW, BANDPASS_HIGH,
                    MIC_SPACING, SPEED_OF_SOUND, SCAN_ANGLES)

# ─────────────────────────────────────────────────────────────────────────────
#  DSPWorker — Wideband Frequency-Domain Beamforming
#
#  Replaces the old time-domain SRP-PHAT (120 mic-pair loops + integer delay
#  lookup) with a steering-matrix approach from the notebook.
#
#  Algorithm summary
#  -----------------
#  1. FFT all 16 channels at once                    → X[ch, bin]
#  2. PHAT-whiten every bin                          → X̂[ch, bin]
#  3. Pick the N_FREQS bins matching steering freqs  → X̂[freq, ch]
#  4. Beamform via einsum: Y = W† · X̂              → Y[freq, angle]
#  5. Average power across frequencies               → P[angle]
#  6. Peak of P → DOA estimate
#
#  Pre-computed once at __init__:
#  • Butterworth bandpass SOS coefficients  (unchanged from old code)
#  • Steering matrix W  shape (N_FREQS, N_CHANNELS, N_ANGLES)  complex64
#  • FFT bin indices matching the N_FREQS steering frequencies
#
#  Everything else (QThread lifecycle, mutex drop-policy, signal API) is
#  identical to the old file — no changes needed in main_window.py.
# ─────────────────────────────────────────────────────────────────────────────

# Number of frequency bins to steer across.
# 64 bins spread across BANDPASS_LOW–BANDPASS_HIGH is a good trade-off:
# more bins = more accuracy and noise rejection, more compute per frame.
# You can raise this to 128 with minimal performance impact on modern hardware.
N_STEERING_FREQS = 64


class DSPWorker(QThread):
    # Signal API is unchanged — main_window.py does not need to change.
    # Emits: (raw_waveform, doa_degrees, normalised_spectrum)
    # waveform shape : (N_CHANNELS, BLOCK_SIZE) float32
    # spectrum shape : (len(SCAN_ANGLES),)       float32  values in [0, 1]
    result = pyqtSignal(np.ndarray, float, np.ndarray)

    def __init__(self):
        super().__init__()
        self._pending  = None
        self._mutex    = QMutex()
        self._running  = False

        # Pre-compute bandpass filter — unchanged from old code
        self._sos = butter(
            4, [BANDPASS_LOW, BANDPASS_HIGH],
            btype='bandpass', fs=SAMPLE_RATE, output='sos'
        )

        # Pre-compute steering matrix and frequency bin indices
        self._precompute_steering()

    # ── Startup: build the steering matrix ───────────────────────────────────

    def _precompute_steering(self):
        """
        Build the wideband steering matrix W of shape
        (N_STEERING_FREQS, N_CHANNELS, N_ANGLES).

        W[f, n, a] = exp(-j * k[f] * d * mic_n * sin(theta_a))

        where:
            k[f]    = 2*pi*freq[f] / c      wavenumber   (rad/m)
            d       = MIC_SPACING            mic spacing  (m)
            mic_n   = mic index centred on 0 (e.g. -7.5 .. +7.5 for 16 mics)
            theta_a = SCAN_ANGLES[a]         candidate DOA in degrees

        This is computed once at startup. Per-frame cost is zero.
        """

        # ── Mic indices, centred ─────────────────────────────────────────────
        # Centre the array so that the phase reference is the array midpoint.
        # For 16 mics: indices are [-7.5, -6.5, ..., +6.5, +7.5]
        # (half-integer because 16 is even — midpoint falls between mics 7 and 8)
        mic_idx = np.arange(N_CHANNELS) - (N_CHANNELS - 1) / 2.0
        # shape: (16,)   e.g. [-7.5, -6.5, ..., +7.5]

        # ── Steering frequencies ─────────────────────────────────────────────
        # Spread N_STEERING_FREQS evenly across the bandpass band.
        # Using the bandpass limits ensures every steering frequency is
        # inside the band that the Butterworth filter passes.
        freqs = np.linspace(BANDPASS_LOW, BANDPASS_HIGH, N_STEERING_FREQS)
        # shape: (N_STEERING_FREQS,)  e.g. 64 values from 300 to 3400 Hz

        # Wavenumber k = 2*pi*f / c   (unit: rad/m)
        k = 2.0 * np.pi * freqs / SPEED_OF_SOUND
        # shape: (N_STEERING_FREQS,)

        # ── Scan angles ───────────────────────────────────────────────────────
        # SCAN_ANGLES is a list of integers from -90 to +90 (from config.py).
        angles_rad = np.deg2rad(SCAN_ANGLES)
        # shape: (181,)

        # ── Steering matrix via broadcasting ─────────────────────────────────
        #
        # We want W[f, n, a] = exp(-j * k[f] * d * mic[n] * sin(theta[a]))
        #
        # Shapes before broadcasting:
        #   k         (N_STEERING_FREQS,  1,            1          )
        #   mic_idx   (1,                 N_CHANNELS,   1          )
        #   sin(theta)(1,                 1,            N_ANGLES   )
        #
        # NumPy broadcasts these to (N_STEERING_FREQS, N_CHANNELS, N_ANGLES)
        # in one C-level operation — no Python loops.
        #
        # np.sin(angles_rad) uses sin because SCAN_ANGLES uses the broadside
        # convention (0° = straight ahead). The notebook uses cos because it
        # uses the axial convention (90° = straight ahead). Same physics.

        exponent = (
            -1j * MIC_SPACING
            * k[:, np.newaxis, np.newaxis]           # (F,  1,  1)
            * mic_idx[np.newaxis, :, np.newaxis]     # (1,  M,  1)
            * np.sin(angles_rad)[np.newaxis, np.newaxis, :]  # (1, 1, A)
        )
        # shape: (N_STEERING_FREQS, N_CHANNELS, N_ANGLES)

        self._W = np.exp(exponent).astype(np.complex64)
        # Store as complex64 (single precision) — halves memory and is faster
        # on most hardware with negligible accuracy loss for this application.

        # ── FFT bin lookup ────────────────────────────────────────────────────
        # rfft on a real signal of length BLOCK_SIZE gives BLOCK_SIZE//2 + 1
        # complex bins. Each bin k corresponds to frequency k / (BLOCK_SIZE * T).
        # We pre-compute which bin index corresponds to each steering frequency
        # so that per-frame we can do a simple array index instead of a search.

        fft_freqs = np.fft.rfftfreq(BLOCK_SIZE, d=1.0 / SAMPLE_RATE)
        # shape: (BLOCK_SIZE//2 + 1,)

        self._freq_idx = np.array([
            int(np.argmin(np.abs(fft_freqs - f)))
            for f in freqs
        ], dtype=np.intp)
        # shape: (N_STEERING_FREQS,)
        # _freq_idx[i] is the rfft bin closest to freqs[i]

    # ── QThread lifecycle — unchanged ─────────────────────────────────────────

    def process(self, data: np.ndarray):
        """
        Called from UDPWorker via queued signal on the GUI thread.
        Stores the latest frame and overwrites any unprocessed one.
        This intentional drop keeps the display real-time.
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
                # Bandpass filter — same as before, keeps 300–3400 Hz
                filtered = sosfilt(self._sos, data, axis=1).astype(np.float32)
                angle, spectrum = self._beamform(filtered)
                self.result.emit(data, float(angle), spectrum)
            else:
                self.msleep(5)

    # ── Core DSP ───────────────────────────────────────────────────────────────

    def _beamform(self, data: np.ndarray):
        """
        Wideband frequency-domain beamforming with PHAT whitening.

        Parameters
        ----------
        data : (N_CHANNELS, BLOCK_SIZE) float32
            Bandpass-filtered multichannel audio block.

        Returns
        -------
        angle    : float   — DOA estimate in degrees, range [-90, +90]
        spectrum : float32 ndarray shape (len(SCAN_ANGLES),) — normalised [0, 1]

        Step-by-step
        ------------
        1. rfft(data, axis=1)
               One FFT call for all 16 channels simultaneously.
               Output shape: (N_CHANNELS, BLOCK_SIZE//2 + 1)  complex64

        2. PHAT whitening: Xf / (|Xf| + ε)
               Divides every bin by its magnitude, leaving phase only.
               Makes every frequency equally important for timing — loud
               tones don't dominate over quiet ones.

        3. Frequency selection: Xf_phat[:, self._freq_idx].T
               Picks the N_STEERING_FREQS bins we built W for.
               Transposes to shape (N_STEERING_FREQS, N_CHANNELS) so the
               axes match what einsum expects.

        4. einsum('fma, fm -> fa', W.conj(), signal)
               f = frequency,  m = mic,  a = angle
               For each (freq, angle): sum over mics of W*[f,m,a] · X[f,m]
               When the signal's phases match W*'s phases (i.e. source is
               at angle a), the terms add coherently → large |Y|².
               Output shape: (N_STEERING_FREQS, N_ANGLES)

        5. mean(|Y|², axis=0)
               Average power across the frequency axis.
               Output shape: (N_ANGLES,)  — the spatial spectrum
        """

        # Step 1 — FFT all channels at once
        # shape: (N_CHANNELS, BLOCK_SIZE//2 + 1)
        Xf = np.fft.rfft(data, axis=1).astype(np.complex64)

        # Step 2 — PHAT whitening
        # Divide by magnitude so every bin has |X| = 1, phase preserved.
        # The 1e-10 prevents division by zero in silent frames.
        Xf_phat = Xf / (np.abs(Xf) + 1e-10)
        # shape: still (N_CHANNELS, BLOCK_SIZE//2 + 1)

        # Step 3 — Select the N_STEERING_FREQS bins matching W's frequencies
        # Xf_phat[:, self._freq_idx] picks columns → shape (N_CHANNELS, N_STEERING_FREQS)
        # .T transposes                            → shape (N_STEERING_FREQS, N_CHANNELS)
        signal_aligned = Xf_phat[:, self._freq_idx].T
        # shape: (N_STEERING_FREQS, N_CHANNELS)

        # Step 4 — Beamform via Einstein summation
        # self._W.conj() shape: (N_STEERING_FREQS, N_CHANNELS, N_ANGLES)
        # signal_aligned  shape: (N_STEERING_FREQS, N_CHANNELS)
        # Y               shape: (N_STEERING_FREQS, N_ANGLES)
        #
        # Y[f, a] = sum_m  W*[f, m, a] · signal[f, m]
        #
        # W.conj() undoes the steering delay — when the signal's phase matches
        # the expected delay for angle a, the sum is large. See main.typ §7.
        Y = np.einsum('fma, fm -> fa', self._W.conj(), signal_aligned)
        # shape: (N_STEERING_FREQS, N_ANGLES)

        # Step 5 — Wideband power: average |Y|² across frequencies
        P = np.mean(np.abs(Y) ** 2, axis=0).astype(np.float64)
        # shape: (N_ANGLES,)  = (181,)

        # ── DOA estimate ──────────────────────────────────────────────────────
        peak_idx = int(np.argmax(P))
        angle    = float(SCAN_ANGLES[peak_idx])

        # ── Normalise to [0, 1] for the display widgets ───────────────────────
        p_min, p_max = P.min(), P.max()
        if p_max - p_min > 1e-10:
            spectrum = ((P - p_min) / (p_max - p_min)).astype(np.float32)
        else:
            spectrum = np.zeros(len(SCAN_ANGLES), dtype=np.float32)

        return angle, spectrum

    def stop(self):
        self._running = False
        self.wait()




# import numpy as np
# from scipy.signal import butter, sosfilt
# from PyQt6.QtCore import QThread, pyqtSignal, QMutex
# from config import (N_CHANNELS, SAMPLE_RATE, BLOCK_SIZE,
#                     BANDPASS_LOW, BANDPASS_HIGH,
#                     MIC_SPACING, SPEED_OF_SOUND, SCAN_ANGLES)


# class DSPWorker(QThread):
#     # Emits: (raw_waveform, doa_degrees, normalised_srp_spectrum)
#     # waveform shape : (N_CHANNELS, BLOCK_SIZE) float32
#     # spectrum shape : (len(SCAN_ANGLES),)       float32  values in [0, 1]
#     result = pyqtSignal(np.ndarray, float, np.ndarray)

#     def __init__(self):
#         super().__init__()
#         self._pending  = None
#         self._mutex    = QMutex()
#         self._running  = False

#         # Pre-compute Butterworth bandpass filter (done once — expensive)
#         self._sos = butter(
#             4, [BANDPASS_LOW, BANDPASS_HIGH],
#             btype='bandpass', fs=SAMPLE_RATE, output='sos'
#         )

#         # Pre-compute integer sample delays for all mic pairs x all scan angles
#         self._precompute_delays()

#     def _precompute_delays(self):
#         """
#         For every unique mic pair (i, j) and every candidate angle, compute the
#         expected inter-mic delay in samples (integer).

#         With 16 mics there are 16 choose 2 = 120 unique pairs.
#         self._delays[(i, j)] is a 181-element int array (one value per scan angle).
#         """
#         angles_rad = np.deg2rad(SCAN_ANGLES)
#         mic_pos    = np.arange(N_CHANNELS) * MIC_SPACING   # [0.0, 0.05, ..., 0.75] m

#         self._delays = {}
#         for i in range(N_CHANNELS):
#             for j in range(i + 1, N_CHANNELS):
#                 # Path length difference in metres for each candidate angle
#                 d = (mic_pos[i] - mic_pos[j]) * np.sin(angles_rad)
#                 # Convert to integer sample delay
#                 self._delays[(i, j)] = (d / SPEED_OF_SOUND * SAMPLE_RATE).astype(int)

#     def process(self, data: np.ndarray):
#         """
#         Called from UDPWorker via Qt signal — stores the latest frame.
#         If a frame is already waiting (DSP is still busy), it is overwritten.
#         This intentionally drops stale frames to keep the display real-time.
#         """
#         self._mutex.lock()
#         self._pending = data
#         self._mutex.unlock()

#     def run(self):
#         self._running = True
#         while self._running:
#             self._mutex.lock()
#             data          = self._pending
#             self._pending = None
#             self._mutex.unlock()

#             if data is not None:
#                 filtered          = sosfilt(self._sos, data, axis=1).astype(np.float32)
#                 angle, spectrum   = self._srp_phat(filtered)
#                 self.result.emit(data, float(angle), spectrum)
#             else:
#                 self.msleep(5)   # nothing pending — sleep 5 ms

#     def _srp_phat(self, data: np.ndarray):
#         """
#         Steered Response Power with PHAse Transform (SRP-PHAT).

#         With 16 channels there are 120 mic pairs.  The inner Python loop over
#         pairs is the bottleneck; consider replacing with vectorised NumPy or
#         moving to a C extension if CPU load becomes an issue.

#         Returns:
#             angle    (float)           — DOA estimate in degrees [-90, +90]
#             spectrum (np.ndarray f32)  — normalised power per scan angle [0, 1]
#         """
#         n_fft = data.shape[1]   # = BLOCK_SIZE = 256
#         P     = np.zeros(len(SCAN_ANGLES), dtype=np.float64)

#         for i in range(N_CHANNELS):
#             for j in range(i + 1, N_CHANNELS):
#                 Xi    = np.fft.rfft(data[i], n=n_fft)
#                 Xj    = np.fft.rfft(data[j], n=n_fft)
#                 GCC   = Xi * np.conj(Xj)
#                 PHAT  = GCC / (np.abs(GCC) + 1e-10)
#                 gcc_t = np.real(np.fft.irfft(PHAT, n=n_fft))

#                 delays = self._delays[(i, j)]
#                 for a_idx, tau in enumerate(delays):
#                     P[a_idx] += gcc_t[int(tau) % n_fft]

#         peak_idx = int(np.argmax(P))
#         angle    = float(SCAN_ANGLES[peak_idx])

#         # Normalise to [0, 1] for display
#         p_min, p_max = P.min(), P.max()
#         if p_max - p_min > 1e-10:
#             spectrum = ((P - p_min) / (p_max - p_min)).astype(np.float32)
#         else:
#             spectrum = np.zeros(len(SCAN_ANGLES), dtype=np.float32)

#         return angle, spectrum

#     def stop(self):
#         self._running = False
#         self.wait()
