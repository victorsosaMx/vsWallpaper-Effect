from __future__ import annotations

import math

import cairo

from .base import BaseEffect
from ..utils import darken_hex, hex_to_rgb


class GradientFlowEffect(BaseEffect):
    """Animated mesh-gradient: soft color blobs drifting in Lissajous paths.

    Parameters:
        color / color2 / color3 — the three blob colors (auto-derived from color1 if empty)
        speed                   — animation rate
        opacity                 — overall blend strength
        density                 — number of blobs (10–500, mapped to 2–6)
        vertical_pos            — blob coverage radius (0 = tight, 100 = full-screen)
    """

    name = "gradient"

    # (phase_x, phase_y, freq_x, freq_y) per blob slot
    _BLOB_PARAMS = [
        (0.00, 0.00, 0.23, 0.17),
        (2.09, 3.72, 0.19, 0.28),
        (5.24, 1.38, 0.31, 0.21),
        (1.11, 4.90, 0.14, 0.36),
        (3.87, 2.55, 0.27, 0.13),
        (0.63, 6.01, 0.36, 0.24),
    ]

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._time = 0.0

    def on_resize(self, width: int, height: int) -> None:
        pass

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        self._time += dt * self.speed * 0.3

    def draw(self, cr, width: int, height: int) -> None:
        t = self._time
        c1_hex = self.config.color or self.accent_color
        c2_hex = self.config.color2 or darken_hex(c1_hex, 0.35)
        c3_hex = self.config.color3 or darken_hex(c1_hex, 0.65)

        palette = [
            hex_to_rgb(c1_hex),
            hex_to_rgb(c2_hex),
            hex_to_rgb(c3_hex),
        ]

        # Background: darkest tone
        r3, g3, b3 = palette[2]
        cr.set_source_rgba(r3, g3, b3, self.opacity)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Blob count: density mapped 10-500 → 2-6
        n_blobs = max(2, min(6, 1 + self.config.density // 70))

        # Coverage radius: vertical_pos 0-100 → 50%-100% of screen diagonal
        coverage = 0.50 + (self.config.vertical_pos / 100.0) * 0.50
        base_radius = max(width, height) * coverage

        # Movement amplitude: blobs drift within 35% of screen
        amp_x = width * 0.35
        amp_y = height * 0.35

        for i in range(n_blobs):
            px, py, fx, fy = self._BLOB_PARAMS[i]
            bx = width * 0.5 + amp_x * math.sin(t * fx + px)
            by = height * 0.5 + amp_y * math.cos(t * fy + py)
            r, g, b = palette[i % len(palette)]
            radius = base_radius * (0.75 + 0.25 * math.sin(t * 0.11 + i * 1.7))
            grad = cairo.RadialGradient(bx, by, 0, bx, by, radius)
            grad.add_color_stop_rgba(0.0, r, g, b, self.opacity * (0.85 - i * 0.08))
            grad.add_color_stop_rgba(0.6, r, g, b, self.opacity * (0.3 - i * 0.03))
            grad.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.rectangle(0, 0, width, height)
            cr.set_source(grad)
            cr.fill()
