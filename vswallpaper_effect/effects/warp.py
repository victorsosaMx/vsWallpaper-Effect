from __future__ import annotations

import math

from .base import BaseEffect


class WarpEffect(BaseEffect):
    name = "warp"

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._center_x = 0.0
        self._center_y = 0.0
        self._max_distance = 1.0
        self._stars = []

    def on_resize(self, width: int, height: int) -> None:
        self._center_x = width / 2.0
        self._center_y = height / 2.0
        self._max_distance = math.sqrt(self._center_x ** 2 + self._center_y ** 2) * 1.2
        self._stars = [self._new_star(initial=True) for _ in range(self.density)]

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)
        for star in self._stars:
            star["dist"] += star["speed"] * (1.0 + star["dist"] / max(1.0, self._max_distance * 0.4)) * frame
            if star["dist"] > self._max_distance:
                star.update(self._new_star(initial=False))

    def draw(self, cr, width: int, height: int) -> None:
        red, green, blue = self.color_rgb
        for star in self._stars:
            distance = star["dist"]
            if distance < 1:
                continue
            trail = max(2.0, distance * 0.15)
            x1 = self._center_x + math.cos(star["angle"]) * distance
            y1 = self._center_y + math.sin(star["angle"]) * distance
            x0 = self._center_x + math.cos(star["angle"]) * (distance - trail)
            y0 = self._center_y + math.sin(star["angle"]) * (distance - trail)
            alpha = star["alpha"] * min(1.0, distance / max(1.0, self._max_distance * 0.3)) * self.opacity
            cr.set_line_width(0.55 + (distance / self._max_distance) * 1.8)
            cr.set_source_rgba(red, green, blue, alpha)
            cr.move_to(x0, y0)
            cr.line_to(x1, y1)
            cr.stroke()

    def _new_star(self, initial: bool) -> dict:
        return {
            "angle": self.random.uniform(0.0, 2.0 * math.pi),
            "dist": self.random.uniform(0.0, self._max_distance if initial else 5.0),
            "speed": self.random.uniform(1.0, 3.0) * self.speed * (self._max_distance / 900.0),
            "alpha": self.random.uniform(0.35, 1.0),
        }
