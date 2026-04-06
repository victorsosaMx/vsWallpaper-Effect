from __future__ import annotations

import math

from .base import BaseEffect
from ..utils import hex_to_rgb


class StarsEffect(BaseEffect):
    """Three-layer parallax starfield with subtle drift and foreground twinkle.

    Parameters:
        color   — star tint (default: accent)
        speed   — drift and twinkle rate
        opacity — overall brightness
        density — total star count (10–500)
    """

    name = "stars"

    # (fraction of total, size_min, size_max, alpha_min, alpha_max, speed_factor, twinkle)
    _LAYERS = [
        (0.55, 0.4, 1.1, 0.10, 0.30, 0.08, False),  # far  — tiny, very dim, barely moving
        (0.32, 0.9, 2.0, 0.28, 0.58, 0.25, False),  # mid
        (0.13, 1.8, 3.5, 0.50, 0.95, 0.55, True),   # near — bright, twinkle
    ]

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._stars: list[dict] = []

    def on_resize(self, width: int, height: int) -> None:
        total = max(40, min(800, self.density * 2))
        self._stars = []
        for layer_idx, layer in enumerate(self._LAYERS):
            frac, *_ = layer
            count = int(total * frac)
            for _ in range(count):
                self._stars.append(self._new_star(layer_idx, width, height, initial=True))

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)
        for s in self._stars:
            _, _, _, _, _, spd, twinkle = self._LAYERS[s["layer"]]
            step = spd * self.speed * frame * 0.5
            s["x"] += math.cos(s["drift"]) * step
            s["y"] += math.sin(s["drift"]) * step
            if twinkle:
                s["phase"] += 0.03 * frame * self.speed
            # Wrap
            if s["x"] > width + 4:
                s["x"] = -4.0
            elif s["x"] < -4:
                s["x"] = float(width + 4)
            if s["y"] > height + 4:
                s["y"] = -4.0
            elif s["y"] < -4:
                s["y"] = float(height + 4)

    def draw(self, cr, width: int, height: int) -> None:
        r, g, b = self.color_rgb
        for s in self._stars:
            _, _, _, _, _, _, twinkle = self._LAYERS[s["layer"]]
            alpha = s["alpha"] * self.opacity
            if twinkle:
                alpha *= 0.5 + 0.5 * math.sin(s["phase"])
            if alpha < 0.01:
                continue
            cr.set_source_rgba(r, g, b, alpha)
            cr.arc(s["x"], s["y"], s["size"], 0, 2 * math.pi)
            cr.fill()

    def _new_star(self, layer_idx: int, width: int, height: int, initial: bool) -> dict:
        _, sz_min, sz_max, a_min, a_max, *_ = self._LAYERS[layer_idx]
        return {
            "layer":  layer_idx,
            "x":      self.random.uniform(0.0, float(width)),
            "y":      self.random.uniform(0.0, float(height)),
            "size":   self.random.uniform(sz_min, sz_max),
            "alpha":  self.random.uniform(a_min, a_max),
            "drift":  self.random.uniform(0.0, 2.0 * math.pi),
            "phase":  self.random.uniform(0.0, 2.0 * math.pi),
        }
