from __future__ import annotations

import colorsys
import os
import re


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def expand_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser((path or "").strip()))


def normalize_hex_color(value: str, fallback: str = "") -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    if not text.startswith("#"):
        text = "#" + text
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.lower()
    return fallback


def hex_to_rgb(value: str, fallback: str = "#80c8e0") -> tuple[float, float, float]:
    color = normalize_hex_color(value, fallback).lstrip("#")
    return tuple(int(color[idx:idx + 2], 16) / 255.0 for idx in (0, 2, 4))


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        round(clamp(rgb[0], 0.0, 1.0) * 255),
        round(clamp(rgb[1], 0.0, 1.0) * 255),
        round(clamp(rgb[2], 0.0, 1.0) * 255),
    )


def mix_rgb(a: tuple[float, float, float], b: tuple[float, float, float], amount: float) -> tuple[float, float, float]:
    amt = clamp(amount, 0.0, 1.0)
    return (
        a[0] + (b[0] - a[0]) * amt,
        a[1] + (b[1] - a[1]) * amt,
        a[2] + (b[2] - a[2]) * amt,
    )


def shift_hue(value: str, degrees: float) -> str:
    r, g, b = hex_to_rgb(value)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    return rgb_to_hex(colorsys.hsv_to_rgb(h, s, v))


def darken_hex(value: str, factor: float) -> str:
    """Return a darker version of *value* by reducing HSL lightness by *factor* (0–1)."""
    r, g, b = hex_to_rgb(value)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = clamp(l * (1.0 - factor), 0.0, 1.0)
    return rgb_to_hex(colorsys.hls_to_rgb(h, l, s))


def list_image_files(folder: str) -> list[str]:
    path = expand_path(folder)
    if not os.path.isdir(path):
        return []
    items = []
    for name in sorted(os.listdir(path)):
        candidate = os.path.join(path, name)
        if os.path.isfile(candidate) and candidate.lower().endswith(IMAGE_SUFFIXES):
            items.append(candidate)
    return items


def format_seconds(seconds: int) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
