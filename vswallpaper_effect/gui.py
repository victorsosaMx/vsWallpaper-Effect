from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from . import __version__
from .config import PID_PATH, load_config, resolve_config_path, save_config
from .layer_window import make_preview_area
from .model import AUTOSTART_CONF, DISABLE_MARKER, SERVICE_NAME, AppConfig
from .style import THEME_DARK, THEME_LIGHT, build_css
from .utils import format_seconds, hex_to_rgb, normalize_hex_color

# (label, pacman_pkg_or_None, python_import_or_None, which_binary_or_None, install_cmd, description)
_DEPS = [
    ("python-gobject",  "python-gobject",  "gi",      None,       "sudo pacman -S --needed python-gobject",  "GTK3 Python bindings"),
    ("gtk3",            "gtk3",            None,      None,       "sudo pacman -S --needed gtk3",            "GTK3 toolkit"),
    ("gtk-layer-shell", "gtk-layer-shell", None,      None,       "sudo pacman -S --needed gtk-layer-shell", "Wayland layer-shell support"),
    ("python-cairo",    "python-cairo",    "cairo",   None,       "sudo pacman -S --needed python-cairo",    "Cairo rendering (preview)"),
    ("PyOpenGL",        None,              "OpenGL",  None,       "pip install --user PyOpenGL",             "OpenGL renderer — required for daemon"),
    ("fontconfig",      "fontconfig",      None,      "fc-list",  "sudo pacman -S --needed fontconfig",      "Font detection for matrix effect"),
]

_WALLPAPER_DAEMONS = [
    ("swww",       "swww",       "swww"),
    ("swaybg",     "swaybg",     "swaybg"),
    ("hyprpaper",  "hyprpaper",  "hyprpaper"),
    ("mpvpaper",   "mpvpaper",   "mpvpaper-git"),
    ("xwallpaper", "xwallpaper", "xwallpaper"),
]


def _hex_to_rgba(value: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.red, color.green, color.blue = hex_to_rgb(value, "#80c8e0")
    color.alpha = 1.0
    return color


def _rgba_to_hex(color: Gdk.RGBA) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        round(color.red * 255),
        round(color.green * 255),
        round(color.blue * 255),
    )


def _lbl(text: str, style: str = "field-label", xalign: float = 0.0) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_xalign(xalign)
    label.get_style_context().add_class(style)
    return label


def _section(text: str) -> Gtk.Label:
    return _lbl(text.upper(), "section-title")


def _hint(text: str) -> Gtk.Label:
    label = _lbl(text, "hint-label")
    label.set_line_wrap(True)
    label.set_margin_bottom(8)
    return label


def _spin(value, lower, upper, step=1, digits=0) -> Gtk.SpinButton:
    adj = Gtk.Adjustment(value=float(value), lower=lower, upper=upper, step_increment=step, page_increment=step * 10)
    button = Gtk.SpinButton(adjustment=adj, digits=digits)
    button.set_numeric(True)
    return button


def _combo(options: list[str], active: str) -> Gtk.ComboBoxText:
    combo = Gtk.ComboBoxText()
    for option in options:
        combo.append_text(option)
    try:
        combo.set_active(options.index(str(active)))
    except ValueError:
        combo.set_active(0)
    return combo


def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.get_style_context().add_class("page-scroll")
    viewport = Gtk.Viewport()
    viewport.set_shadow_type(Gtk.ShadowType.NONE)
    viewport.get_style_context().add_class("page-scroll")
    viewport.add(child)
    scrolled.add(viewport)
    return scrolled


def _field(label: str, widget: Gtk.Widget) -> Gtk.Box:
    row = Gtk.Box(spacing=12)
    row.set_margin_bottom(8)
    caption = _lbl(label)
    caption.set_size_request(180, -1)
    row.pack_start(caption, False, False, 0)
    row.pack_start(widget, True, True, 0)
    return row


def _switch_row(label: str, active: bool) -> tuple[Gtk.Box, Gtk.Switch]:
    row = Gtk.Box(spacing=12)
    row.set_margin_bottom(8)
    caption = _lbl(label)
    caption.set_size_request(180, -1)
    switch = Gtk.Switch()
    switch.set_active(active)
    switch.set_valign(Gtk.Align.CENTER)
    row.pack_start(caption, False, False, 0)
    row.pack_start(switch, False, False, 0)
    return row, switch


class VsWallpaperEffectEditor(Gtk.Window):
    def __init__(self, config_path: str | None = None, launcher_path: str | None = None):
        super().__init__(title="vsWallpaper-Effect")
        self.set_default_size(1080, 760)
        self.set_size_request(980, 680)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self._on_close)
        self.connect("key-press-event", self._on_key)

        self._config_path = resolve_config_path(config_path)
        self._launcher_path = os.path.abspath(launcher_path or sys.argv[0])
        self._cfg = AppConfig()
        self._w = {}
        self._preview = None
        self._notebook = None
        self._status_timer = 0
        self._dark = False
        self._theme = THEME_LIGHT
        self._css_provider = Gtk.CssProvider()
        self._path_lbl = None
        self._status_lbl = None
        self._status_hint = None
        self._theme_btn = None
        self._mode_rows = []
        self._aurora_container = None
        self._interval_hint = None

        display = Gdk.Display.get_default()
        screen = display.get_default_screen() if display else Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(screen, self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._apply_css()
        self._load_config()
        self._build_ui()
        self.show_all()

    def _on_close(self, *_):
        if self._preview:
            self._preview.stop()
        Gtk.main_quit()
        return False

    def _on_key(self, _, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval == Gdk.KEY_s:
            self._on_apply()
            return True
        return False

    def _apply_css(self):
        self._css_provider.load_from_data(build_css(self._theme))

    def _toggle_theme(self, *_):
        self._dark = not self._dark
        self._theme = THEME_DARK if self._dark else THEME_LIGHT
        self._apply_css()
        if self._theme_btn:
            self._theme_btn.set_label("☾" if self._dark else "☀")

    def _load_config(self):
        try:
            self._cfg = load_config(self._config_path)
        except Exception as exc:
            self._cfg = AppConfig()
            self._status(f"Config error, using defaults: {exc}", error=True)

    def _save_config(self, path: str | None = None) -> str:
        self._collect()
        self._config_path = save_config(self._cfg, path or self._config_path)
        if self._path_lbl:
            self._path_lbl.set_text(self._config_path)
        return self._config_path

    def _build_ui(self):
        self._w = {}
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        for widget, expand in (
            (self._make_header(), False),
            (self._make_preview(), False),
            (self._make_notebook(), True),
            (self._make_statusbar(), False),
        ):
            widget.set_margin_top(0)
            widget.set_margin_bottom(0)
            widget.set_margin_start(0)
            widget.set_margin_end(0)
            outer.pack_start(widget, expand, expand, 0)

        self.add(outer)
        self._sync_sensitive_rows()
        GLib.idle_add(self._refresh_preview)

    def _make_header(self) -> Gtk.Widget:
        header = Gtk.Box(spacing=0)
        header.get_style_context().add_class("app-header")

        _logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vswallpaper-effect.png")
        try:
            _pb = GdkPixbuf.Pixbuf.new_from_file_at_size(_logo_path, 40, 40)
            logo = Gtk.Image.new_from_pixbuf(_pb)
        except Exception:
            logo = Gtk.Label()
            logo.set_markup(f'<span font_desc="JetBrainsMono Nerd Font 22" foreground="{self._theme["acc"]}">󰸉</span>')
        logo.set_margin_end(10)
        header.pack_start(logo, False, False, 0)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        left.set_valign(Gtk.Align.CENTER)
        left.pack_start(_lbl("vsWallpaper-Effect", "app-title"), False, False, 0)
        self._path_lbl = _lbl(self._config_path, "app-path")
        left.pack_start(self._path_lbl, False, False, 0)
        header.pack_start(left, True, True, 0)

        buttons = Gtk.Box(spacing=8)
        buttons.set_valign(Gtk.Align.CENTER)

        theme_btn = Gtk.Button(label="☾" if self._dark else "☀")
        theme_btn.get_style_context().add_class("theme-btn")
        theme_btn.connect("clicked", self._toggle_theme)
        self._theme_btn = theme_btn

        open_btn = Gtk.Button(label="Open...")
        open_btn.connect("clicked", self._on_open)

        saveas_btn = Gtk.Button(label="Save As...")
        saveas_btn.connect("clicked", self._on_save_as)

        stop_btn = Gtk.Button(label="Stop")
        stop_btn.get_style_context().add_class("danger-btn")
        stop_btn.connect("clicked", self._on_stop)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.get_style_context().add_class("save-btn")
        apply_btn.connect("clicked", self._on_apply)

        for button in (theme_btn, open_btn, saveas_btn, stop_btn, apply_btn):
            buttons.pack_start(button, False, False, 0)
        header.pack_start(buttons, False, False, 0)
        return header

    def _make_preview(self) -> Gtk.Widget:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        wrap.get_style_context().add_class("preview-strip")
        preview_lbl = _lbl("Preview", "section-title")
        preview_lbl.set_margin_top(0)
        wrap.pack_start(preview_lbl, False, False, 0)

        frame = Gtk.Frame()
        frame.get_style_context().add_class("preview-frame")
        self._preview = make_preview_area(self._cfg)
        self._preview.set_size_request(-1, 240)
        frame.add(self._preview)
        wrap.pack_start(frame, True, True, 0)
        return wrap

    def _make_notebook(self) -> Gtk.Widget:
        notebook = Gtk.Notebook()
        notebook.set_tab_pos(Gtk.PositionType.LEFT)
        notebook.set_show_border(False)
        self._notebook = notebook

        pages = [
            ("Wallpaper", self._page_wallpaper()),
            ("Effect", self._page_effect()),
            ("Runtime", self._page_runtime()),
            ("Setup", self._page_setup()),
            ("vsHub", self._page_hub()),
            ("About", self._page_about()),
        ]
        for title, page in pages:
            tab = Gtk.Label(label=title)
            tab.set_xalign(0)
            notebook.append_page(page, tab)
        return notebook

    def _page_wallpaper(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(28)
        box.set_margin_end(28)
        box.set_margin_top(10)
        box.set_margin_bottom(18)

        box.pack_start(_section("Source"), False, False, 0)
        box.pack_start(_hint("Single mode renders one image. Folder mode rotates images at the configured interval."), False, False, 0)

        mode = _combo(["single", "folder"], self._cfg.mode)
        self._w["mode"] = mode
        mode.connect("changed", self._on_controls_changed)
        box.pack_start(_field("Mode", mode), False, False, 0)

        wallpaper_entry = Gtk.Entry()
        wallpaper_entry.set_text(self._cfg.wallpaper)
        wallpaper_entry.connect("changed", self._on_controls_changed)
        wall_browse = Gtk.Button(label="Browse...")
        wall_browse.connect("clicked", self._choose_image, wallpaper_entry)
        wall_row_box = Gtk.Box(spacing=6)
        wall_row_box.pack_start(wallpaper_entry, True, True, 0)
        wall_row_box.pack_start(wall_browse, False, False, 0)
        wall_row = _field("Image", wall_row_box)
        self._mode_rows.append((wall_row, "single"))
        self._w["wallpaper"] = wallpaper_entry
        box.pack_start(wall_row, False, False, 0)

        folder_entry = Gtk.Entry()
        folder_entry.set_text(self._cfg.folder)
        folder_entry.connect("changed", self._on_controls_changed)
        folder_browse = Gtk.Button(label="Browse...")
        folder_browse.connect("clicked", self._choose_folder, folder_entry)
        folder_row_box = Gtk.Box(spacing=6)
        folder_row_box.pack_start(folder_entry, True, True, 0)
        folder_row_box.pack_start(folder_browse, False, False, 0)
        folder_row = _field("Folder", folder_row_box)
        self._mode_rows.append((folder_row, "folder"))
        self._w["folder"] = folder_entry
        box.pack_start(folder_row, False, False, 0)

        interval = _spin(self._cfg.interval, 5, 86400, step=5)
        interval.connect("value-changed", self._on_controls_changed)
        self._w["interval"] = interval
        box.pack_start(_field("Interval (s)", interval), False, False, 0)
        self._interval_hint = _hint(f"Current rotation interval: {format_seconds(self._cfg.interval)}")
        box.pack_start(self._interval_hint, False, False, 0)

        return _scrolled(box)

    def _page_effect(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(28)
        box.set_margin_end(28)
        box.set_margin_top(10)
        box.set_margin_bottom(18)

        box.pack_start(_section("Effect"), False, False, 0)
        box.pack_start(_hint("Effects are rendered live in Cairo on top of the wallpaper."), False, False, 0)

        enabled_row, enabled = _switch_row("Enabled", self._cfg.effect.enabled)
        enabled.connect("notify::active", self._on_controls_changed)
        self._w["effect.enabled"] = enabled
        box.pack_start(enabled_row, False, False, 0)

        effect_type = _combo(
            ["rain", "matrix", "aurora", "warp", "snow", "gradient", "stars", "waves", "droplets"],
            self._cfg.effect.type,
        )
        effect_type.connect("changed", self._on_controls_changed)
        self._w["effect.type"] = effect_type
        box.pack_start(_field("Type", effect_type), False, False, 0)

        speed = _spin(self._cfg.effect.speed, 0.1, 10.0, step=0.1, digits=1)
        speed.connect("value-changed", self._on_controls_changed)
        self._w["effect.speed"] = speed
        box.pack_start(_field("Speed", speed), False, False, 0)

        opacity = _spin(self._cfg.effect.opacity, 0.0, 1.0, step=0.05, digits=2)
        opacity.connect("value-changed", self._on_controls_changed)
        self._w["effect.opacity"] = opacity
        box.pack_start(_field("Opacity", opacity), False, False, 0)

        density = _spin(self._cfg.effect.density, 10, 500, step=5)
        density.connect("value-changed", self._on_controls_changed)
        self._w["effect.density"] = density
        box.pack_start(_field("Density", density), False, False, 0)
        box.pack_start(_hint("Density controls particle count, wave frequency, spawn rate or blob count depending on the effect."), False, False, 0)

        color_entry = Gtk.Entry()
        color_entry.set_text(self._cfg.effect.color)
        color_entry.connect("changed", self._on_controls_changed)
        color_button = Gtk.ColorButton()
        color_button.set_rgba(_hex_to_rgba(self._cfg.effect.color or self._cfg.theme_accent))
        color_button.connect("color-set", self._on_effect_color_set, color_entry)
        use_accent = Gtk.Button(label="Use Accent")
        use_accent.connect("clicked", self._on_use_accent)
        color_row_box = Gtk.Box(spacing=6)
        color_row_box.pack_start(color_entry, True, True, 0)
        color_row_box.pack_start(color_button, False, False, 0)
        color_row_box.pack_start(use_accent, False, False, 0)
        self._w["effect.color"] = color_entry
        self._w["effect.color_button"] = color_button
        box.pack_start(_field("Color 1", color_row_box), False, False, 0)
        box.pack_start(_hint("Leave empty to use the theme accent color."), False, False, 0)

        # ── Extended controls (aurora / gradient / waves) ─────────────
        aurora_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        def _color_picker_row(key, initial):
            entry = Gtk.Entry()
            entry.set_text(initial)
            entry.connect("changed", self._on_controls_changed)
            btn = Gtk.ColorButton()
            btn.set_rgba(_hex_to_rgba(initial or self._cfg.theme_accent))
            def _on_btn_set(b, e=entry):
                e.set_text(_rgba_to_hex(b.get_rgba()))
                self._on_controls_changed()
            def _on_clear(*_, e=entry):
                e.set_text("")
                self._on_controls_changed()
            btn.connect("color-set", _on_btn_set)
            clear = Gtk.Button(label="Clear")
            clear.connect("clicked", _on_clear)
            row_box = Gtk.Box(spacing=6)
            row_box.pack_start(entry, True, True, 0)
            row_box.pack_start(btn, False, False, 0)
            row_box.pack_start(clear, False, False, 0)
            self._w[key] = entry
            self._w[key + "_button"] = btn
            return row_box

        c2_row = _color_picker_row("effect.color2", self._cfg.effect.color2)
        aurora_container.pack_start(_field("Color 2", c2_row), False, False, 0)
        c3_row = _color_picker_row("effect.color3", self._cfg.effect.color3)
        aurora_container.pack_start(_field("Color 3", c3_row), False, False, 0)
        aurora_container.pack_start(_hint("Colors 2 & 3: leave empty to auto-derive darker tones from Color 1."), False, False, 0)

        aurora_pos = _spin(self._cfg.effect.vertical_pos, 0, 100, step=5)
        aurora_pos.connect("value-changed", self._on_controls_changed)
        self._w["effect.vertical_pos"] = aurora_pos
        aurora_container.pack_start(_field("Vertical position", aurora_pos), False, False, 0)
        aurora_container.pack_start(_hint(
            "Aurora / waves: 0 = top, 50 = center, 100 = bottom. "
            "Gradient: controls blob coverage radius."
        ), False, False, 0)

        self._aurora_container = aurora_container
        box.pack_start(aurora_container, False, False, 0)

        return _scrolled(box)

    def _page_runtime(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(28)
        box.set_margin_end(28)
        box.set_margin_top(10)
        box.set_margin_bottom(18)

        box.pack_start(_section("Runtime"), False, False, 0)
        box.pack_start(_hint("The daemon runs as a fullscreen background layer and should stay below normal windows."), False, False, 0)

        monitors_row, monitors = _switch_row("All monitors", self._cfg.runtime.all_monitors)
        monitors.connect("notify::active", self._on_controls_changed)
        self._w["runtime.all_monitors"] = monitors
        box.pack_start(monitors_row, False, False, 0)

        click_row, click_switch = _switch_row("Click-through", self._cfg.runtime.click_through)
        click_switch.connect("notify::active", self._on_controls_changed)
        self._w["runtime.click_through"] = click_switch
        box.pack_start(click_row, False, False, 0)

        box.pack_start(_section("Theme"), False, False, 0)
        accent_entry = Gtk.Entry()
        accent_entry.set_text(self._cfg.theme_accent)
        accent_entry.connect("changed", self._on_controls_changed)
        accent_button = Gtk.ColorButton()
        accent_button.set_rgba(_hex_to_rgba(self._cfg.theme_accent))
        accent_button.connect("color-set", self._on_accent_color_set, accent_entry)
        self._w["theme_accent"] = accent_entry
        self._w["theme_accent_button"] = accent_button
        accent_row = Gtk.Box(spacing=6)
        accent_row.pack_start(accent_entry, True, True, 0)
        accent_row.pack_start(accent_button, False, False, 0)
        box.pack_start(_field("Accent", accent_row), False, False, 0)
        box.pack_start(_hint("The accent color is used when an effect does not define its own color."), False, False, 0)

        box.pack_start(_section("CLI"), False, False, 0)
        commands = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        commands.pack_start(_lbl("./vswallpaper-effect --daemon --replace", "module-title"), False, False, 0)
        commands.pack_start(_lbl("./vswallpaper-effect --stop", "module-title"), False, False, 0)
        commands.pack_start(_lbl("./vswallpaper-effect --write-default-config", "module-title"), False, False, 0)
        box.pack_start(commands, False, False, 0)

        return _scrolled(box)

    # ------------------------------------------------------------------
    # Autostart / service helpers
    # ------------------------------------------------------------------

    def _run_in_terminal(self, cmds: list[str], on_done=None) -> None:
        script = " && ".join(cmds) + "; echo; echo 'Done — press Enter to close'; read"
        try:
            proc = subprocess.Popen(["kitty", "-e", "bash", "-c", script])
            if on_done:
                def _wait():
                    proc.wait()
                    GLib.idle_add(on_done)
                threading.Thread(target=_wait, daemon=True).start()
        except FileNotFoundError:
            # kitty not available — try foot, then alacritty
            for term in ("foot", "alacritty"):
                try:
                    proc = subprocess.Popen([term, "-e", "bash", "-c", script])
                    if on_done:
                        def _wait():
                            proc.wait()
                            GLib.idle_add(on_done)
                        threading.Thread(target=_wait, daemon=True).start()
                    return
                except FileNotFoundError:
                    continue

    @staticmethod
    def _service_dir() -> str:
        return os.path.expanduser("~/.config/systemd/user")

    @staticmethod
    def _service_path() -> str:
        return os.path.join(
            os.path.expanduser("~/.config/systemd/user"), SERVICE_NAME
        )

    def _ensure_service_file(self) -> bool:
        """Write the systemd unit file if it does not exist. Returns True on success."""
        path = self._service_path()
        if os.path.exists(path):
            return True
        exe = shutil.which("vswallpaper-effect") or "vswallpaper-effect"
        unit = (
            "[Unit]\n"
            "Description=vsWallpaper-Effect — animated wallpaper daemon\n"
            "After=graphical-session.target\n"
            "PartOf=graphical-session.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={exe} --daemon --replace\n"
            f"ExecStop={exe} --stop\n"
            "Restart=on-failure\n"
            "RestartSec=3s\n\n"
            "[Install]\n"
            "WantedBy=graphical-session.target\n"
        )
        try:
            os.makedirs(self._service_dir(), exist_ok=True)
            with open(path, "w") as f:
                f.write(unit)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            return True
        except Exception:
            return False

    def _service_status(self) -> str:
        """Returns 'active', 'inactive', 'enabled', 'disabled', or 'not-installed'."""
        if not os.path.exists(self._service_path()):
            return "not-installed"
        r = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True, text=True
        )
        return r.stdout.strip() or "inactive"

    def _service_is_enabled(self) -> bool:
        r = subprocess.run(
            ["systemctl", "--user", "is-enabled", SERVICE_NAME],
            capture_output=True, text=True
        )
        return r.stdout.strip() == "enabled"

    @staticmethod
    def _autostart_path() -> str:
        return os.path.expanduser(AUTOSTART_CONF)

    def _autostart_scan(self) -> list[dict]:
        """Return list of {line, name, active} for wallpaper entries in autostart.conf."""
        path = self._autostart_path()
        if not os.path.exists(path):
            return []
        keywords = {n: b for n, b, _ in _WALLPAPER_DAEMONS}
        keywords["wallpaper.sh"] = "wallpaper.sh"
        results = []
        with open(path) as f:
            for raw in f:
                line = raw.rstrip("\n")
                # Already disabled by us
                if DISABLE_MARKER in line:
                    # extract the original name
                    inner = line.lstrip("#").replace(DISABLE_MARKER, "").strip()
                    name = next((n for n, b in keywords.items() if b in inner), inner[:40])
                    results.append({"line": line, "name": name, "active": False, "ours": True})
                    continue
                # Active exec-once with a known wallpaper keyword
                if line.strip().startswith("exec-once") and not line.strip().startswith("#"):
                    name = next((n for n, b in keywords.items() if b in line), None)
                    if name:
                        results.append({"line": line, "name": name, "active": True, "ours": False})
        return results

    def _autostart_disable(self, entry: dict) -> None:
        """Comment out a line in autostart.conf and record it in config."""
        path = self._autostart_path()
        with open(path) as f:
            content = f.read()
        new_line = f"#{entry['line']}  {DISABLE_MARKER}"
        content = content.replace(entry["line"], new_line, 1)
        with open(path, "w") as f:
            f.write(content)
        if entry["line"] not in self._cfg.autostart.disabled_entries:
            self._cfg.autostart.disabled_entries.append(entry["line"])
        self._save_config()

    def _autostart_enable(self, entry: dict) -> None:
        """Restore a previously commented-out line."""
        path = self._autostart_path()
        with open(path) as f:
            content = f.read()
        disabled_line = f"#{entry['line']}  {DISABLE_MARKER}"
        content = content.replace(disabled_line, entry["line"], 1)
        with open(path, "w") as f:
            f.write(content)
        try:
            self._cfg.autostart.disabled_entries.remove(entry["line"])
        except ValueError:
            pass
        self._save_config()

    # ------------------------------------------------------------------
    # Setup tab
    # ------------------------------------------------------------------

    def _page_setup(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(28)
        box.set_margin_end(28)
        box.set_margin_top(10)
        box.set_margin_bottom(18)

        # ── vsWallpaper-Effect Service ────────────────────────────────
        box.pack_start(_section("vsWallpaper-Effect Service"), False, False, 0)
        box.pack_start(_hint(
            f"Managed via systemd user service ({SERVICE_NAME}). "
            "Enable to auto-start on login. You can always revert."
        ), False, False, 0)

        svc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(svc_box, False, False, 0)

        def _build_service(*_):
            for c in svc_box.get_children():
                svc_box.remove(c)

            status = self._service_status()
            enabled = self._service_is_enabled()
            not_installed = status == "not-installed"

            row = Gtk.Box(spacing=10)
            row.set_margin_bottom(4)

            sym = Gtk.Label(label="●" if status == "active" else ("○" if not not_installed else "✗"))
            sym.get_style_context().add_class(
                "status-ok" if status == "active" else
                ("hint-label" if not not_installed else "danger-btn")
            )
            sym.set_size_request(18, -1)

            status_parts = []
            if not_installed:
                status_parts.append("service file not found")
            else:
                status_parts.append(status)
                status_parts.append("autostart: on" if enabled else "autostart: off")
            status_lbl = Gtk.Label(label="  ·  ".join(status_parts))
            status_lbl.set_xalign(0)
            status_lbl.get_style_context().add_class("field-label")

            row.pack_start(sym, False, False, 0)
            row.pack_start(status_lbl, True, True, 0)
            svc_box.pack_start(row, False, False, 0)

            btn_row = Gtk.Box(spacing=6)
            btn_row.set_margin_top(4)
            btn_row.set_margin_bottom(6)

            def _svc_run(cmds):
                self._ensure_service_file()
                self._run_in_terminal(cmds, on_done=lambda: GLib.idle_add(_build_service))

            if not_installed or not enabled:
                en_btn = Gtk.Button(label="Enable autostart")
                en_btn.get_style_context().add_class("save-btn")
                en_btn.connect("clicked", lambda *_: _svc_run([
                    "systemctl --user daemon-reload",
                    f"systemctl --user enable --now {SERVICE_NAME}",
                ]))
                btn_row.pack_start(en_btn, False, False, 0)
            if not not_installed and enabled:
                dis_btn = Gtk.Button(label="Disable autostart")
                dis_btn.get_style_context().add_class("danger-btn")
                dis_btn.connect("clicked", lambda *_: _svc_run([
                    f"systemctl --user disable --now {SERVICE_NAME}",
                ]))
                btn_row.pack_start(dis_btn, False, False, 0)
            if not not_installed and status != "active":
                start_btn = Gtk.Button(label="Start now")
                start_btn.connect("clicked", lambda *_: _svc_run([
                    f"systemctl --user start {SERVICE_NAME}",
                ]))
                btn_row.pack_start(start_btn, False, False, 0)
            if not not_installed and status == "active":
                stop_btn = Gtk.Button(label="Stop")
                stop_btn.get_style_context().add_class("danger-btn")
                stop_btn.connect("clicked", lambda *_: _svc_run([
                    f"systemctl --user stop {SERVICE_NAME}",
                ]))
                btn_row.pack_start(stop_btn, False, False, 0)

            ref_btn = Gtk.Button(label="⟳ Refresh")
            ref_btn.connect("clicked", _build_service)
            btn_row.pack_start(ref_btn, False, False, 0)
            svc_box.pack_start(btn_row, False, False, 0)
            svc_box.show_all()

        _build_service()

        # ── Autostart conflicts ───────────────────────────────────────
        aconf = self._autostart_path()
        box.pack_start(_section("Autostart Conflicts"), False, False, 0)
        box.pack_start(_hint(
            f"Entries in {AUTOSTART_CONF} that start on login and may conflict. "
            "Disable to comment them out — re-enable to restore exactly."
        ), False, False, 0)

        ac_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(ac_box, False, False, 0)

        def _build_autostart(*_):
            for c in ac_box.get_children():
                ac_box.remove(c)

            if not os.path.exists(aconf):
                ac_box.pack_start(_hint(f"File not found: {aconf}"), False, False, 0)
                ac_box.show_all()
                return

            entries = self._autostart_scan()
            if not entries:
                ac_box.pack_start(_hint("✓ No conflicting wallpaper entries found in autostart.conf."), False, False, 0)
            else:
                for entry in entries:
                    row = Gtk.Box(spacing=10)
                    row.set_margin_bottom(2)

                    sym = Gtk.Label(label="●" if entry["active"] else "○")
                    sym.get_style_context().add_class("status-ok" if entry["active"] else "hint-label")
                    sym.set_size_request(18, -1)

                    name_lbl = Gtk.Label(label=entry["name"])
                    name_lbl.set_xalign(0)
                    name_lbl.set_size_request(120, -1)
                    name_lbl.get_style_context().add_class("field-label")

                    st_lbl = Gtk.Label(label="active in autostart" if entry["active"] else "disabled in autostart")
                    st_lbl.set_xalign(0)
                    st_lbl.get_style_context().add_class("status-ok" if entry["active"] else "hint-label")

                    if entry["active"]:
                        tog_btn = Gtk.Button(label="Disable")
                        tog_btn.get_style_context().add_class("danger-btn")
                        def _do_disable(*_, e=entry):
                            self._autostart_disable(e)
                            GLib.idle_add(_build_autostart)
                        tog_btn.connect("clicked", _do_disable)
                    else:
                        tog_btn = Gtk.Button(label="Re-enable")
                        def _do_enable(*_, e=entry):
                            self._autostart_enable(e)
                            GLib.idle_add(_build_autostart)
                        tog_btn.connect("clicked", _do_enable)

                    row.pack_start(sym, False, False, 0)
                    row.pack_start(name_lbl, False, False, 0)
                    row.pack_start(st_lbl, True, True, 0)
                    row.pack_end(tog_btn, False, False, 0)
                    ac_box.pack_start(row, False, False, 0)

            ref_btn = Gtk.Button(label="⟳ Refresh")
            ref_btn.set_margin_top(4)
            ref_btn.connect("clicked", _build_autostart)
            ac_box.pack_start(ref_btn, False, False, 0)
            ac_box.show_all()

        _build_autostart()

        # ── Running daemons (current session) ────────────────────────
        box.pack_start(_section("Running Daemons"), False, False, 0)
        box.pack_start(_hint("Kill conflicting wallpaper daemons for the current session."), False, False, 0)

        daemon_results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(daemon_results, False, False, 0)

        def _is_running(binary):
            try:
                return subprocess.run(["pgrep", "-x", binary], capture_output=True).returncode == 0
            except Exception:
                return False

        def _build_daemons(*_):
            for c in daemon_results.get_children():
                daemon_results.remove(c)
            any_running = False
            for name, binary, _ in _WALLPAPER_DAEMONS:
                if not shutil.which(binary):
                    continue
                running = _is_running(binary)
                if running:
                    any_running = True
                row = Gtk.Box(spacing=10)
                row.set_margin_bottom(2)
                sym = Gtk.Label(label="●" if running else "○")
                sym.get_style_context().add_class("status-ok" if running else "hint-label")
                sym.set_size_request(18, -1)
                name_lbl = Gtk.Label(label=name)
                name_lbl.set_xalign(0)
                name_lbl.set_size_request(100, -1)
                name_lbl.get_style_context().add_class("field-label")
                st_lbl = Gtk.Label(label="running" if running else "stopped")
                st_lbl.set_xalign(0)
                st_lbl.get_style_context().add_class("status-ok" if running else "hint-label")
                kill_btn = Gtk.Button(label="Kill")
                kill_btn.get_style_context().add_class("danger-btn")
                kill_btn.set_sensitive(running)
                def _kill(*_, b=binary):
                    subprocess.run(["pkill", "-x", b], capture_output=True)
                    GLib.timeout_add(400, _build_daemons)
                kill_btn.connect("clicked", _kill)
                row.pack_start(sym, False, False, 0)
                row.pack_start(name_lbl, False, False, 0)
                row.pack_start(st_lbl, True, True, 0)
                row.pack_end(kill_btn, False, False, 0)
                daemon_results.pack_start(row, False, False, 0)

            if any_running:
                kill_all = Gtk.Button(label="⚠ Kill all")
                kill_all.get_style_context().add_class("danger-btn")
                kill_all.set_margin_top(6)
                def _kill_all(*_):
                    for _, b, _ in _WALLPAPER_DAEMONS:
                        subprocess.run(["pkill", "-x", b], capture_output=True)
                    GLib.timeout_add(400, _build_daemons)
                kill_all.connect("clicked", _kill_all)
                daemon_results.pack_start(kill_all, False, False, 0)
            elif not any(shutil.which(b) for _, b, _ in _WALLPAPER_DAEMONS):
                daemon_results.pack_start(_hint("No recognized wallpaper daemons installed."), False, False, 0)
            else:
                daemon_results.pack_start(_hint("✓ No conflicting daemons running."), False, False, 0)

            ref_btn = Gtk.Button(label="⟳ Refresh")
            ref_btn.set_margin_top(4)
            ref_btn.connect("clicked", _build_daemons)
            daemon_results.pack_start(ref_btn, False, False, 0)
            daemon_results.show_all()

        _build_daemons()

        # ── Dependencies ──────────────────────────────────────────────
        box.pack_start(_section("Dependencies"), False, False, 0)
        box.pack_start(_hint("Required libraries. PyOpenGL is required — without it the daemon will not start."), False, False, 0)

        dep_results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(dep_results, False, False, 0)

        def _dep_ok(pacman_pkg, py_import, which_bin):
            if pacman_pkg:
                try:
                    if subprocess.run(["pacman", "-Q", pacman_pkg], capture_output=True).returncode == 0:
                        return True
                except Exception:
                    pass
            if py_import:
                try:
                    subprocess.run(
                        ["python", "-c", f"import {py_import}"],
                        capture_output=True, check=True
                    )
                    return True
                except Exception:
                    pass
            if which_bin:
                return shutil.which(which_bin) is not None
            return False

        def _build_deps(*_):
            for c in dep_results.get_children():
                dep_results.remove(c)
            # missing: list of (label, install_cmd)
            missing = []
            for label, pacman_pkg, py_import, which_bin, install_cmd, desc in _DEPS:
                ok = _dep_ok(pacman_pkg, py_import, which_bin)
                if not ok:
                    missing.append((label, install_cmd))
                row = Gtk.Box(spacing=10)
                row.set_margin_bottom(2)
                sym = Gtk.Label(label="✓" if ok else "✗")
                sym.get_style_context().add_class("status-ok" if ok else "danger-btn")
                sym.set_size_request(18, -1)
                name_lbl = Gtk.Label(label=label)
                name_lbl.set_xalign(0)
                name_lbl.get_style_context().add_class("field-label" if ok else "module-title")
                desc_lbl = Gtk.Label(label=f"— {desc}")
                desc_lbl.set_xalign(0)
                desc_lbl.get_style_context().add_class("hint-label")
                row.pack_start(sym, False, False, 0)
                row.pack_start(name_lbl, False, False, 0)
                row.pack_start(desc_lbl, False, False, 0)
                dep_results.pack_start(row, False, False, 0)
            dep_results.show_all()

            btn_row = Gtk.Box(spacing=8)
            btn_row.set_margin_top(8)
            if missing:
                # Group by install_cmd so one terminal per command type
                from collections import defaultdict
                by_cmd: dict = defaultdict(list)
                for lbl, cmd in missing:
                    by_cmd[cmd].append(lbl)
                cmds = list(by_cmd.keys())
                labels = ", ".join(lbl for lbl, _ in missing)
                install_btn = Gtk.Button(label=f"Install missing ({len(missing)}): {labels}")
                install_btn.get_style_context().add_class("save-btn")
                install_btn.connect("clicked", lambda *_: self._run_in_terminal(
                    cmds, on_done=_build_deps
                ))
                btn_row.pack_start(install_btn, False, False, 0)
            ref_btn = Gtk.Button(label="⟳ Refresh")
            ref_btn.connect("clicked", _build_deps)
            btn_row.pack_start(ref_btn, False, False, 0)
            dep_results.pack_start(btn_row, False, False, 0)

        _build_deps()

        return _scrolled(box)

    # ------------------------------------------------------------------
    # vsHub tab
    # ------------------------------------------------------------------

    def _page_hub(self) -> Gtk.Widget:
        _HUB_URL   = "https://raw.githubusercontent.com/victorsosaMx/vsHub/main/tools.json"
        _CACHE     = os.path.expanduser("~/.cache/vshub/tools.json")
        _FALLBACK  = [
            {"name": "vsWallpaper-Effect", "desc": "Animated wallpaper with GL effects",
             "icon": "󰸉", "exe": "vswallpaper-effect", "aur": "vswallpaper-effect-git",
             "github": "https://github.com/victorsosaMx/vsWalpaper-Effect"},
            {"name": "vsWaybar Studio",    "desc": "Graphical Waybar configurator",
             "icon": "󰀙", "exe": "vswaybar-studio",    "aur": "vswaybar-studio-git",
             "github": "https://github.com/victorsosaMx/vsWaybar-Studio"},
            {"name": "vsFetch Settings",   "desc": "Neofetch/fastfetch visual editor",
             "icon": "󰍛", "exe": "vsfetch-settings",   "aur": "vsfetch-settings-git",
             "github": "https://github.com/victorsosaMx/vsFetch-Settings"},
            {"name": "vsHyprland Manager", "desc": "Hyprland graphical config editor",
             "icon": "󱙌", "exe": "vshyprland-manager",  "aur": "vshyprland-manager-git",
             "github": "https://github.com/victorsosaMx/vsHyprland-Manager"},
        ]

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_margin_top(10)
        box.set_margin_bottom(18)

        # Header
        hdr = Gtk.Box(spacing=10)
        title_lbl = Gtk.Label()
        title_lbl.set_markup('<span size="large" weight="bold">vsHub</span>')
        title_lbl.set_xalign(0)
        hdr.pack_start(title_lbl, True, True, 0)
        refresh_btn = Gtk.Button(label="⟳")
        hdr.pack_end(refresh_btn, False, False, 0)
        box.pack_start(hdr, False, False, 0)

        sub_lbl = Gtk.Label(label="The vs ecosystem — all tools in one place")
        sub_lbl.set_xalign(0)
        sub_lbl.get_style_context().add_class("hint-label")
        box.pack_start(sub_lbl, False, False, 0)

        source_lbl = Gtk.Label(label="Built-in list · fetching updates…")
        source_lbl.set_xalign(0)
        source_lbl.get_style_context().add_class("hint-label")
        source_lbl.set_margin_bottom(10)
        box.pack_start(source_lbl, False, False, 0)

        cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(cards_box, True, True, 0)

        _tools = [list(t.values()) and t for t in _FALLBACK]  # start with fallback

        def _aur_helper():
            if shutil.which("yay"):  return "yay"
            if shutil.which("paru"): return "paru"
            return None

        def _build_cards(tools=None):
            nonlocal _tools
            if tools:
                _tools = tools
            for child in cards_box.get_children():
                cards_box.remove(child)
            helper = _aur_helper()
            for tool in _tools:
                name    = tool.get("name", "")
                desc    = tool.get("desc", "")
                icon    = tool.get("icon", "󰀻")
                exe     = tool.get("exe", "")
                aur     = tool.get("aur", "")
                github  = tool.get("github", "")
                installed = bool(shutil.which(exe)) if exe else False

                card = Gtk.Box(spacing=12)
                card.set_margin_bottom(4)
                card.get_style_context().add_class("plugin-card-active" if installed else "plugin-card")

                icon_lbl = Gtk.Label(label=icon)
                icon_lbl.set_markup(f'<span size="large" foreground="{self._theme["acc"] if installed else self._theme["dim"]}">{icon}</span>')
                icon_lbl.set_size_request(28, -1)
                card.pack_start(icon_lbl, False, False, 0)

                info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                name_lbl = Gtk.Label()
                name_lbl.set_markup(f'<b>{name}</b>')
                name_lbl.set_xalign(0)
                desc_lbl = Gtk.Label(label=desc)
                desc_lbl.set_xalign(0)
                desc_lbl.get_style_context().add_class("hint-label")
                info.pack_start(name_lbl, False, False, 0)
                info.pack_start(desc_lbl, False, False, 0)
                card.pack_start(info, True, True, 0)

                if installed:
                    launch_btn = Gtk.Button(label="Launch →")
                    launch_btn.get_style_context().add_class("save-btn")
                    launch_btn.connect("clicked", lambda *_, e=exe: subprocess.Popen([e]))
                    card.pack_end(launch_btn, False, False, 0)
                else:
                    btn_box = Gtk.Box(spacing=6)
                    if github:
                        gh_btn = Gtk.Button(label="GitHub")
                        gh_btn.connect("clicked", lambda *_, u=github: subprocess.Popen(["xdg-open", u]))
                        btn_box.pack_start(gh_btn, False, False, 0)
                    if aur and helper:
                        inst_btn = Gtk.Button(label=f"Install ({helper})")
                        inst_btn.get_style_context().add_class("open-btn")
                        inst_btn.connect("clicked", lambda *_, p=aur, h=helper: subprocess.Popen(
                            f"{h} -S {p}", shell=True
                        ))
                        btn_box.pack_start(inst_btn, False, False, 0)
                    card.pack_end(btn_box, False, False, 0)

                cards_box.pack_start(card, False, False, 0)
            cards_box.show_all()

        def _fetch(*_):
            try:
                os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
                req = urllib.request.Request(_HUB_URL,
                    headers={"User-Agent": f"vsWallpaper-Effect/{__version__}"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                with open(_CACHE, "w") as f:
                    json.dump(data, f)
                ts = time.strftime("%H:%M")
                GLib.idle_add(source_lbl.set_text, f"github.com/victorsosaMx/vsHub · updated {ts}")
                GLib.idle_add(_build_cards, data)
            except Exception:
                if os.path.exists(_CACHE):
                    try:
                        with open(_CACHE) as f:
                            data = json.load(f)
                        GLib.idle_add(source_lbl.set_text, "Cached list (offline)")
                        GLib.idle_add(_build_cards, data)
                    except Exception:
                        pass
                else:
                    GLib.idle_add(source_lbl.set_text, "Built-in list (offline)")

        _build_cards()
        refresh_btn.connect("clicked", lambda *_: threading.Thread(target=_fetch, daemon=True).start())
        threading.Thread(target=_fetch, daemon=True).start()

        return _scrolled(box)

    # ------------------------------------------------------------------
    # About tab
    # ------------------------------------------------------------------

    def _page_about(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_start(28)
        box.set_margin_end(28)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_halign(Gtk.Align.CENTER)

        # ── App identity ──────────────────────────────────────────────
        _logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vswallpaper-effect.png")
        try:
            _pb = GdkPixbuf.Pixbuf.new_from_file_at_size(_logo_path, 72, 72)
            icon_widget = Gtk.Image.new_from_pixbuf(_pb)
        except Exception:
            icon_widget = Gtk.Label()
            icon_widget.set_markup('<span font_desc="JetBrainsMono Nerd Font 40">󰸉</span>')
        icon_widget.set_margin_bottom(8)
        box.pack_start(icon_widget, False, False, 0)

        app_name = Gtk.Label()
        app_name.set_markup('<span size="xx-large" weight="bold">vsWallpaper-Effect</span>')
        box.pack_start(app_name, False, False, 0)

        ver_lbl = Gtk.Label(label=f"v{__version__}")
        ver_lbl.get_style_context().add_class("hint-label")
        box.pack_start(ver_lbl, False, False, 0)

        desc_lbl = Gtk.Label(label="Animated wallpaper with real-time generative effects")
        desc_lbl.get_style_context().add_class("hint-label")
        desc_lbl.set_margin_bottom(4)
        box.pack_start(desc_lbl, False, False, 0)

        lic_lbl = Gtk.Label(label="MIT License")
        lic_lbl.set_markup(f'<span foreground="{self._theme["acc"]}" size="small">MIT License</span>')
        lic_lbl.set_margin_bottom(16)
        box.pack_start(lic_lbl, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 8)

        # ── Author ────────────────────────────────────────────────────
        author_row = Gtk.Box(spacing=12)
        author_row.set_halign(Gtk.Align.CENTER)
        author_row.set_margin_top(8)
        author_row.set_margin_bottom(8)
        author_icon = Gtk.Label()
        author_icon.set_markup('<span font="28">󰀄</span>')
        author_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        author_name = Gtk.Label()
        author_name.set_markup('<b>Víctor Sosa</b>')
        author_name.set_xalign(0)
        author_role = Gtk.Label(label="Developer · victorsosa.com")
        author_role.set_xalign(0)
        author_role.get_style_context().add_class("hint-label")
        author_info.pack_start(author_name, False, False, 0)
        author_info.pack_start(author_role, False, False, 0)
        author_row.pack_start(author_icon, False, False, 0)
        author_row.pack_start(author_info, False, False, 0)
        box.pack_start(author_row, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 8)

        # ── Links ─────────────────────────────────────────────────────
        link_row = Gtk.Box(spacing=8)
        link_row.set_halign(Gtk.Align.CENTER)
        link_row.set_margin_top(4)
        link_row.set_margin_bottom(16)
        for label, url in [
            ("GitHub", "https://github.com/victorsosaMx/vsWalpaper-Effect"),
            ("Hyprland", "https://hyprland.org"),
            ("Website", "https://victorsosa.com"),
        ]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda *_, u=url: subprocess.Popen(["xdg-open", u]))
            link_row.pack_start(btn, False, False, 0)
        box.pack_start(link_row, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 8)

        # ── Stack ─────────────────────────────────────────────────────
        stack_lbl = Gtk.Label()
        stack_lbl.set_markup('<span size="small">GTK3 + Cairo + OpenGL (gl-renderer) + gtk-layer-shell</span>')
        stack_lbl.get_style_context().add_class("hint-label")
        stack_lbl.set_margin_top(8)
        stack_lbl.set_margin_bottom(4)
        box.pack_start(stack_lbl, False, False, 0)

        note_lbl = Gtk.Label(label="Preview uses Cairo · Daemon uses OpenGL when available")
        note_lbl.get_style_context().add_class("hint-label")
        box.pack_start(note_lbl, False, False, 0)

        return _scrolled(box)

    def _make_statusbar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=10)
        bar.get_style_context().add_class("status-bar")
        self._status_lbl = Gtk.Label(label="")
        self._status_lbl.set_xalign(0)
        self._status_lbl.get_style_context().add_class("status-ok")
        self._status_hint = Gtk.Label(label="")
        self._status_hint.set_xalign(0)
        self._status_hint.get_style_context().add_class("status-hint")
        bar.pack_start(self._status_lbl, False, False, 0)
        bar.pack_start(self._status_hint, False, False, 0)
        return bar

    def _status(self, text: str, hint: str = "", error: bool = False):
        if self._status_lbl:
            self._status_lbl.set_text(text)
        if self._status_hint:
            self._status_hint.set_text(hint)
        if self._status_timer:
            GLib.source_remove(self._status_timer)
            self._status_timer = 0
        if text:
            self._status_timer = GLib.timeout_add_seconds(5, self._clear_status)

    def _clear_status(self):
        if self._status_lbl:
            self._status_lbl.set_text("")
        if self._status_hint:
            self._status_hint.set_text("")
        self._status_timer = 0
        return False

    def _refresh_preview(self):
        self._collect()
        self._sync_sensitive_rows()
        if self._preview:
            self._preview.set_config(self._cfg)
        return False

    def _collect(self):
        self._cfg.mode = self._w["mode"].get_active_text()
        self._cfg.wallpaper = self._w["wallpaper"].get_text().strip()
        self._cfg.folder = self._w["folder"].get_text().strip()
        self._cfg.interval = int(self._w["interval"].get_value())
        self._cfg.theme_accent = normalize_hex_color(self._w["theme_accent"].get_text(), self._cfg.theme_accent)
        self._cfg.effect.enabled = self._w["effect.enabled"].get_active()
        self._cfg.effect.type = self._w["effect.type"].get_active_text()
        self._cfg.effect.speed = float(self._w["effect.speed"].get_value())
        self._cfg.effect.opacity = float(self._w["effect.opacity"].get_value())
        self._cfg.effect.density = int(self._w["effect.density"].get_value())
        self._cfg.effect.color = normalize_hex_color(self._w["effect.color"].get_text(), "")
        self._cfg.effect.color2 = normalize_hex_color(self._w["effect.color2"].get_text(), "")
        self._cfg.effect.color3 = normalize_hex_color(self._w["effect.color3"].get_text(), "")
        self._cfg.effect.vertical_pos = int(self._w["effect.vertical_pos"].get_value())
        self._cfg.runtime.all_monitors = self._w["runtime.all_monitors"].get_active()
        self._cfg.runtime.click_through = self._w["runtime.click_through"].get_active()
        self._cfg.normalize()

    def _sync_sensitive_rows(self):
        mode = self._w["mode"].get_active_text()
        for row, target_mode in self._mode_rows:
            row.set_sensitive(mode == target_mode)
        effect_type = self._w["effect.type"].get_active_text()
        if self._aurora_container is not None:
            self._aurora_container.set_visible(effect_type in ("aurora", "gradient", "waves"))
        if self._interval_hint is not None:
            self._interval_hint.set_text(f"Current rotation interval: {format_seconds(int(self._w['interval'].get_value()))}")

    def _on_controls_changed(self, *_):
        self._refresh_preview()

    def _on_effect_color_set(self, button, entry):
        entry.set_text(_rgba_to_hex(button.get_rgba()))

    def _on_accent_color_set(self, button, entry):
        entry.set_text(_rgba_to_hex(button.get_rgba()))

    def _on_use_accent(self, *_):
        self._w["effect.color"].set_text("")
        self._refresh_preview()

    def _choose_image(self, _, entry):
        dialog = Gtk.FileChooserDialog(
            title="Select wallpaper image",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK),
        )
        filter_images = Gtk.FileFilter()
        filter_images.set_name("Images")
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.webp"):
            filter_images.add_pattern(pattern)
        dialog.add_filter(filter_images)
        if dialog.run() == Gtk.ResponseType.OK:
            entry.set_text(dialog.get_filename())
        dialog.destroy()

    def _choose_folder(self, _, entry):
        dialog = Gtk.FileChooserDialog(
            title="Select wallpaper folder",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK),
        )
        if dialog.run() == Gtk.ResponseType.OK:
            entry.set_text(dialog.get_filename())
        dialog.destroy()

    def _on_open(self, *_):
        dialog = Gtk.FileChooserDialog(
            title="Open config",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK),
        )
        filter_json = Gtk.FileFilter()
        filter_json.set_name("JSON")
        filter_json.add_pattern("*.json")
        dialog.add_filter(filter_json)
        if dialog.run() == Gtk.ResponseType.OK:
            self._config_path = dialog.get_filename()
            dialog.destroy()
            self._load_config()
            self._rebuild_ui()
            self._status("Config loaded")
            return
        dialog.destroy()

    def _on_save_as(self, *_):
        dialog = Gtk.FileChooserDialog(
            title="Save config as",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK),
        )
        dialog.set_current_name(os.path.basename(self._config_path))
        dialog.set_do_overwrite_confirmation(True)
        if dialog.run() == Gtk.ResponseType.OK:
            destination = dialog.get_filename()
            dialog.destroy()
            self._save_config(destination)
            self._status("Config saved", destination)
            return
        dialog.destroy()

    def _on_apply(self, *_):
        try:
            config_path = self._save_config()
            self._launch_daemon(config_path)
            self._status("Background applied", config_path)
        except Exception as exc:
            self._status(f"Apply failed: {exc}", error=True)

    def _on_stop(self, *_):
        if self._stop_daemon():
            self._status("Background stopped")
        else:
            self._status("No running daemon found")

    def _launch_daemon(self, config_path: str):
        self._stop_daemon()
        import time as _time
        _time.sleep(0.25)  # let the old daemon release the layer-shell surface
        log_path = os.path.join(os.path.dirname(PID_PATH), "daemon.log")
        command = [sys.executable, self._launcher_path, "--daemon", "--replace", "--config", config_path]
        with open(log_path, "w") as log_fh:
            proc = subprocess.Popen(
                command, stdout=log_fh, stderr=log_fh,
                start_new_session=True,  # detach from editor's process group
            )
        # give it 0.4 s and check it hasn't died immediately
        _time.sleep(0.4)
        if proc.poll() is not None:
            try:
                with open(log_path, "r") as lf:
                    error_text = lf.read(300).strip()
            except Exception:
                error_text = "unknown error"
            raise RuntimeError(f"Daemon exited ({proc.returncode}): {error_text}")

    def _stop_daemon(self) -> bool:
        try:
            with open(PID_PATH, "r", encoding="utf-8") as handle:
                pid = int(handle.read().strip())
        except Exception:
            return False
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False
        finally:
            try:
                os.remove(PID_PATH)
            except OSError:
                pass

    def _rebuild_ui(self):
        page = self._notebook.get_current_page() if self._notebook else 0
        if self._preview:
            self._preview.stop()
        for child in self.get_children():
            self.remove(child)
        self._build_ui()
        self._notebook.set_current_page(page)
        self.show_all()
