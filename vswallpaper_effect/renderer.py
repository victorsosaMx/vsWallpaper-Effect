from __future__ import annotations

import time

import cairo

from .effects import create_effect
from .model import AppConfig
from .utils import hex_to_rgb, mix_rgb, shift_hue
from .wallpaper import WallpaperManager


class WallpaperEffectRenderer:
    def __init__(self, config: AppConfig):
        self._config = config.normalize()
        self._wallpaper = WallpaperManager(self._config)
        self._effect = create_effect(self._config.effect, self._config.theme_accent)
        self._last_tick = time.monotonic()

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def needs_animation(self) -> bool:
        return bool(self._config.effect.enabled)

    @property
    def tick_interval_ms(self) -> int:
        return 16 if self.needs_animation else 1000

    @property
    def current_wallpaper_path(self) -> str:
        return self._wallpaper.current_path

    def set_config(self, config: AppConfig) -> None:
        self._config = config.normalize()
        self._wallpaper.configure(self._config)
        self._effect = create_effect(self._config.effect, self._config.theme_accent)
        self._last_tick = time.monotonic()

    def tick(self, width: int, height: int) -> bool:
        now = time.monotonic()
        dt = min(0.08, max(0.0, now - self._last_tick))
        self._last_tick = now
        wallpaper_changed = self._wallpaper.advance_if_due(now)
        if self._config.effect.enabled:
            self._effect.update(dt, width, height)
            return True
        return wallpaper_changed

    def draw(self, cr, width: int, height: int) -> None:
        self._draw_base(cr, width, height)
        has_wallpaper = self._wallpaper.draw(cr, width, height)
        if not has_wallpaper:
            self._draw_placeholder(cr, width, height)
        self._draw_vignette(cr, width, height)
        if self._config.effect.enabled:
            self._effect.draw(cr, width, height)

    def _draw_base(self, cr, width: int, height: int) -> None:
        cr.set_source_rgb(0.02, 0.05, 0.08)
        cr.rectangle(0, 0, width, height)
        cr.fill()

    def _draw_placeholder(self, cr, width: int, height: int) -> None:
        accent = self._config.theme_accent
        color_a = hex_to_rgb(shift_hue(accent, -18), accent)
        color_b = hex_to_rgb(accent, accent)
        color_c = mix_rgb(hex_to_rgb(shift_hue(accent, 28), accent), (0.02, 0.05, 0.08), 0.45)

        grad = cairo.LinearGradient(0, 0, width, height)
        grad.add_color_stop_rgb(0.0, *color_a)
        grad.add_color_stop_rgb(0.55, *color_b)
        grad.add_color_stop_rgb(1.0, *color_c)
        cr.rectangle(0, 0, width, height)
        cr.set_source(grad)
        cr.fill()

        cr.set_line_width(1.0)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        step = max(24, min(width, height) // 14)
        for xpos in range(0, width + step, step):
            cr.move_to(xpos, 0)
            cr.line_to(xpos, height)
        for ypos in range(0, height + step, step):
            cr.move_to(0, ypos)
            cr.line_to(width, ypos)
        cr.stroke()

    def _draw_vignette(self, cr, width: int, height: int) -> None:
        shade = cairo.RadialGradient(width / 2.0, height / 2.0, width * 0.18, width / 2.0, height / 2.0, width * 0.72)
        shade.add_color_stop_rgba(0.0, 0.0, 0.0, 0.0, 0.0)
        shade.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.32)
        cr.rectangle(0, 0, width, height)
        cr.set_source(shade)
        cr.fill()
