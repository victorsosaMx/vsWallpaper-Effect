from __future__ import annotations

import math

import cairo

from .base import BaseEffect


class RainEffect(BaseEffect):
    name = "rain"

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._drops = []
        self._wind_force = 0.0
        self._wind_target = 0.0

    def on_resize(self, width: int, height: int) -> None:
        self._drops = [self._new_drop(initial=True) for _ in range(self.density)]

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)

        # Organic wind: lerp toward a slowly-changing target
        if self.random.random() < 0.01:
            self._wind_target = self.random.uniform(-1.5, 1.5)
        self._wind_force += (self._wind_target - self._wind_force) * 0.02

        for drop in self._drops:
            # Wind accelerates lighter drops more (mass in [0.7, 1.3])
            drop["vx"] += (self._wind_force / drop["mass"]) * 0.03
            drop["vx"] *= 0.96  # friction
            drop["x"] += drop["vx"] * frame
            drop["y"] += drop["vy"] * frame

            off_bottom = drop["y"] - drop["length"] > height
            off_sides = drop["x"] > width + 80 or drop["x"] < -80
            if off_bottom or off_sides:
                drop.update(self._new_drop(initial=False))

    def draw(self, cr, width: int, height: int) -> None:
        red, green, blue = self.color_rgb
        cr.set_line_width(1.5)
        for drop in self._drops:
            cr.set_source_rgba(red, green, blue, drop["alpha"] * self.opacity)
            cr.move_to(drop["x"], drop["y"])
            # Tail: fixed length in the direction opposite to velocity
            speed = math.sqrt(drop["vx"] ** 2 + drop["vy"] ** 2)
            if speed > 0.01:
                nx = drop["vx"] / speed
                ny = drop["vy"] / speed
            else:
                nx, ny = 0.0, 1.0
            cr.line_to(
                drop["x"] - nx * drop["length"],
                drop["y"] - ny * drop["length"],
            )
            cr.stroke()

    def _new_drop(self, initial: bool) -> dict:
        width = max(1, self._width)
        height = max(1, self._height)
        vy = self.random.uniform(4.0, 10.0) * self.speed * (height / 900.0)
        return {
            "x": self.random.uniform(-80, width),
            "y": self.random.uniform(-height, height if initial else 0),
            "length": self.random.randint(12, 42),
            "vx": 0.0,
            "vy": vy,
            "mass": self.random.uniform(0.7, 1.3),
            "alpha": self.random.uniform(0.25, 0.95),
        }
