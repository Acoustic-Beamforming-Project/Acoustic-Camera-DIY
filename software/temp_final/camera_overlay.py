"""
camera_overlay.py — SRP-PHAT spectrum curve overlaid on live webcam feed.

Draws exactly the same curve shown in SpectrumPlot, but painted directly
on top of the camera frame.  Nothing else — no fan, no DOA indicator,
no grid decorations beyond the axes needed to read the curve.
"""

import math
import numpy as np
import cv2

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QCheckBox, QSlider, QSizePolicy)
from PyQt6.QtCore    import Qt, QThread, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui     import (QFont, QPainter, QColor, QPen, QBrush,
                             QImage, QPixmap, QPolygonF, QPainterPath)

from config import (ACCENT_COLOR, BORDER_COLOR, DIM_COLOR, BG_COLOR, SCAN_ANGLES)


# ─────────────────────────────────────────────────────────────────────────────
#  Camera thread
# ─────────────────────────────────────────────────────────────────────────────

class CameraThread(QThread):
    frame_ready = pyqtSignal(QImage)
    cam_error   = pyqtSignal(str)

    def __init__(self, cam_index: int = 0, fps: int = 30):
        super().__init__()
        self._cam_index = cam_index
        self._fps       = fps
        self._running   = False

    def run(self):
        self._running = True
        cap = cv2.VideoCapture(self._cam_index)
        if not cap.isOpened():
            self.cam_error.emit(
                f"Cannot open camera {self._cam_index}. "
                "Check that a webcam is connected and not in use."
            )
            return
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        ms = max(1, int(1000 / self._fps))
        while self._running:
            ok, frame = cap.read()
            if not ok:
                self.cam_error.emit("Camera read failed.")
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w,
                         QImage.Format.Format_RGB888).copy()
            self.frame_ready.emit(img)
            self.msleep(ms)
        cap.release()

    def stop(self):
        self._running = False
        self.wait(3000)


# ─────────────────────────────────────────────────────────────────────────────
#  Canvas
# ─────────────────────────────────────────────────────────────────────────────

# Margins for the plot area inside the canvas (pixels)
_ML = 48   # left   (Y-axis labels)
_MR = 16   # right
_MT = 16   # top
_MB = 36   # bottom (X-axis labels)


class _OverlayCanvas(QWidget):

    def __init__(self, owner: "CameraOverlayView"):
        super().__init__()
        self._owner = owner
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(260)

    def tick(self):
        self.update()

    def paintEvent(self, _event):
        owner   = self._owner
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # ── 1. Camera frame ───────────────────────────────────────────────────
        if owner._cam_frame is not None:
            pix = QPixmap.fromImage(owner._cam_frame).scaled(
                W, H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = (pix.width()  - W) // 2
            sy = (pix.height() - H) // 2
            painter.drawPixmap(0, 0, pix, sx, sy, W, H)
        else:
            painter.fillRect(0, 0, W, H, QColor(13, 13, 13))
            painter.setPen(QPen(QColor(28, 28, 28), 1))
            for x in range(0, W, 40):
                painter.drawLine(x, 0, x, H)
            for y in range(0, H, 40):
                painter.drawLine(0, y, W, y)
            painter.setPen(QPen(QColor(60, 60, 60)))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(0, 0, W, H,
                             Qt.AlignmentFlag.AlignCenter,
                             "No camera — click  ▶ START CAMERA")

        # ── 2. SRP-PHAT curve ─────────────────────────────────────────────────
        self._draw_spectrum(painter, W, H)

        painter.end()

    # ── spectrum ──────────────────────────────────────────────────────────────

    def _draw_spectrum(self, p: QPainter, W: int, H: int):
        angles  = self._owner._angles
        spec    = self._owner._smooth_spectrum

        if not len(spec) or not len(angles):
            return

        # Plot area in canvas coordinates
        px = _ML
        py = _MT
        pw = W - _ML - _MR
        ph = H - _MT - _MB

        if pw < 10 or ph < 10:
            return

        ang_min, ang_max = float(angles[0]), float(angles[-1])
        ang_span = ang_max - ang_min if ang_max != ang_min else 1.0

        def to_canvas(ang: float, val: float) -> QPointF:
            cx = px + (ang - ang_min) / ang_span * pw
            cy = py + (1.0 - float(val)) * ph
            return QPointF(cx, cy)

        # ── semi-transparent dark backdrop behind the plot area ───────────────
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 140)))
        p.drawRect(QRectF(px, py, pw, ph))

        # ── axis lines ────────────────────────────────────────────────────────
        ax_pen = QPen(QColor(60, 60, 60), 1)
        p.setPen(ax_pen)
        # bottom (x-axis)
        p.drawLine(QPointF(px, py + ph), QPointF(px + pw, py + ph))
        # left (y-axis)
        p.drawLine(QPointF(px, py), QPointF(px, py + ph))

        # ── y tick lines + labels (0.0, 0.2, 0.4, 0.6, 0.8, 1.0) ─────────────
        p.setFont(QFont("Consolas", 7))
        for v in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            cy = py + (1.0 - v) * ph
            # subtle dotted gridline
            grid_pen = QPen(QColor(255, 255, 255, 18), 1, Qt.PenStyle.DotLine)
            p.setPen(grid_pen)
            p.drawLine(QPointF(px, cy), QPointF(px + pw, cy))
            # label
            p.setPen(QPen(QColor(85, 85, 85)))
            p.drawText(QRectF(0, cy - 7, _ML - 4, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{v:.1f}")

        # ── x tick labels (-90, -60, ..., 90) ────────────────────────────────
        p.setFont(QFont("Consolas", 7))
        p.setPen(QPen(QColor(85, 85, 85)))
        for ang in range(-90, 91, 30):
            cx = px + (ang - ang_min) / ang_span * pw
            p.drawText(QRectF(cx - 14, py + ph + 4, 28, 14),
                       Qt.AlignmentFlag.AlignCenter,
                       f"{ang}")

        # ── x-axis label ──────────────────────────────────────────────────────
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(85, 85, 85)))
        p.drawText(QRectF(px, py + ph + 20, pw, 14),
                   Qt.AlignmentFlag.AlignCenter, "Angle (°)")

        # ── curve fill (under-curve, very faint) ──────────────────────────────
        fill_path = QPainterPath()
        fill_path.moveTo(to_canvas(float(angles[0]), 0.0))
        for ang, val in zip(angles, spec):
            fill_path.lineTo(to_canvas(float(ang), float(val)))
        fill_path.lineTo(to_canvas(float(angles[-1]), 0.0))
        fill_path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(56, 189, 248, 28)))   # very faint cyan fill
        p.drawPath(fill_path)

        # ── curve line ────────────────────────────────────────────────────────
        curve_pen = QPen(QColor(56, 189, 248), 1.8,
                         Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                         Qt.PenJoinStyle.RoundJoin)
        p.setPen(curve_pen)
        path = QPainterPath()
        first = True
        for ang, val in zip(angles, spec):
            pt = to_canvas(float(ang), float(val))
            if first:
                path.moveTo(pt)
                first = False
            else:
                path.lineTo(pt)
        p.drawPath(path)

        # ── peak dashed line ──────────────────────────────────────────────────
        peak_ang = self._owner._peak_angle
        peak_x   = px + (peak_ang - ang_min) / ang_span * pw
        dash_pen = QPen(QColor(232, 255, 71), 1.2, Qt.PenStyle.DashLine)
        dash_pen.setDashPattern([6, 4])
        p.setPen(dash_pen)
        p.drawLine(QPointF(peak_x, py), QPointF(peak_x, py + ph))

        # Peak angle label (same position as in SpectrumPlot)
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.setPen(QPen(QColor(232, 255, 71)))
        label = f"{peak_ang:.0f}°"
        lx = peak_x + 3 if peak_x < px + pw - 30 else peak_x - len(label) * 7 - 3
        p.drawText(QPointF(lx, py + ph * 0.25), label)


# ─────────────────────────────────────────────────────────────────────────────
#  Public widget
# ─────────────────────────────────────────────────────────────────────────────

class CameraOverlayView(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self._angles:          list        = list(SCAN_ANGLES)
        self._spectrum:        np.ndarray  = np.zeros(len(SCAN_ANGLES), dtype=np.float32)
        self._smooth_spectrum: np.ndarray  = np.zeros(len(SCAN_ANGLES), dtype=np.float32)
        self._peak_angle:      float       = 0.0
        self._cam_frame:       QImage|None = None
        self._alpha_smooth:    float       = 0.30

        self._cam_thread: CameraThread | None = None

        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"background:{BG_COLOR};")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        root.addLayout(self._build_header())
        self._canvas = _OverlayCanvas(self)
        root.addWidget(self._canvas, stretch=1)
        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(10)

        title = QLabel("ACOUSTIC CAMERA  —  SRP-PHAT OVERLAY")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{DIM_COLOR}; letter-spacing:3px;")
        h.addWidget(title)
        h.addStretch()

        self._btn_cam = QPushButton("▶  START CAMERA")
        self._btn_cam.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._btn_cam.setFixedHeight(26)
        self._btn_cam.setStyleSheet(f"""
            QPushButton {{
                background:#0d1f0d; color:#39d353;
                border:1px solid #39d353; border-radius:4px;
                padding:0 12px; letter-spacing:1px;
            }}
            QPushButton:hover {{ background:#142814; }}
            QPushButton[camActive=true] {{
                background:#1f0d0d; color:#f85149; border-color:#f85149;
            }}
            QPushButton[camActive=true]:hover {{ background:#2a1010; }}
        """)
        self._btn_cam.clicked.connect(self._toggle_camera)
        h.addWidget(self._btn_cam)
        return h

    def _build_footer(self) -> QHBoxLayout:
        h = QHBoxLayout()
        self._lbl_doa = QLabel("DOA  —°")
        self._lbl_doa.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self._lbl_doa.setStyleSheet(f"color:{ACCENT_COLOR};")
        h.addWidget(self._lbl_doa)

        self._lbl_cam_status = QLabel("● CAMERA OFF")
        self._lbl_cam_status.setFont(QFont("Segoe UI", 8))
        self._lbl_cam_status.setStyleSheet("color:#555555;")
        h.addWidget(self._lbl_cam_status)
        h.addStretch()
        return h

    # ── camera ────────────────────────────────────────────────────────────────

    def _toggle_camera(self):
        if self._cam_thread and self._cam_thread.isRunning():
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self, cam_index: int = 0):
        if self._cam_thread and self._cam_thread.isRunning():
            return
        self._cam_thread = CameraThread(cam_index, fps=30)
        self._cam_thread.frame_ready.connect(self._on_frame)
        self._cam_thread.cam_error.connect(self._on_cam_error)
        self._cam_thread.start()
        self._set_cam_ui(True)

    def stop_camera(self):
        if self._cam_thread:
            self._cam_thread.stop()
            self._cam_thread = None
        self._cam_frame = None
        self._set_cam_ui(False)
        self._canvas.update()

    def _set_cam_ui(self, running: bool):
        if running:
            self._btn_cam.setText("■  STOP CAMERA")
            self._btn_cam.setProperty("camActive", True)
            self._lbl_cam_status.setText("● CAMERA ON")
            self._lbl_cam_status.setStyleSheet("color:#39d353;")
        else:
            self._btn_cam.setText("▶  START CAMERA")
            self._btn_cam.setProperty("camActive", False)
            self._lbl_cam_status.setText("● CAMERA OFF")
            self._lbl_cam_status.setStyleSheet("color:#555555;")
        self._btn_cam.style().unpolish(self._btn_cam)
        self._btn_cam.style().polish(self._btn_cam)

    def _on_frame(self, img: QImage):
        self._cam_frame = img
        # IIR smooth toward latest DSP spectrum
        self._smooth_spectrum += self._alpha_smooth * (
            self._spectrum - self._smooth_spectrum
        )
        self._canvas.tick()   # only place that triggers repaint

    def _on_cam_error(self, msg: str):
        self._cam_frame = None
        self._lbl_cam_status.setText(f"⚠ {msg[:70]}")
        self._lbl_cam_status.setStyleSheet("color:#f85149;")

    # ── public DSP API ────────────────────────────────────────────────────────

    def update_overlay(self, angles: list, spectrum: np.ndarray,
                       peak_angle: float):
        """Store DSP result. Never triggers repaint — camera thread does that."""
        self._angles      = list(angles)
        self._spectrum    = np.asarray(spectrum, dtype=np.float32)
        self._peak_angle  = float(peak_angle)
        self._lbl_doa.setText(
            f"DOA  <span style='color:{ACCENT_COLOR}'>{peak_angle:+.1f}°</span>"
        )
        self._lbl_doa.setTextFormat(Qt.TextFormat.RichText)

    def closeEvent(self, event):
        self.stop_camera()
        super().closeEvent(event)