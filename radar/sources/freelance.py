"""Freelance project marketplaces."""
from __future__ import annotations

from typing import List

from ..http import get_json
from ..textutil import strip_html, to_iso
from .base import Item, register, split_targets


@register("freelancer", "Freelancer.com (پروژه فریلنس)", "عبارت جستجو، مثلا: seo  یا  wordpress (چندتا با ویرگول)")
def freelancer(target: str, limit: int) -> List[Item]:
    items = []
    for term in split_targets(target) or ["seo"]:
        data = get_json(
            "https://www.freelancer.com/api/projects/0.1/projects/active/",
            params={"query": term, "limit": min(limit, 50), "full_description": "true", "job_details": "true"},
        )
        for p in (data.get("result") or {}).get("projects", []):
            budget = p.get("budget") or {}
            currency = (p.get("currency") or {}).get("code", "")
            kind = "Hourly" if p.get("type") == "hourly" else "Fixed"
            salary = ""
            if budget.get("minimum") or budget.get("maximum"):
                salary = f"{budget.get('minimum') or '?'} - {budget.get('maximum') or '?'} {currency} ({kind})"
            slug = p.get("seo_url") or p.get("id")
            items.append(
                Item(
                    title=p.get("title", ""),
                    company="Freelancer.com client",
                    url=f"https://www.freelancer.com/projects/{slug}",
                    location="Remote",
                    description=strip_html(p.get("description") or p.get("preview_description")),
                    posted_at=to_iso(p.get("time_submitted")),
                    job_type="Freelance",
                    salary=salary,
                    tags=[j.get("name", "") for j in (p.get("jobs") or []) if isinstance(j, dict)] + ["Remote"],
                    external_id=str(p.get("id")),
                )
            )
    return items
