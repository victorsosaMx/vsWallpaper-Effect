from __future__ import annotations

import json
import os

from .model import AppConfig


APP_ID = "vswallpaper-effect"
CONFIG_DIR = os.path.expanduser(f"~/.config/{APP_ID}")
CACHE_DIR = os.path.expanduser(f"~/.cache/{APP_ID}")
DEFAULT_CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
PID_PATH = os.path.join(CACHE_DIR, "daemon.pid")


def resolve_config_path(path: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(path or DEFAULT_CONFIG_PATH))


def ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def load_config(path: str | None = None) -> AppConfig:
    config_path = resolve_config_path(path)
    if not os.path.exists(config_path):
        return AppConfig()
    with open(config_path, "r", encoding="utf-8") as handle:
        return AppConfig.from_dict(json.load(handle))


def save_config(config: AppConfig, path: str | None = None) -> str:
    config_path = resolve_config_path(path)
    ensure_parent_dir(config_path)
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config.normalize().to_dict(), handle, indent=2, ensure_ascii=False)
    return config_path


def write_default_config(path: str | None = None) -> str:
    return save_config(AppConfig(), path)
