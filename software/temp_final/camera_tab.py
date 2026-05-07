"""
camera_tab.py — Acoustic Camera: live webcam + SRP-PHAT curve overlay.

Layout (inside the tab)
───────────────────────
┌──────────────────────────────────────────────────────────┐
│  CAMERA  [cam selector ▼]  [▶ START / ■ STOP]  ● LIVE   │  ← toolbar
├──────────────────────────────────────────────────────────┤
│                                                          │
│   Live webcam frame                                      │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  SRP-PHAT spectrum curve (same shape as Tab 1)     │  │  ← semi-transparent
│  │  cyan polyline  +  accent dashed peak line         │  │    panel at bottom
│  │  −90°                0°                   +90°     │  │
│  └────────────────────────────────────────────────────┘  │
│   ════════════ heatmap colour bar ════════════════════   │
├──────────────────────────────────────────────────────────┤
│  angle readout │ peak power │ cam FPS                    │  ← info strip
└──────────────────────────────────────────────────────────┘

All compositing is done with NumPy + OpenCV on every camera frame.
"""

import cv2
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QComboBox, QFrame,
                             QSizePolicy)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QImage, QPixmap, QPainter, QPen, QColor, QBrush

from config import (SCAN_ANGLES, ACCENT_COLOR, BORDER_COLOR,
                    DIM_COLOR, LIVE_COLOR, BG_COLOR, PANEL_COLOR)


# ── tuneable constants ─────────────────────────────────────────────────────────

# SRP-PHAT curve panel (drawn at the bottom of the video frame)
_CURVE_PANEL_H   = 0.28   # fraction of frame height the curve panel occupies
_CURVE_PANEL_ALPHA = 0.72 # panel background opacity (0=transparent, 1=opaque)
_CURVE_PAD_X     = 40     # horizontal padding inside the panel (pixels)
_CURVE_PAD_TOP   = 10     # pixels from panel top to curve ceiling
_CURVE_PAD_BOT   = 22     # pixels from curve floor to panel bottom (space for labels)
_CURVE_COLOR     = (0xf8, 0xbd, 0x38)   # BGR ≈ #38bdf8 cyan
_CURVE_THICKNESS = 2
_PEAK_COLOR      = (71, 255, 232)        # BGR ≈ ACCENT_COLOR #e8ff47 yellow-green
_PEAK_THICKNESS  = 2

# Bottom colour bar
_BAR_HEIGHT_PX   = 24

_FONT_FACE  = cv2.FONT_HERSHEY_DUPLEX
_FONT_SCALE = 0.48
_CAM_TIMER_MS = 33   # ~30 fps


class CameraTab(QWidget):
    """
    Drop this widget into a QTabWidget.  Call update_dsp(angle, spectrum)
    whenever a new DSP result arrives — it is thread-safe (stores atomically).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap:    cv2.VideoCapture | None = None
        self._angle:  float      = 0.0
        self._spectrum: np.ndarray = np.zeros(len(SCAN_ANGLES), dtype=np.float32)
        self._frame_count = 0
        self._fps_display = 0.0
        self._fps_timer   = 0

        self._cam_timer = QTimer(self)
        self._cam_timer.timeout.connect(self._grab_and_paint)

        self._init_ui()
        self._populate_cameras()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setStyleSheet(f"background-color: {BG_COLOR};")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        root.addWidget(self._build_toolbar())

        # Video display label — expands to fill available space
        self._video_lbl = QLabel()
        self._video_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
        self._video_lbl.setStyleSheet(
            f"background: #0a0a0a; border: 1px solid {BORDER_COLOR}; border-radius: 6px;"
        )
        self._video_lbl.setText("No camera — press  ▶ START")
        self._video_lbl.setFont(QFont("Segoe UI", 12))
        self._video_lbl.setStyleSheet(
            f"color: {DIM_COLOR}; background: #0a0a0a; "
            f"border: 1px solid {BORDER_COLOR}; border-radius: 6px;"
        )
        root.addWidget(self._video_lbl, stretch=1)

        root.addWidget(self._build_info_strip())

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1a1a25, stop:0.5 #252535, stop:1 #1a1a25);
                border: 2px solid #404060;
                border-radius: 8px;
            }
        """)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)

        title = QLabel("ACOUSTIC CAMERA  —  LIVE OVERLAY")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet(
            "color: #ffffff; letter-spacing: 2px; "
            "padding: 3px 10px; background-color: #2a2a3a; border-radius: 5px;"
        )
        h.addWidget(title)
        h.addStretch()

        cam_lbl = QLabel("CAM:")
        cam_lbl.setFont(QFont("Segoe UI", 9))
        cam_lbl.setStyleSheet(f"color: {DIM_COLOR};")
        h.addWidget(cam_lbl)

        self._cam_combo = QComboBox()
        self._cam_combo.setFixedWidth(160)
        self._cam_combo.setFont(QFont("Segoe UI", 9))
        self._cam_combo.setStyleSheet(f"""
            QComboBox {{
                background: #1a2a35; color: #00ccff;
                border: 1px solid #00ccff40; border-radius: 5px; padding: 3px 6px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: #1a2a35; color: #00ccff;
                selection-background-color: #252535;
            }}
        """)
        h.addWidget(self._cam_combo)

        _btn = lambda text, color: self._make_btn(text, color)

        self._btn_start = QPushButton("▶  START")
        self._btn_start.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #0066dd, stop:1 #004499);
                border: 2px solid #0088ff; border-radius: 6px;
                padding: 5px 16px; color: white;
            }
            QPushButton:hover    { background: #0077ee; }
            QPushButton:disabled { background: #333; border-color: #555; color: #555; }
        """)
        self._btn_start.clicked.connect(self._on_start)
        h.addWidget(self._btn_start)

        self._btn_stop = QPushButton("■  STOP")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._btn_stop.setStyleSheet(
            "QPushButton { background: #3d1f1f; border: 2px solid #f85149; "
            "border-radius: 6px; padding: 5px 16px; color: #f85149; }"
            "QPushButton:disabled { background: #222; border-color: #444; color: #444; }"
        )
        self._btn_stop.clicked.connect(self._on_stop)
        h.addWidget(self._btn_stop)

        self._live_dot = QLabel("●")
        self._live_dot.setStyleSheet(f"color: {LIVE_COLOR}; font-size: 18px;")
        self._live_dot.setVisible(False)
        h.addWidget(self._live_dot)

        return bar

    def _build_info_strip(self) -> QFrame:
        strip = QFrame()
        strip.setFixedHeight(32)
        strip.setStyleSheet(
            f"background: #111111; border: 1px solid {BORDER_COLOR}; border-radius: 5px;"
        )
        h = QHBoxLayout(strip)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(24)

        def _seg(icon, key):
            row = QHBoxLayout()
            row.setSpacing(5)
            il = QLabel(icon)
            il.setFont(QFont("Segoe UI", 8))
            il.setStyleSheet(f"color: {DIM_COLOR};")
            kl = QLabel(key)
            kl.setFont(QFont("Segoe UI", 8))
            kl.setStyleSheet("color: #333333;")
            vl = QLabel("—")
            vl.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            vl.setMinimumWidth(60)
            row.addWidget(il); row.addWidget(kl); row.addWidget(vl)
            return row, vl

        r1, self._info_angle = _seg("◈", "DOA")
        r2, self._info_peak  = _seg("▲", "PEAK POWER")
        r3, self._info_fps   = _seg("⏱", "CAM FPS")

        for r in (r1, r2, r3):
            h.addLayout(r)
        h.addStretch()

        hint = QLabel("heatmap = SRP-PHAT spectrum  |  arrow = DOA estimate")
        hint.setFont(QFont("Segoe UI", 7))
        hint.setStyleSheet("color: #2a2a2a;")
        h.addWidget(hint)

        return strip

    # ── Camera enumeration ────────────────────────────────────────────────────

    def _populate_cameras(self):
        """Try indices 0-4 and list any that open successfully."""
        self._cam_combo.clear()
        found = []
        for idx in range(5):
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                found.append(idx)
                cap.release()
        if found:
            for idx in found:
                self._cam_combo.addItem(f"Camera {idx}", idx)
        else:
            self._cam_combo.addItem("No camera found", -1)

    # ── Start / stop ──────────────────────────────────────────────────────────

    def _on_start(self):
        idx = self._cam_combo.currentData()
        if idx is None or idx < 0:
            print("[camera_tab] No valid camera selected")
            return
        self._cap = cv2.VideoCapture(idx)
        if not self._cap.isOpened():
            print(f"[camera_tab] VideoCapture({idx}) failed to open")
            self._cap = None
            return
        # Test-read one frame — on Linux some indices open but never deliver frames
        ok, frame = self._cap.read()
        if not ok or frame is None:
            print(f"[camera_tab] Camera {idx} opened but first read() failed")
            self._cap.release()
            self._cap = None
            return
        print(f"[camera_tab] Camera {idx} OK — frame shape {frame.shape}")
        self._frame_count = 0
        self._fps_timer   = 0
        self._cam_timer.start(_CAM_TIMER_MS)
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._live_dot.setVisible(True)

    def _on_stop(self):
        self._cam_timer.stop()
        if self._cap:
            self._cap.release()
            self._cap = None
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._live_dot.setVisible(False)
        self._video_lbl.setText("No camera — press  ▶ START")
        self._video_lbl.setStyleSheet(
            f"color: {DIM_COLOR}; background: #0a0a0a; "
            f"border: 1px solid {BORDER_COLOR}; border-radius: 6px;"
        )

    def closeEvent(self, event):
        self._on_stop()
        super().closeEvent(event)

    # ── DSP update (called by MainWindow on every DSP frame) ──────────────────

    def update_dsp(self, angle: float, spectrum: np.ndarray):
        """Thread-safe enough — Python GIL protects simple attribute assignment."""
        self._angle    = angle
        self._spectrum = spectrum.copy()

    # ── Frame compositing ─────────────────────────────────────────────────────

    def _grab_and_paint(self):
        if self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok or frame is None:
            print("[camera_tab] cap.read() failed — check camera index")
            return

        # FPS bookkeeping
        self._frame_count += 1
        self._fps_timer   += _CAM_TIMER_MS
        if self._fps_timer >= 1000:
            self._fps_display = self._frame_count
            self._frame_count = 0
            self._fps_timer   = 0

        frame = self._composite(frame, self._angle, self._spectrum)
        self._display(frame)
        self._update_info_strip()

    def _composite(self, frame: np.ndarray,
                   angle: float, spectrum: np.ndarray) -> np.ndarray:
        """Apply all overlays onto the BGR frame and return the result."""
        h, w = frame.shape[:2]
        out  = frame.copy()
        out  = self._draw_srp_curve(out, h, w, spectrum, angle)
        out  = self._draw_heatmap_bar(out, h, w, spectrum, angle)
        out  = self._draw_angle_text(out, h, w, angle)
        return out

    # ── Overlay layers ────────────────────────────────────────────────────────

    def _draw_srp_curve(self, frame, h, w, spectrum, angle):
        """
        Draws the SRP-PHAT spectrum as a polyline overlaid on the bottom portion
        of the frame — same shape as the SpectrumPlot in Tab 1.

        A semi-transparent dark panel is composited first so the curve is legible
        over any camera background.  Then:
          • Cyan polyline   — the normalised power curve
          • Dashed accent vertical line  — the detected DOA angle (peak marker)
          • Axis labels and grid ticks
        """
        out = frame.copy()

        panel_h = max(int(h * _CURVE_PANEL_H), 80)
        panel_y = h - _BAR_HEIGHT_PX - panel_h   # sits just above the colour bar

        # ── Semi-transparent dark background panel ────────────────────────────
        overlay = out.copy()
        cv2.rectangle(overlay, (0, panel_y), (w, panel_y + panel_h),
                      (13, 13, 13), -1)
        cv2.addWeighted(overlay, _CURVE_PANEL_ALPHA,
                        out,     1 - _CURVE_PANEL_ALPHA, 0, out)

        # Thin top border line on the panel
        cv2.line(out, (0, panel_y), (w, panel_y), (42, 42, 42), 1)

        # ── Coordinate helpers ────────────────────────────────────────────────
        plot_x0 = _CURVE_PAD_X
        plot_x1 = w - _CURVE_PAD_X
        plot_y0 = panel_y + _CURVE_PAD_TOP          # top of curve area (power=1)
        plot_y1 = panel_y + panel_h - _CURVE_PAD_BOT  # bottom of curve area (power=0)
        plot_w  = plot_x1 - plot_x0
        plot_h_px = plot_y1 - plot_y0

        angles = np.array(SCAN_ANGLES, dtype=np.float32)

        def angle_to_x(a):
            return int(np.interp(a, [angles[0], angles[-1]],
                                 [plot_x0, plot_x1]))

        def power_to_y(p):
            return int(np.interp(p, [0.0, 1.0], [plot_y1, plot_y0]))

        # ── Subtle horizontal grid lines at 0.25, 0.5, 0.75 ─────────────────
        for level in (0.25, 0.5, 0.75):
            gy = power_to_y(level)
            cv2.line(out, (plot_x0, gy), (plot_x1, gy), (35, 35, 35), 1)

        # ── Zero-power baseline ───────────────────────────────────────────────
        cv2.line(out, (plot_x0, plot_y1), (plot_x1, plot_y1), (55, 55, 55), 1)

        # ── SRP-PHAT polyline ─────────────────────────────────────────────────
        pts = []
        for i, s in enumerate(spectrum):
            px = int(np.interp(angles[i], [angles[0], angles[-1]],
                               [plot_x0, plot_x1]))
            py = power_to_y(float(s))
            pts.append((px, py))

        if len(pts) >= 2:
            pts_arr = np.array(pts, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(out, [pts_arr], False, _CURVE_COLOR,
                          _CURVE_THICKNESS, cv2.LINE_AA)

        # ── Dashed vertical peak line (accent color) ──────────────────────────
        peak_x  = angle_to_x(angle)
        dash_on = 5
        dash_off = 4
        y = plot_y0
        drawing = True
        while y < plot_y1:
            y_end = min(y + (dash_on if drawing else dash_off), plot_y1)
            if drawing:
                cv2.line(out, (peak_x, y), (peak_x, y_end),
                         _PEAK_COLOR, _PEAK_THICKNESS, cv2.LINE_AA)
            y = y_end
            drawing = not drawing

        # ── Axis tick labels ──────────────────────────────────────────────────
        label_y = panel_y + panel_h - 6
        tick_color = (85, 85, 85)

        for a_lbl, txt in [(-90, "-90"), (-45, "-45"), (0, "0"),
                           (45, "+45"), (90, "+90")]:
            lx = angle_to_x(a_lbl)
            cv2.line(out, (lx, plot_y1), (lx, plot_y1 + 4), tick_color, 1)
            (tw, th), baseline = cv2.getTextSize(txt, _FONT_FACE, _FONT_SCALE, 1)
            cv2.putText(out, txt, (lx - tw // 2, label_y),
                        _FONT_FACE, _FONT_SCALE, tick_color, 1, cv2.LINE_AA)
            

        # "SRP-PHAT" label top-right of panel
        cv2.putText(out, "SRP-PHAT", (w - _CURVE_PAD_X - 2, panel_y + 14),
                    _FONT_FACE, _FONT_SCALE * 0.85, (55, 55, 55), 1, cv2.LINE_AA)

        return out

    def _draw_heatmap_bar(self, frame, h, w, spectrum, angle):
        """
        Solid colour bar at the very bottom of the frame.
        Left = -90°, right = +90°.  A white tick marks the current DOA angle.
        """
        bar_y = h - _BAR_HEIGHT_PX
        angles = np.array(SCAN_ANGLES, dtype=np.float32)
        cols   = np.interp(angles, [angles[0], angles[-1]], [0, w - 1]).astype(int)

        # Build a 1×W power bar
        bar_row = np.zeros(w, dtype=np.float32)
        for i, c in enumerate(cols):
            if 0 <= c < w:
                bar_row[c] = spectrum[i]

        # Smooth and normalise
        k = cv2.getGaussianKernel(max(int(w * 0.03) | 1, 7), -1)
        bar_row = cv2.filter2D(bar_row.reshape(1, -1), -1, k.T).flatten()
        bar_row = np.clip(bar_row, 0, 1)

        bar_u8  = (bar_row * 255).astype(np.uint8)
        bar_rgb = cv2.applyColorMap(bar_u8.reshape(1, -1), cv2.COLORMAP_JET)
        bar_rgb = np.repeat(bar_rgb, _BAR_HEIGHT_PX, axis=0)

        # Blend (full opacity for the bar)
        out = frame.copy()
        out[bar_y:h, :w] = (
            frame[bar_y:h, :w].astype(np.float32) * 0.30 +
            bar_rgb.astype(np.float32) * 0.70
        ).clip(0, 255).astype(np.uint8)

        # Angle tick and label
        tick_x = int(np.interp(angle, [-90, 90], [0, w - 1]))
        cv2.line(out, (tick_x, bar_y), (tick_x, h), (255, 255, 255), 2)

        # Edge labels
        cv2.putText(out, "-90°", (4, h - 6),
                    _FONT_FACE, _FONT_SCALE * 0.85, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(out, "+90°", (w - 46, h - 6),
                    _FONT_FACE, _FONT_SCALE * 0.85, (200, 200, 200), 1, cv2.LINE_AA)

        # Centre zero marker
        mid = w // 2
        cv2.line(out, (mid, bar_y), (mid, h), (100, 100, 100), 1)
        cv2.putText(out, "0°", (mid - 8, h - 6),
                    _FONT_FACE, _FONT_SCALE * 0.8, (130, 130, 130), 1, cv2.LINE_AA)

        return out

    def _draw_angle_text(self, frame, h, w, angle):
        """Angle readout in the top-left corner."""
        txt = f"{angle:+.1f} deg"
        cv2.putText(frame, txt, (14, 34),
                    _FONT_FACE, 0.9, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, txt, (14, 34),
                    _FONT_FACE, 0.9, _PEAK_COLOR, 2, cv2.LINE_AA)
        return frame

    # ── Display helpers ───────────────────────────────────────────────────────

    def _display(self, bgr_frame: np.ndarray):
        """Convert OpenCV BGR frame → QPixmap and show in the label."""
        h, w, _ = bgr_frame.shape
        # Keep rgb alive on self — QImage does NOT copy the buffer, so the
        # numpy array must outlive the QImage / QPixmap construction.
        self._rgb_buf = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        self._rgb_buf = np.ascontiguousarray(self._rgb_buf)
        img = QImage(self._rgb_buf.data, w, h, w * 3,
                     QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(img)

        lbl_w = max(self._video_lbl.width(),  1)
        lbl_h = max(self._video_lbl.height(), 1)
        scaled = pix.scaled(lbl_w, lbl_h,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        self._video_lbl.setPixmap(scaled)
        self._video_lbl.setStyleSheet(
            f"background: #0a0a0a; border: 1px solid {BORDER_COLOR}; border-radius: 6px;"
        )

    def _update_info_strip(self):
        peak = float(np.max(self._spectrum))
        self._info_angle.setText(f"{self._angle:+.1f}°")
        self._info_angle.setStyleSheet(f"color: {ACCENT_COLOR}; font-weight: bold;")
        self._info_peak.setText(f"{peak:.3f}")
        self._info_peak.setStyleSheet(f"color: {LIVE_COLOR}; font-weight: bold;")
        self._info_fps.setText(f"{self._fps_display} fps")
        self._info_fps.setStyleSheet(f"color: #38bdf8; font-weight: bold;")