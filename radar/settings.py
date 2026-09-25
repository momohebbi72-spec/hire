"""Paths and environment configuration."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE per line). Real env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def runner() -> str:
    """Where this process runs: 'cloud' (GitHub Actions) or 'local' (your Mac)."""
    value = env("RADAR_RUNNER").lower()
    if value in ("cloud", "local"):
        return value
    return "cloud" if env("GITHUB_ACTIONS") == "true" else "local"


CONFIG_DIR = ROOT / "config"
DATA_DIR = resolve_path(env("RADAR_DATA_DIR", "data"))
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "radar.db"
PROFILE_PATH = CONFIG_DIR / "profile.yaml"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
