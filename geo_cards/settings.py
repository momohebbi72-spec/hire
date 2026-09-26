"""Paths, .env and YAML files for the GEO cards tool."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE per line). Real env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env_file(PKG_DIR / ".env")
_load_env_file(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


CONFIG_PATH = PKG_DIR / "config.yaml"
QUESTIONS_PATH = PKG_DIR / "questions.yaml"
FONTS_DIR = PKG_DIR / "assets" / "fonts"
OUTPUT_DIR = Path(env("GEO_CARDS_OUTPUT") or PKG_DIR / "output").expanduser().resolve()


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_questions() -> list:
    with QUESTIONS_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("questions") or []
