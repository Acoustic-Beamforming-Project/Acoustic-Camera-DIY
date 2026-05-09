"""
doa_filter.py — Spatial (DOA) Band-Pass Filter
================================================
Post-processes the SRP-PHAT spectrum that DSPWorker already emits.
Zero changes to DSPWorker, zero changes to the UDP/embedded pipeline.

The filter defines an angular acceptance window:

    [ center_angle - half_width  …  center_angle + half_width ]

Spectrum power OUTSIDE that window is zeroed (or attenuated by `rejection_dB`).
Inside the window a raised-cosine taper smooths the edges so the peak-finder
does not lock on to a hard step artefact.

Public API
----------
DOAFilter.apply(angles, spectrum)  →  (filtered_spectrum, gated_peak_angle)

    angles          : list/array of scan angles in degrees (e.g. SCAN_ANGLES)
    spectrum        : float32 ndarray, normalised [0,1], same length as angles
    filtered_spectrum : float32 ndarray — same length, out-of-window ≈ 0
    gated_peak_angle  : float — argmax inside the acceptance window

DOAFilter.set_window(center, half_width)
DOAFilter.set_rejection_db(db)       — floor for out-of-window bins (default –40 dB)
DOAFilter.enabled                    — bool; if False, apply() is a no-op pass-through
"""

import numpy as np


class DOAFilter:
    """
    Spatial acceptance-window filter on a normalised SRP-PHAT spectrum.

    Parameters
    ----------
    center_deg    : float  — desired look direction  (default 0°)
    half_width_deg: float  — ±half-width of acceptance window (default 15°)
    rejection_db  : float  — out-of-window floor in dB (default –40 dB ≈ 0.01×)
    enabled       : bool   — pass-through when False
    """

    def __init__(self,
                 center_deg: float     = 0.0,
                 half_width_deg: float = 15.0,
                 rejection_db: float   = -40.0,
                 enabled: bool         = True):
        self.center_deg     = float(center_deg)
        self.half_width_deg = float(half_width_deg)
        self.rejection_db   = float(rejection_db)
        self.enabled        = enabled

    # ── Setters ───────────────────────────────────────────────────────────────

    def set_window(self, center_deg: float, half_width_deg: float):
        self.center_deg     = float(center_deg)
        self.half_width_deg = max(1.0, float(half_width_deg))

    def set_rejection_db(self, db: float):
        self.rejection_db = float(db)

    # ── Core ──────────────────────────────────────────────────────────────────

    def apply(self, angles, spectrum: np.ndarray):
        """
        Apply the spatial window to `spectrum`.

        Returns
        -------
        filtered  : float32 ndarray, same shape as spectrum
        peak_angle: float — peak angle *inside* the acceptance window
        """
        angles_arr = np.asarray(angles, dtype=np.float32)

        if not self.enabled:
            # Pass-through — return original spectrum and its peak
            peak_angle = float(angles_arr[int(np.argmax(spectrum))])
            return spectrum.copy(), peak_angle

        # ── Build window mask with raised-cosine taper ────────────────────────
        lo  = self.center_deg - self.half_width_deg
        hi  = self.center_deg + self.half_width_deg

        # Linear distance from window edge (negative = inside, positive = outside)
        dist_from_center = np.abs(angles_arr - self.center_deg)
        dist_from_edge   = dist_from_center - self.half_width_deg  # <0 inside, >0 outside

        # Taper zone: 20% of half_width on each side of the window edge
        taper_zone = max(2.0, self.half_width_deg * 0.20)

        # Raised-cosine ramp: 1.0 well inside, 0.0 well outside
        ramp = np.where(
            dist_from_edge <= 0.0,
            1.0,                                                # fully inside
            np.where(
                dist_from_edge < taper_zone,
                0.5 * (1.0 + np.cos(np.pi * dist_from_edge / taper_zone)),  # taper
                0.0                                             # fully outside
            )
        ).astype(np.float32)

        # Out-of-window floor (linear)
        floor = float(10.0 ** (self.rejection_db / 20.0))      # e.g. –40 dB → 0.01
        mask  = np.where(ramp > 0.0, ramp, floor)

        filtered = spectrum * mask

        # ── Peak inside acceptance window ─────────────────────────────────────
        inside = (angles_arr >= lo) & (angles_arr <= hi)
        if inside.any():
            inside_idx = np.where(inside)[0]
            best_local = inside_idx[int(np.argmax(filtered[inside_idx]))]
            peak_angle = float(angles_arr[best_local])
        else:
            # Window is fully outside scan range — fall back to global peak
            peak_angle = float(angles_arr[int(np.argmax(filtered))])

        return filtered.astype(np.float32), peak_angle