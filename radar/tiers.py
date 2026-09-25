"""SEO / GEO tier classifier — decides match / review / drop for every opportunity.

The same rules run inside the dashboard (JavaScript) so settings changes apply live;
this Python copy is used for the e-mail report and the feed export.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .textutil import normalize, parse_iso

DEFAULT_RULES: Dict = {
    "days": 7,
    "iranFoundAsDate": True,  # undated postings scraped from Iranian boards: use the day they were first seen
    "role_terms": ["سئو", "سئوکار", "seo", "search engine optimi", "بهینه سازی موتور جستجو", "!GEO", "جئو",
                   "generative engine", "!AEO", "answer engine", "ai search", "ai visibility", "llm optimi",
                   "llm seo", "ai seo", "سئو هوش مصنوعی", "نتایج هوش مصنوعی", "جستجوی هوش مصنوعی", "chatgpt seo"],
    "exclude_title": ["دیجیتال مارکتینگ", "digital marketing", "بازاریابی دیجیتال", "مارکتینگ", "marketing manager",
                      "social media", "سوشال مدیا", "اینستاگرام", "ادمین", "تولید محتوا", "محتوانویس", "content writer",
                      "copywriter", "کپی رایتر", "sem ", "google ads", "گوگل ادز", "ppc", "کارشناس فروش", "sales", "برنامه نویس", "developer"],
    "junior_terms": ["کارآموز", "کارورز", "intern", "internship", "junior", "جونیور", "تازه کار", "entry level",
                     "entry-level", "trainee", "بدون سابقه"],
    "remote_terms": ["دورکاری", "دورکار", "دور کاری", "ریموت", "remote", "از راه دور", "work from home", "wfh",
                     "انجام از منزل", "غیرحضوری"],
    "project_terms": ["پروژه", "فریلنس", "freelance", "contract", "قراردادی", "project", "پاره وقت", "پاره‌وقت",
                      "part-time", "part time", "ساعتی"],
    "parttime_terms": ["پاره وقت", "پاره‌وقت", "part-time", "part time", "نیمه وقت", "ساعتی"],
    "onsite_terms": ["حضوری", "on-site", "onsite", "in office", "in-office"],
    "hybrid_terms": ["هیبرید", "hybrid", "ترکیبی", "نیمه حضوری"],
    "senior_terms": ["ارشد", "senior", "مدیر", "سرپرست", "مسئول", "lead", "head of", "manager", "principal", "مشاور",
                     "consultant", "expert", "متخصص"],
    "project_hosts": ["ponisha.ir", "karlancer.com", "parscoders.com", "t.me/ponisha_ir", "t.me/karlancer_projects"],
}


def _pats(terms: List[str]):
    out = []
    for term in terms:
        term = str(term).strip()
        if not term:
            continue
        cs = term.startswith("!")
        word = normalize(term.lstrip("!"))
        esc = re.escape(word).replace(r"\ ", r"\s*")
        if re.match(r"^[\u0600-\u06ff]", word):
            esc = r"(?<![\u0620-\u064a\u066e-\u06d3\u06fa-\u06ff])" + esc
        if re.match(r"^[a-z0-9 .\-]+$", word, re.I):
            esc = rf"(?<![A-Za-z0-9]){esc}"
            if len(word) <= 4:
                esc += r"(?![A-Za-z0-9])"
        out.append(re.compile(esc, 0 if cs else re.I))
    return out


def _has(pats, text: str) -> bool:
    return any(p.search(text) for p in pats)


# connectors that read an Iranian board directly (newest first) — see iranFoundAsDate
IRAN_SCRAPERS = ("jobinja", "jobvision", "eestekhdam", "karbord", "kardix", "divar", "ponisha", "karlancer",
                 "parscoders", "lancerify", "webpage")


class Classifier:
    def __init__(self, rules: Optional[Dict] = None):
        r = dict(DEFAULT_RULES)
        r.update({k: v for k, v in (rules or {}).items() if v not in (None, "")})
        self.rules = r
        self.days = int(r["days"])
        self.role = _pats(r["role_terms"])
        self.excl = _pats(r["exclude_title"])
        self.remote = _pats(r["remote_terms"])
        self.project = _pats(r["project_terms"])
        self.parttime = _pats(r["parttime_terms"])
        self.onsite = _pats(r["onsite_terms"])
        self.hybrid = _pats(r["hybrid_terms"])
        self.senior = _pats(r["senior_terms"])
        self.junior = _pats(r["junior_terms"])
        self.hosts = [h.lower() for h in r["project_hosts"]]

    def classify(self, title: str, body: str, url: str = "", posted: str = "", remote_hint: str = "",
                 type_hint: str = "", source_type: str = "", found: str = "") -> Dict:
        t = normalize(title or "")
        b = normalize(body or "")
        u = (url or "").lower()
        facets = {"role": "none", "mode": "unknown", "parttime": False, "level": "any", "fresh": "unknown"}
        why: List[str] = []

        if _has(self.role, t):
            facets["role"] = "geo" if re.search(r"(?<![a-z])(geo|aeo)(?![a-z])|جئو|generative|answer engine|هوش مصنوعی|ai |llm",
                                                 t, re.I) else "seo"
        elif _has(self.role, re.sub(r"#\S+", " ", b)[:1500]):  # category hashtags are not a signal
            facets["role"] = "body"
        mixed = _has(self.excl, t)

        rem = _has(self.remote, t + " " + b) or remote_hint == "Remote"
        proj = any(h in u for h in self.hosts) or _has(self.project, t) or type_hint in ("Freelance", "Contract", "Project")
        onsite = _has(self.onsite, t + " " + b[:600]) and not rem
        if rem:
            facets["mode"] = "remote"
        elif proj:
            facets["mode"] = "project"
        elif _has(self.hybrid, t + " " + b[:600]) or remote_hint == "Hybrid":
            facets["mode"] = "hybrid"
        elif onsite or remote_hint == "On-site":
            facets["mode"] = "onsite"
        facets["parttime"] = _has(self.parttime, t + " " + b[:800])
        facets["level"] = "senior" if _has(self.senior, t) else "any"

        dt = parse_iso(posted)
        if not dt and source_type in IRAN_SCRAPERS and self.rules.get("iranFoundAsDate", True) is not False:
            dt = parse_iso(found)
            facets["approx"] = bool(dt)
        if dt:
            age = datetime.now(timezone.utc) - dt
            facets["fresh"] = "week" if age <= timedelta(days=self.days) else "old"
            facets["age_days"] = max(0, age.days)

        if facets["role"] == "none":
            return {"tier": "drop", "why": ["نامرتبط با سئو/جئو"], **facets}
        if _has(self.junior, t):
            return {"tier": "drop", "why": ["جونیور / کارآموزی"], **facets}
        if facets["fresh"] == "old":
            return {"tier": "drop", "why": [f"قدیمی‌تر از {self.days} روز"], **facets}
        if facets["mode"] == "onsite":
            return {"tier": "drop", "why": ["حضوری"], **facets}
        if mixed and facets["role"] == "body":
            return {"tier": "drop", "why": ["دیجیتال مارکتینگ / نقش دیگر"], **facets}

        if facets["role"] == "body":
            why.append("سئو فقط در متن آمده، نه در عنوان")
        if mixed:
            why.append("عنوان با نقش دیگری ترکیب شده")
        if facets["mode"] in ("unknown", "hybrid"):
            why.append("دورکاری بودن مشخص نیست" if facets["mode"] == "unknown" else "هیبرید")
        if facets["fresh"] == "unknown":
            why.append("تاریخ انتشار نامشخص")
        return {"tier": "review" if why else "match", "why": why or ["سئو/جئو · دورکار/پروژه‌ای · این هفته"], **facets}


IRAN_HOSTS = ("jobinja.ir", "jobvision.ir", "ponisha.ir", "karlancer.com", "parscoders.com", "e-estekhdam.com",
              "iranestekhdam.ir", "karbord.io", "kardix.com", "karpishe.com", "divar.ir", "jobteam.ir", "lancerify.com")


CUSTOM_HOSTS: Dict[str, str] = {}  # host → "iran" | "intl", from the dashboard's own sites


def register_custom_hosts(sources_doc: Optional[Dict]) -> None:
    for c in (sources_doc or {}).get("custom") or []:
        host = re.sub(r"^https?://(www\.)?", "", str(c.get("url") or "").lower()).split("/", 1)[0]
        if host:
            CUSTOM_HOSTS[host] = "intl" if c.get("region") == "intl" else "iran"


def channel_of(source_type: str, url: str) -> str:
    """Which dashboard page an item belongs to: the posting's own site wins over where it was found."""
    st = (source_type or "").lower()
    u = (url or "").lower()
    host = re.sub(r"^https?://(www\.)?", "", u).split("/", 1)[0]
    for h, page in CUSTOM_HOSTS.items():
        if host == h or host.endswith("." + h):
            return page
    if st == "linkedin" or "linkedin.com" in host:
        return "linkedin"
    if any(h in host for h in IRAN_HOSTS) or host.endswith(".ir"):
        return "iran"
    if st in ("telegram", "instagram") or host in ("t.me", "telegram.me") or "instagram.com" in host:
        return "social"
    if st in ("iran", "websearch", "manual", "jobinja", "jobvision", "ponisha", "karlancer", "parscoders",
              "eestekhdam", "iranestekhdam", "karbord", "kardix", "divar", "lancerify"):
        return "iran"
    return "intl"
