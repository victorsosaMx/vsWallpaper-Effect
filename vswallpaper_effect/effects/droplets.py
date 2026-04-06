from __future__ import annotations

import math

from .base import BaseEffect


class DropletsEffect(BaseEffect):
    """Raindrop ripples: points spawn at random positions and emit expanding rings.

    Parameters:
        color       — ring color
        speed       — expansion speed and spawn rate
        opacity     — ring peak opacity
        density     — spawn rate (impacts per second, scaled by speed)
    """

    name = "droplets"

    # Concentric ring delays and relative sizes within one impact
    _RING_DEFS = [
        {"delay": 0.00, "line_w": 1.8},
        {"delay": 0.18, "line_w": 1.3},
        {"delay": 0.36, "line_w": 0.9},
    ]

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._impacts: list[dict] = []
        self._spawn_acc: float = 0.0

    def on_resize(self, width: int, height: int) -> None:
        self._impacts.clear()
        self._spawn_acc = 0.0

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)

        # Spawn rate: density/60 impacts/sec, scaled by speed
        rate = (self.config.density / 60.0) * self.speed
        self._spawn_acc += dt * rate
        while self._spawn_acc >= 1.0:
            self._spawn_acc -= 1.0
            self._spawn_impact(width, height)

        # Expand rings
        expand_speed = max(width, height) * 0.22 * self.speed
        fade_speed = self.opacity * 1.1 * self.speed

        for impact in self._impacts:
            for ring in impact["rings"]:
                ring["delay"] -= dt
                if ring["delay"] > 0:
                    continue
                ring["radius"] += expand_speed * dt * frame
                ring["alpha"] = max(0.0, ring["alpha"] - fade_speed * dt)

        # Remove fully faded impacts
        self._impacts = [
            imp for imp in self._impacts
            if any(r["alpha"] > 0.005 or r["delay"] > 0 for r in imp["rings"])
        ]

    def draw(self, cr, width: int, height: int) -> None:
        r, g, b = self.color_rgb
        for impact in self._impacts:
            for ring in impact["rings"]:
                if ring["delay"] > 0 or ring["radius"] < 0.5 or ring["alpha"] < 0.005:
                    continue
                cr.set_line_width(ring["line_w"])
                cr.set_source_rgba(r, g, b, ring["alpha"])
                cr.arc(impact["x"], impact["y"], ring["radius"], 0, 2 * math.pi)
                cr.stroke()

    def _spawn_impact(self, width: int, height: int) -> None:
        x = self.random.uniform(width * 0.05, width * 0.95)
        y = self.random.uniform(height * 0.05, height * 0.95)
        rings = [
            {
                "delay":  rd["delay"],
                "radius": 1.0,
                "alpha":  self.opacity * self.random.uniform(0.55, 0.90),
                "line_w": rd["line_w"],
            }
            for rd in self._RING_DEFS
        ]
        self._impacts.append({"x": x, "y": y, "rings": rings})
