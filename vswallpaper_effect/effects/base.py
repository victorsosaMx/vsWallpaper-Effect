from __future__ import annotations

import random

from ..model import EffectConfig
from ..utils import hex_to_rgb


class BaseEffect:
    name = "base"

    def __init__(self, config: EffectConfig, accent_color: str):
        self.config = config.normalize()
        self.accent_color = accent_color
        self.random = random.Random()
        self._width = 0
        self._height = 0

    @property
    def color_rgb(self) -> tuple[float, float, float]:
        return hex_to_rgb(self.config.color or self.accent_color, self.accent_color)

    @property
    def density(self) -> int:
        return int(self.config.density)

    @property
    def speed(self) -> float:
        return float(self.config.speed)

    @property
    def opacity(self) -> float:
        return float(self.config.opacity)

    def resize(self, width: int, height: int) -> None:
        if width == self._width and height == self._height:
            return
        self._width = width
        self._height = height
        self.on_resize(width, height)

    def on_resize(self, width: int, height: int) -> None:
        pass

    def update(self, dt: float, width: int, height: int) -> None:
        self.resize(width, height)

    def draw(self, cr, width: int, height: int) -> None:
        pass

    @staticmethod
    def frame_scale(dt: float) -> float:
        if dt <= 0:
            return 1.0
        return max(0.35, min(4.0, dt * 60.0))
