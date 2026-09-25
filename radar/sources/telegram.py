"""Public Telegram channels via the web preview (t.me/s/<channel>) — no bot or login needed."""
from __future__ import annotations

import re
from typing import List

from ..http import get_text
from ..textutil import first_line, strip_html, to_iso
from .base import Item, register, split_targets

_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time[^>]+datetime="([^"]+)"')


def _channel(value: str) -> str:
    value = value.strip()
    for prefix in ("https://", "http://", "t.me/s/", "t.me/", "telegram.me/", "@"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.strip("/")


@register("telegram", "کانال عمومی تلگرام", "یوزرنیم کانال عمومی بدون @ (چندتا با ویرگول)، مثلا: seo_jobs")
def telegram(target: str, limit: int) -> List[Item]:
    items = []
    for raw in split_targets(target):
        channel = _channel(raw)
        page = get_text(f"https://t.me/s/{channel}")
        posts = []
        for chunk in page.split('data-post="')[1:]:
            post_id = chunk.split('"', 1)[0]
            match = _TEXT.search(chunk)
            if not match:
                continue
            text = strip_html(match.group(1))
            if not text:
                continue
            when = _TIME.search(chunk)
            posts.append(
                Item(
                    title=first_line(text),
                    company=f"@{channel}",
                    url=f"https://t.me/{post_id}",
                    description=text,
                    posted_at=to_iso(when.group(1)) if when else None,
                    external_id=post_id,
                )
            )
        items += list(reversed(posts))[:limit]  # page lists oldest first
    return items
