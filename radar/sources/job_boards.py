"""Remote job boards with free public APIs."""
from __future__ import annotations

from typing import List

import requests

from ..http import get_json
from ..textutil import strip_html, to_iso
from .base import Item, register, split_targets


def _salary(lo, hi, currency="USD") -> str:
    if not lo and not hi:
        return ""
    return f"{lo or '?'} - {hi or '?'} {currency or ''}".strip()


@register("remoteok", "RemoteOK", "تگ‌ها با ویرگول انگلیسی، مثلا: seo,marketing (خالی = همه‌ی آگهی‌های جدید)", needs_target=False)
def remoteok(target: str, limit: int) -> List[Item]:
    items, seen = [], set()
    for tag in split_targets(target) or [""]:
        data = get_json("https://remoteok.com/api", params={"tag": tag} if tag else None)
        for job in data if isinstance(data, list) else []:
            if not isinstance(job, dict) or not job.get("position"):
                continue  # first element is a legal notice
            jid = str(job.get("id") or job.get("slug") or job.get("url"))
            if jid in seen:
                continue
            seen.add(jid)
            items.append(
                Item(
                    title=job.get("position", ""),
                    company=job.get("company", ""),
                    url=job.get("url") or job.get("apply_url") or "",
                    location=job.get("location") or "Remote",
                    description=strip_html(job.get("description")),
                    posted_at=to_iso(job.get("epoch") or job.get("date")),
                    tags=list(job.get("tags") or []) + ["Remote"],
                    salary=_salary(job.get("salary_min"), job.get("salary_max")),
                    external_id=jid,
                )
            )
    return items[:limit]


@register("remotive", "Remotive", "عبارت جستجو، مثلا: seo  یا  category:marketing (چندتا با ویرگول)")
def remotive(target: str, limit: int) -> List[Item]:
    items = []
    for term in split_targets(target) or ["seo"]:
        params = {"limit": limit}
        if term.lower().startswith("category:"):
            params["category"] = term.split(":", 1)[1].strip()
        else:
            params["search"] = term
        data = get_json("https://remotive.com/api/remote-jobs", params=params)
        for job in data.get("jobs", []):
            items.append(
                Item(
                    title=job.get("title", ""),
                    company=job.get("company_name", ""),
                    url=job.get("url", ""),
                    location=job.get("candidate_required_location") or "Remote",
                    description=strip_html(job.get("description")),
                    posted_at=to_iso(job.get("publication_date")),
                    job_type=(job.get("job_type") or "").replace("_", " ").title(),
                    salary=job.get("salary") or "",
                    tags=list(job.get("tags") or []) + [job.get("category") or "", "Remote"],
                    external_id=str(job.get("id") or job.get("url")),
                )
            )
    return items


@register("jobicy", "Jobicy", "تگ، مثلا: seo  یا  industry:marketing (چندتا با ویرگول)")
def jobicy(target: str, limit: int) -> List[Item]:
    items = []
    for term in split_targets(target) or ["seo"]:
        params = {"count": min(limit, 50)}
        if term.lower().startswith("industry:"):
            params["industry"] = term.split(":", 1)[1].strip()
        else:
            params["tag"] = term
        data = get_json("https://jobicy.com/api/v2/remote-jobs", params=params)
        for job in data.get("jobs", []) or []:
            job_type = job.get("jobType") or []
            industry = job.get("jobIndustry") or []
            items.append(
                Item(
                    title=strip_html(job.get("jobTitle", "")),
                    company=job.get("companyName", ""),
                    url=job.get("url", ""),
                    location=job.get("jobGeo") or "Remote",
                    description=strip_html(job.get("jobDescription") or job.get("jobExcerpt")),
                    posted_at=to_iso(job.get("pubDate")),
                    job_type=", ".join(job_type) if isinstance(job_type, list) else str(job_type),
                    salary=_salary(job.get("annualSalaryMin"), job.get("annualSalaryMax"), job.get("salaryCurrency")),
                    tags=(list(industry) if isinstance(industry, list) else [str(industry)]) + ["Remote"],
                    external_id=str(job.get("id") or job.get("url")),
                )
            )
    return items


def _himalayas_item(job: dict) -> Item:
    locs = job.get("locationRestrictions") or []
    loc_names = [x if isinstance(x, str) else (x.get("name") or "") for x in locs]
    cats = [c if isinstance(c, str) else (c.get("name") or "") for c in (job.get("categories") or [])]
    return Item(
        title=job.get("title", ""),
        company=job.get("companyName", ""),
        url=job.get("applicationLink") or job.get("guid") or "",
        location=", ".join(n for n in loc_names if n) or "Remote (Worldwide)",
        description=strip_html(job.get("description") or job.get("excerpt")),
        posted_at=to_iso(job.get("pubDate")),
        job_type=job.get("employmentType") or "",
        salary=_salary(job.get("minSalary"), job.get("maxSalary"), job.get("currency")),
        tags=cats + ["Remote"],
        external_id=str(job.get("guid") or job.get("applicationLink") or job.get("title")),
    )


@register("himalayas", "Himalayas", "عبارت جستجو، مثلا: seo  یا  digital marketing")
def himalayas(target: str, limit: int) -> List[Item]:
    items = []
    for term in split_targets(target) or ["seo"]:
        try:
            data = get_json("https://himalayas.app/jobs/api/search", params={"q": term})
            jobs = data.get("jobs", [])
        except requests.HTTPError:
            # Fallback: latest jobs feed; scoring filters out the irrelevant ones.
            jobs = []
            for offset in (0, 20, 40):
                jobs += get_json("https://himalayas.app/jobs/api", params={"limit": 20, "offset": offset}).get("jobs", [])
        items += [_himalayas_item(job) for job in jobs[:limit]]
    return items


@register("arbeitnow", "Arbeitnow (اروپا)", "بدون نیاز به مقدار", needs_target=False)
def arbeitnow(target: str, limit: int) -> List[Item]:
    data = get_json("https://www.arbeitnow.com/api/job-board-api")
    items = []
    for job in data.get("data", [])[:limit]:
        tags = list(job.get("tags") or []) + list(job.get("job_types") or [])
        if job.get("remote"):
            tags.append("Remote")
        items.append(
            Item(
                title=job.get("title", ""),
                company=job.get("company_name", ""),
                url=job.get("url", ""),
                location=job.get("location") or "",
                description=strip_html(job.get("description")),
                posted_at=to_iso(job.get("created_at")),
                job_type=", ".join(job.get("job_types") or []),
                tags=tags,
                external_id=str(job.get("slug") or job.get("url")),
            )
        )
    return items
