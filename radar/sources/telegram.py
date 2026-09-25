"""Public Telegram channels via the web preview (t.me/s/<channel>) — no bot or login needed."""
from __future__ import annotations

import re
from typing import List

from datetime import datetime, timedelta, timezone

from ..http import get_text, pause
from ..textutil import first_line, parse_iso, strip_html, to_iso
from .base import Item, SourceConfig, register, split_targets

_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time[^>]+datetime="([^"]+)"')
_HREF = re.compile(r'href="(https?://[^"]+)"')
_BUDGET = re.compile(r"(?:بودجه|قیمت پیشنهادی[^:\n]*)\s*:?\s*\n?\s*([^\n]{3,80})")
_EMOJI = re.compile(r"^[\W_]+")
# promo / news posts that are never a job
PROMO = ("نواتم", "رزرو تبلیغ", "تعرفه تبلیغات", "کد تخفیف", "خرید قالب", "دوره آموزش", "وبینار", "نتایج آزمون",
         "زمان آزمون", "کارت ورود به جلسه", "منابع مطالعاتی", "کنکور")
# links that point to the real posting (preferred over the t.me link)
_POSTING_LINK = re.compile(r"(ponisha\.ir/project/|karlancer\.com/projects/|e-estekhdam\.com/\?p=|jobinja\.ir/companies/"
                           r"|jobvision\.ir/jobs/|parscoders\.com/project|linkedin\.com/jobs/)")


def _channel(value: str) -> str:
    value = value.strip()
    for prefix in ("https://", "http://", "t.me/s/", "t.me/", "telegram.me/", "@"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.strip("/")


@register("telegram", "کانال عمومی تلگرام", group="feed", keyword_mode="filter", needs_target=True,
          target_label="کانال‌ها",
          help="یوزرنیم یا لینک کانال عمومی (t.me/xxx) — چندتا با ویرگول. کلمات کلیدی برای فیلتر پیام‌ها.")
def _clean_title(line: str) -> str:
    return _EMOJI.sub("", line).strip(" :-–|")[:200]


def _unquote(url: str) -> str:
    from urllib.parse import unquote
    return unquote(url)


def parse_post(channel: str, post_id: str, raw_html: str, text: str, posted) -> List[Item]:
    """Turns one channel post into zero or more Items (digest posts hold several jobs)."""
    if any(p in text for p in PROMO):
        return []
    links = [_unquote(u) for u in _HREF.findall(raw_html) if _POSTING_LINK.search(u)]
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    base = dict(company=f"@{channel}", posted_at=posted, source_type="telegram")
    tg_url = f"https://t.me/{post_id}"

    # karlancer_projects: "✒ عنوان پروژه:\n<title> ... 💰 قیمت پیشنهادی کارفرما: ..."
    if "عنوان پروژه" in text:
        idx = next((i for i, l in enumerate(lines) if "عنوان پروژه" in l), 0)
        after = re.sub(r"^.*?عنوان پروژه\s*:?", "", lines[idx]).strip()
        title = after or (lines[idx + 1] if idx + 1 < len(lines) else "")
        budget = _BUDGET.search(text)
        return [Item(title=_clean_title(title), url=links[0] if links else tg_url, description=text,
                     salary=budget.group(1).strip() if budget else "", external_id=post_id, **base)]

    # e-estekhdam digests: one "✅ استخدام ... در #شهر" line per job, each followed by its link
    digest = [l for l in lines if l.startswith("✅") and "استخدام" in l]
    if len(digest) >= 2:
        out = []
        for n, line in enumerate(digest):
            title = _clean_title(line).replace("#", "")
            out.append(Item(title=title, url=links[n] if n < len(links) else tg_url, description=title,
                            location=title.rsplit(" در ", 1)[-1] if " در " in title else "",
                            external_id=f"{post_id}#{n}", **base))
        return out

    budget = _BUDGET.search(text)
    return [Item(title=_clean_title(first_line(text)), url=links[0] if links else tg_url, description=text,
                 salary=budget.group(1).strip() if budget else "", external_id=post_id, **base)]


def telegram(src: SourceConfig, limit: int, days: int = 7, max_pages: int = 12) -> List[Item]:
    """Reads the public web preview t.me/s/<channel> (no bot, no login), paging back
    until posts are older than `days`.

    For private channels / groups a Telegram API client (Telethon, api_id + api_hash)
    can be plugged in later behind the same function signature.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: List[Item] = []
    for raw in split_targets(src.target):
        channel = _channel(raw)
        before = None
        for _ in range(max_pages):
            url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
            page = get_text(url)
            posts, oldest_id, oldest_dt = [], None, None
            for chunk in page.split('data-post="')[1:]:
                post_id = chunk.split('"', 1)[0]
                num = post_id.rsplit("/", 1)[-1]
                if num.isdigit():
                    oldest_id = int(num) if oldest_id is None else min(oldest_id, int(num))
                match = _TEXT.search(chunk)
                if not match:
                    continue
                text = strip_html(match.group(1))
                if not text:
                    continue
                when = _TIME.search(chunk)
                posted = to_iso(when.group(1)) if when else None
                dt = parse_iso(posted)
                if dt and (oldest_dt is None or dt < oldest_dt):
                    oldest_dt = dt
                if dt and dt < cutoff:
                    continue
                posts += parse_post(channel, post_id, chunk, text, posted)
            items += posts
            if not oldest_id or (oldest_dt and oldest_dt < cutoff) or oldest_id <= 1:
                break
            before = oldest_id
            pause(1)
    return items
