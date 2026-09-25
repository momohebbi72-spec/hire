"""Match score (0-100) + human-readable reasons for every opportunity.

Points:  title/role 35  +  skills 40  +  location 15  +  work type 10  (- penalties)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from .profile import REMOTE_TERMS, Profile, compile_term
from .sources.base import Item
from .textutil import parse_iso

_REMOTE = [compile_term(t) for t in REMOTE_TERMS]

CATEGORY_RULES = [
    ("SEO", ["seo", "search engine", "organic search", "organic growth", "سئو"]),
    ("Consulting", ["consultant", "consulting", "advisor", "adviser", "fractional", "مشاور", "مشاوره"]),
    ("Website", ["wordpress", "website", "web design", "web designer", "landing page", "shopify", "webflow",
                 "woocommerce", "elementor", "وردپرس", "وبسایت", "طراحی سایت"]),
    ("Digital Marketing", ["marketing", "growth", "content", "ppc", "paid media", "paid search", "social media",
                           "analytics", "email marketing", "demand generation", "مارکتینگ", "بازاریابی"]),
]
_CATEGORIES = [(name, [compile_term(t) for t in terms]) for name, terms in CATEGORY_RULES]
_FREELANCE = [compile_term(t) for t in ["freelance", "freelancer", "contract", "contractor", "gig", "project based",
                                        "فریلنس", "پروژه‌ای"]]

CATEGORIES = [name for name, _ in CATEGORY_RULES] + ["Freelance", "Other"]


@dataclass
class ScoreResult:
    score: int
    reasons: List[str]
    category: str


def _any(patterns, text: str) -> bool:
    return bool(text) and any(p.search(text) for p in patterns)


def classify(item: Item) -> str:
    if item.source_type == "freelancer":
        return "Freelance"
    for text in (item.title, item.text()):
        for name, pats in _CATEGORIES:
            if _any(pats, text):
                return name
    if _any(_FREELANCE, item.job_type):
        return "Freelance"
    return "Other"


def score_item(item: Item, profile: Profile) -> ScoreResult:
    title = item.title or ""
    body = item.text()
    meta = " ".join([item.location or "", title, item.job_type or "", " ".join(item.tags or [])])
    category = classify(item)

    for term in profile.exclude_in_title:
        if term.search(title):
            return ScoreResult(0, [f"✗ Excluded: {term.label}"], category)
    for term in profile.exclude_anywhere:
        if term.search(body):
            return ScoreResult(0, [f"✗ Excluded: {term.label}"], category)

    points = 0
    reasons: List[str] = []

    # 1) Title / target role (35)
    role = next((r for r in profile.target_roles if r.search(title)), None)
    title_skill = next((s for s in profile.skills if s.search(title)), None)
    if role:
        points += 35
        reasons.append(f"✓ Role: {role.label}")
    elif title_skill:
        points += 22
        reasons.append(f"✓ Title: {title_skill.label}")

    # 2) Skills anywhere in the posting (40)
    matched = sorted((s for s in profile.skills if s.search(body)), key=lambda s: -s.weight)
    if matched:
        points += min(40, round(sum(s.weight for s in matched) * 40 / profile.skill_target))
        reasons += [f"✓ {s.label}" for s in matched[:8]]
    relevant = bool(role or matched)

    # 3) Location (15)
    loc_points = 0
    is_remote = _any(_REMOTE, meta) or (not item.location and _any(_REMOTE, body[:1500]))
    if is_remote and profile.wants_remote:
        loc_points += 10
        reasons.append("✓ Remote")
    place = next((p for p in profile.places if p.search(meta)), None)
    if place:
        loc_points += 5 if loc_points else 10
        reasons.append(f"✓ {place.label}")
    avoid = next((a for a in profile.avoid_locations if a.search(meta)), None)
    if avoid:
        loc_points -= 20
        reasons.append(f"✗ Location: {avoid.label}")
    points += loc_points

    # 4) Preferred work type (10)
    work = next((w for w in profile.work_types if w.search(meta)), None)
    if work:
        points += 10
        reasons.append(f"✓ {work.label}")

    # 5) Freshness penalty
    posted = parse_iso(item.posted_at)
    if posted:
        age = (datetime.now(timezone.utc) - posted).days
        if age > 14:
            points -= 5
            reasons.append(f"⚠ {age} days old")

    if not relevant:
        points = min(points, 15)
    return ScoreResult(max(0, min(100, int(points))), reasons, category)
