from __future__ import annotations

import argparse
import atexit
import os
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from .config import CACHE_DIR, PID_PATH, load_config, resolve_config_path, save_config, write_default_config
from .gui import VsWallpaperEffectEditor
from .layer_window import BackgroundSession
from .model import AppConfig
from . import __version__


def _read_pid() -> int | None:
    try:
        with open(PID_PATH, "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
    except Exception:
        return None


def _write_pid() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(PID_PATH, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def _clear_pid() -> None:
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def stop_running_daemon() -> bool:
    pid = _read_pid()
    if not pid:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    finally:
        _clear_pid()


def run_editor(config_path: str | None = None) -> int:
    window = VsWallpaperEffectEditor(config_path=config_path, launcher_path=os.path.abspath(sys.argv[0]))
    window.show_all()
    Gtk.main()
    return 0


def run_daemon(config_path: str | None = None, replace: bool = False) -> int:
    if replace:
        stop_running_daemon()
        time.sleep(0.15)

    path = resolve_config_path(config_path)
    if not os.path.exists(path):
        save_config(AppConfig(), path)
    config = load_config(path)
    session = BackgroundSession(config)

    def _handle_signal(*_):
        GLib.idle_add(session.stop)
        GLib.idle_add(Gtk.main_quit)

    def _reload_config():
        """Reload config from disk and apply to all background windows."""
        try:
            new_config = load_config(path)
            for window in session._windows:
                if window:
                    GLib.idle_add(window._area.set_config, new_config)
        except Exception:
            pass
        return True  # keep polling

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGHUP, lambda *_: _reload_config())
    _write_pid()
    atexit.register(_clear_pid)

    # Poll config file for changes every 2 seconds
    _mtime = [os.path.getmtime(path) if os.path.exists(path) else 0]

    def _watch_config():
        try:
            mtime = os.path.getmtime(path)
            if mtime != _mtime[0]:
                _mtime[0] = mtime
                _reload_config()
        except OSError:
            pass
        return True

    GLib.timeout_add(2000, _watch_config)

    session.show_all()
    Gtk.main()
    _clear_pid()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vswallpaper-effect")
    parser.add_argument("--config", help="Path to JSON config")
    parser.add_argument("--editor", action="store_true", help="Open the GTK editor")
    parser.add_argument("--daemon", action="store_true", help="Run the wallpaper background session")
    parser.add_argument("--replace", action="store_true", help="Replace an existing daemon session")
    parser.add_argument("--stop", action="store_true", help="Stop the running daemon")
    parser.add_argument("--write-default-config", action="store_true", help="Write the default config and exit")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.write_default_config:
        path = write_default_config(args.config)
        print(path)
        return 0

    if args.stop:
        return 0 if stop_running_daemon() else 1

    if args.daemon:
        return run_daemon(args.config, replace=args.replace)

    return run_editor(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
