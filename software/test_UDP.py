import socket, numpy as np, time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    # 8 channels x 256 samples = 2048 int16 values = 4096 bytes
    fake = np.random.randint(-3000, 3000,
                             size=(256, 8), dtype=np.int16)
    sock.sendto(fake.tobytes(), ("127.0.0.1", 5005))
    time.sleep(0.005)   # ~200 packets per second