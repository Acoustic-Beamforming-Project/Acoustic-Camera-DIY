#!/usr/bin/env python3
"""
udp_receiver.py — STM32 AD7606 ADC UDP packet receiver
=======================================================

Receives 144-byte UDP datagrams from the WIZ820io (W5200) Ethernet module
running on the STM32F411.  Each datagram is 4 batched ADC frames:

    Frame layout (36 bytes each, 4 frames = 144 bytes total):
        Byte  0– 3 : 0xDEADBEEF  sync word
        Byte  4– 5 : CH0  (big-endian int16, ±5 V range)
        Byte  6– 7 : CH1
        ...
        Byte 34–35 : CH15

Usage:
    python udp_receiver.py [OPTIONS]

    -p, --port      UDP listen port            (default: 5000)
    -i, --ip        Listen interface           (default: 0.0.0.0)
    -o, --output    Binary log file path       (default: None, no logging)
    -t, --timeout   Socket receive timeout, s  (default: 5.0)
    -v, --verbose   Print decoded channel data (default: False)
    --max-packets   Stop after N packets       (default: 0 = run forever)

Examples:
    python udp_receiver.py
    python udp_receiver.py -p 5000 -o capture.bin
    python udp_receiver.py -v --max-packets 1000
"""

import argparse
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Protocol constants (must match ad7606_config.h) ──────────────────────────

EXPECTED_PACKET_SIZE  = 144       # AD7606_BATCH_SIZE
FRAMES_PER_BATCH      = 4         # AD7606_BATCH_FRAMES
FRAME_SIZE            = 36        # AD7606_FRAME_SIZE  (4 sync + 32 data)
CHANNELS_PER_FRAME    = 16        # AD7606_NUM_CHANNELS
SYNC_WORD             = 0xDEADBEEF
SYNC_BYTES            = 4
VREF_MV               = 5000      # ±5 V range (RANGE pin = GND)
FULLSCALE_CODE        = 32767     # 0x7FFF

# ── Stats dataclass ───────────────────────────────────────────────────────────

@dataclass
class ReceiverStats:
    packets_received:  int   = 0
    packets_bad_size:  int   = 0
    packets_bad_sync:  int   = 0
    bytes_received:    int   = 0
    start_time:        float = field(default_factory=time.monotonic)
    last_report_time:  float = field(default_factory=time.monotonic)
    last_report_count: int   = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.start_time

    def packets_per_sec(self) -> float:
        """Instantaneous rate over the last reporting interval."""
        now    = time.monotonic()
        dt     = now - self.last_report_time
        if dt < 1e-6:
            return 0.0
        rate = (self.packets_received - self.last_report_count) / dt
        self.last_report_time  = now
        self.last_report_count = self.packets_received
        return rate

    def average_rate(self) -> float:
        elapsed = self.elapsed()
        if elapsed < 1e-6:
            return 0.0
        return self.packets_received / elapsed

    def throughput_kbps(self) -> float:
        elapsed = self.elapsed()
        if elapsed < 1e-6:
            return 0.0
        return (self.bytes_received * 8) / elapsed / 1000.0


# ── Frame / batch parsing ─────────────────────────────────────────────────────

@dataclass
class ADC_Frame:
    """One decoded AD7606 frame: 16 channels of int16 raw samples."""
    sync_ok:   bool
    channels:  tuple   # 16 × int (raw int16)

    def channel_mv(self, ch: int) -> float:
        """Convert raw code to millivolts (linear, ±5 V range)."""
        if not 0 <= ch < CHANNELS_PER_FRAME:
            raise IndexError(f"Channel index {ch} out of range 0–15")
        return (self.channels[ch] * VREF_MV) / FULLSCALE_CODE


def parse_frame(data: bytes, offset: int) -> ADC_Frame:
    """
    Parse one 36-byte frame starting at data[offset].

    Frame memory layout (big-endian):
        [0:4]   sync word  0xDEADBEEF
        [4:36]  CH0–CH15   int16 big-endian
    """
    sync = struct.unpack_from(">I", data, offset)[0]
    # 16 signed 16-bit big-endian integers starting at offset+4
    channels = struct.unpack_from(">16h", data, offset + SYNC_BYTES)
    return ADC_Frame(sync_ok=(sync == SYNC_WORD), channels=channels)


def parse_batch(data: bytes) -> Optional[list]:
    """
    Parse a 144-byte UDP payload into a list of 4 ADC_Frame objects.
    Returns None if the payload size is wrong.
    """
    if len(data) != EXPECTED_PACKET_SIZE:
        return None
    frames = []
    for i in range(FRAMES_PER_BATCH):
        frames.append(parse_frame(data, i * FRAME_SIZE))
    return frames


# ── Optional binary log ───────────────────────────────────────────────────────

class BinaryLogger:
    """
    Writes raw 144-byte UDP payloads to a binary file, prefixed with a
    compact 8-byte header per packet:

        [4 bytes: monotonic_ms uint32] [4 bytes: packet_seq uint32]

    Total per record: 8 + 144 = 152 bytes.
    Open the log in numpy with:
        data = np.fromfile("capture.bin", dtype=np.uint8).reshape(-1, 152)
    """
    HEADER_FMT  = ">II"    # monotonic_ms, seq
    HEADER_SIZE = struct.calcsize(HEADER_FMT)   # 8
    RECORD_SIZE = HEADER_SIZE + EXPECTED_PACKET_SIZE  # 152

    def __init__(self, path: Path):
        self._path = path
        self._fh   = open(path, "wb")
        self._seq  = 0
        self._t0   = time.monotonic()
        print(f"[LOG] Binary log open: {path}  (record={self.RECORD_SIZE} B)")

    def write(self, payload: bytes) -> None:
        ms_now = int((time.monotonic() - self._t0) * 1000) & 0xFFFFFFFF
        header = struct.pack(self.HEADER_FMT, ms_now, self._seq)
        self._fh.write(header)
        self._fh.write(payload)
        self._seq += 1

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()
        size_mb = self._path.stat().st_size / (1024 * 1024)
        print(f"[LOG] Binary log closed: {self._path} "
              f"({self._seq} records, {size_mb:.2f} MB)")


# ── Display helpers ───────────────────────────────────────────────────────────

# ANSI escape codes (safe on Linux/macOS terminals)
_ANSI_CLEAR_LINE  = "\r\033[K"
_ANSI_BOLD        = "\033[1m"
_ANSI_RESET       = "\033[0m"
_ANSI_GREEN       = "\033[32m"
_ANSI_YELLOW      = "\033[33m"
_ANSI_RED         = "\033[31m"
_ANSI_CYAN        = "\033[36m"

def _ansi(code: str, text: str) -> str:
    """Wrap text in ANSI code + reset."""
    return f"{code}{text}{_ANSI_RESET}"


def print_status(stats: ReceiverStats, rate: float, addr: tuple) -> None:
    """Overwrite the current terminal line with a live stats summary."""
    elapsed  = stats.elapsed()
    ok_count = stats.packets_received
    bad      = stats.packets_bad_size + stats.packets_bad_sync
    throughput = stats.throughput_kbps()

    color = _ANSI_GREEN if bad == 0 else _ANSI_YELLOW
    line  = (
        f"{_ANSI_CLEAR_LINE}"
        f"{_ansi(_ANSI_CYAN, 'PKT')}: {ok_count:>10,} | "
        f"{_ansi(color, 'RATE')}: {rate:>8.1f} pkt/s | "
        f"{_ansi(_ANSI_CYAN, 'BW')}: {throughput:>7.1f} kbit/s | "
        f"{_ansi(_ANSI_CYAN, 'UP')}: {elapsed:>8.1f} s | "
        f"{_ansi(_ANSI_RED if bad else _ANSI_GREEN, 'BAD')}: {bad}"
    )
    sys.stdout.write(line)
    sys.stdout.flush()


def print_verbose_frame(frame_idx: int, frame: ADC_Frame, pkt_num: int) -> None:
    """Pretty-print a single decoded ADC frame."""
    sync_str = _ansi(_ANSI_GREEN, "OK") if frame.sync_ok else _ansi(_ANSI_RED, "BAD")
    print(f"\n  Pkt {pkt_num:>6}  Frame {frame_idx}  sync={sync_str}")
    for ch in range(CHANNELS_PER_FRAME):
        mv = frame.channel_mv(ch)
        bar_len = int(abs(mv) / VREF_MV * 20)
        bar = ("█" * bar_len).ljust(20)
        sign = "+" if mv >= 0 else "-"
        print(f"    CH{ch:>2}: {sign}{abs(mv):>7.1f} mV  |{bar}|  raw={frame.channels[ch]:>6}")


def print_final_report(stats: ReceiverStats) -> None:
    """Print a summary report on exit."""
    print(f"\n\n{'─'*60}")
    print(f"  {_ansi(_ANSI_BOLD, 'Session Summary')}")
    print(f"{'─'*60}")
    print(f"  Duration          : {stats.elapsed():.2f} s")
    print(f"  Packets received  : {stats.packets_received:,}")
    print(f"  Average rate      : {stats.average_rate():.1f} pkt/s")
    print(f"  Total bytes       : {stats.bytes_received:,} B  "
          f"({stats.bytes_received/1024/1024:.2f} MB)")
    print(f"  Avg throughput    : {stats.throughput_kbps():.1f} kbit/s")
    if stats.packets_bad_size:
        print(f"  {_ansi(_ANSI_RED, 'Bad size (dropped)')}: {stats.packets_bad_size}")
    if stats.packets_bad_sync:
        print(f"  {_ansi(_ANSI_RED, 'Bad sync (logged)')}: {stats.packets_bad_sync}")
    print(f"{'─'*60}\n")


# ── Signal handling ───────────────────────────────────────────────────────────

_shutdown_requested = False

def _sigint_handler(signum, frame):
    """Catch Ctrl+C and set a flag — avoids raising inside socket.recvfrom."""
    global _shutdown_requested
    _shutdown_requested = True


# ── Core receive loop ─────────────────────────────────────────────────────────

def run_receiver(
    listen_ip:   str,
    listen_port: int,
    timeout_s:   float,
    log_path:    Optional[Path],
    verbose:     bool,
    max_packets: int,
) -> None:
    """
    Main receive loop.

    Creates a UDP socket, binds it, then loops calling recvfrom().
    Each valid 144-byte datagram is:
        1. Validated (size, sync word in each frame)
        2. Optionally decoded and printed (--verbose)
        3. Optionally written to a binary log file (--output)
        4. Counted for live stats

    The loop exits on:
        - Ctrl+C  (SIGINT)
        - --max-packets reached
        - Unrecoverable socket error
    """
    global _shutdown_requested

    signal.signal(signal.SIGINT, _sigint_handler)

    stats  = ReceiverStats()
    logger: Optional[BinaryLogger] = None

    if log_path is not None:
        logger = BinaryLogger(log_path)

    # ── Create and bind socket ──────────────────────────────────────────────
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Increase OS receive buffer to handle bursts without kernel-level drops.
    # 4 MB should absorb several hundred milliseconds of ADC data at full rate.
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass  # Not fatal; some platforms restrict this without root

    sock.settimeout(timeout_s)

    try:
        sock.bind((listen_ip, listen_port))
    except OSError as e:
        print(f"[ERROR] Cannot bind {listen_ip}:{listen_port} — {e}", file=sys.stderr)
        sys.exit(1)

    print(f"{_ansi(_ANSI_BOLD, 'STM32 AD7606 UDP Receiver')}")
    print(f"  Listen   : {listen_ip}:{listen_port}")
    print(f"  Expected : {EXPECTED_PACKET_SIZE} B/packet  "
          f"({FRAMES_PER_BATCH} frames × {FRAME_SIZE} B)")
    print(f"  Logging  : {log_path if log_path else 'disabled'}")
    print(f"  Verbose  : {'yes' if verbose else 'no'}")
    print(f"  Max pkts : {max_packets if max_packets else 'unlimited'}")
    print(f"\n  Waiting for packets…  (Ctrl+C to stop)\n")

    report_interval_s = 1.0   # update terminal stats every second
    last_flush_time   = time.monotonic()

    try:
        while not _shutdown_requested:
            # ── Check max-packets limit ─────────────────────────────────────
            if max_packets and stats.packets_received >= max_packets:
                print(f"\n[INFO] Reached --max-packets {max_packets}, stopping.")
                break

            # ── Receive one datagram ────────────────────────────────────────
            try:
                payload, addr = sock.recvfrom(2048)  # 2048 >> 144, avoids truncation
            except socket.timeout:
                # No data in timeout_s seconds — update display and loop.
                # This also gives us a chance to check _shutdown_requested.
                rate = stats.packets_per_sec()   # resets interval timer
                print_status(stats, rate, ("", 0))
                continue
            except OSError as e:
                if _shutdown_requested:
                    break
                print(f"\n[ERROR] recvfrom: {e}", file=sys.stderr)
                break

            # ── Validate size ───────────────────────────────────────────────
            if len(payload) != EXPECTED_PACKET_SIZE:
                stats.packets_bad_size += 1
                print(f"\n[WARN] Unexpected packet size: {len(payload)} B "
                      f"(expected {EXPECTED_PACKET_SIZE}) from {addr[0]}:{addr[1]}",
                      file=sys.stderr)
                continue

            # ── Parse all 4 frames ──────────────────────────────────────────
            frames = parse_batch(payload)   # always returns list here (size checked above)

            # Count frames with bad sync words
            bad_sync_in_pkt = sum(1 for f in frames if not f.sync_ok)
            if bad_sync_in_pkt:
                stats.packets_bad_sync += 1
                print(f"\n[WARN] {bad_sync_in_pkt} frame(s) with bad sync in pkt "
                      f"{stats.packets_received} from {addr[0]}:{addr[1]}",
                      file=sys.stderr)

            # ── Update stats ────────────────────────────────────────────────
            stats.packets_received += 1
            stats.bytes_received   += len(payload)

            # ── Optional binary log ─────────────────────────────────────────
            if logger is not None:
                logger.write(payload)
                # Flush to disk every 5 seconds to limit data loss on crash
                now = time.monotonic()
                if now - last_flush_time >= 5.0:
                    logger.flush()
                    last_flush_time = now

            # ── Optional verbose decode ─────────────────────────────────────
            if verbose:
                for i, frame in enumerate(frames):
                    print_verbose_frame(i, frame, stats.packets_received)

            # ── Periodic status line (non-verbose mode) ─────────────────────
            if not verbose:
                now = time.monotonic()
                if now - stats.last_report_time >= report_interval_s:
                    rate = stats.packets_per_sec()
                    print_status(stats, rate, addr)

    finally:
        sock.close()
        if logger is not None:
            logger.close()
        print_final_report(stats)


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="STM32 AD7606 UDP packet receiver",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-p", "--port",        type=int,   default=5000,
                   help="UDP listen port")
    p.add_argument("-i", "--ip",          type=str,   default="0.0.0.0",
                   help="Listen interface IP")
    p.add_argument("-o", "--output",      type=Path,  default=None,
                   help="Binary log file path (omit to disable)")
    p.add_argument("-t", "--timeout",     type=float, default=5.0,
                   help="Socket receive timeout in seconds")
    p.add_argument("-v", "--verbose",     action="store_true",
                   help="Decode and print all channel values")
    p.add_argument("--max-packets",       type=int,   default=0,
                   help="Stop after N packets (0 = run forever)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_receiver(
        listen_ip   = args.ip,
        listen_port = args.port,
        timeout_s   = args.timeout,
        log_path    = args.output,
        verbose     = args.verbose,
        max_packets = args.max_packets,
    )
