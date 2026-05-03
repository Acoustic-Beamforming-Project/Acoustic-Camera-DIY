# config.py — single source of truth for all constants
# Updated for AD7606 16-channel ADC over WIZ820io (W5200) Ethernet

# --- Network ---
UDP_IP      = "127.0.0.1"
UDP_PORT    = 5000          # must match STM32 firmware (was 5005, now 5000)
BUFFER_SIZE = 2048          # recvfrom ceiling — larger than any expected packet

# --- AD7606 Packet Protocol ---
# Each UDP datagram = 4 frames batched together = 144 bytes total
# Frame layout (36 bytes):
#   [0:4]  sync word 0xDEADBEEF  (big-endian uint32)
#   [4:36] CH0..CH15              (big-endian int16, 16 values x 2 bytes = 32 bytes)
FRAMES_PER_BATCH   = 4
FRAME_SIZE         = 36          # 4 sync bytes + 16 channels x 2 bytes
SYNC_WORD          = 0xDEADBEEF
EXPECTED_PKT_SIZE  = FRAMES_PER_BATCH * FRAME_SIZE   # = 144 bytes

# --- Hardware ---
N_CHANNELS     = 16         # AD7606 has 16 channels (was 8)
SAMPLE_RATE    = 48000      # Hz — must match STM32 ADC configuration
ADC_BITS       = 16
VREF_MV        = 5000       # ±5 V range (RANGE pin = GND on AD7606)
FULLSCALE_CODE = 32767      # 0x7FFF — max positive int16
MIC_SPACING    = 0.05       # meters between adjacent microphones
SPEED_OF_SOUND = 343.0      # m/s

# --- DSP ---
# BLOCK_SIZE = samples per processing frame.
# Each UDP packet carries 4 ADC frames (4 samples per channel).
# We accumulate ACCUMULATE_PACKETS packets before running SRP-PHAT.
# 4 samples/pkt x 64 pkts = 256 samples — same block size as before.
SAMPLES_PER_PACKET = FRAMES_PER_BATCH          # = 4 samples per channel per packet
ACCUMULATE_PACKETS = 64                        # collect this many packets -> one DSP frame
BLOCK_SIZE         = SAMPLES_PER_PACKET * ACCUMULATE_PACKETS   # = 256

BANDPASS_LOW  = 300
BANDPASS_HIGH = 3400
SCAN_ANGLES   = list(range(-90, 91, 1))

# --- Display ---
PLOT_HISTORY     = 500
WAVEFORM_RATE_HZ = 30
SPECTRUM_RATE_HZ = 15

# --- Colors ---
BG_COLOR = "#12121a"
PANEL_COLOR = "#161620"
CARD_COLOR_START = "#1e1e2a"
CARD_COLOR_END = "#252535"
ACCENT_COLOR = "#ff3366"
LIVE_COLOR = "#00ff55"
TEXT_COLOR = "#d0d0d0"
BORDER_COLOR = "#353550"

# 16 colors — one per channel
CHANNEL_COLORS = [
    '#00e5ff', '#ff5252', '#69f0ae', '#ffd740',
    '#b388ff', '#ff9100', '#40c4ff', '#ff4081',
    '#e040fb', '#00bcd4', '#8bc34a', '#ff6e40',
    '#26c6da', '#ef5350', '#ab47bc', '#66bb6a',
]
