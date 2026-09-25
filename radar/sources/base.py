"""Common data model and registry for opportunity sources."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


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
        """Cross-source duplicate key (same job posted on several boards)."""
        if not self.company or self.source_type in ("freelancer", "telegram", "manual"):
            return None
        raw = f"{self.title}|{self.company}".lower()
        return re.sub(r"[^0-9a-z؀-ۿ]+", "", raw)[:200] or None


@dataclass
class SourceType:
    key: str
    label: str
    help: str
    needs_target: bool
    fetch: Callable[[str, int], List[Item]]


FETCHERS: Dict[str, SourceType] = {}


def register(key: str, label: str, help: str, needs_target: bool = True):
    def deco(fn):
        FETCHERS[key] = SourceType(key, label, help, needs_target, fn)
        return fn

    return deco


def split_targets(target: str) -> List[str]:
    return [t.strip() for t in (target or "").split(",") if t.strip()]
