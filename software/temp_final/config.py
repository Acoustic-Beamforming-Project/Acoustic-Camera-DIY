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
BG_COLOR        = "#0d0d0d"   # near-black, not navy
PANEL_COLOR     = "#111111"   # panels, slightly lighter
CARD_COLOR      = "#161616"   # channel cards — single flat color, no gradient
ACCENT_COLOR    = "#e8ff47"   # acid yellow-green — punchy, not pink
LIVE_COLOR      = "#39d353"   # GitHub-green for live indicators
TEXT_COLOR      = "#c9c9c9"
DIM_COLOR       = "#555555"   # for secondary labels, axis ticks
BORDER_COLOR    = "#2a2a2a"   # barely-there borders

# 16 colors — one per channel
CHANNEL_COLORS = [
    '#38bdf8', '#f87171', '#4ade80', '#facc15',
    '#c084fc', '#fb923c', '#22d3ee', '#f472b6',
    '#a78bfa', '#34d399', '#818cf8', '#fb7185',
    '#2dd4bf', '#e879f9', '#86efac', '#fbbf24',
]
