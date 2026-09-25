"""Iranian job boards & freelance marketplaces (Jobinja, JobVision, Ponisha, Karlancer, ...).

Most Iranian sites refuse connections from outside Iran, so these connectors run
on your Mac (runner="local"; VPN off). Results are synced to GitHub for the
daily e-mail.

Instead of fragile CSS selectors, listing pages are parsed with a *link
harvester*: every <a> whose URL matches the site's job-detail pattern becomes an
item (the anchor text is the title; text around the card is the description).
When a site changes its HTML only the URL pattern matters, and a generic
`webpage` connector works for any site that isn't built in.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse

import requests

from ..http import get_text, pause, post_json
from ..textutil import fa_date, first_line, normalize, strip_html, to_iso
from .base import Item, SourceConfig, register

_NAV_WORDS = re.compile(
    r"(ورود|ثبت ?نام|درباره|تماس|قوانین|حریم|وبلاگ|بلاگ|راهنما|سوالات|login|register|signup|about|contact|"
    r"privacy|terms|blog|help|faq|pricing|تعرفه|دانلود|اپلیکیشن)", re.I)


class _Anchors(HTMLParser):
    """Collect (href, text, context) for every <a> on the page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Dict] = []
        self._stack: List[Dict] = []
        self._recent: List[str] = []  # text seen recently, used as card context

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._stack.append({"href": href, "text": []})

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            a = self._stack.pop()
            text = re.sub(r"\s+", " ", " ".join(a["text"])).strip()
            self.links.append({"href": a["href"], "text": text, "index": len(self._recent)})

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
        for a in self._stack:
            a["text"].append(data)
        self._recent.append(data)


def harvest(page: str, base_url: str, pattern: Optional[str] = None, limit: int = 60) -> List[Item]:
    parser = _Anchors()
    parser.feed(page)
    base_host = urlparse(base_url).netloc.lower().replace("www.", "")
    rx = re.compile(pattern) if pattern else None
    found: Dict[str, Item] = {}
    for link in parser.links:
        href = link["href"]
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        if base_host not in host:
            continue
        path = unquote(parsed.path)
        text = link["text"]
        if rx:
            if not rx.search(path):
                continue
        else:  # heuristic: detail-looking URL + meaningful anchor text
            has_id = bool(re.search(r"/\d{3,}|/[A-Za-z0-9]{3,8}/[^/]{6,}", path))
            if not has_id or len(path) < 8 or _NAV_WORDS.search(text or path):
                continue
        if len(text) < 6:
            continue
        # Context: the text that follows the anchor on the page (company, city, salary…)
        ctx = " · ".join(parser._recent[link["index"]: link["index"] + 6])
        key = url.rstrip("/")
        prev = found.get(key)
        if prev is None or len(text) > len(prev.title):
            # «(۳ روز پیش)» usually sits right after the title link on Iranian boards
            near = " ".join(parser._recent[link["index"]: link["index"] + 4])
            found[key] = Item(title=first_line(text, 160), url=url, description=strip_html(ctx)[:600],
                              posted_at=fa_date(near) or (prev.posted_at if prev else None), external_id=key)
        if len(found) >= limit:
            break
    return list(found.values())


_SEO_TITLE = re.compile(r"(?<![\u0620-\u064a\u066e-\u06d3\u06fa-\u06ff])سئو|seo|جئو|(?<![a-z])geo(?![a-z])|موتور جستجو", re.I)
_REMOTE_HINT = re.compile(r"دورکار|دور کار|ریموت|remote|غیرحضوری", re.I)


def enrich(items: List[Item], max_fetch: int = 12) -> None:
    """Open the detail page of SEO/GEO postings that lack a date or a remote hint.

    Listing cards on Iranian boards are short; the detail page holds the publish
    date («۳ روز پیش» / ۱۴۰۵/۰۷/۰۱) and the work type (دورکاری / تمام‌وقت).
    """
    done = 0
    for it in items:
        if done >= max_fetch:
            break
        if not _SEO_TITLE.search(normalize(it.title)):
            continue
        if it.posted_at and _REMOTE_HINT.search(it.title + " " + it.description):
            continue
        try:
            text = strip_html(get_text(it.url))
        except requests.RequestException:
            continue
        done += 1
        text = re.sub(r"[ \t]+", " ", text)
        pos = text.find(it.title[:25])
        body = text[pos: pos + 3000] if pos > -1 else text[:3000]
        if not it.posted_at:
            spots = [text[max(0, m.start() - 60): m.end() + 60]
                     for m in re.finditer(r"انتشار|منتشر شده|تاریخ ثبت|ثبت آگهی|Posted", text)]
            for spot in spots + [body[:400]]:
                it.posted_at = fa_date(spot)
                if it.posted_at:
                    break
        if len(body) > len(it.description or ""):
            it.description = body
        pause(1)


def _fill(template: str, keyword: str) -> str:
    slug = quote(keyword.strip().replace(" ", "-"))
    return template.format(q=quote_plus(keyword.strip()), slug=slug)


# key: (label, url template, detail-URL regex, default keyword, company-from-url regex)
PRESETS = {
    "jobinja": ("جابینجا (Jobinja)", "https://jobinja.ir/jobs?filters%5Bkeywords%5D%5B0%5D={q}&sort_by=published_at_desc",
                r"^/companies/[^/]+/jobs/[A-Za-z0-9]+", "سئو", r"/companies/([^/]+)/jobs"),
    "ponisha": ("پونیشا (Ponisha)", "https://ponisha.ir/search/projects/{slug}",
                r"^/project/\d+", "seo", None),
    "karlancer": ("کارلنسر (Karlancer)", "https://www.karlancer.com/jobs/{slug}",
                  r"^/projects/[^/?#]+", "seo", None),
    "parscoders": ("پارس‌کدرز (Parscoders)", "https://parscoders.com/project/skills/{slug}",
                   r"^/project/\d+", "seo", None),
    "eestekhdam": ("ای‌استخدام (e-estekhdam)", "https://www.e-estekhdam.com/search/{slug}",
                   None, "استخدام متخصص SEO", None),
    "karbord": ("کاربرد (Karbord)", "https://karbord.io/jobs/{slug}", r"^/jobs/(?:detail/)?\d+", "seo", None),
    "kardix": ("کاردیکس (Kardix)", "https://kardix.com/jobs/q-{slug}", None, "seo", None),
    "lancerify": ("لنسریفای (Lancerify)", "https://lancerify.com/projects/{slug}", r"^/project", "seo", None),
    "divar": ("دیوار — نیازمندی‌ها", "https://divar.ir/s/{city}/jobs?q={q}", r"^/v/", "سئو", None),
}


def _preset_fetch(key: str):
    label, template, pattern, default_kw, company_rx = PRESETS[key]

    def fetch(src: SourceConfig, limit: int) -> List[Item]:
        items: List[Item] = []
        for kw in src.keywords or [default_kw]:
            url = _fill(template.replace("{city}", (src.target or "tehran").strip() or "tehran"), kw)
            found = harvest(get_text(url), url, pattern, limit)
            for it in found:
                it.location = it.location or "Iran"
                if company_rx:
                    m = re.search(company_rx, urlparse(it.url).path)
                    if m:
                        it.company = unquote(m.group(1)).replace("-", " ")
                if key in ("ponisha", "karlancer", "parscoders", "lancerify"):
                    it.job_type = "Freelance"
                    it.company = it.company or label
            enrich(found)
            items += found
            pause(2)
        return items[: limit * 2]

    return fetch


for _key, (_label, _tpl, _pat, _kw, _crx) in PRESETS.items():
    register(_key, _label, group="iran", runner="local",
             target_label="شهر (فقط دیوار)" if _key == "divar" else "—",
             help=f"کلمات کلیدی = عبارت جستجو (پیش‌فرض: {_kw}). فقط از IP ایران (مک، VPN خاموش) کار می‌کند.")(
        _preset_fetch(_key))


@register("jobvision", "جاب‌ویژن (JobVision)", group="iran", runner="local", target_label="—",
          help="کلمات کلیدی = عبارت جستجو (سئو، دیجیتال مارکتینگ). فقط از IP ایران.")
def jobvision(src: SourceConfig, limit: int) -> List[Item]:
    items: List[Item] = []
    for kw in src.keywords or ["سئو"]:
        try:
            data = post_json("https://candidateapi.jobvision.ir/api/v1/JobPost/List",
                             {"pageSize": 30, "requestedPage": 1, "sortBy": 1, "searchId": None, "keyword": kw})
            posts = ((data or {}).get("data") or {}).get("jobPosts") or []
        except (requests.RequestException, ValueError):
            posts = []
        if posts:
            for p in posts:
                company = p.get("company") or {}
                loc = p.get("location") or {}
                province = (loc.get("province") or {}).get("titleFa", "") if isinstance(loc, dict) else ""
                city = (loc.get("city") or {}).get("titleFa", "") if isinstance(loc, dict) else ""
                activation = p.get("activationTime") or {}
                flags = " ".join(str(v) for k, v in p.items() if "remote" in k.lower() and v)
                work = p.get("workType") if isinstance(p.get("workType"), dict) else {}
                items.append(Item(
                    title=p.get("title", ""), company=company.get("nameFa") or company.get("nameEn") or "",
                    url=f"https://jobvision.ir/jobs/{p.get('id')}", location=" - ".join(x for x in (province, city) if x) or "Iran",
                    posted_at=to_iso(activation.get("date") if isinstance(activation, dict) else activation),
                    job_type=str(work.get("titleFa", "")), tags=["Remote"] if flags and flags not in ("False", "0") else [],
                    description=" ".join(x for x in (str(work.get("titleFa", "")), "دورکاری" if flags and flags not in ("False", "0") else "",
                                                       strip_html(str(p.get("description") or ""))[:1500]) if x),
                    salary=str((p.get("salary") or {}).get("titleFa", "")) if isinstance(p.get("salary"), dict) else "",
                    external_id=str(p.get("id")),
                ))
        else:  # fallback: harvest the public listing page
            url = f"https://jobvision.ir/jobs/keyword/{quote(kw)}"
            found = harvest(get_text(url), url, r"^/jobs/\d+", limit)
            enrich(found)
            for it in found:
                it.location = "Iran"
                items.append(it)
        pause(2)
    return items


@register("webpage", "هر صفحه‌ی وب (لیست آگهی)", group="iran", runner="both", needs_target=True,
          keyword_mode="filter", target_label="آدرس صفحه",
          help="آدرس صفحه‌ی لیست آگهی‌ها (مثلا نتیجه‌ی جستجوی یک سایت کاریابی). اختیاری: بعد از | یک الگوی "
               "Regex برای مسیر لینک آگهی‌ها، مثلا: https://site.ir/jobs?q=seo | ^/job/\\d+")
def webpage(src: SourceConfig, limit: int) -> List[Item]:
    url, _, pattern = (src.target or "").partition("|")
    url = url.strip()
    items = harvest(get_text(url), url, pattern.strip() or None, limit)
    enrich(items)
    host = urlparse(url).netloc.replace("www.", "")
    for it in items:
        it.company = it.company or host
        if normalize(host).endswith(".ir"):
            it.location = it.location or "Iran"
    return items
