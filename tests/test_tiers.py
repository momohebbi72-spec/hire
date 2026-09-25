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
