import socket
import struct
import time
import math
import itertools
import numpy as np

# Import your hardware parameters
import config
from config import UDP_IP, UDP_PORT, SYNC_WORD, N_CHANNELS

# --- DYNAMIC PARAMETER DISCOVERY ---
# We use getattr to handle cases where names might vary slightly
FRAMES_PER_PKT = getattr(config, 'FRAMES_PER_PKT', 32) 
# The size of one frame: 4 bytes (sync) + (N_CHANNELS * 2 bytes)
FRAME_SIZE_BYTES = 4 + (N_CHANNELS * 2)
EXPECTED_SIZE = FRAMES_PER_PKT * FRAME_SIZE_BYTES

def generate_test_payloads(count=1000):
    print(f"Configuring test for {N_CHANNELS} channels and {FRAMES_PER_PKT} frames...")
    print(f"Target Packet Size: {EXPECTED_SIZE} bytes")
    
    payloads = []
    for p in range(count):
        packet_bytes = bytearray()
        
        for f in range(FRAMES_PER_PKT):
            # 1. Prepare simulated channel data (16-bit signed)
            channels = []
            for ch in range(N_CHANNELS):
                # Frequency varies by channel so you can see them distinct in the GUI
                t = (p * FRAMES_PER_PKT + f) * 0.02 + (ch * 0.2)
                val = int(math.sin(t) * 32760)
                channels.append(val)
            
            # 2. Pack Frame: Sync Word (Uint32) + Channels (N x Int16)
            # Format string: e.g., ">I16h" for 16 channels
            fmt = f">I{N_CHANNELS}h"
            try:
                frame_data = struct.pack(fmt, SYNC_WORD, *channels)
                packet_bytes.extend(frame_data)
            except struct.error as e:
                print(f"Struct Error: Check if N_CHANNELS ({N_CHANNELS}) matches your data.")
                raise e
                
        payloads.append(bytes(packet_bytes))
    return payloads

def run_stress_test():
    payloads = generate_test_payloads()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Increase OS send buffer to prevent packet loss at high speeds
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
    
    print(f"\nSending to {UDP_IP}:{UDP_PORT} | Sync: {hex(SYNC_WORD)}")
    
    packets_sent = 0
    start_time = time.time()
    last_report = start_time
    
    try:
        # Blast packets as fast as possible
        for payload in itertools.cycle(payloads):
            sock.sendto(payload, (UDP_IP, UDP_PORT))
            packets_sent += 1
            
            now = time.time()
            if now - last_report >= 1.0:
                elapsed = now - last_report
                rate = packets_sent / elapsed
                mbps = (rate * EXPECTED_SIZE * 8) / 1_000_000
                print(f"Rate: {rate:,.0f} pkt/s | Throughput: {mbps:.2f} Mbps")
                packets_sent = 0
                last_report = now
                
    except KeyboardInterrupt:
        print("\nTest stopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    run_stress_test()