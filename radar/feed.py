"""Export opportunities as compact chunk documents for the Claude artifact dashboard.

Every item carries its page (`ch`: iran / linkedin / social / intl), its tier
(match / review — drops are never exported) and the facets the checkbox filters use.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from . import db as dbm
from .tiers import Classifier, channel_of

_FA = re.compile(r"[؀-ۿ]")
IRAN_HOSTS = ("jobinja.ir", "jobvision.ir", "ponisha.ir", "karlancer.com", "parscoders.com", "e-estekhdam.com",
              "iranestekhdam.ir", "karbord.io", "kardix.com", "karpishe.com", "divar.ir", "jobteam.ir", "lancerify.com")


def region(row) -> str:
    text = f"{row['title']} {row['description'] or ''}"[:600]
    loc = (row["location"] or "").lower()
    host = urlparse(row["url"] or "").netloc.lower()
    if _FA.search(text) or "iran" in loc or "ایران" in loc or "تهران" in loc or host.endswith(".ir") \
            or any(h in host for h in IRAN_HOSTS):
        return "iran"
    return "intl"


def _email(text: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text or "")
    return m.group(0) if m else ""


def item(row, clf: Optional[Classifier] = None) -> Dict:
    clf = clf or Classifier()
    reasons = json.loads(row["reasons"] or "[]")
    tier = clf.classify(row["title"], row["description"] or "", row["url"] or "", row["posted_at"] or "",
                        row["remote_type"] or "", row["opp_type"] or "", row["source_type"] or "", row["found_at"] or "")
    host = urlparse(row["url"] or "").netloc.lower().replace("www.", "")
    return {
        "id": row["uid"][:16], "title": row["title"], "company": row["company"] or "", "location": row["location"] or "",
        "source": row["source"] or "", "host": host, "url": row["url"] or "", "score": row["score"] or 0,
        "reasons": reasons[:6], "type": row["opp_type"] or "", "rh": row["remote_type"] or "", "region": region(row),
        "ch": channel_of(row["source_type"] or "", row["url"] or ""),
        "tier": tier["tier"], "why": tier["why"], "role": tier["role"], "mode": tier["mode"],
        "pt": tier["parttime"], "lvl": tier["level"], "fresh": tier["fresh"], "age": tier.get("age_days"),
        "approx": tier.get("approx", False), "st": row["source_type"] or "",
        "salary": row["salary"] or "", "found": (row["found_at"] or "")[:19], "posted": (row["posted_at"] or "")[:19],
        "desc": re.sub(r"\s+", " ", row["description"] or "")[:420], "email": _email(row["description"] or ""),
    }


def export(out: Path, since: str = "", min_score: int = 0, chunk: int = 150, days: int = 7,
           rules: Optional[Dict] = None) -> dict:
    """Writes chunk files with every non-dropped item of the last `days` days."""
    out.mkdir(parents=True, exist_ok=True)
    clf = Classifier(rules)
    floor = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    since = max(since or "", floor)
    with dbm.get_db() as con:
        rows = con.execute("SELECT * FROM opportunities WHERE found_at > ? ORDER BY found_at", (since,)).fetchall()
        stats = dbm.stats(con, 55)
        from .config_store import load_sources

        dbm.sync_sources(con, load_sources())  # the status list follows the current source settings
        src_rows = con.execute("SELECT id, name, type, enabled, last_run, last_count, last_new, last_error FROM sources "
                               "WHERE last_run IS NOT NULL AND enabled = 1 ORDER BY name").fetchall()
    items = [item(r, clf) for r in rows]
    items = [i for i in items if i["tier"] != "drop" and i["score"] >= min_score]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    files = []
    for n in range(0, len(items), chunk):
        path = out / f"c{stamp}-{n // chunk}.json"
        path.write_text(json.dumps({"created": stamp, "items": items[n:n + chunk]}, ensure_ascii=False), encoding="utf-8")
        files.append(str(path))
    count = lambda **kw: sum(all(i[k] == v for k, v in kw.items()) for i in items)  # noqa: E731
    meta = {"lastRun": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scannedToday": stats["scanned_today"],
            "newItems": len(items), "match": count(tier="match"), "review": count(tier="review"),
            "iran": count(ch="iran"), "linkedin": count(ch="linkedin"), "social": count(ch="social"),
            "intl": count(ch="intl"), "days": days,
            "sources": [{"id": r[0], "name": r[1], "type": r[2], "on": bool(r[3]), "at": r[4], "n": r[5] or 0,
                         "new": r[6] or 0, "err": r[7] or ""} for r in src_rows]}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"files": files, "meta": str(out / "meta.json"), **meta}
