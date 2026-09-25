"""Applies the dashboard's «تنظیمات → منابع» document (config/sources) to config/sources.yaml.

Used by the local Mac app (on save) and by the cloud routine (`python -m radar apply-config`).
"""
from __future__ import annotations

from typing import Dict, List

from .config_store import load_sources, save_sources

IRAN_MAP: Dict[str, List[str]] = {
    "jobinja": ["jobinja-seo"], "jobvision": ["jobvision-seo", "jobvision-collection"], "eestekhdam": ["eestekhdam-seo"],
    "iranestekhdam": ["iranestekhdam-seo"], "karbord": ["karbord-seo"], "kardix": ["kardix-seo"],
    "karpishe": ["karpishe-seo"], "jobteam": ["jobteam-seo"], "divar": ["divar-tehran"], "ponisha": ["ponisha-seo"],
    "karlancer": ["karlancer-seo"], "parscoders": ["parscoders-seo"], "lancerify": ["lancerify-seo"],
    "googleFa": ["google-fa"],
}
FOREIGN_MAP: Dict[str, List[str]] = {
    "remoteok": ["remoteok"], "remotive": ["remotive-seo"], "jobicy": ["jobicy"], "himalayas": ["himalayas"],
    "wwr": ["wwr-marketing"], "freelancer": ["freelancer-seo"], "reddit": ["reddit-forhire"],
    "wellfound": ["wellfound-seo"], "indeed": ["indeed-seo"],
}


def _clean(values) -> List[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def apply_sources(doc: dict) -> dict:
    """Returns {source_id: enabled} for what changed. Unknown keys are ignored."""
    if not doc:
        return {}
    sources = load_sources()
    by_id = {s.id: s for s in sources}
    changed = {}

    def toggle(mapping, flags):
        for key, ids in mapping.items():
            if key not in (flags or {}):
                continue
            for sid in ids:
                if sid in by_id and by_id[sid].enabled != bool(flags[key]):
                    by_id[sid].enabled = bool(flags[key])
                    changed[sid] = by_id[sid].enabled

    toggle(IRAN_MAP, doc.get("iran"))
    toggle(FOREIGN_MAP, doc.get("foreign"))

    tg = by_id.get("telegram-jobs")
    if tg is not None and "telegram" in doc:
        channels = [c.lstrip("@") for c in _clean(doc["telegram"])]
        tg.target, tg.enabled = ", ".join(channels), bool(channels)
        changed["telegram-jobs"] = tg.enabled
    ig = by_id.get("instagram-seo")
    if ig is not None and "instagram" in doc:
        ig.target = ", ".join(_clean(doc["instagram"]))
    li = by_id.get("linkedin-jobs")
    if li is not None:
        if doc.get("linkedinKeywords"):
            li.keywords = _clean(doc["linkedinKeywords"])
        if doc.get("linkedinLocations"):
            li.target = ", ".join(_clean(doc["linkedinLocations"]))
    g = by_id.get("google-fa")
    if g is not None and ("google" in doc or "sites" in doc):
        queries = _clean(doc.get("google")) or g.keywords
        queries += [f"site:{d.replace('https://', '').replace('http://', '').strip('/')} استخدام سئو"
                    for d in _clean(doc.get("sites"))]
        g.keywords = queries
    save_sources(sources)
    return changed
