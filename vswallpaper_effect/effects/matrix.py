from __future__ import annotations

import random

import cairo
import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

from .base import BaseEffect

try:
    import ctypes
    import os
    fontconfig = ctypes.CDLL("libfontconfig.so.1")
    fontconfig.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    # Path is relative to effects/ -> font/
    font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "font", "matrix code nfi.ttf")
    if os.path.exists(font_path):
        fontconfig.FcConfigAppFontAddFile(None, font_path.encode('utf-8'))
except Exception:
    pass


class MatrixEffect(BaseEffect):
    name = "matrix"
    CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def __init__(self, config, accent_color):
        super().__init__(config, accent_color)
        self._char_size = 14
        self._streams = []

    def on_resize(self, width: int, height: int) -> None:
        self._char_size = max(12, min(18, width // 72 if width else 14))
        max_columns = max(8, width // self._char_size)
        target_columns = min(max_columns, max(8, self.density))
        positions = list(range(max_columns))
        self.random.shuffle(positions)
        self._streams = [
            self._new_stream(positions[idx] * self._char_size, initial=True)
            for idx in range(target_columns)
        ]

    def update(self, dt: float, width: int, height: int) -> None:
        super().update(dt, width, height)
        frame = self.frame_scale(dt)
        for stream in self._streams:
            stream["y"] += stream["speed"] * frame
            if random.random() < 0.15:
                pos = self.random.randint(0, len(stream["chars"]) - 1)
                stream["chars"][pos] = self.random.choice(self.CHARS)
            if stream["y"] - stream["trail"] * self._char_size > height:
                stream.update(self._new_stream(stream["x"], initial=False))

    def draw(self, cr, width: int, height: int) -> None:
        red, green, blue = self.color_rgb
        layout = PangoCairo.create_layout(cr)
        font_desc = Pango.FontDescription(f"Matrix Code NFI {max(self._char_size - 2, 8)}px")
        layout.set_font_description(font_desc)
        for stream in self._streams:
            for idx in range(stream["trail"]):
                cy = stream["y"] - idx * self._char_size
                if cy < -self._char_size or cy > height + self._char_size:
                    continue
                if idx == 0:
                    cr.set_source_rgba(0.95, 1.0, 0.95, self.opacity)
                else:
                    alpha = ((1.0 - idx / stream["trail"]) ** 1.45) * self.opacity
                    cr.set_source_rgba(red, green, blue, alpha)
                cr.move_to(stream["x"], cy)
                char = stream["chars"][idx % len(stream["chars"])]
                layout.set_text(char, -1)
                PangoCairo.show_layout(cr, layout)

    def _new_stream(self, x: float, initial: bool) -> dict:
        height = max(1, self._height)
        return {
            "x": x,
            "y": self.random.uniform(-height, height if initial else 0),
            "speed": self.random.uniform(2.0, 7.0) * self.speed * (height / 900.0),
            "trail": self.random.randint(8, 24),
            "chars": [self.random.choice(self.CHARS) for _ in range(32)],
        }
