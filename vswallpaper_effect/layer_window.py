from __future__ import annotations

import cairo
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

from .model import AppConfig
from .renderer import WallpaperEffectRenderer


def make_preview_area(config: AppConfig) -> "RendererAreaCairo":
    """Editor preview widget — always Cairo (small 240 px strip, CPU cost is negligible)."""
    return RendererAreaCairo(config)


def make_daemon_area(config: AppConfig):
    """Daemon background widget — OpenGL required.  Exits with a clear error if unavailable."""
    try:
        from .gl_renderer import GLRendererWidget
        return GLRendererWidget(config)
    except ImportError:
        print(
            "\n[vsWallpaper-Effect] OpenGL (PyOpenGL) is required for daemon mode.\n"
            "Install it with:  pip install --user PyOpenGL\n"
            "Then restart the daemon.\n",
            file=sys.stderr,
        )
        sys.exit(1)


class RendererAreaCairo(Gtk.DrawingArea):
    def __init__(self, config: AppConfig):
        super().__init__()
        self._renderer = WallpaperEffectRenderer(config)
        self._tick_id = 0
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.connect("draw", self._on_draw)
        self._restart_loop()

    @property
    def renderer(self) -> WallpaperEffectRenderer:
        return self._renderer

    def set_config(self, config: AppConfig) -> None:
        self._renderer.set_config(config)
        self._restart_loop()
        self.queue_draw()

    def stop(self) -> None:
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0

    def _restart_loop(self) -> None:
        self.stop()
        self._tick_id = GLib.timeout_add(self._renderer.tick_interval_ms, self._on_tick)

    def _on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        self._renderer.draw(cr, width, height)
        return False

    def _on_tick(self) -> bool:
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width > 0 and height > 0:
            changed = self._renderer.tick(width, height)
            if changed or self._renderer.needs_animation:
                self.queue_draw()
        return True


class BackgroundWindow(Gtk.Window):
    def __init__(self, config: AppConfig, monitor=None):
        super().__init__(title="vsWallpaper-Effect Background")
        self._config = config.normalize()
        self._monitor = monitor
        self._area = make_daemon_area(self._config)

        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_below(True)
        self.stick()

        self.add(self._area)
        self.connect("realize", self._on_realize)
        self.connect("destroy", self._on_destroy)
        self._init_layer_surface()

    def stop(self) -> None:
        self._area.stop()
        self.destroy()

    def _init_layer_surface(self) -> None:
        screen = self.get_screen()
        if screen:
            visual = screen.get_rgba_visual()
            if visual:
                self.set_visual(visual)

        if GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "vswallpaper-effect")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BACKGROUND)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_exclusive_zone(self, -1)  # extend behind waybar/dock zones
            for edge in (
                GtkLayerShell.Edge.TOP,
                GtkLayerShell.Edge.BOTTOM,
                GtkLayerShell.Edge.LEFT,
                GtkLayerShell.Edge.RIGHT,
            ):
                GtkLayerShell.set_anchor(self, edge, True)
            if self._monitor is not None:
                GtkLayerShell.set_monitor(self, self._monitor)
        else:
            self.fullscreen()
            if self._monitor is not None:
                geometry = self._monitor.get_geometry()
                self.set_default_size(geometry.width, geometry.height)

    def _on_realize(self, *_):
        if not self._config.runtime.click_through:
            return
        gdk_window = self.get_window()
        if not gdk_window:
            return
        try:
            gdk_window.set_pass_through(True)
        except Exception:
            pass
        try:
            gdk_window.input_shape_combine_region(cairo.Region(), 0, 0)
        except Exception:
            pass

    def _on_destroy(self, *_):
        self._area.stop()


class BackgroundSession:
    def __init__(self, config: AppConfig):
        self._config = config.normalize()
        self._windows = []
        self._open_windows = 0

    def show_all(self) -> None:
        display = Gdk.Display.get_default()
        monitors = []
        if display and self._config.runtime.all_monitors:
            monitors = [display.get_monitor(idx) for idx in range(display.get_n_monitors())]
        elif display:
            primary = display.get_primary_monitor() or display.get_monitor(0)
            monitors = [primary] if primary else []
        if not monitors:
            monitors = [None]

        self._windows = [BackgroundWindow(self._config, monitor) for monitor in monitors]
        self._open_windows = len(self._windows)
        for window in self._windows:
            window.connect("destroy", self._on_window_destroy)
            window.show_all()

    def stop(self) -> None:
        for window in list(self._windows):
            if window:
                window.stop()

    def _on_window_destroy(self, *_):
        self._open_windows -= 1
        if self._open_windows <= 0:
            Gtk.main_quit()
