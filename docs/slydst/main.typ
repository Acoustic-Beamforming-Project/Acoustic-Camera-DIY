#import "@preview/slydst:0.1.5": *

#show: slides.with(
  title: "Acoustic DOA Radar — Software Architecture",
  subtitle: "Threading, PyQt6 Signals, and the SRP-PHAT Pipeline",
  authors: "AD7606 · 16-Channel Acoustic Camera",
  subslide-numbering: "(i)",
)

#show raw: set block(
  fill: rgb("#1a1a1a").lighten(80%),
  width: 100%,
  inset: 1em,
  radius: 4pt,
)

#set text(font: "Segoe UI", size: 13pt)

// ─────────────────────────────────────────────────────────────────────────────
== Outline
#outline()

// ─────────────────────────────────────────────────────────────────────────────
= Why the Architecture Matters

== The Problem We Are Solving

The system must do several things simultaneously and without dropping data:

- *Receive* UDP packets from the STM32 over Ethernet at \~48 kHz (16 channels)
- *Process* each block of 1216 samples through a bandpass filter and SRP-PHAT (120 mic-pair GCC-PHAT operations per frame)
- *Render* waveforms, spectra, a zoomable channel view, and a live camera overlay at 30 fps
- *Never* let the GUI freeze, and *never* let DSP lag starve the display

If any of these tasks blocks the others, the system either drops audio data, freezes the UI, or produces stale DOA estimates.
The architecture is the answer to this tension.

== What Makes This Non-Trivial

#table(
  columns: (auto, 1fr, 1fr),
  stroke: 0.5pt + rgb("#444444"),
  inset: 0.6em,
  fill: (col, row) => if row == 0 { rgb("#2a2a2a") } else { rgb("#1a1a1a").lighten(5%) },
  text(fill: white)[*Concern*], text(fill: white)[*Naive approach*], text(fill: white)[*What breaks*],
  [Network I/O], [`recvfrom` on main thread], [GUI freezes during recv],
  [DSP (SRP-PHAT)], [Compute inline in slot], [120 GCC-PHAT loops block render],
  [Camera capture], [`cv2.read()` on main thread], [UI stutters, missed frames],
  [Rendering], [Repaint on every DSP result], [DSP/s collapses under paint load],
)

#v(0.5em)
Each concern needs its own execution context.
Python's GIL would normally prevent true parallelism — PyQt6 sidesteps this completely.

// ─────────────────────────────────────────────────────────────────────────────
= PyQt6 Concurrency Primitives

== QThread — Not Just a Python Thread

`QThread` is a Qt-managed OS thread. It is *not* a Python `threading.Thread`.

```python
class UDPWorker(QThread):
    raw_packet = pyqtSignal(np.ndarray)   # signal, not a return value

    def run(self):          # executes in the OS thread
        while self._running:
            data, _ = sock.recvfrom(BUFFER_SIZE)
            frame = _parse_packet(data)
            self.raw_packet.emit(frame)   # crosses thread boundary safely
```

Key points:
- `run()` executes on a *separate OS thread*, fully outside the GUI event loop
- Signals emitted from a `QThread` are automatically *queued* across the thread boundary
- The receiving slot executes on the *GUI thread* — no explicit locking needed for UI updates
- `self.msleep(5)` yields the OS thread without holding the GIL

== The Qt Signal/Slot System

Signals are the *only* safe way to communicate between threads in Qt.

```python
# Wire-up in MainWindow.setup_connections()
self._udp.raw_packet.connect(self._dsp.process)   # UDP → DSP
self._dsp.result.connect(self._on_result)          # DSP → GUI
self._udp.pkt_counted.connect(self._on_pkt_counted)
```

#v(0.5em)

#table(
  columns: (auto, 1fr),
  stroke: 0.5pt + rgb("#444444"),
  inset: 0.6em,
  fill: (col, row) => if row == 0 { rgb("#2a2a2a") } else { rgb("#1a1a1a").lighten(5%) },
  text(fill: white)[*Connection type*], text(fill: white)[*What it means*],
  [Same thread], [Direct call — synchronous, like a function call],
  [Cross-thread (default)], [Queued — argument is serialised into the event loop queue],
  [`Qt.BlockingQueuedConnection`], [Caller blocks until slot finishes — used for sync handshakes],
)

#v(0.5em)
The cross-thread queued connection is the critical mechanism: `raw_packet.emit(buf.copy())` on the UDP OS thread posts a *copy* of the numpy array into Qt's event queue. The GUI thread picks it up and calls `self._dsp.process()` safely, with no mutex needed.

== Escaping the GIL

Python's Global Interpreter Lock (GIL) prevents two Python threads from executing bytecode simultaneously. This would cripple a pure-Python concurrency model.

Qt bypasses it in two ways used here:

*1. I/O waits release the GIL automatically.*
`sock.recvfrom()` is a blocking C-level system call. Python releases the GIL during it. The DSP thread can run Python/NumPy code freely while the UDP thread waits for the next packet.

*2. NumPy operations release the GIL.*
`sosfilt`, `np.fft.rfft`, `np.fft.irfft`, and `np.abs` are all implemented in C/Fortran. The GIL is released during their execution. This means the DSP thread's inner loop over 120 mic pairs is largely GIL-free.

*3. Qt's event loop is C++.*
Signal delivery, widget painting, and timer dispatch all happen inside Qt's C++ runtime. The GIL is only re-acquired when a Python slot is invoked.

In practice: UDP I/O, DSP compute, and GUI rendering run concurrently with only brief GIL re-acquisitions at slot boundaries.

// ─────────────────────────────────────────────────────────────────────────────
= The Data Pipeline

== From UDP Packet to DOA Estimate

Every sample travels a deterministic path through the system:

```
STM32 firmware
    │  UDP/IP (WIZ820io, port 5002)
    ▼
UDPWorker.run()                         [OS Thread 1]
    │  recvfrom(BUFFER_SIZE=2048)
    │  _parse_packet()  →  validate sync 0xDEADBEEF, unpack 32 frames × 36 bytes
    │  accumulate into buf[16, 1216]
    │  raw_packet.emit(buf.copy())       ← queued signal crossing thread boundary
    ▼
DSPWorker.process()  [slot, GUI thread, but immediately stores to _pending]
    │
DSPWorker.run()                         [OS Thread 2]
    │  sosfilt(sos, data)               ← Butterworth bandpass 300–3400 Hz
    │  _srp_phat(filtered)
    │     └─ 120 mic-pair GCC-PHAT
    │         rfft → GCC → PHAT → irfft → accumulate P[181]
    │  result.emit(waveform, angle, spectrum)   ← queued back to GUI
    ▼
MainWindow._on_result()                 [GUI Thread]
    │  ChannelCard[i].update_data()     × 16
    │  SpectrumPlot.update_spectrum()
    │  ChannelZoomView.update_channel_data()
    │  CameraOverlayView.update_overlay()   ← stores only, no repaint
    ▼
CameraThread.run()                      [OS Thread 3]
    │  cv2.VideoCapture.read()          ← GIL released during C++ frame grab
    │  frame_ready.emit(QImage)         ← queued to GUI
    ▼
_OverlayCanvas._on_frame()             [GUI Thread]
    │  IIR smooth spectrum
    │  self._canvas.tick() → update()  ← schedules ONE repaint
```

== Drop Policy and Back-pressure

The system deliberately *drops stale frames* rather than queuing them.

```python
# DSPWorker.process() — called from GUI thread via queued signal
def process(self, data: np.ndarray):
    self._mutex.lock()
    self._pending = data        # overwrites any unprocessed frame
    self._mutex.unlock()
```

If DSP is slower than the UDP receive rate, `_pending` is overwritten on each new packet. The DSP thread always processes the *most recent* data available. This keeps the display real-time at the cost of occasionally skipping a frame — which is the correct trade-off for a live acoustic camera.

The camera overlay uses the same philosophy: `update_overlay()` only writes to `self._spectrum`. The paint is driven by the camera thread at 30 fps. If DSP runs faster than 30 fps, intermediate results are simply read on the next camera frame.

// ─────────────────────────────────────────────────────────────────────────────
= Class Design

== CRC Cards — Core Classes

*CRC* (Class · Responsibility · Collaborator) cards describe each class's contract.

#v(0.5em)

```
┌────────────────────────────────────────────────────────────────┐
│  CLASS: UDPWorker  (QThread)                                   │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Bind UDP socket (IP, port)      config (UDP_IP, UDP_PORT,   │
│  • Receive & validate packets        BUFFER_SIZE, SYNC_WORD,   │
│  • Unpack int16 → float32 ±1.0       FRAMES_PER_BATCH,         │
│  • Accumulate into (16, 1216) buf    FRAME_SIZE, N_CHANNELS)   │
│  • Emit raw_packet when full       DSPWorker.process [signal]  │
│  • Emit pkt_counted per packet     MainWindow._on_pkt_counted  │
│  • Emit error on socket failure    MainWindow._on_udp_error    │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CLASS: DSPWorker  (QThread)                                   │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Pre-compute Butterworth SOS     config (SAMPLE_RATE,        │
│  • Pre-compute all delay tables      BANDPASS_LOW/HIGH,        │
│    for 120 mic pairs × 181 angles    MIC_SPACING, SCAN_ANGLES) │
│  • Apply bandpass filter           UDPWorker [receives signal] │
│  • Run SRP-PHAT, return angle      MainWindow._on_result       │
│    and normalised spectrum           [emits result signal]     │
│  • Drop stale pending frames       QMutex (internal)           │
└────────────────────────────────────────────────────────────────┘
```

== CRC Cards — Display Classes

```
┌────────────────────────────────────────────────────────────────┐
│  CLASS: MainWindow  (QMainWindow)                              │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Own and wire all workers        UDPWorker, DSPWorker        │
│  • Build tab layout (Dashboard /   ChannelCard[16]             │
│    Acoustic Camera)                SpectrumPlot                │
│  • Route DSP results to widgets    ChannelZoomView             │
│  • Maintain status bar metrics     CameraOverlayView           │
│  • Handle connect / stop lifecycle config (all display consts) │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CLASS: CameraOverlayView  (QWidget)                           │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Own CameraThread lifecycle      CameraThread                │
│  • Store DSP spectrum (no repaint) _OverlayCanvas              │
│  • IIR-smooth spectrum per frame   config (SCAN_ANGLES,        │
│  • Expose start/stop_camera()        ACCENT_COLOR)             │
│  • Drive repaints from cam frames  MainWindow [caller]         │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CLASS: CameraThread  (QThread)                                │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Open cv2.VideoCapture(index)    OpenCV (cv2)                │
│  • Read frames at target fps       CameraOverlayView._on_frame │
│  • Convert BGR → RGB QImage          [frame_ready signal]      │
│  • Emit cam_error on device fault  CameraOverlayView._on_cam_  │
│  • Release capture on stop()         error [cam_error signal]  │
└────────────────────────────────────────────────────────────────┘
```

== CRC Cards — Plot Widgets

```
┌────────────────────────────────────────────────────────────────┐
│  CLASS: ChannelCard  (QFrame)                                  │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Display mini waveform plot      pyqtgraph PlotWidget        │
│  • Show peak amplitude value       MainWindow (16 instances)   │
│  • Colour-coded per channel index  config (CHANNEL_COLORS)     │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CLASS: SpectrumPlot  (QFrame)                                 │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Plot SRP-PHAT power vs angle    pyqtgraph PlotWidget        │
│  • Show peak DOA dashed line       MainWindow                  │
│  • Update at DSP frame rate        config (ACCENT_COLOR)       │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CLASS: ChannelZoomView  (QFrame)                              │
│  ───────────────────────────────────────────────────────────── │
│  RESPONSIBILITIES                  COLLABORATORS               │
│  • Show full-res waveform for one  pyqtgraph PlotWidget        │
│    user-selected channel           MainWindow                  │
│  • Enable mouse zoom / pan         config (N_CHANNELS,         │
│  • Show PEAK and RMS per frame       CHANNEL_COLORS)           │
└────────────────────────────────────────────────────────────────┘
```

// ─────────────────────────────────────────────────────────────────────────────
= Full System Interaction

== Class Interaction Map

```
                        ┌─────────────┐
                        │  config.py  │
                        │  (constants)│
                        └──────┬──────┘
                               │ imported by all
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐      ┌──────▼──────┐      ┌──────▼──────────┐
   │  UDPWorker  │      │  DSPWorker  │      │   MainWindow    │
   │  (QThread)  │      │  (QThread)  │      │  (QMainWindow)  │
   │             │      │             │      │                 │
   │ run()       │      │ run()       │      │ owns & wires    │
   │  socket I/O │      │  bandpass   │      │ all workers     │
   │  parse pkt  │      │  SRP-PHAT   │      │ and widgets     │
   └──────┬──────┘      └──────┬──────┘      └────────┬────────┘
          │                    │                      │
          │ raw_packet         │ result               │ creates
          │ [signal]           │ [signal]             │
          │                    │                      │
          └──────────┬─────────┘              ┌───────▼─────────────────────┐
                     │                        │         Widgets             │
                     │ both signals           │                             │
                     │ queued to GUI thread   │  ┌─────────────────────┐    │
                     │                        │  │  ChannelCard × 16   │    │
                     └────────────────────────►  ├─────────────────────┤    │
                                              │  │  SpectrumPlot       │    │
                                              │  ├─────────────────────┤    │
                                              │  │  ChannelZoomView    │    │
                                              │  ├─────────────────────┤    │
                                              │  │ CameraOverlayView   │    │
                                              │  │   ┌──────────────┐  │    │
                                              │  │   │ CameraThread │  │    │
                                              │  │   │  (QThread)   │  │    │
                                              │  │   │  cv2 frames  │  │    │
                                              │  │   └──────┬───────┘  │    │
                                              │  │          │ 30 fps   │    │
                                              │  │   _OverlayCanvas    │    │
                                              │  │   paintEvent()      │    │
                                              │  └─────────────────────┘    │
                                              └─────────────────────────────┘
```

== Thread Ownership Map

Three OS threads run concurrently. The GUI thread is never blocked.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    OS THREAD 1 — UDP                        │
  │  UDPWorker.run()                                            │
  │  • sock.recvfrom()  ←     GIL released (C syscall)          │
  │  • struct.unpack_from()                                     │
  │  • numpy float32 normalisation                              │
  │  • raw_packet.emit()  ──►  posted to Qt event queue         │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │                    OS THREAD 2 — DSP                        │
  │  DSPWorker.run()                                            │
  │  • scipy sosfilt()     ← GIL released (Fortran)             │
  │  • numpy rfft/irfft()  ← GIL released (C)                   │
  │  • 120-pair GCC-PHAT loop                                   │
  │  • result.emit()  ──►  posted to Qt event queue             │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │                    OS THREAD 3 — CAMERA                     │
  │  CameraThread.run()                                         │
  │  • cv2.VideoCapture.read()  ←   GIL released (C++)          │
  │  • cv2.cvtColor BGR→RGB                                     │
  │  • frame_ready.emit()  ──►  posted to Qt event queue        │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │                    GUI THREAD (main)                        │
  │  Qt Event Loop                                              │
  │  • Dequeues signals, calls slots                            │
  │  • _on_result()  → updates 16 cards + 3 plots               │
  │  • _on_frame()   → IIR smooth + schedules repaint           │
  │  • paintEvent()  → composites camera frame + curve          │
  │  • User input (buttons, spinbox, slider)                    │
  │  NEVER blocked by I/O or compute                            │
  └─────────────────────────────────────────────────────────────┘
```

// ─────────────────────────────────────────────────────────────────────────────
= Key Design Decisions

== Decisions Worth Knowing Before You Contribute

These are the choices that look surprising until you understand the reason.

#v(0.5em)

*1. DSP result update never triggers a repaint in CameraOverlayView.*

`update_overlay()` only writes `self._spectrum`. The camera thread at 30 fps is the sole repaint driver. If DSP runs at 40 fps and camera at 30, the curve is simply sampled at 30 fps — no lost work, no paint thrashing.

*2. DSPWorker drops, not queues, stale frames.*

`self._pending = data` overwrites any unprocessed frame. The result is always the most recent audio block. A FIFO queue here would cause latency to grow unboundedly under load.

*3. `buf.copy()` before `raw_packet.emit()`.*

The accumulation buffer is reused. Emitting `buf` directly would be a race condition — by the time the DSP thread reads it, UDP has already written new data into it. The copy is a deliberate and necessary cost.

*4. Pre-computed delay tables in `_precompute_delays()`.*

At startup, all 120 × 181 integer delays are computed once. The inner SRP-PHAT loop then does integer array indexing, not floating-point trigonometry per frame. This is the single biggest DSP performance lever.

*5. IIR smoother on the display side, not the DSP side.*

The smoothing `α = 0.30` lives in `CameraOverlayView`, not `DSPWorker`. DSP always emits the true estimate. Smoothing is a display concern — it makes the visualisation feel fluid without corrupting the underlying measurement.

// ─────────────────────────────────────────────────────────────────────────────
= Summary

== What We Built and Why It Works

#table(
  columns: (1fr, 1fr),
  stroke: 0.5pt + rgb("#444444"),
  inset: 0.7em,
  fill: (col, row) => if row == 0 { rgb("#2a2a2a") } else { rgb("#1a1a1a").lighten(5%) },
  text(fill: white)[*Mechanism*], text(fill: white)[*Role in the system*],
  [`QThread` + OS thread], [True concurrency for I/O and compute],
  [Qt queued signals], [Safe cross-thread data transfer, no mutexes on UI path],
  [GIL release in C extensions], [NumPy, SciPy, OpenCV run in parallel],
  [Drop policy on DSP], [Bounded latency, always-fresh estimates],
  [Camera-driven repaints], [DSP throughput fully decoupled from render cost],
  [Pre-computed delay tables], [SRP-PHAT loop is index lookup, not trig],
  [IIR on display side], [Smooth visuals without corrupting measurements],
)

#v(1em)

The architecture is deliberately *flat*: three worker threads, one GUI thread, one signal per handoff. There is no scheduler, no message broker, no shared mutable state outside the single `_pending` slot protected by one mutex. If you need to add a feature, find the right thread boundary, add a signal, and wire it in `setup_connections()`.