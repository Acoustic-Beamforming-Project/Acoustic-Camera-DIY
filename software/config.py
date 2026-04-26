# config.py — single source of truth for all constants

# --- Network ---
UDP_IP      = "0.0.0.0"
UDP_PORT    = 5005
BUFFER_SIZE = 4096        # bytes per UDP packet

# --- Hardware ---
N_CHANNELS     = 8
SAMPLE_RATE    = 48000    # Hz
ADC_BITS       = 16
MIC_SPACING    = 0.05     # meters
SPEED_OF_SOUND = 343.0    # m/s

# --- DSP ---
BLOCK_SIZE    = 256
BANDPASS_LOW  = 300
BANDPASS_HIGH = 3400
SCAN_ANGLES   = list(range(-90, 91, 1))

# --- Display ---
PLOT_HISTORY     = 500
WAVEFORM_RATE_HZ = 30
SPECTRUM_RATE_HZ = 15

# --- Sh3rawy Radar Colors ---
BG_COLOR = "#12121a"
PANEL_COLOR = "#161620"
CARD_COLOR_START = "#1e1e2a"
CARD_COLOR_END = "#252535"
ACCENT_COLOR = "#ff3366"  # DOA/Peak color
LIVE_COLOR = "#00ff55"
TEXT_COLOR = "#d0d0d0"
BORDER_COLOR = "#353550"

CHANNEL_COLORS = [
    '#00e5ff', '#ff5252', '#69f0ae', '#ffd740',
    '#b388ff', '#ff9100', '#40c4ff', '#ff4081'
]
