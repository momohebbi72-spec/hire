"""Matching engine: 0-100 score + reasons. No AI required.

Weights (as specified):
  Skill match 35 · Keyword match 25 · Opportunity type 15 · Location 10 · Preference 15
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from .profile import REMOTE_TERMS, Profile, compile_term
from .sources.base import Item
from .textutil import normalize, parse_iso


def _pats(terms):
    return [compile_term(t) for t in terms]


_REMOTE = _pats(REMOTE_TERMS)
_HYBRID = _pats(["hybrid", "هیبرید", "ترکیبی", "نیمه حضوری", "دورکاری و حضوری"])
_ONSITE = _pats(["on-site", "onsite", "in office", "in-office", "حضوری", "تمام حضوری"])

CATEGORY_RULES = [
    ("SEO", ["seo", "search engine", "organic search", "organic growth", "سئو", "سئوکار", "!GEO", "جئو",
             "generative engine optimization", "aeo", "answer engine"]),
    ("Consulting", ["consultant", "consulting", "advisor", "adviser", "fractional", "مشاور", "مشاوره"]),
    ("Website", ["wordpress", "website", "web design", "web designer", "landing page", "shopify", "webflow",
                 "woocommerce", "elementor", "وردپرس", "وبسایت", "وب سایت", "طراحی سایت", "سایت"]),
    ("Content", ["content", "copywriter", "copywriting", "محتوا", "تولید محتوا", "کپی رایتر", "کپی‌رایتر"]),
    ("Digital Marketing", ["marketing", "growth", "ppc", "paid media", "paid search", "social media", "analytics",
                           "email marketing", "demand generation", "مارکتینگ", "بازاریابی", "دیجیتال مارکتینگ"]),
]
_CATEGORIES = [(name, _pats(terms)) for name, terms in CATEGORY_RULES]
CATEGORIES = [name for name, _ in CATEGORY_RULES] + ["Other"]

OPP_TYPE_RULES = [
    ("Freelance", ["freelance", "freelancer", "project based", "gig", "one-time project", "فریلنس", "فریلنسری",
                   "پروژه ای", "پروژه‌ای", "انجام پروژه", "سفارش"]),
    ("Consulting", ["consultant", "consulting", "advisor", "fractional", "مشاور", "مشاوره"]),
    ("Contract", ["contract", "contractor", "temporary", "قراردادی", "موقت"]),
    ("Part-time", ["part time", "part-time", "پاره وقت", "پاره‌وقت", "نیمه وقت"]),
    ("Collaboration", ["collaboration", "partnership", "partner", "همکاری", "مشارکت"]),
    ("Full-time", ["full time", "full-time", "permanent", "تمام وقت", "تمام‌وقت"]),
]
_OPP_TYPES = [(name, _pats(terms)) for name, terms in OPP_TYPE_RULES]
OPP_TYPES = [name for name, _ in OPP_TYPE_RULES] + ["Job"]
REMOTE_TYPES = ["Remote", "Hybrid", "On-site", "Unknown"]
FREELANCE_SOURCES = {"freelancer", "ponisha", "karlancer", "parscoders", "lancerify"}


@dataclass
class ScoreResult:
    score: int
    reasons: List[str]
    category: str
    remote_type: str = "Unknown"
    opp_type: str = "Job"
    skills: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    breakdown: Dict[str, int] = field(default_factory=dict)


def _any(patterns, text: str) -> bool:
    return bool(text) and any(p.search(text) for p in patterns)


def classify(title: str, body: str) -> str:
    for text in (title, body):
        for name, pats in _CATEGORIES:
            if _any(pats, text):
                return name
    return "Other"


def detect_remote(item: Item, meta: str, body: str) -> str:
    if _any(_HYBRID, meta) or _any(_HYBRID, body[:2000]):
        return "Hybrid"
    if _any(_REMOTE, meta) or _any(_REMOTE, body[:2000]):
        return "Remote"
    if _any(_ONSITE, meta) or item.location:
        return "On-site"
    return "Unknown"


def detect_type(item: Item, meta: str, body: str) -> str:
    if item.source_type in FREELANCE_SOURCES:
        return "Freelance"
    for text in (meta, body[:3000]):
        for name, pats in _OPP_TYPES:
            if _any(pats, text):
                return name
    return "Job"


def score_item(item: Item, profile: Profile) -> ScoreResult:
    title = normalize(item.title)
    body = normalize(item.text())
    meta = normalize(" ".join([item.location or "", item.title or "", item.job_type or "", " ".join(item.tags or [])]))
    category = classify(title, body)
    remote_type = detect_remote(item, meta, body)
    opp_type = detect_type(item, meta, body)
    base = dict(category=category, remote_type=remote_type, opp_type=opp_type)

    for term in profile.exclude_in_title:
        if term.search(title):
            return ScoreResult(0, [f"✗ Excluded: {term.label}"], **base)
    for term in profile.exclude_anywhere:
        if term.search(body):
            return ScoreResult(0, [f"✗ Excluded: {term.label}"], **base)

    reasons: List[str] = []
    bd = {"skills": 0, "keywords": 0, "type": 0, "location": 0, "preference": 0}

    # 1) Skill match — 35
    skills = sorted((s for s in profile.skills if s.search(body)), key=lambda s: -s.weight)
    if skills:
        bd["skills"] = min(35, round(sum(s.weight for s in skills) * 35 / profile.skill_target))
        reasons += [f"✓ {s.label}" for s in skills[:7]]

    # 2) Keyword / target-role match — 25
    role = next((r for r in profile.target_roles if r.search(title)), None)
    kw_title = [k for k in profile.keywords if k.search(title)]
    kw_body = [k for k in profile.keywords if k not in kw_title and k.search(body)]
    if role:
        bd["keywords"] = 25
        reasons.insert(0, f"✓ Role: {role.label}")
    else:
        bd["keywords"] = min(25, 15 * bool(kw_title) + 4 * len(kw_body) + 3 * max(0, len(kw_title) - 1))
        if kw_title:
            reasons.insert(0, f"✓ Title: {kw_title[0].label}")
    keywords = [k.label for k in kw_title + kw_body]

    # 3) Opportunity type — 15
    type_term = next((w for w in profile.work_types if w.search(normalize(opp_type)) or w.search(meta)), None)
    remote_wanted = any(w.label.lower() == "remote" for w in profile.work_types)
    if type_term and type_term.label.lower() != "remote":
        bd["type"] = 15
        reasons.append(f"✓ {type_term.label}")
    elif remote_type == "Remote" and remote_wanted:
        bd["type"] = 15
    elif opp_type == "Job":
        bd["type"] = 5  # type not stated: neutral

    # 4) Location — 10
    place = next((p for p in profile.places if p.search(meta)), None)
    if remote_type == "Remote" and profile.wants_remote:
        bd["location"] = 10
        reasons.append("✓ Remote")
    elif place:
        bd["location"] = 10
    elif remote_type == "Hybrid":
        bd["location"] = 5
    elif remote_type == "Unknown":
        bd["location"] = 3
    if place:
        reasons.append(f"✓ {place.label}")
    avoid = next((a for a in profile.avoid_locations if a.search(meta) or a.search(body[:3000])), None)
    if avoid:
        bd["location"] = -15
        reasons.append(f"✗ Location: {avoid.label}")

    # 5) Preference — 15 (industry + freshness)
    industries = [i for i in profile.industries if i.search(body)]
    if industries:
        bd["preference"] += 6 + 3 * (len(industries) > 1)
        reasons.append(f"✓ {industries[0].label}")
    posted = parse_iso(item.posted_at)
    if posted:
        age = (datetime.now(timezone.utc) - posted).days
        if age <= 3:
            bd["preference"] += 6
            reasons.append("✓ Fresh")
        elif age <= 7:
            bd["preference"] += 3
        elif age > 14:
            bd["preference"] -= 5
            reasons.append(f"⚠ {age} days old")
    else:
        bd["preference"] += 2

    total = sum(bd.values())
    if not skills and not role and not keywords:
        total = min(total, 15)  # nothing relevant matched
    return ScoreResult(max(0, min(100, int(total))), reasons, skills=[s.label for s in skills],
                       keywords=keywords, breakdown=bd, **base)
