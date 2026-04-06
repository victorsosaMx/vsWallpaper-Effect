from __future__ import annotations

import math

import cairo

from .base import BaseEffect


class SnowEffect(BaseEffect):
    name = "snow"

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._flakes = []

    def on_resize(self, width: int, height: int) -> None:
        count = max(30, min(400, self.density * 2))
        self._flakes = []
        for _ in range(count):
            self._flakes.append({
                "x":          self.random.uniform(0, width),
                "y":          self.random.uniform(-height, height),
                "size":       self.random.uniform(1.5, 5.0),
                "speed":      self.random.uniform(0.6, 2.2) * self.speed,
                "drift_amp":  self.random.uniform(0.4, 1.8),
                "drift_freq": self.random.uniform(0.4, 1.2),
                "phase":      self.random.uniform(0, 2 * math.pi),
                "alpha":      self.opacity * self.random.uniform(0.45, 0.95),
            })

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)
        for f in self._flakes:
            f["y"] += f["speed"] * frame * 2.0
            f["phase"] += 0.018 * frame * self.speed
            f["x"] += math.sin(f["phase"]) * f["drift_amp"] * 0.35
            if f["y"] > height + f["size"]:
                f["y"] = -f["size"] * 2
                f["x"] = self.random.uniform(0, width)

    def draw(self, cr, width: int, height: int) -> None:
        if not self._flakes:
            return
        base_r, base_g, base_b = self.color_rgb
        # Blend toward white/ice-blue
        r = base_r * 0.15 + 0.85
        g = base_g * 0.15 + 0.88
        b = base_b * 0.15 + 0.97
        for f in self._flakes:
            cr.arc(f["x"], f["y"], f["size"], 0, 2 * math.pi)
            cr.set_source_rgba(r, g, b, f["alpha"])
            cr.fill()
