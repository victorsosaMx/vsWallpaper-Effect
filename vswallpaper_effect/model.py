from __future__ import annotations

from dataclasses import dataclass, field

from .utils import clamp, normalize_hex_color


SUPPORTED_EFFECTS = ("rain", "matrix", "aurora", "warp", "snow", "gradient", "stars", "waves", "droplets")
SUPPORTED_MODES = ("single", "folder")
DEFAULT_ACCENT_COLOR = "#80c8e0"

AUTOSTART_CONF = "~/.config/hypr/modules/autostart.conf"
SERVICE_NAME   = "vswallpaper-effect.service"
DISABLE_MARKER = "# disabled by vsWallpaper-Effect"


@dataclass
class AutostartConfig:
    """Tracks autostart state so the user can always revert."""
    service_enabled: bool = False
    # Original lines commented-out in autostart.conf, stored verbatim for exact restore.
    disabled_entries: list = field(default_factory=list)

    def normalize(self) -> "AutostartConfig":
        self.service_enabled = bool(self.service_enabled)
        self.disabled_entries = [str(e) for e in (self.disabled_entries or [])]
        return self

    @classmethod
    def from_dict(cls, data: dict | None) -> "AutostartConfig":
        payload = data or {}
        return cls(
            service_enabled=payload.get("service_enabled", False),
            disabled_entries=list(payload.get("disabled_entries", [])),
        ).normalize()

    def to_dict(self) -> dict:
        return {
            "service_enabled": self.service_enabled,
            "disabled_entries": self.disabled_entries,
        }


@dataclass
class EffectConfig:
    type: str = "rain"
    enabled: bool = True
    speed: float = 1.0
    opacity: float = 0.55
    color: str = ""
    color2: str = ""
    color3: str = ""
    density: int = 100
    vertical_pos: int = 70

    def normalize(self) -> "EffectConfig":
        if self.type not in SUPPORTED_EFFECTS:
            self.type = "rain"
        self.enabled = bool(self.enabled)
        self.speed = float(clamp(float(self.speed or 1.0), 0.1, 10.0))
        self.opacity = float(clamp(float(self.opacity or 0.0), 0.0, 1.0))
        self.color = normalize_hex_color(self.color, "")
        self.color2 = normalize_hex_color(self.color2, "")
        self.color3 = normalize_hex_color(self.color3, "")
        self.density = int(clamp(int(self.density or 100), 10, 500))
        self.vertical_pos = int(clamp(int(self.vertical_pos if self.vertical_pos is not None else 70), 0, 100))
        return self

    @classmethod
    def from_dict(cls, data: dict | None) -> "EffectConfig":
        payload = data or {}
        return cls(
            type=payload.get("type", "rain"),
            enabled=payload.get("enabled", True),
            speed=payload.get("speed", 1.0),
            opacity=payload.get("opacity", 0.55),
            color=payload.get("color", ""),
            color2=payload.get("color2", ""),
            color3=payload.get("color3", ""),
            density=payload.get("density", 100),
            vertical_pos=payload.get("vertical_pos", 70),
        ).normalize()

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "enabled": self.enabled,
            "speed": self.speed,
            "opacity": self.opacity,
            "color": self.color,
            "color2": self.color2,
            "color3": self.color3,
            "density": self.density,
            "vertical_pos": self.vertical_pos,
        }


@dataclass
class RuntimeConfig:
    all_monitors: bool = True
    click_through: bool = True

    def normalize(self) -> "RuntimeConfig":
        self.all_monitors = bool(self.all_monitors)
        self.click_through = bool(self.click_through)
        return self

    @classmethod
    def from_dict(cls, data: dict | None) -> "RuntimeConfig":
        payload = data or {}
        return cls(
            all_monitors=payload.get("all_monitors", True),
            click_through=payload.get("click_through", True),
        ).normalize()

    def to_dict(self) -> dict:
        return {
            "all_monitors": self.all_monitors,
            "click_through": self.click_through,
        }


@dataclass
class AppConfig:
    wallpaper: str = ""
    folder: str = ""
    mode: str = "single"
    interval: int = 300
    theme_accent: str = DEFAULT_ACCENT_COLOR
    effect: EffectConfig = field(default_factory=EffectConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    autostart: AutostartConfig = field(default_factory=AutostartConfig)

    def normalize(self) -> "AppConfig":
        self.wallpaper = (self.wallpaper or "").strip()
        self.folder = (self.folder or "").strip()
        if self.mode not in SUPPORTED_MODES:
            self.mode = "single"
        if self.mode == "folder" and not self.folder and self.wallpaper:
            self.folder = self.wallpaper
        self.interval = int(clamp(int(self.interval or 300), 5, 86400))
        self.theme_accent = normalize_hex_color(self.theme_accent, DEFAULT_ACCENT_COLOR)
        self.effect = self.effect.normalize()
        self.runtime = self.runtime.normalize()
        self.autostart = self.autostart.normalize()
        return self

    @classmethod
    def from_dict(cls, data: dict | None) -> "AppConfig":
        payload = data or {}
        return cls(
            wallpaper=payload.get("wallpaper", ""),
            folder=payload.get("folder", ""),
            mode=payload.get("mode", "single"),
            interval=payload.get("interval", 300),
            theme_accent=payload.get("theme_accent", DEFAULT_ACCENT_COLOR),
            effect=EffectConfig.from_dict(payload.get("effect")),
            runtime=RuntimeConfig.from_dict(payload.get("runtime")),
            autostart=AutostartConfig.from_dict(payload.get("autostart")),
        ).normalize()

    def to_dict(self) -> dict:
        return {
            "wallpaper": self.wallpaper,
            "folder": self.folder,
            "mode": self.mode,
            "interval": self.interval,
            "theme_accent": self.theme_accent,
            "effect": self.effect.to_dict(),
            "runtime": self.runtime.to_dict(),
            "autostart": self.autostart.to_dict(),
        }
