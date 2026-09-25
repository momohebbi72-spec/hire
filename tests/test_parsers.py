from radar.sources.feeds import parse_feed
from radar.sources.iran import harvest
from radar.sources.linkedin import parse_cards

RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>Acme: SEO Lead</title><link>https://x.test/1</link><pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Remote SEO&lt;/p&gt;</description></item></channel></rss>"""

JOBINJA = """<ul><li class="c-jobListView__item">
<a class="c-jobListView__titleLink" href="https://jobinja.ir/companies/ostadkar-1/jobs/swL/abc">استخدام متخصص سئو (دورکاری)</a>
<span>استادکار</span><span>تهران</span></li>
<li><a href="/login">ورود کارجو</a></li></ul>"""

LINKEDIN = """<li><div class="base-card" data-entity-urn="urn:li:jobPosting:12345">
<h3 class="base-search-card__title">SEO Manager</h3>
<h4 class="base-search-card__subtitle"><a href="#">Acme</a></h4>
<span class="job-search-card__location">Toronto, ON</span><time datetime="2026-09-20">x</time></div></li>"""


def test_rss():
    entries = parse_feed(RSS)
    assert entries[0]["title"] == "Acme: SEO Lead"
    assert entries[0]["link"] == "https://x.test/1"


def test_harvest_with_pattern():
    items = harvest(JOBINJA, "https://jobinja.ir/jobs", r"^/companies/[^/]+/jobs/[A-Za-z0-9]+")
    assert len(items) == 1
    assert "سئو" in items[0].title
    assert "تهران" in items[0].description


def test_linkedin_cards():
    cards = parse_cards(LINKEDIN)
    assert cards[0]["id"] == "12345"
    assert cards[0]["title"] == "SEO Manager"
    assert cards[0]["company"] == "Acme"
