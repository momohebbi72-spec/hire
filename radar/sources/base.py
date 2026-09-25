"""Common data model and registry for opportunity connectors.

Adding a new website = one function decorated with @register(...) in any
module of this package. It receives a SourceConfig and returns Items.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from ..textutil import normalize


@dataclass
class Item:
    title: str
    url: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    posted_at: Optional[str] = None
    job_type: str = ""
    salary: str = ""
    tags: List[str] = field(default_factory=list)
    external_id: str = ""
    source: str = ""
    source_type: str = ""

    def text(self) -> str:
        return " \n".join(
            [
                self.title or "",
                self.company or "",
                self.location or "",
                self.job_type or "",
                " ".join(self.tags or []),
                (self.description or "")[:8000],
            ]
        )

    def uid(self) -> str:
        key = self.external_id or self.url or f"{self.title}|{self.company}"
        return hashlib.sha1(f"{self.source_type}:{key}".encode("utf-8")).hexdigest()

    def fingerprint(self) -> Optional[str]:
        """Duplicate key from Title + Company + Location (+ URL host when no company).

        The same job re-posted on several boards collapses to one record.
        """
        def clean(value: str) -> str:
            return re.sub(r"[^0-9a-z؀-ۿ]+", "", normalize(value).lower())

        title = clean(self.title)
        if not title:
            return None
        company = clean(self.company)
        if not company or self.source_type in ("freelancer", "telegram", "websearch", "manual"):
            host = urlparse(self.url or "").netloc.lower()
            path = urlparse(self.url or "").path
            company = f"{host}{path}" if host else ""
            if not company:
                return None
        return f"{title}|{company}|{clean(self.location)}"[:300]


@dataclass
class SourceConfig:
    id: str
    name: str
    type: str
    target: str = ""
    keywords: List[str] = field(default_factory=list)
    frequency_hours: int = 24
    enabled: bool = True
    runner: str = ""  # local | cloud | both ('' = connector default)

    def queries(self, fallback: str = "") -> List[str]:
        """Search terms for query-style connectors: keywords, else comma-split target."""
        if self.keywords:
            return self.keywords
        parts = [t.strip() for t in (self.target or "").split(",") if t.strip()]
        return parts or ([fallback] if fallback else [])


@dataclass
class SourceType:
    key: str
    label: str
    group: str
    help: str
    fetch: Callable[[SourceConfig, int], List[Item]]
    keyword_mode: str = "query"   # query: keywords are search terms · filter: keep items containing a keyword
    target_label: str = "Target"
    needs_target: bool = False
    runner: str = "cloud"         # where it can reach the site: local (Iran IP) | cloud | both
    available: bool = True        # False = architecture only (future connector)


FETCHERS: Dict[str, SourceType] = {}

GROUPS = {
    "jobs": "سایت‌های کاریابی بین‌المللی",
    "iran": "سایت‌های کاریابی و فریلنس ایرانی",
    "freelance": "پروژه‌های فریلنس",
    "company": "سایت شرکت‌ها",
    "search": "جستجوی وب (گوگل) و شبکه‌های اجتماعی",
    "feed": "RSS و کانال‌ها",
}


def register(key: str, label: str, *, group: str, help: str, keyword_mode: str = "query",
             target_label: str = "Target", needs_target: bool = False, runner: str = "cloud",
             available: bool = True):
    def deco(fn):
        FETCHERS[key] = SourceType(key, label, group, help, fn, keyword_mode, target_label,
                                   needs_target, runner, available)
        return fn

    return deco


def split_targets(target: str) -> List[str]:
    return [t.strip() for t in (target or "").split(",") if t.strip()]
