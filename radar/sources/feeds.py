"""Generic RSS / Atom feeds (We Work Remotely, Reddit, Google Alerts, company blogs...)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List
from urllib.parse import urlparse

from ..http import get_bytes
from ..textutil import strip_html, to_iso
from .base import Item, SourceConfig, register


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(payload: bytes) -> List[Dict]:
    root = ET.fromstring(payload)
    entries = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        fields: Dict = {"categories": []}
        for child in el:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "link":
                href = child.attrib.get("href")
                if href and child.attrib.get("rel", "alternate") == "alternate":
                    fields.setdefault("link", href)
                elif text:
                    fields.setdefault("link", text)
            elif name == "category":
                value = text or child.attrib.get("term", "")
                if value:
                    fields["categories"].append(value)
            elif name == "author":
                fields.setdefault("author", text or "".join(n.text or "" for n in child if _local(n.tag) == "name"))
            elif text:
                fields.setdefault(name, text)
        entries.append(fields)
    return entries


@register("rss", "RSS / Atom Feed", group="feed", keyword_mode="filter", needs_target=True, runner="both",
          target_label="آدرس فید",
          help="هر فید RSS: وبلاگ‌ها، سایت‌های کاریابی (WordPress: آدرس/feed)، Google Alerts، Reddit. کلمات کلیدی برای فیلتر.")
def rss(src: SourceConfig, limit: int) -> List[Item]:
    url = (src.target or "").strip()
    host = urlparse(url).netloc.lower()
    items = []
    for e in parse_feed(get_bytes(url))[:limit]:
        title = strip_html(e.get("title", ""))
        company = ""
        if "weworkremotely" in host and ": " in title:
            company, title = title.split(": ", 1)
        items.append(
            Item(
                title=title,
                company=company,
                url=e.get("link") or e.get("guid") or e.get("id") or "",
                location=e.get("region") or e.get("location") or "",
                description=strip_html(e.get("encoded") or e.get("description") or e.get("content") or e.get("summary")),
                posted_at=to_iso(e.get("pubdate") or e.get("published") or e.get("updated") or e.get("date")),
                job_type=e.get("type") or "",
                tags=e.get("categories") or [],
                external_id=e.get("guid") or e.get("id") or e.get("link") or title,
            )
        )
    return items
