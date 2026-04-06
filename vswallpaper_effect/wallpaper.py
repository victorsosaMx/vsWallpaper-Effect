from __future__ import annotations

import math
import os
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf

from .model import AppConfig
from .utils import expand_path, list_image_files


class WallpaperManager:
    def __init__(self, config: AppConfig):
        self._signature = None
        self._mode = "single"
        self._interval = 300
        self._playlist: list[str] = []
        self._index = 0
        self._current_path = ""
        self._next_rotation = time.monotonic()
        self._original_path = ""
        self._original_pixbuf = None
        self._scaled_key = None
        self._scaled_pixbuf = None
        self._scaled_offset = (0, 0)
        self.configure(config)

    def configure(self, config: AppConfig) -> None:
        cfg = config.normalize()
        source_wallpaper = expand_path(cfg.wallpaper) if cfg.wallpaper else ""
        source_folder = expand_path(cfg.folder) if cfg.folder else ""
        signature = (cfg.mode, source_wallpaper, source_folder, cfg.interval)
        if signature == self._signature:
            return

        previous = self._current_path
        self._signature = signature
        self._mode = cfg.mode
        self._interval = cfg.interval
        self._next_rotation = time.monotonic() + self._interval

        if self._mode == "folder":
            folder = source_folder or source_wallpaper
            self._playlist = list_image_files(folder)
            if previous and previous in self._playlist:
                self._index = self._playlist.index(previous)
            else:
                self._index = 0
            self._current_path = self._playlist[self._index] if self._playlist else ""
        else:
            self._playlist = []
            self._index = 0
            self._current_path = source_wallpaper

        self._clear_cache()

    @property
    def current_path(self) -> str:
        return self._current_path

    def advance_if_due(self, now: float | None = None) -> bool:
        if self._mode != "folder" or len(self._playlist) < 2:
            return False
        current_time = now if now is not None else time.monotonic()
        if current_time < self._next_rotation:
            return False
        self._index = (self._index + 1) % len(self._playlist)
        self._current_path = self._playlist[self._index]
        self._next_rotation = current_time + self._interval
        self._clear_cache()
        return True

    def draw(self, cr, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            return False
        path = self._current_path
        if not path or not os.path.isfile(path):
            return False
        pixbuf, offset = self._get_scaled_pixbuf(path, width, height)
        if pixbuf is None:
            return False
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, offset[0], offset[1])
        cr.paint()
        return True

    def _clear_cache(self) -> None:
        self._original_path = ""
        self._original_pixbuf = None
        self._scaled_key = None
        self._scaled_pixbuf = None
        self._scaled_offset = (0, 0)

    def _get_scaled_pixbuf(self, path: str, width: int, height: int):
        key = (path, width, height)
        if key == self._scaled_key and self._scaled_pixbuf is not None:
            return self._scaled_pixbuf, self._scaled_offset

        try:
            if path != self._original_path or self._original_pixbuf is None:
                self._original_path = path
                self._original_pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            original = self._original_pixbuf
            if original is None:
                return None, (0, 0)
            scale = max(width / original.get_width(), height / original.get_height())
            scaled_w = max(1, int(math.ceil(original.get_width() * scale)))
            scaled_h = max(1, int(math.ceil(original.get_height() * scale)))
            self._scaled_pixbuf = original.scale_simple(scaled_w, scaled_h, GdkPixbuf.InterpType.BILINEAR)
            self._scaled_key = key
            self._scaled_offset = ((width - scaled_w) // 2, (height - scaled_h) // 2)
            return self._scaled_pixbuf, self._scaled_offset
        except Exception:
            self._clear_cache()
            return None, (0, 0)
