"""Indeed, Glassdoor and Google Jobs through the open-source `python-jobspy` library.

Installed only in GitHub Actions (requirements-cloud.txt, Python 3.10+).
"""
from __future__ import annotations

from typing import List

from ..http import pause
from ..textutil import to_iso
from .base import Item, SourceConfig, register, split_targets


def _country(location: str) -> str:
    loc = location.lower()
    for key, country in (("canada", "Canada"), ("united kingdom", "UK"), ("uk", "UK"), ("germany", "Germany"),
                         ("netherlands", "Netherlands"), ("australia", "Australia"), ("uae", "United Arab Emirates"),
                         ("dubai", "United Arab Emirates"), ("turkey", "Turkey")):
        if key in loc:
            return country
    return "USA"


def _scrape(site: str, src: SourceConfig, limit: int) -> List[Item]:
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError("python-jobspy is not installed (pip install -r requirements-cloud.txt)") from exc

    items: List[Item] = []
    for location in split_targets(src.target) or ["Remote"]:
        remote = location.lower() == "remote"
        for term in src.queries("SEO"):
            kwargs = dict(site_name=[site], search_term=term, results_wanted=min(limit, 30),
                          hours_old=72, verbose=0)
            if site == "google":
                where = "remote" if remote else f"near {location}"
                kwargs["google_search_term"] = f"{term} jobs {where} since yesterday"
            else:
                kwargs["location"] = "" if remote else location
                kwargs["country_indeed"] = _country(location)
                if remote:
                    kwargs["search_term"] = f"{term} remote"
            df = scrape_jobs(**kwargs)
            if df is None or df.empty:
                continue
            for row in df.fillna("").to_dict("records"):
                lo, hi = row.get("min_amount"), row.get("max_amount")
                salary = f"{lo} - {hi} {row.get('currency') or ''} {row.get('interval') or ''}".strip() if (lo or hi) else ""
                tags = ["Remote"] if str(row.get("is_remote")).lower() == "true" else []
                items.append(Item(
                    title=str(row.get("title") or ""), company=str(row.get("company") or ""),
                    url=str(row.get("job_url_direct") or row.get("job_url") or ""),
                    location=str(row.get("location") or location),
                    description=str(row.get("description") or "")[:8000],
                    posted_at=to_iso(str(row.get("date_posted") or "")),
                    job_type=str(row.get("job_type") or ""), salary=salary, tags=tags,
                    external_id=str(row.get("id") or row.get("job_url") or ""),
                ))
            pause(3)
    return items


_HELP = "موقعیت‌ها با ویرگول (Remote, Canada, United States). کلمات کلیدی = عنوان‌های جستجو."


@register("indeed", "Indeed", group="jobs", target_label="موقعیت‌ها", help=_HELP)
def indeed(src: SourceConfig, limit: int) -> List[Item]:
    return _scrape("indeed", src, limit)


@register("glassdoor", "Glassdoor", group="jobs", target_label="موقعیت‌ها", help=_HELP)
def glassdoor(src: SourceConfig, limit: int) -> List[Item]:
    return _scrape("glassdoor", src, limit)


@register("google_jobs", "Google Jobs", group="search", target_label="موقعیت‌ها", help=_HELP)
def google_jobs(src: SourceConfig, limit: int) -> List[Item]:
    return _scrape("google", src, limit)
