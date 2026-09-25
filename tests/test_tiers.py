from datetime import datetime, timedelta, timezone

from radar.sources.telegram import parse_post
from radar.tiers import Classifier, channel_of


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def test_match_review_drop():
    c = Classifier()
    assert c.classify("استخدام کارشناس سئو (دورکاری)", "", "https://jobinja.ir/x", _ago(1))["tier"] == "match"
    assert c.classify("Senior SEO Manager", "Fully remote role", "https://linkedin.com/jobs/view/1", _ago(2))["tier"] == "match"
    assert c.classify("کارشناس سئو", "", "https://jobinja.ir/x", "")["tier"] == "review"          # no date, no mode
    assert c.classify("کارشناس سئو", "دورکاری", "https://jobinja.ir/x", _ago(20))["tier"] == "drop"  # too old
    assert c.classify("کارشناس دیجیتال مارکتینگ", "آشنا با سئو، دورکاری", "", _ago(1))["tier"] == "drop"
    assert c.classify("Junior SEO Executive", "remote", "", _ago(1))["tier"] == "drop"
    assert c.classify("کارشناس سئو حضوری", "تهران", "", _ago(1))["tier"] == "drop"
    assert c.classify("GEOINT Analyst", "remote", "", _ago(1))["tier"] == "drop"


def test_persian_word_boundary():
    c = Classifier()
    # «مسئول» contains «سئو» but is not SEO
    assert c.classify("استخدام مسئول دفتر", "مسئولیت‌ها", "", _ago(1))["role"] == "none"
    assert c.classify("طراحی و سئوی سایت", "", "https://ponisha.ir/project/1", _ago(1))["tier"] == "match"


def test_geo_role():
    r = Classifier().classify("SEO & GEO Manager", "remote", "", _ago(1))
    assert r["role"] == "geo" and r["tier"] == "match"


def test_channel_of():
    assert channel_of("telegram", "https://ponisha.ir/project/1") == "iran"
    assert channel_of("telegram", "https://t.me/doorkaari/1") == "social"
    assert channel_of("linkedin", "https://www.linkedin.com/jobs/view/1") == "linkedin"
    assert channel_of("remotive", "https://remotive.com/x") == "intl"


def test_karlancer_post():
    text = "✒ عنوان پروژه:\nسئو سایت فروشگاهی\n\n💰 قیمت پیشنهادی کارفرما:\nبین ۱ تا ۲ میلیون تومان\n"
    html = 'href="https://www.karlancer.com/projects/abc-123"'
    items = parse_post("karlancer_projects", "karlancer_projects/5", html, text, _ago(0))
    assert items[0].title == "سئو سایت فروشگاهی"
    assert items[0].url.startswith("https://www.karlancer.com/projects/")
    assert "میلیون" in items[0].salary


def test_digest_post_and_promo():
    text = "✅ استخدام کارشناس سئو در #تهران\n✅ استخدام حسابدار در #اصفهان\n"
    html = 'href="https://www.e-estekhdam.com/?p=1" href="https://www.e-estekhdam.com/?p=2"'
    items = parse_post("eestekhdam_com", "eestekhdam_com/9", html, text, _ago(0))
    assert [i.url[-1] for i in items] == ["1", "2"] and items[0].location == "تهران"
    assert parse_post("doorkaari", "doorkaari/1", "", "قالب نواتم با تخفیف", _ago(0)) == []


def test_custom_site_goes_to_iran_page(tmp_path, monkeypatch):
    import shutil

    import radar.config_store as cs
    from radar.remote_config import apply_sources

    tmp = tmp_path / "sources.yaml"
    shutil.copy(cs.SOURCES_PATH, tmp)
    monkeypatch.setattr(cs, "SOURCES_PATH", tmp)
    doc = {"custom": [{"id": "kb", "name": "کاربوم", "url": "https://karboom.io/jobs?q=seo", "region": "iran"}],
           "linkedinOn": False}
    apply_sources(doc)
    by_id = {s.id: s for s in cs.load_sources()}
    assert by_id["custom-kb"].type == "webpage" and by_id["custom-kb"].target.startswith("https://karboom.io")
    assert by_id["linkedin-jobs"].enabled is False
    assert channel_of("websearch", "https://www.karboom.io/job/1") == "iran"
    apply_sources({"custom": []})
    assert "custom-kb" not in {s.id for s in cs.load_sources()}


JOBINJA_CARD = """
<ul><li class="c-jobListView__item"><div><h2 class="c-jobListView__title">
<a class="c-jobListView__titleLink" href="https://jobinja.ir/companies/acme/jobs/AbC1/استخدام-کارشناس-سئو">استخدام کارشناس سئو (دورکاری)</a>
<span class="c-jobListView__passedDays">(۲ روز پیش)</span></h2>
<ul><li><span>شرکت نمونه</span></li><li><span>تهران ، تهران</span></li></ul></div></li>
<li class="c-jobListView__item"><div><h2><a href="https://jobinja.ir/companies/beta/jobs/XyZ9/استخدام-متخصص-سئو">استخدام متخصص سئو</a>
<span>(امروز)</span></h2></div></li></ul>
"""


def test_harvest_reads_passed_days(monkeypatch):
    from radar.sources import iran

    monkeypatch.setattr(iran, "get_text", lambda url, **kw: "<h1>استخدام متخصص سئو</h1><p>نوع همکاری: دورکاری</p>")
    monkeypatch.setattr(iran, "pause", lambda *a: None)
    items = iran.harvest(JOBINJA_CARD, "https://jobinja.ir/jobs", r"^/companies/[^/]+/jobs/[A-Za-z0-9]+")
    assert [i.title for i in items] == ["استخدام کارشناس سئو (دورکاری)", "استخدام متخصص سئو"]
    assert items[0].posted_at and items[1].posted_at
    iran.enrich(items)
    assert "دورکاری" in items[1].description
    c = Classifier()
    assert c.classify(items[1].title, items[1].description, items[1].url, items[1].posted_at)["tier"] == "match"


def test_undated_iran_scrape_uses_found_date():
    c = Classifier()
    r = c.classify("استخدام کارشناس سئو (دورکاری)", "", "https://jobinja.ir/x", "", source_type="jobinja", found=_ago(1))
    assert r["tier"] == "match" and r["approx"]
    r = c.classify("استخدام کارشناس سئو (دورکاری)", "", "https://jobinja.ir/x", "", source_type="websearch", found=_ago(1))
    assert r["tier"] == "review"
