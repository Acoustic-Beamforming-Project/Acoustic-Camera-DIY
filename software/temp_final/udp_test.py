"""
udp_test.py  —  AD7606 UDP packet simulator
============================================

Sends synthetic 16-channel audio to the DOA radar software over UDP,
using the exact same packet format as the STM32 firmware:

    Packet = 4 frames × 36 bytes = 144 bytes
    Frame  = [0xDEADBEEF uint32 BE] + [CH0..CH15 int16 BE]

Three test modes selected by the MODE constant at the top:

    "harmonics"  —  Each of the 16 channels receives the same 1 kHz sine
                    but with a progressive phase delay that simulates a
                    sound source arriving from a known angle (TARGET_ANGLE).
                    The DOA indicator should lock onto TARGET_ANGLE.

    "sweep"      —  Same as harmonics but TARGET_ANGLE sweeps slowly from
                    -60° to +60° and back.  Watch the DOA indicator track it.

    "noise"      —  Pure white noise on all 16 channels, equal amplitude.
                    No spatial coherence — DOA output will be random/jumpy.
                    Use this to verify the channel cards all light up and
                    the software doesn't crash under constant load.

Usage:
    python udp_test.py                  # uses defaults below
    python udp_test.py --mode sweep
    python udp_test.py --mode noise
    python udp_test.py --mode harmonics --angle 35
    python udp_test.py --ip 192.168.1.50 --port 5000
"""

import argparse
import struct
import time
import socket
import numpy as np

# ── Configuration — edit these or pass as CLI args ────────────────────────────

MODE         = "harmonics"   # "harmonics" | "sweep" | "noise"
TARGET_IP    = "127.0.0.1"   # destination IP  (loopback = same PC)
TARGET_PORT  = 5000          # must match UDP_PORT in config.py
TARGET_ANGLE = 30.0          # degrees — used only in "harmonics" mode

# ── AD7606 protocol constants — must match config.py ──────────────────────────

N_CHANNELS      = 16
FRAMES_PER_PKT  = 32
SYNC_WORD       = 0xDEADBEEF
FRAME_FMT       = ">I16h"        # big-endian: uint32 sync + 16× int16
FRAME_SIZE      = struct.calcsize(FRAME_FMT)   # = 36 bytes
PACKET_SIZE     = FRAMES_PER_PKT * FRAME_SIZE  # = 144 bytes

# ── Physical constants ────────────────────────────────────────────────────────

SAMPLE_RATE    = 48000    # Hz — must match STM32 ADC rate
MIC_SPACING    = 0.05     # metres between adjacent mics
SPEED_OF_SOUND = 343.0    # m/s
FULLSCALE      = 32767    # int16 max  (maps to +1.0 normalised)

# ── Signal parameters ─────────────────────────────────────────────────────────

TONE_FREQ      = 1000     # Hz — must be inside the 300–3400 Hz bandpass
TONE_AMPLITUDE = 0.6      # fraction of full scale  (0.0 – 1.0)
NOISE_FLOOR    = 0.02     # fraction of full scale added to every mode


# ─────────────────────────────────────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────────────────────────────────────

def _delays_for_angle(angle_deg: float) -> np.ndarray:
    """
    Return the propagation delay in SAMPLES for each of the 16 microphones
    relative to microphone 0, for a plane wave arriving from angle_deg.

    Physics:
        path_difference[i] = mic_pos[i] * sin(angle)
        delay_seconds[i]   = path_difference[i] / speed_of_sound
        delay_samples[i]   = delay_seconds[i]   * sample_rate

    Positive delay = sound arrives LATER at that mic.
    """
    angle_rad = np.deg2rad(angle_deg)
    mic_pos   = np.arange(N_CHANNELS) * MIC_SPACING          # [0, 0.05, ..., 0.75] m
    return mic_pos * np.sin(angle_rad) / SPEED_OF_SOUND * SAMPLE_RATE  # float samples


def _build_packet(samples_16ch: np.ndarray) -> bytes:
    """
    Pack a (N_CHANNELS, FRAMES_PER_PKT) float32 array into a 144-byte
    AD7606 UDP packet.

    samples_16ch[ch, frame] must be in [-1.0, +1.0].
    Values are clipped, scaled to int16, and packed big-endian with sync words.
    """
    # Clip and scale to int16 range
    raw = np.clip(samples_16ch, -1.0, 1.0)
    raw = (raw * FULLSCALE).astype(np.int16)  # shape (16, 4)

    buf = bytearray(PACKET_SIZE)
    for f in range(FRAMES_PER_PKT):
        offset   = f * FRAME_SIZE
        ch_vals  = tuple(int(raw[ch, f]) for ch in range(N_CHANNELS))
        struct.pack_into(FRAME_FMT, buf, offset, SYNC_WORD, *ch_vals)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# Signal generators  —  each returns (16, FRAMES_PER_PKT) float32
# ─────────────────────────────────────────────────────────────────────────────

def gen_harmonic_frame(t0: float, angle_deg: float) -> np.ndarray:
    """
    Generate FRAMES_PER_PKT samples for each of 16 channels.

    Each channel receives a 1 kHz sine delayed by the propagation time
    corresponding to angle_deg.  The SRP-PHAT algorithm should recover
    angle_deg from the cross-correlations.

    t0: absolute time of the first sample in this frame (seconds).
        Increment by FRAMES_PER_PKT / SAMPLE_RATE between calls.
    """
    delays  = _delays_for_angle(angle_deg)           # shape (16,) float samples
    t_frame = t0 + np.arange(FRAMES_PER_PKT) / SAMPLE_RATE   # shape (4,) seconds

    out = np.zeros((N_CHANNELS, FRAMES_PER_PKT), dtype=np.float32)
    for ch in range(N_CHANNELS):
        # Delay this channel by shifting its time axis
        t_delayed = t_frame - delays[ch] / SAMPLE_RATE
        sig        = TONE_AMPLITUDE * np.sin(2 * np.pi * TONE_FREQ * t_delayed)
        noise      = NOISE_FLOOR    * np.random.normal(size=FRAMES_PER_PKT)
        out[ch]    = (sig + noise).astype(np.float32)
    return out


def gen_noise_frame() -> np.ndarray:
    """
    White noise on all 16 channels — equal power, no spatial coherence.
    DOA output will be random.  Use to stress-test the UI and UDP path.
    """
    return (np.random.uniform(-TONE_AMPLITUDE, TONE_AMPLITUDE,
                              size=(N_CHANNELS, FRAMES_PER_PKT))
            .astype(np.float32))


# ─────────────────────────────────────────────────────────────────────────────
# Main sender loop
# ─────────────────────────────────────────────────────────────────────────────

def run(mode: str, ip: str, port: int, angle: float) -> None:
    sock  = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest  = (ip, port)

    # How long to wait between packets so we match the real ADC rate.
    # Real hardware: 1 packet = FRAMES_PER_PKT ADC samples = 4/48000 s ≈ 83 µs
    # We send slightly slower (every 5 ms) to avoid flooding a loopback socket
    # and to keep CPU usage reasonable during testing.
    interval = 0.005   # seconds between packets  (~200 pkt/s)

    t0           = time.monotonic()
    sample_clock = 0.0       # absolute time of current sample (seconds)
    sweep_angle  = 0.0
    sweep_step   = 0.3       # degrees per packet in sweep mode

    sent = 0
    print(f"[udp_test] mode={mode!r}  target={ip}:{port}  "
          f"packet={PACKET_SIZE}B  interval={interval*1000:.1f}ms")
    if mode == "harmonics":
        print(f"[udp_test] fixed angle = {angle:.1f}°  "
              f"→ DOA indicator should read ≈ {angle:.1f}°")
    elif mode == "sweep":
        print(f"[udp_test] sweeping ±60°  →  DOA indicator should track the angle")
    else:
        print(f"[udp_test] white noise  →  DOA indicator will be erratic (expected)")

    print(f"[udp_test] press Ctrl+C to stop\n")

    try:
        while True:
            loop_start = time.monotonic()

            if mode == "harmonics":
                frame = gen_harmonic_frame(sample_clock, angle)

            elif mode == "sweep":
                sweep_angle += sweep_step
                if abs(sweep_angle) > 60.0:
                    sweep_step *= -1
                frame = gen_harmonic_frame(sample_clock, sweep_angle)

            else:  # noise
                frame = gen_noise_frame()

            pkt = _build_packet(frame)
            sock.sendto(pkt, dest)

            # Advance the sample clock by exactly FRAMES_PER_PKT samples
            sample_clock += FRAMES_PER_PKT / SAMPLE_RATE
            sent         += 1

            if sent % 200 == 0:
                elapsed = time.monotonic() - t0
                pps     = sent / elapsed
                current_angle = sweep_angle if mode == "sweep" else angle
                angle_str = f"{current_angle:+.1f}°" if mode != "noise" else "N/A"
                print(f"\r  {sent:>8,} pkts  |  {pps:>7.1f} pkt/s  |  angle: {angle_str}   ",
                      end="", flush=True)

            # Busy-wait for the remainder of the interval to keep timing tight
            elapsed_loop = time.monotonic() - loop_start
            remaining    = interval - elapsed_loop
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        print(f"\n[udp_test] stopped after {sent:,} packets")
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AD7606 UDP test sender")
    p.add_argument("--mode",  choices=["harmonics", "sweep", "noise"],
                   default=MODE)
    p.add_argument("--ip",    default=TARGET_IP,    help="Destination IP")
    p.add_argument("--port",  type=int, default=TARGET_PORT, help="Destination port")
    p.add_argument("--angle", type=float, default=TARGET_ANGLE,
                   help="Fixed source angle in degrees (harmonics mode only)")
    args = p.parse_args()

    run(mode=args.mode, ip=args.ip, port=args.port, angle=args.angle)
