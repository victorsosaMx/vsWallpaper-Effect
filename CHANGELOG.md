# Changelog

## [1.0.0] — 2026-04-05

### Initial release

#### Effects
- **Rain** — animated raindrops with customizable density, speed, and opacity
- **Matrix** — cascading character streams using a custom glyph atlas rendered via Cairo/Pango; custom Matrix font included
- **Aurora** — multi-band sine-wave aurora borealis; supports up to 3 explicit colors with automatic darker-tone derivation when left empty; vertical position control
- **Warp** — hyperspace warp tunnel effect
- **Snow** — drifting snowflake particles
- **Gradient** — animated mesh gradient: soft color blobs drift in Lissajous paths creating a macOS-style flowing gradient; density controls blob count; vertical position controls coverage radius
- **Stars** — three-layer parallax starfield; far/mid/near layers at different speeds; near layer twinkles
- **Waves** — multi-layer water waves scrolling horizontally; front layers faster and brighter, back layers slower and darker; vertical position sets water level; density controls wave frequency
- **Droplets** — raindrop ripples: random impact points emit 3 concentric expanding rings that fade as they grow

#### Dual renderer
- **OpenGL renderer** (daemon) — GPU-accelerated GLSL shaders via PyOpenGL for all 9 effects; runs as a fullscreen Wayland layer surface using gtk-layer-shell; click-through support; covers waybar exclusive zones (`set_exclusive_zone(-1)`)
- **Cairo renderer** (editor preview fallback) — software fallback when PyOpenGL is not installed; no GPU dependency required

#### Editor (GTK3)
- Live preview embedded in the editor window via `RendererAreaCairo`
- **Effect** tab — type selector (all 9 effects), speed, opacity, density, color picker; Color 2 / Color 3 / Vertical position controls visible for `aurora`, `gradient`, and `waves`
- **Wallpaper** tab — single image or folder rotation mode with configurable interval
- **Runtime** tab — all-monitors toggle, click-through toggle, theme accent color
- **Setup** tab — systemd user service management (enable/disable/start/stop via terminal); autostart conflict detection with reversible disable/re-enable; wallpaper daemon manager (swww, swaybg, hyprpaper, mpvpaper, xwallpaper); dependency checker with multi-strategy detection (pacman, python import, which) and install via terminal
- **vsHub** tab — ecosystem browser fetching live tool manifest from GitHub
- **About** tab — version, author, license, stack info
- Dark / Light theme toggle (default: light)
- App icon in header and About page (`vswallpaper-effect.png`)
- Ctrl+S applies and saves; Open / Save As support

#### Daemon mode
- `--daemon --replace` — starts as background Wayland layer surface, replaces any running instance
- `--stop` — stops the running daemon via PID file
- `--write-default-config` — writes a default config to `~/.config/vswallpaper-effect/config.json`
- Multi-monitor support via `BackgroundSession`

#### Configuration
- Config: `~/.config/vswallpaper-effect/config.json`
- PID file: `~/.cache/vswallpaper-effect/daemon.pid`
- Fields: `wallpaper`, `folder`, `mode`, `interval`, `theme_accent`; effect: `type`, `enabled`, `speed`, `opacity`, `color`, `color2`, `color3`, `density`, `vertical_pos`; runtime: `all_monitors`, `click_through`; autostart: `service_enabled`, `disabled_entries`
