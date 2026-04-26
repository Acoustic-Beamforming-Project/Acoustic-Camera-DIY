# Acoustic Camera DIY — Project Context for Gemini

## What This Project Is
A DIY acoustic camera that:
- Captures audio from a microphone array connected to an **STM32 microcontroller**
- Streams raw multi-channel audio data to a PC over **USB Serial**
- Runs **beamforming algorithms** (MVDR, MUSIC) in Python to localize sound sources
- Overlays a **heatmap** of sound intensity on a live **OpenCV camera feed**
- Displays results in a **PyQt6 desktop GUI** with real-time graphs

## Repo Structure
```
Acoustic-Camera-DIY/
├── GEMINI.md           ← you are here (project-wide context)
├── firmware/           ← STM32 C code (HAL, DMA, USB CDC)
├── hardware/           ← schematics, PCB, BOM
├── simulation/         ← Python algorithm prototyping (numpy/scipy)
├── software/           ← PyQt6 desktop application
└── docs/               ← reports, diagrams, references
```

## Core Tech Stack
- **MCU**: STM32 (HAL library, DMA for ADC, USB CDC for serial)
- **PC Language**: Python 3.11+
- **GUI**: PyQt6 + PyQtGraph (real-time plots)
- **Vision**: OpenCV (camera capture + heatmap overlay)
- **DSP**: NumPy, SciPy (beamforming, FFT)
- **Serial**: PySerial (USB communication with STM32)

## Key Domain Vocabulary
- **Beamforming**: Spatial filtering using phase differences between mics
- **MVDR** (Capon): Minimum Variance Distortionless Response beamformer
- **MUSIC**: MUltiple SIgnal Classification (subspace method)
- **Steering vector**: Array response vector for a given direction
- **Array manifold**: Collection of steering vectors across all angles
- **DOA**: Direction of Arrival estimation
- **Heatmap**: 2D energy map overlaid on camera frame (cv2.applyColorMap)
- **USB CDC**: USB Communication Device Class — how STM32 appears as serial port

## Threading Architecture (DO NOT suggest alternatives)
```
MainThread (PyQt6 UI)
├── SerialWorker(QThread)   — reads STM32 packets, emits signal(np.ndarray)
├── CameraWorker(QThread)   — reads OpenCV frames, emits signal(QImage)
└── BeamformWorker(QThread) — runs MVDR/MUSIC, emits signal(np.ndarray heatmap)
```
Always use **Qt signals/slots** for inter-thread communication. Never use shared global variables or threading.Thread.

## STM32 Packet Format
Each USB packet: `[0xAA, channel_id (1 byte), value_high (1 byte), value_low (1 byte), 0xFF]`
- 8 microphone channels, 16-bit ADC values
- Baud: 115200 (USB CDC, actual rate is USB full-speed)
- Parse with `struct.unpack` or manual byte masking

## Coding Conventions
- All files use **type hints**
- NumPy arrays: always specify dtype explicitly (`np.float32`, `np.complex64`)
- PyQt6 signals: defined as class variables using `pyqtSignal`
- No blocking calls on the main thread — ever
- PyQtGraph plots update via `plot.setData()`, not `plot.clear()` + `plot.plot()`

## What To Avoid
- Do NOT suggest matplotlib for real-time plots (use PyQtGraph)
- Do NOT suggest Tkinter, Dear PyGui, or Streamlit
- Do NOT use threading.Thread — use QThread
- Do NOT use time.sleep() in Qt threads — use QTimer
- Do NOT suggest Arduino — hardware is STM32 with HAL