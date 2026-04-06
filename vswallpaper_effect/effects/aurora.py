from __future__ import annotations

import math

import cairo

from .base import BaseEffect
from ..utils import darken_hex, hex_to_rgb


class AuroraEffect(BaseEffect):
    name = "aurora"

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._bands = []

    def on_resize(self, width: int, height: int) -> None:
        c1_hex = self.config.color or self.accent_color
        c2_hex = self.config.color2 or darken_hex(c1_hex, 0.40)
        c3_hex = self.config.color3 or darken_hex(c1_hex, 0.72)
        palette = [
            hex_to_rgb(c1_hex),
            hex_to_rgb(c2_hex),
            hex_to_rgb(c3_hex),
        ]
        count = max(3, min(6, 2 + self.density // 55))
        spread = 0.28
        # y_offset is a relative offset from center: first band at -spread/2, last at +spread/2
        self._bands = []
        for idx in range(count):
            rel = -spread / 2 + idx * (spread / max(1, count - 1))
            self._bands.append(
                {
                    "y_rel": rel,   # relative to the vertical_pos center
                    "amp": height * self.random.uniform(0.03, 0.07),
                    "freq_a": self.random.uniform(0.003, 0.010) * (1920 / max(width, 1)),
                    "freq_b": self.random.uniform(0.002, 0.008) * (1920 / max(width, 1)),
                    "phase": self.random.uniform(0, 2 * math.pi),
                    "speed": self.random.uniform(0.007, 0.019) * self.speed,
                    "color": palette[idx % len(palette)],
                    "alpha": self.opacity * self.random.uniform(0.35, 0.65),
                    "thickness": height * self.random.uniform(0.08, 0.16),
                }
            )

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)
        for band in self._bands:
            band["phase"] += band["speed"] * frame

    def draw(self, cr, width: int, height: int) -> None:
        if not self._bands:
            return

        # vertical_pos read at draw-time so it responds without needing on_resize
        vpos = self.config.vertical_pos / 100.0
        y_center = height * vpos

        base_red, base_green, base_blue = self.color_rgb
        glow = cairo.RadialGradient(width * 0.5, y_center, 0, width * 0.5, y_center, width * 0.6)
        glow.add_color_stop_rgba(0.0, base_red, base_green, base_blue, 0.12 * self.opacity)
        glow.add_color_stop_rgba(1.0, base_red, base_green, base_blue, 0.0)
        cr.rectangle(0, 0, width, height)
        cr.set_source(glow)
        cr.fill()

        for band in self._bands:
            y_base = y_center + band["y_rel"] * height
            amp = band["amp"]
            thickness = band["thickness"]
            red, green, blue = band["color"]
            cr.move_to(0, height)
            for x in range(0, width + 6, 6):
                wave = (
                    amp * math.sin(x * band["freq_a"] + band["phase"])
                    + amp * 0.38 * math.sin(x * band["freq_b"] + band["phase"] * 1.6)
                )
                cr.line_to(x, y_base + wave)
            cr.line_to(width, height)
            cr.close_path()
            # Gradient starts at y_base (top of fill) so the bright peak is visible
            grad = cairo.LinearGradient(0, y_base, 0, y_base + thickness * 2)
            grad.add_color_stop_rgba(0.0, red, green, blue, band["alpha"])
            grad.add_color_stop_rgba(1.0, red, green, blue, 0.0)
            cr.set_source(grad)
            cr.fill()
