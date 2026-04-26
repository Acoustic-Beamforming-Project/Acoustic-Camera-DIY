import socket
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from config import UDP_IP, UDP_PORT, BUFFER_SIZE, N_CHANNELS, BLOCK_SIZE

class UDPWorker(QThread):
    raw_packet = pyqtSignal(np.ndarray)  # shape (N_CHANNELS, BLOCK_SIZE) float32
    error      = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.bind((UDP_IP, UDP_PORT))
        sock.settimeout(1.0)             # CRITICAL: allows clean stop

        while self._running:
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                arr /= 32768.0           # normalize to -1.0 .. +1.0

                # STM32 sends interleaved: [ch0s0, ch1s0,...,ch7s0, ch0s1,...]
                arr = arr.reshape(-1, N_CHANNELS).T  # -> (N_CHANNELS, N_SAMPLES)

                if arr.shape[1] >= BLOCK_SIZE:
                    self.raw_packet.emit(arr[:, :BLOCK_SIZE].copy())

            except socket.timeout:
                continue                 # check _running flag and loop back
            except Exception as e:
                self.error.emit(str(e))
                break

        sock.close()

    def stop(self):
        self._running = False
        self.wait()
