"""
udp_test_sender.py — Acoustic Beamforming Test Signal Generator
================================================================
Sends synthetic 16-channel acoustic waveforms over UDP to the DOA radar system.

Packet format (matches AD7606 firmware protocol):
  Each UDP datagram = FRAMES_PER_BATCH (32) frames × FRAME_SIZE (36) bytes = 1152 bytes
  Frame layout:
    [0:4]   sync word  0xDEADBEEF  (big-endian uint32)
    [4:36]  CH0..CH15              (big-endian int16, 16 values × 2 bytes)

Usage:
  python udp_test_sender.py
  Then follow the interactive prompts.
"""

import socket
import struct
import time
import threading
import argparse
import math
import sys
import numpy as np

# ── Protocol constants (must match config.py) ─────────────────────────────────
UDP_IP            = "127.0.0.1"
UDP_PORT          = 5002
FRAMES_PER_BATCH  = 32
FRAME_SIZE        = 36          # 4 sync bytes + 16 ch × 2 bytes
SYNC_WORD         = 0xDEADBEEF
EXPECTED_PKT_SIZE = FRAMES_PER_BATCH * FRAME_SIZE   # 1152 bytes
N_CHANNELS        = 16
FULLSCALE_CODE    = 32767       # int16 max → maps to ±1.0 in the receiver
SAMPLE_RATE       = 48000       # Hz — must match firmware
MIC_SPACING       = 0.05        # meters between adjacent mics
SPEED_OF_SOUND    = 343.0       # m/s
SAMPLES_PER_PKT   = FRAMES_PER_BATCH   # 32 new samples per channel per packet

TARGET_PKT_RATE   = 2000        # packets / second

_FRAME_FMT = ">I16h"           # big-endian: uint32 + 16× int16


# ── Signal generation ─────────────────────────────────────────────────────────

def _itd_samples(channel: int, doa_deg: float) -> float:
    """
    Inter-channel delay (in samples) for a plane wave arriving at `doa_deg`
    degrees relative to channel 0.

    Positive angle = source to the right of the array.
    """
    sin_theta = math.sin(math.radians(doa_deg))
    delay_s   = channel * MIC_SPACING * sin_theta / SPEED_OF_SOUND
    return delay_s * SAMPLE_RATE   # convert to samples


class SignalGenerator:
    """
    Stateful generator: keeps a running sample counter so the waveform is
    phase-continuous across packets.
    """

    def __init__(self, mode: str, doa_deg: float,
                 freq: float = 1000.0, amplitude: float = 0.85):
        """
        Parameters
        ----------
        mode      : 'wideband' or 'singleband'
        doa_deg   : direction of arrival in degrees  [-90 … +90]
        freq      : centre / single frequency in Hz  (used for singleband only)
        amplitude : signal amplitude [0.0 … 1.0]
        """
        self.mode      = mode
        self.doa_deg   = doa_deg
        self.freq      = freq
        self.amplitude = amplitude

        # Running sample index for phase continuity
        self._sample_idx = 0

        # Pre-compute per-channel delays (fractional samples)
        self._delays = [_itd_samples(ch, doa_deg) for ch in range(N_CHANNELS)]

        # Wideband: pick a handful of decorrelated frequency components
        if mode == 'wideband':
            self._wb_freqs  = [300, 600, 900, 1400, 2200, 3400]   # Hz
            self._wb_phases = [np.random.uniform(0, 2 * math.pi)
                               for _ in self._wb_freqs]            # random init phases
        
        # Noise amplitude for realism
        self._noise_level = 0.05

    def next_packet_samples(self) -> np.ndarray:
        """
        Returns float64 array shape (N_CHANNELS, SAMPLES_PER_PKT).
        Values are in [-1.0, +1.0].
        """
        n   = SAMPLES_PER_PKT
        t0  = self._sample_idx
        t   = np.arange(t0, t0 + n, dtype=np.float64) / SAMPLE_RATE
        out = np.zeros((N_CHANNELS, n), dtype=np.float64)

        for ch in range(N_CHANNELS):
            d   = self._delays[ch] / SAMPLE_RATE   # delay in seconds
            t_d = t - d                             # delayed time axis

            if self.mode == 'singleband':
                sig = self.amplitude * np.sin(2 * math.pi * self.freq * t_d)

            else:  # wideband
                sig = np.zeros(n, dtype=np.float64)
                per_comp = self.amplitude / len(self._wb_freqs)
                for f, phi in zip(self._wb_freqs, self._wb_phases):
                    sig += per_comp * np.sin(2 * math.pi * f * t_d + phi)

            # Add small white-noise floor
            sig += self._noise_level * np.random.standard_normal(n)
            sig  = np.clip(sig, -1.0, 1.0)
            out[ch] = sig

        self._sample_idx += n
        return out


# ── Packet encoding ───────────────────────────────────────────────────────────

def encode_packet(samples: np.ndarray) -> bytes:
    """
    Encode (N_CHANNELS, SAMPLES_PER_PKT) float64 → 1152-byte UDP payload.

    samples[ch, frame] is normalised to [-1.0, +1.0]; we scale to int16.
    """
    payload = bytearray(EXPECTED_PKT_SIZE)
    for f in range(FRAMES_PER_BATCH):
        offset = f * FRAME_SIZE
        ch_ints = [int(np.clip(samples[ch, f], -1.0, 1.0) * FULLSCALE_CODE)
                   for ch in range(N_CHANNELS)]
        struct.pack_into(_FRAME_FMT, payload, offset, SYNC_WORD, *ch_ints)
    return bytes(payload)


# ── Sender thread ─────────────────────────────────────────────────────────────

class UDPSender:
    def __init__(self, gen: SignalGenerator):
        self._gen    = gen
        self._sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

        # Stats
        self.total_sent  = 0
        self.last_pkt_s  = 0.0
        self._stat_lock  = threading.Lock()

    def start(self):
        self._stop.clear()
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=3.0)
        self._sock.close()

    def _run(self):
        interval     = 1.0 / TARGET_PKT_RATE   # seconds between packets
        dest         = (UDP_IP, UDP_PORT)
        count        = 0
        stat_t0      = time.perf_counter()
        stat_count   = 0

        t_next = time.perf_counter()

        while not self._stop.is_set():
            now = time.perf_counter()
            if now < t_next:
                # Busy-spin for sub-millisecond precision
                # (sleep(0) yields to OS scheduler but stays tight)
                time.sleep(0)
                continue

            t_next += interval

            samples = self._gen.next_packet_samples()
            pkt     = encode_packet(samples)
            try:
                self._sock.sendto(pkt, dest)
            except OSError:
                break   # socket closed

            count       += 1
            stat_count  += 1

            # Update stats every second
            elapsed = now - stat_t0
            if elapsed >= 1.0:
                with self._stat_lock:
                    self.total_sent  = count
                    self.last_pkt_s  = stat_count / elapsed
                stat_t0   = now
                stat_count = 0


# ── Interactive CLI ───────────────────────────────────────────────────────────

BANNER = r"""
╔══════════════════════════════════════════════════════════════════╗
║        ACOUSTIC BEAMFORMING — UDP TEST SIGNAL GENERATOR         ║
║         AD7606  |  16 CH  |  48 kHz  |  ~2000 pkt/s            ║
╚══════════════════════════════════════════════════════════════════╝
"""

def prompt_int(msg: str, lo: int, hi: int, default: int) -> int:
    while True:
        raw = input(f"  {msg} [{lo}…{hi}, default={default}]: ").strip()
        if raw == "":
            return default
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"    ✗ Enter an integer between {lo} and {hi}.")

def prompt_float(msg: str, lo: float, hi: float, default: float) -> float:
    while True:
        raw = input(f"  {msg} [{lo}…{hi}, default={default}]: ").strip()
        if raw == "":
            return default
        try:
            v = float(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"    ✗ Enter a number between {lo} and {hi}.")

def prompt_choice(msg: str, choices: list[str], default: str) -> str:
    opts = "/".join(choices)
    while True:
        raw = input(f"  {msg} [{opts}, default={default}]: ").strip().lower()
        if raw == "":
            return default
        if raw in [c.lower() for c in choices]:
            return raw
        print(f"    ✗ Choose one of: {opts}")


def main():
    print(BANNER)
    print(f"  Target: {UDP_IP}:{UDP_PORT}   Rate: ~{TARGET_PKT_RATE} pkt/s\n")

    # ── Mode ─────────────────────────────────────────────────────────────────
    mode = prompt_choice(
        "Signal mode (wideband = multi-freq broadband, singleband = pure tone)",
        ["wideband", "singleband"],
        default="wideband"
    )

    # ── DOA ──────────────────────────────────────────────────────────────────
    doa = prompt_int(
        "Direction of Arrival in degrees (negative = left, positive = right)",
        lo=-90, hi=90, default=30
    )

    # ── Frequency (singleband only) ───────────────────────────────────────────
    freq = 1000.0
    if mode == "singleband":
        freq = float(prompt_int(
            "Tone frequency (Hz)",
            lo=100, hi=3400, default=1000
        ))

    # ── Amplitude ─────────────────────────────────────────────────────────────
    amp_pct = prompt_int(
        "Signal amplitude % (100 = full-scale ±1.0)",
        lo=1, hi=100, default=85
    )
    amplitude = amp_pct / 100.0

    # ── Confirm ───────────────────────────────────────────────────────────────
    print()
    print("  ┌─ Configuration ──────────────────────────────────────┐")
    print(f"  │  Mode       : {mode.upper():<38}│")
    print(f"  │  DOA        : {doa:+d}°{'':<37}│")
    if mode == "singleband":
        print(f"  │  Frequency  : {freq:.0f} Hz{'':<35}│")
    print(f"  │  Amplitude  : {amp_pct}%{'':<38}│")
    print(f"  │  Destination: {UDP_IP}:{UDP_PORT:<38}│")
    print(f"  │  Rate       : ~{TARGET_PKT_RATE} pkt/s{'':<31}│")
    print(f"  │  Pkt size   : {EXPECTED_PKT_SIZE} bytes (FRAMES_PER_BATCH={FRAMES_PER_BATCH}){'':<10}│")
    print("  └──────────────────────────────────────────────────────┘")
    print()

    go = input("  Start sending? [Y/n]: ").strip().lower()
    if go == "n":
        print("  Aborted.")
        return

    print()
    print("  Sending… (press Ctrl+C to stop)\n")

    gen    = SignalGenerator(mode=mode, doa_deg=doa, freq=freq, amplitude=amplitude)
    sender = UDPSender(gen)
    sender.start()

    # ── Live stats loop ───────────────────────────────────────────────────────
    try:
        t0 = time.time()
        while True:
            time.sleep(1.0)
            with sender._stat_lock:
                pkt_s = sender.last_pkt_s
                total = sender.total_sent
            elapsed = time.time() - t0
            data_mb = total * EXPECTED_PKT_SIZE / 1e6
            print(
                f"  ▲ {pkt_s:6.0f} pkt/s   "
                f"Σ {total:>8,} pkts   "
                f"≈ {data_mb:6.2f} MB sent   "
                f"elapsed {elapsed:5.0f}s   "
                f"DOA={doa:+d}°",
                end="\r", flush=True
            )
    except KeyboardInterrupt:
        print("\n\n  Stopping…")
        sender.stop()
        print(f"  Done. Sent {sender.total_sent:,} packets total.")


if __name__ == "__main__":
    main()