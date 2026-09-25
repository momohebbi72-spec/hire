"""LinkedIn job search via the public guest endpoint (no login, no cookies).

Note: LinkedIn is filtered in Iran — this connector runs on GitHub Actions (cloud).
LinkedIn *posts* (hiring posts) are covered by the `site_search` connector.
"""
from __future__ import annotations

import html as html_mod
import re
from typing import List
from urllib.parse import quote

import requests

from ..http import get_text, pause
from ..textutil import strip_html, to_iso
from .base import Item, SourceConfig, register, split_targets

_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


def _text(pattern: str, chunk: str) -> str:
    m = re.search(pattern, chunk, re.S)
    return re.sub(r"\s+", " ", html_mod.unescape(m.group(1))).strip() if m else ""


def parse_cards(page: str) -> List[dict]:
    cards = []
    for chunk in re.split(r"<li[^>]*>", page)[1:]:
        urn = re.search(r'urn:li:jobPosting:(\d+)', chunk)
        if not urn:
            continue
        company = _text(r'base-search-card__subtitle[^>]*>.*?<a[^>]*>(.*?)</a>', chunk) or \
            _text(r'base-search-card__subtitle[^>]*>(.*?)</', chunk)
        cards.append({
            "id": urn.group(1),
            "title": _text(r'base-search-card__title[^>]*>(.*?)</', chunk),
            "company": strip_html(company),
            "location": _text(r'job-search-card__location[^>]*>(.*?)</', chunk),
            "date": (re.search(r'<time[^>]*datetime="([^"]+)"', chunk) or [None, None])[1],
            "salary": _text(r'job-search-card__salary-info[^>]*>(.*?)</', chunk),
        })
    return cards


def _description(job_id: str) -> str:
    try:
        page = get_text(_POSTING.format(id=job_id))
    except requests.RequestException:
        return ""
    m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page, re.S)
    return strip_html(m.group(1)) if m else ""


@register("linkedin", "LinkedIn Jobs", group="jobs", target_label="موقعیت‌ها",
          help="موقعیت‌ها با ویرگول (Canada, United States, Iran, Remote). کلمات کلیدی = عنوان‌های جستجو (SEO Specialist, SEO Manager).")
def linkedin(src: SourceConfig, limit: int) -> List[Item]:
    locations = split_targets(src.target) or ["Worldwide"]
    days = max(1, min(30, (src.frequency_hours or 24) // 24 * 2 or 2))
    items, seen = [], set()
    described = 0
    for location in locations:
        remote = location.strip().lower() == "remote"
        for term in src.queries("SEO"):
            for start in (0, 10, 20):
                params = f"keywords={quote(term)}&location={quote('Worldwide' if remote else location)}" \
                         f"&f_TPR=r{days * 86400}&start={start}" + ("&f_WT=2" if remote else "")
                page = get_text(f"{_SEARCH}?{params}")
                cards = parse_cards(page)
                if not cards:
                    break
                for c in cards:
                    if c["id"] in seen:
                        continue
                    seen.add(c["id"])
                    desc = ""
                    if described < 20:  # fetch full text for the first results only (rate limits)
                        desc = _description(c["id"])
                        described += 1
                        pause(1)
                    items.append(Item(
                        title=c["title"], company=c["company"] or "LinkedIn",
                        url=f"https://www.linkedin.com/jobs/view/{c['id']}/",
                        location=c["location"] + (" (Remote)" if remote else ""),
                        description=desc, posted_at=to_iso(c["date"]), salary=c["salary"],
                        tags=["Remote"] if remote else [], external_id=c["id"],
                    ))
                pause(2)
                if len(items) >= limit:
                    return items
    return items
