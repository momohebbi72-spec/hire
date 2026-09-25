from datetime import datetime, timezone

from radar.profile import load_profile, parse_profile
from radar.scoring import score_item
from radar.sources.base import Item

NOW = datetime.now(timezone.utc).isoformat()


def test_strong_seo_match():
    item = Item(title="SEO Specialist", company="Acme SaaS", location="Remote - Canada", posted_at=NOW,
                description="We need Technical SEO, GA4, Google Search Console and WordPress experience. "
                            "Full-time remote role at a SaaS startup.")
    r = score_item(item, load_profile())
    assert r.score >= 80, r
    assert "✓ Remote" in r.reasons
    assert r.remote_type == "Remote"
    assert r.category == "SEO"
    assert "Search Console & Analytics" in r.skills


def test_persian_posting_matches():
    item = Item(title="استخدام كارشناس سئو (دورکاری)", company="استادکار", location="تهران", posted_at=NOW,
                description="آشنایی با وردپرس و گوگل آنالیتیکس و سرچ کنسول")
    r = score_item(item, load_profile())
    assert r.score >= 60, r
    assert r.remote_type == "Remote"
    assert "WordPress / Ecommerce SEO" in r.skills


def test_irrelevant_job_is_low():
    item = Item(title="Senior Java Backend Engineer", description="Spring boot microservices", posted_at=NOW)
    assert score_item(item, load_profile()).score <= 15


def test_excluded_title_scores_zero():
    item = Item(title="SEO Intern", description="SEO internship", posted_at=NOW)
    assert score_item(item, load_profile()).score == 0


def test_geo_is_case_sensitive():
    profile = parse_profile({"skills": {"AI SEO": {"weight": 9, "aliases": ["!GEO"]}}})
    assert score_item(Item(title="GEO specialist"), profile).skills == ["AI SEO"]
    assert score_item(Item(title="geo-targeting analyst"), profile).skills == []
