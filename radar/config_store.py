"""Read/write the YAML configuration (profile, sources, settings).

The YAML files in config/ are the single source of truth: the Mac dashboard
edits them and (when GitHub sync is configured) pushes them to the repo, so
GitHub Actions always uses the same profile and sources.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Dict, List

import yaml

from .settings import PROFILE_PATH, SETTINGS_PATH, SOURCES_PATH
from .sources.base import FETCHERS, SourceConfig

DEFAULT_SETTINGS = {
    "timezone": "Asia/Tehran",
    "report": {
        "email_to": "",            # empty = REPORT_EMAIL_TO from .env / GitHub secret
        "time": "09:30",           # local time (timezone above)
        "frequency": "daily",      # daily | weekly | off
        "weekly_day": "sat",       # for weekly: sat sun mon tue wed thu fri
        "sender": "cloud",         # cloud = GitHub Actions sends · local = your Mac sends
        "send_empty": True,
        "subject": "Daily Opportunity Radar Report",
    },
    "sync": {"data_branch": "radar-data"},
}

FREQUENCIES = {0: "فقط دستی", 6: "هر ۶ ساعت", 12: "هر ۱۲ ساعت", 24: "روزانه", 72: "هر ۳ روز", 168: "هفتگی"}


def _read(path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _dump(data) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


# ------------------------------------------------------------------ settings
def _merge(base: dict, over: dict) -> dict:
    out = deepcopy(base)
    for key, value in (over or {}).items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load_settings() -> dict:
    return _merge(DEFAULT_SETTINGS, _read(SETTINGS_PATH))


def save_settings(data: dict) -> None:
    header = "# تنظیمات گزارش و زمان‌بندی — از صفحه‌ی «تنظیمات» داشبورد هم قابل ویرایش است.\n"
    SETTINGS_PATH.write_text(header + _dump(_merge(DEFAULT_SETTINGS, data)), encoding="utf-8")


# ------------------------------------------------------------------- sources
def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z؀-ۿ]+", "-", str(text).strip().lower()).strip("-")
    return slug[:60] or "source"


def _as_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = re.split(r"[,\n،]", value)
    return [str(v).strip() for v in value if str(v).strip()]


def load_sources() -> List[SourceConfig]:
    data = _read(SOURCES_PATH)
    out, seen = [], set()
    for raw in data.get("sources") or []:
        stype = str(raw.get("type") or "").strip()
        if not stype:
            continue
        sid = str(raw.get("id") or slugify(raw.get("name") or f"{stype}-{raw.get('target', '')}"))
        while sid in seen:
            sid += "-2"
        seen.add(sid)
        out.append(SourceConfig(
            id=sid,
            name=str(raw.get("name") or stype),
            type=stype,
            target=str(raw.get("target") or "").strip(),
            keywords=_as_list(raw.get("keywords")),
            frequency_hours=int(raw.get("frequency_hours", 24) or 0),
            enabled=bool(raw.get("enabled", True)),
            runner=str(raw.get("runner") or "").strip(),
        ))
    return out


def save_sources(sources: List[SourceConfig]) -> None:
    rows = []
    for s in sources:
        row: Dict = {"id": s.id, "name": s.name, "type": s.type}
        if s.target:
            row["target"] = s.target
        if s.keywords:
            row["keywords"] = s.keywords
        row["frequency_hours"] = s.frequency_hours
        row["enabled"] = s.enabled
        if s.runner:
            row["runner"] = s.runner
        rows.append(row)
    header = (
        "# منابع — از صفحه‌ی «منابع» داشبورد مدیریت می‌شود (یا همین‌جا دستی ویرایش کنید).\n"
        "# type ها: " + ", ".join(sorted(FETCHERS)) + "\n"
        "# frequency_hours: 0 = فقط دستی · runner: local (مک/IP ایران) | cloud (GitHub) | both\n"
    )
    SOURCES_PATH.write_text(header + _dump({"sources": rows}), encoding="utf-8")


def effective_runner(src: SourceConfig) -> str:
    if src.runner in ("local", "cloud", "both"):
        return src.runner
    stype = FETCHERS.get(src.type)
    return stype.runner if stype else "both"


# ------------------------------------------------------------------- profile
def read_profile_text() -> str:
    return PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.exists() else ""


def write_profile_text(text: str) -> None:
    PROFILE_PATH.write_text(text, encoding="utf-8")


def read_profile_data() -> dict:
    return _read(PROFILE_PATH)


def write_profile_data(data: dict) -> None:
    header = "# پروفایل مهارتی — از صفحه‌ی «پروفایل» داشبورد ویرایش می‌شود.\n"
    PROFILE_PATH.write_text(header + _dump(data), encoding="utf-8")
