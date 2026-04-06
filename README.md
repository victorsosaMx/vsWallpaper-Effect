<h1 align="center">vsWallpaper-Effect</h1>

<p align="center">
  <img src="vswallpaper-effect.png" alt="vsWallpaper-Effect" width="180"/>
</p>

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A wallpaper effects engine for Wayland — animate your desktop with GPU-accelerated effects rendered in real time on top of any image or folder slideshow.

Includes a GTK3 editor for live configuration and a background daemon that pins itself to the Wayland background layer via `gtk-layer-shell`.

---

## Who is this for?

vsWallpaper-Effect is for people who want their desktop to feel alive without sacrificing performance.

If you run Hyprland (or any Wayland compositor that supports the layer-shell protocol) and want rain, aurora lights, a matrix rain, starfields or animated water over your wallpaper — and you want it configurable without editing JSON files by hand — this is the tool.

The editor shows a live preview as you change every parameter. The daemon runs as a systemd user service and starts automatically on login.

---

## Features

- **GPU-accelerated rendering** — all effects run as GLSL fragment shaders via OpenGL; Cairo is only used as a fallback when PyOpenGL is not installed
- **9 built-in effects** — rain, matrix, aurora, warp, snow, gradient, stars, waves, droplets
- **Live editor preview** — embedded preview updates in real time as you adjust any parameter
- **Daemon mode** — fullscreen background layer via `gtk-layer-shell`; click-through, all monitors supported
- **Wallpaper support** — single image or folder slideshow with configurable rotation interval
- **Per-effect parameters** — speed, opacity, density, 3 explicit colors, vertical position
- **Theme accent color** — one global color drives defaults; each effect can override it
- **Setup tab** — manage the systemd user service and disable conflicting wallpaper daemons (swww, swaybg, hyprpaper…) from inside the editor
- **Reversible autostart management** — conflicting `exec-once` entries in `autostart.conf` are commented out and can be restored verbatim
- **Light / Dark editor theme** — toggle in the header; defaults to light
- **Export config** — export `config.json` as a zip for backup or sharing
- **vsHub tab** — browse and launch other tools in the vs ecosystem

---

## Effects

| Effect | Description | Key parameters |
|---|---|---|
| **rain** | Streaking raindrops with organic wind drift | speed, density, color |
| **matrix** | Falling character streams with a custom Matrix font | speed, density, color |
| **aurora** | Sine-wave light bands with gradient fill | speed, density, color × 3, vertical position |
| **warp** | Star trails radiating from center — warp speed | speed, density, color |
| **snow** | Soft circular flakes with sine drift | speed, density, color |
| **gradient** | Animated mesh gradient — soft color blobs in Lissajous paths | speed, density, color × 3, vertical position (coverage) |
| **stars** | Three-layer parallax starfield — far/mid/near; near layer twinkles | speed, density, color |
| **waves** | Multi-layer horizontal sine waves scrolling rightward | speed, density, color × 3, vertical position (water level) |
| **droplets** | Raindrop ripples — impact points emit expanding concentric rings | speed, density, color |

All effects overlay seamlessly on top of a static wallpaper or a rotating folder slideshow.

---

## Requirements

- Python 3.10+
- `python-gobject` — GTK3 Python bindings
- `gtk3`
- `gtk-layer-shell` — Wayland layer-shell support
- `python-cairo` — Cairo rendering (editor preview)
- `PyOpenGL` (`pip install --user PyOpenGL`) — **required for the daemon**; without it the background layer will not start

Optional:
- `fontconfig` — font detection for the matrix effect custom font

---

## Installation

### Manual

```bash
git clone https://github.com/victorsosaMx/vsWallpaper-Effect
cd vsWallpaper-Effect
pip install -e .
```

Or run directly without installing:

```bash
chmod +x vswallpaper-effect
./vswallpaper-effect
```

### Install dependencies (Arch Linux)

```bash
sudo pacman -S python-gobject gtk3 gtk-layer-shell python-cairo fontconfig
pip install --user PyOpenGL   # required for the daemon
```

---

## Usage

### Editor (default)

```bash
./vswallpaper-effect
```

Opens the GTK editor with a live preview. **Apply** writes `config.json` and (re)starts the daemon.

### Daemon

```bash
./vswallpaper-effect --daemon --replace
```

Starts the fullscreen background layer. `--replace` kills any running instance before starting.

### Stop

```bash
./vswallpaper-effect --stop
```

Kills the running daemon.

### Write default config

```bash
./vswallpaper-effect --write-default-config
```

Writes a starter `~/.config/vswallpaper-effect/config.json` with all default values.

---

## Configuration

Config file: `~/.config/vswallpaper-effect/config.json`

The editor writes this file on every Apply. You can also edit it by hand — it is plain JSON.

Key fields:

```json
{
  "wallpaper": "/path/to/image.jpg",
  "folder": "",
  "mode": "single",
  "interval": 300,
  "theme_accent": "#80c8e0",
  "effect": {
    "type": "rain",
    "enabled": true,
    "speed": 1.0,
    "opacity": 0.55,
    "density": 100,
    "color": "",
    "color2": "",
    "color3": "",
    "vertical_pos": 50
  },
  "runtime": {
    "all_monitors": false,
    "click_through": true
  }
}
```

`color`, `color2`, `color3` — hex strings. If empty, the effect uses `theme_accent` (and auto-derived darker tones for `color2`/`color3`).

---

## Autostart as a systemd service

The **Setup** tab in the editor manages this for you. It creates and enables a systemd user service so vsWallpaper-Effect starts on login.

To do it manually:

```bash
# Create the service file
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/vswallpaper-effect.service << 'EOF'
[Unit]
Description=vsWallpaper-Effect daemon
After=graphical-session.target

[Service]
ExecStart=/path/to/vswallpaper-effect --daemon --replace
Restart=on-failure

[Install]
WantedBy=graphical-session.target
EOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now vswallpaper-effect.service
```

---

## Acknowledgements

**Runtime**
- [GTK3](https://www.gtk.org/) / [PyGObject](https://gitlab.gnome.org/GNOME/pygobject) — GUI toolkit and Python bindings
- [PyCairo](https://pycairo.readthedocs.io/) — 2D graphics, editor preview and Cairo fallback renderer
- [PyOpenGL](https://pyopengl.sourceforge.net/) — OpenGL bindings for GPU-accelerated GLSL shaders
- [gtk-layer-shell](https://github.com/wmww/gtk-layer-shell) by wmww — Wayland layer-shell protocol for the background layer
- [Hyprland](https://github.com/hyprwm/Hyprland) by Vaxry — Wayland compositor

**Font**
- [Matrix Code NFI](https://www.dafont.com/matrix-code-nfi.font) — custom font used by the matrix effect

---

## License

MIT — do whatever you want, credit appreciated.

---

*Made with GTK3, GLSL and too much caffeine.*
