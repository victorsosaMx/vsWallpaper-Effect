from __future__ import annotations

import math

import cairo

from .base import BaseEffect
from ..utils import darken_hex, hex_to_rgb


class WavesEffect(BaseEffect):
    """Multi-layer water waves scrolling horizontally.

    Layers are ordered back-to-front: back layers are slower, darker, lower amplitude;
    front layers are faster, brighter, higher amplitude.

    Parameters:
        color / color2 / color3 — wave layer colors (auto-derived from color1 if empty)
        speed                   — scroll speed
        opacity                 — overall transparency
        density                 — wave frequency (10–500)
        vertical_pos            — water level (0 = top, 50 = center, 100 = bottom)
    """

    name = "waves"

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._layers: list[dict] = []

    def on_resize(self, width: int, height: int) -> None:
        c1_hex = self.config.color or self.accent_color
        c2_hex = self.config.color2 or darken_hex(c1_hex, 0.40)
        c3_hex = self.config.color3 or darken_hex(c1_hex, 0.70)
        palette = [hex_to_rgb(c1_hex), hex_to_rgb(c2_hex), hex_to_rgb(c3_hex)]

        # 3–5 layers depending on density
        n = max(3, min(5, 2 + self.config.density // 60))
        freq_scale = 0.5 + self.config.density / 80.0  # higher density = more crests

        self._layers = []
        for i in range(n):
            depth = i / max(1, n - 1)  # 0 = backmost, 1 = frontmost
            front = 1.0 - depth
            self._layers.append({
                "phase":     self.random.uniform(0.0, 2.0 * math.pi),
                "phase2":    self.random.uniform(0.0, 2.0 * math.pi),
                "speed":     (0.3 + front * 0.7) * self.speed,
                "amplitude": height * (0.025 + front * 0.055),
                "freq":      freq_scale * (2.8 + depth * 1.4) * math.pi / max(width, 1),
                "freq2":     freq_scale * (1.5 + depth * 0.8) * math.pi / max(width, 1),
                "y_offset":  depth * height * 0.045,   # back layers sit slightly lower
                "color":     palette[i % len(palette)],
                "alpha":     (0.50 + front * 0.35) * self.opacity,
            })

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)
        for layer in self._layers:
            layer["phase"]  += layer["speed"] * 0.045 * frame
            layer["phase2"] += layer["speed"] * 0.028 * frame

    def draw(self, cr, width: int, height: int) -> None:
        if not self._layers:
            return

        vpos = self.config.vertical_pos / 100.0
        y_water = height * vpos

        step = max(3, width // 320)  # adaptive step: smoother on smaller previews

        # Back to front so front layers paint over back layers
        for layer in self._layers:
            r, g, b = layer["color"]
            y_base = y_water + layer["y_offset"]
            amp = layer["amp"] = layer["amplitude"]
            freq = layer["freq"]
            freq2 = layer["freq2"]
            ph = layer["phase"]
            ph2 = layer["phase2"]

            cr.move_to(0, height)
            for x in range(0, width + step, step):
                y = y_base + amp * math.sin(x * freq + ph) + amp * 0.4 * math.sin(x * freq2 + ph2)
                cr.line_to(x, y)
            cr.line_to(width, height)
            cr.close_path()

            # Vertical gradient: crisp at crest, transparent toward bottom fill
            grad = cairo.LinearGradient(0, y_base - amp, 0, y_base + amp * 3.5)
            grad.add_color_stop_rgba(0.0, r, g, b, layer["alpha"])
            grad.add_color_stop_rgba(0.55, r, g, b, layer["alpha"] * 0.55)
            grad.add_color_stop_rgba(1.0, r, g, b, layer["alpha"] * 0.12)
            cr.set_source(grad)
            cr.fill()
