"""Company career sites through their public ATS APIs (Greenhouse, Lever, Ashby).

Target = company board slug, e.g. https://boards.greenhouse.io/airbnb -> "airbnb".
"""
from __future__ import annotations

from typing import List

from ..http import get_json
from ..textutil import strip_html, to_iso
from .base import Item, register, split_targets


@register("greenhouse", "سایت شرکت (Greenhouse)", "اسلاگ شرکت از آدرس boards.greenhouse.io/<slug> — چندتا با ویرگول")
def greenhouse(target: str, limit: int) -> List[Item]:
    items = []
    for slug in split_targets(target):
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
        for job in data.get("jobs", []):
            items.append(
                Item(
                    title=job.get("title", ""),
                    company=job.get("company_name") or slug.replace("-", " ").title(),
                    url=job.get("absolute_url", ""),
                    location=(job.get("location") or {}).get("name", ""),
                    description=strip_html(job.get("content")),
                    posted_at=to_iso(job.get("first_published") or job.get("updated_at")),
                    external_id=f"{slug}:{job.get('id')}",
                )
            )
    return items


@register("lever", "سایت شرکت (Lever)", "اسلاگ شرکت از آدرس jobs.lever.co/<slug> — چندتا با ویرگول")
def lever(target: str, limit: int) -> List[Item]:
    items = []
    for slug in split_targets(target):
        data = get_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
        for job in data if isinstance(data, list) else []:
            cats = job.get("categories") or {}
            tags = [cats.get("team") or "", job.get("workplaceType") or ""]
            items.append(
                Item(
                    title=job.get("text", ""),
                    company=slug.replace("-", " ").title(),
                    url=job.get("hostedUrl", ""),
                    location=cats.get("location") or ", ".join(cats.get("allLocations") or []),
                    description=strip_html(
                        (job.get("descriptionPlain") or "") + "\n" + (job.get("additionalPlain") or "")
                    ),
                    posted_at=to_iso(job.get("createdAt")),
                    job_type=cats.get("commitment") or "",
                    tags=[t for t in tags if t],
                    external_id=f"{slug}:{job.get('id')}",
                )
            )
    return items


@register("ashby", "سایت شرکت (Ashby)", "اسلاگ شرکت از آدرس jobs.ashbyhq.com/<slug> — چندتا با ویرگول")
def ashby(target: str, limit: int) -> List[Item]:
    items = []
    for slug in split_targets(target):
        data = get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}
        )
        for job in data.get("jobs", []):
            tags = [job.get("department") or "", job.get("team") or "", job.get("workplaceType") or ""]
            if job.get("isRemote"):
                tags.append("Remote")
            comp = job.get("compensation") or {}
            items.append(
                Item(
                    title=job.get("title", ""),
                    company=slug.replace("-", " ").title(),
                    url=job.get("jobUrl") or job.get("applyUrl") or "",
                    location=job.get("location") or "",
                    description=strip_html(job.get("descriptionPlain") or job.get("descriptionHtml")),
                    posted_at=to_iso(job.get("publishedAt")),
                    job_type=job.get("employmentType") or "",
                    salary=comp.get("compensationTierSummary") or "",
                    tags=[t for t in tags if t],
                    external_id=f"{slug}:{job.get('id') or job.get('jobUrl')}",
                )
            )
    return items
