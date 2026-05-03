import socket
import struct
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from config import (UDP_IP, UDP_PORT, BUFFER_SIZE,
                    N_CHANNELS, BLOCK_SIZE,
                    FRAMES_PER_BATCH, FRAME_SIZE,
                    SYNC_WORD, EXPECTED_PKT_SIZE,
                    SAMPLES_PER_PACKET, ACCUMULATE_PACKETS,
                    VREF_MV, FULLSCALE_CODE)

# struct format for one frame: big-endian uint32 sync + 16 signed int16 channels
_FRAME_FMT = ">I16h"   # I = uint32, 16h = 16 x int16, all big-endian


def _parse_packet(data: bytes):
    """
    Parse one 144-byte UDP payload from the AD7606.

    Returns a float32 ndarray of shape (N_CHANNELS, FRAMES_PER_BATCH) — i.e.
    (16, 4): 16 channels, 4 new samples each — normalised to [-1.0, +1.0].
    Returns None if the packet is the wrong size or any frame has a bad sync word.
    """
    if len(data) != EXPECTED_PKT_SIZE:
        return None

    # out[channel, sample_within_packet]
    out = np.empty((N_CHANNELS, FRAMES_PER_BATCH), dtype=np.float32)

    for f in range(FRAMES_PER_BATCH):
        offset = f * FRAME_SIZE
        fields = struct.unpack_from(_FRAME_FMT, data, offset)
        sync     = fields[0]           # first field is the uint32 sync word
        channels = fields[1:]          # remaining 16 fields are int16 samples

        if sync != SYNC_WORD:
            return None               # bad sync — drop entire packet

        for ch in range(N_CHANNELS):
            out[ch, f] = channels[ch] / FULLSCALE_CODE   # normalise to ±1.0

    return out


class UDPWorker(QThread):
    """
    Receives AD7606 UDP packets, validates them, accumulates ACCUMULATE_PACKETS
    packets (= BLOCK_SIZE samples per channel), then emits one float32 array of
    shape (N_CHANNELS, BLOCK_SIZE) for the DSP worker to process.
    """
    raw_packet = pyqtSignal(np.ndarray)   # shape (N_CHANNELS, BLOCK_SIZE) float32
    error      = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        self._running = True

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # 4 MB kernel receive buffer — absorbs bursts during DSP processing
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        except OSError:
            pass   # not fatal; some OS configs restrict this without root

        sock.settimeout(1.0)   # allows clean stop via _running flag

        try:
            sock.bind((UDP_IP, UDP_PORT))
        except OSError as e:
            self.error.emit(f"Cannot bind {UDP_IP}:{UDP_PORT} — {e}")
            return

        # Accumulation buffer: collect ACCUMULATE_PACKETS packets before emitting
        # buf[:, col] is filled left-to-right as packets arrive
        buf     = np.zeros((N_CHANNELS, BLOCK_SIZE), dtype=np.float32)
        col     = 0   # next write position (in samples, step = SAMPLES_PER_PACKET)

        while self._running:
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue   # check _running flag, then wait again
            except Exception as e:
                self.error.emit(str(e))
                break

            frame = _parse_packet(data)
            if frame is None:
                continue   # bad size or bad sync — discard silently

            # frame.shape = (16, 4): write 4 new samples into the buffer
            end = col + SAMPLES_PER_PACKET
            buf[:, col:end] = frame
            col = end

            if col >= BLOCK_SIZE:
                # Buffer full — emit a copy and reset
                self.raw_packet.emit(buf.copy())
                buf[:] = 0.0
                col = 0

        sock.close()

    def stop(self):
        self._running = False
        self.wait()
