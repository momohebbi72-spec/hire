"""Web search connectors — the "top Google results" radar.

Backends (first one configured wins):
  1. Serper.dev   (SERPER_API_KEY)   — real Google results, 2,500 free queries
  2. SerpApi      (SERPAPI_API_KEY)  — real Google results, 100 free / month
  3. DuckDuckGo HTML (no key)        — free fallback, may be rate-limited

Every result domain is also recorded as a *discovered site*, so sites you
didn't know about show up on the Sources page and can be added with one click.
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import parse_qs, unquote, urlparse

from ..http import get_json, get_text, pause, post_json
from ..settings import env
from ..textutil import strip_html, to_iso
from .base import Item, SourceConfig, register, split_targets

_PERSIAN = re.compile(r"[؀-ۿ]")
_RANGES = {"day": ("qdr:d", "d"), "week": ("qdr:w", "w"), "month": ("qdr:m", "m"), "any": ("", "")}


def backend_name() -> str:
    if env("SERPER_API_KEY"):
        return "Serper (Google)"
    if env("SERPAPI_API_KEY"):
        return "SerpApi (Google)"
    return "DuckDuckGo"


def search(query: str, when: str = "week", num: int = 10) -> List[dict]:
    """Return [{title, url, snippet, date}] for one query."""
    tbs, ddg_range = _RANGES.get(when, _RANGES["week"])
    fa = bool(_PERSIAN.search(query))
    if env("SERPER_API_KEY"):
        payload = {"q": query, "num": num, "gl": "ir" if fa else "us", "hl": "fa" if fa else "en"}
        if tbs:
            payload["tbs"] = tbs
        data = post_json("https://google.serper.dev/search", payload, headers={"X-API-KEY": env("SERPER_API_KEY")})
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", ""),
                 "date": r.get("date")} for r in data.get("organic", [])]
    if env("SERPAPI_API_KEY"):
        params = {"engine": "google", "q": query, "num": num, "api_key": env("SERPAPI_API_KEY"),
                  "hl": "fa" if fa else "en", "gl": "ir" if fa else "us"}
        if tbs:
            params["tbs"] = tbs
        data = get_json("https://serpapi.com/search.json", params=params)
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", ""),
                 "date": r.get("date")} for r in data.get("organic_results", [])]
    params = {"q": query}
    if ddg_range:
        params["df"] = ddg_range
    page = get_text("https://html.duckduckgo.com/html/", params=params)
    results = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
                         page, re.S):
        href, title, rest = m.group(1), m.group(2), m.group(3)
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if "duckduckgo.com/y.js" in href:  # ads
            continue
        snippet = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.S)
        results.append({"title": strip_html(title), "url": href,
                        "snippet": strip_html(snippet.group(1)) if snippet else "", "date": None})
        if len(results) >= num:
            break
    return results


def _items(results: List[dict], query: str) -> List[Item]:
    items = []
    for r in results:
        if not r.get("url") or not r.get("title"):
            continue
        host = urlparse(r["url"]).netloc.lower().replace("www.", "")
        items.append(Item(
            title=r["title"], url=r["url"], company=host, description=r.get("snippet", ""),
            posted_at=to_iso(r.get("date")), job_type="Web result", tags=[f"query: {query}"],
            external_id=r["url"],
        ))
    return items


def _run(queries: List[str], when: str, limit: int) -> List[Item]:
    items: List[Item] = []
    for q in queries:
        items += _items(search(q, when), q)
        pause(2)
        if len(items) >= limit:
            break
    return items


@register("websearch", "جستجوی گوگل (۱۰ نتیجه‌ی اول)", group="search", target_label="بازه‌ی زمانی",
          help="کلمات کلیدی = عبارت‌های جستجو (استخدام کارشناس سئو، GEO specialist remote). "
               "بازه: day / week / month / any. دامنه‌های جدید در «سایت‌های کشف‌شده» می‌آیند.")
def websearch(src: SourceConfig, limit: int) -> List[Item]:
    return _run(src.queries("استخدام سئو"), (src.target or "week").strip().lower(), limit)


@register("site_search", "جستجو در یک سایت خاص", group="search", needs_target=True, target_label="دامنه/مسیر",
          help="مثلا linkedin.com/posts یا wellfound.com/jobs یا jobinja.ir — کلمات کلیدی = عبارت جستجو. "
               "نتایج یک هفته‌ی اخیر.")
def site_search(src: SourceConfig, limit: int) -> List[Item]:
    sites = split_targets(src.target)
    queries = [f"site:{site} {q}" for site in sites for q in src.queries("SEO")]
    return _run(queries, "week", limit)


@register("linkedin_posts", "پست‌های عمومی LinkedIn", group="search", target_label="—",
          help="پست‌های استخدامی عمومی لینکدین از طریق جستجوی گوگل. کلمات کلیدی مثل: استخدام سئو، hiring SEO.")
def linkedin_posts(src: SourceConfig, limit: int) -> List[Item]:
    queries = [f"site:linkedin.com/posts {q}" for q in src.queries("استخدام سئو")]
    items = _run(queries, "week", limit)
    for it in items:
        it.company = "LinkedIn post"
    return items


@register("instagram", "Instagram (هشتگ/پیج)", group="search", target_label="هشتگ‌ها / پیج‌ها",
          help="هشتگ یا پیج با ویرگول (#seo, #استخدام_سئو, some_agency). از طریق جستجوی گوگل در پست‌های عمومی. "
               "اتصال مستقیم Instagram Graph API برای آینده آماده است.")
def instagram(src: SourceConfig, limit: int) -> List[Item]:
    queries = []
    for tag in split_targets(src.target) or ["#seo"]:
        base = f'site:instagram.com "{tag}"' if tag.startswith("#") else f"site:instagram.com/{tag.lstrip('@')}"
        extra = " ".join(src.keywords[:2]) if src.keywords else "استخدام OR hiring"
        queries.append(f"{base} {extra}")
    items = _run(queries, "month", limit)
    for it in items:
        it.company = "Instagram"
    return items
