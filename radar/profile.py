"""Skill profile loaded from config/profile.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Pattern

import yaml

from .settings import PROFILE_PATH
from .textutil import normalize

REMOTE_TERMS = [
    "remote", "anywhere", "worldwide", "work from home", "wfh", "fully distributed",
    "distributed team", "telecommute", "home based", "دورکاری", "دور کاری", "ریموت", "از راه دور",
]


def compile_term(term: str) -> Optional[Pattern]:
    """Whole-word, case-insensitive pattern. Prefix with '!' for case-sensitive (e.g. '!GEO')."""
    term = normalize(str(term)).strip()
    flags = re.IGNORECASE
    if term.startswith("!"):
        term, flags = term[1:].strip(), 0
    if not term:
        return None
    # "technical seo" also matches "technical-seo"; "e-commerce" also matches "ecommerce".
    words = [r"[\s\-_]?".join(re.escape(part) for part in word.split("-")) for word in term.split()]
    return re.compile(r"(?<!\w)" + r"[\s\-_]+".join(words) + r"(?!\w)", flags)


@dataclass
class Term:
    label: str
    patterns: List[Pattern]
    weight: int = 1

    def search(self, text: str) -> bool:
        """`text` must already be normalize()d."""
        return bool(text) and any(p.search(text) for p in self.patterns)


def make_term(label, aliases=(), weight: int = 1) -> Term:
    pats = [p for p in (compile_term(t) for t in [label, *aliases]) if p]
    return Term(str(label).lstrip("!"), pats, int(weight))


@dataclass
class Profile:
    name: str = ""
    min_score: int = 55
    report_top_n: int = 15
    max_age_days: int = 30
    per_source_limit: int = 60
    skill_target: int = 25
    skills: List[Term] = field(default_factory=list)
    keywords: List[Term] = field(default_factory=list)
    target_roles: List[Term] = field(default_factory=list)
    industries: List[Term] = field(default_factory=list)
    places: List[Term] = field(default_factory=list)
    wants_remote: bool = True
    avoid_locations: List[Term] = field(default_factory=list)
    work_types: List[Term] = field(default_factory=list)
    exclude_in_title: List[Term] = field(default_factory=list)
    exclude_anywhere: List[Term] = field(default_factory=list)


def _weighted(raw, default_weight: int = 5) -> List[Term]:
    """Accepts a list of names or a mapping name -> weight | {weight, aliases}."""
    terms = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, dict):
                terms.append(make_term(x.get("name", ""), x.get("aliases") or [], int(x.get("weight", default_weight))))
            elif str(x).strip():
                terms.append(make_term(x, weight=default_weight))
        return terms
    for name, spec in (raw or {}).items():
        if isinstance(spec, (int, float)):
            spec = {"weight": spec}
        spec = spec or {}
        aliases = [str(a) for a in (spec.get("aliases") or [])]
        terms.append(make_term(name, aliases, int(spec.get("weight", default_weight))))
    return terms


def _terms(data: dict, key: str) -> List[Term]:
    return _weighted(data.get(key) or [], 1)


def parse_profile(data) -> Profile:
    if not isinstance(data, dict):
        raise ValueError("profile.yaml must be a YAML mapping")
    remote_set = set(REMOTE_TERMS)
    locations = [str(x) for x in (data.get("preferred_locations") or [])]
    return Profile(
        name=str(data.get("name") or ""),
        min_score=int(data.get("min_score", 55)),
        report_top_n=int(data.get("report_top_n", 15)),
        max_age_days=int(data.get("max_age_days", 30)),
        per_source_limit=int(data.get("per_source_limit", 60)),
        skill_target=max(1, int(data.get("skill_target", 25))),
        skills=_weighted(data.get("skills") or {}, 5),
        keywords=_terms(data, "keywords"),
        target_roles=_terms(data, "target_roles"),
        industries=_weighted(data.get("industries") or [], 1),
        places=[make_term(x) for x in locations if x.strip().lower() not in remote_set],
        wants_remote=any(x.strip().lower() in remote_set for x in locations) or not locations,
        avoid_locations=_terms(data, "avoid_locations"),
        work_types=_terms(data, "work_types"),
        exclude_in_title=_terms(data, "exclude_in_title"),
        exclude_anywhere=_terms(data, "exclude_anywhere"),
    )


_cache = {"key": None, "profile": None}


def load_profile(path: Path = PROFILE_PATH) -> Profile:
    mtime = path.stat().st_mtime if path.exists() else None
    key = (str(path), mtime)
    if _cache["profile"] is None or _cache["key"] != key:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        _cache["profile"] = parse_profile(data or {})
        _cache["key"] = key
    return _cache["profile"]
