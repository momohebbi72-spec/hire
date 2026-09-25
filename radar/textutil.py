"""Small text / date helpers shared by fetchers, scoring and exporters."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

_BREAKS = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6]|/tr)\s*/?\s*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_FA_MAP = str.maketrans({
    "\u064a": "\u06cc",  # Arabic yeh  -> Persian yeh
    "\u0649": "\u06cc",  # alef maksura -> Persian yeh
    "\u0643": "\u06a9",  # Arabic kaf  -> Persian keheh
    "\u200c": " ",        # ZWNJ (نیم‌فاصله) -> space
    "\u200f": "",
    "\u200e": "",
    "\u0640": "",         # tatweel
})


def normalize(text) -> str:
    """Normalise Persian/Arabic variants so keyword matching is reliable."""
    return str(text or "").translate(_FA_MAP)


def strip_html(value) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))  # some APIs return escaped HTML
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def to_iso(value) -> Optional[str]:
    """Convert epoch (s/ms), ISO-8601 or RFC-822 dates to a UTC ISO string."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_cell(value) -> str:
    """Remove characters that Excel / XML refuse."""
    if value is None:
        return ""
    return _ILLEGAL_XML.sub("", str(value))


def first_line(text: str, limit: int = 120) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


# ---------------------------------------------------------------- Persian dates
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_REL = re.compile(r"(لحظاتی|دقایقی|ساعاتی)\s*پیش|امروز|دیروز|(\d+)\s*(دقیقه|ساعت|روز|هفته|ماه|سال)\s*(?:پیش|قبل)")
_JALALI = re.compile(r"(1[34]\d\d)\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})")


def jalali_to_gregorian(jy: int, jm: int, jd: int):
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    months = [0, 31, 29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return gy, gm, gd


def fa_date(text, now: Optional[datetime] = None) -> Optional[str]:
    """Finds «امروز / ۳ روز پیش / ۱۴۰۵/۰۷/۰۱» in Persian text and returns a UTC ISO date."""
    if not text:
        return None
    from datetime import timedelta

    t = str(text).translate(_FA_DIGITS)
    now = now or datetime.now(timezone.utc)
    m = _REL.search(t)
    if m:
        if m.group(0) == "دیروز":
            return (now - timedelta(days=1)).isoformat(timespec="seconds")
        if not m.group(2):  # امروز / لحظاتی پیش
            return now.isoformat(timespec="seconds")
        n, unit = int(m.group(2)), m.group(3)
        delta = {"دقیقه": timedelta(minutes=n), "ساعت": timedelta(hours=n), "روز": timedelta(days=n),
                 "هفته": timedelta(weeks=n), "ماه": timedelta(days=30 * n), "سال": timedelta(days=365 * n)}[unit]
        return (now - delta).isoformat(timespec="seconds")
    m = _JALALI.search(t)
    if m:
        jy, jm, jd = (int(x) for x in m.groups())
        if 1 <= jm <= 12 and 1 <= jd <= 31:
            try:
                gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
                return datetime(gy, gm, gd, 12, tzinfo=timezone.utc).isoformat(timespec="seconds")
            except ValueError:
                return None
    return None
