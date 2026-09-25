"""Export opportunities as compact chunk documents for the Claude artifact dashboard."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import db as dbm

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


def item(row) -> dict:
    reasons = json.loads(row["reasons"] or "[]")
    return {
        "id": row["uid"][:16], "title": row["title"], "company": row["company"] or "", "location": row["location"] or "",
        "source": row["source"] or "", "url": row["url"] or "", "score": row["score"] or 0, "reasons": reasons[:8],
        "category": row["category"] or "", "type": row["opp_type"] or "", "remote": row["remote_type"] or "",
        "region": region(row), "salary": row["salary"] or "", "found": (row["found_at"] or "")[:19],
        "posted": (row["posted_at"] or "")[:19], "desc": re.sub(r"\s+", " ", row["description"] or "")[:320],
        "email": _email(row["description"] or ""),
    }


def export(out: Path, since: str = "", min_score: int = 35, chunk: int = 150) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    with dbm.get_db() as con:
        rows = con.execute("SELECT * FROM opportunities WHERE found_at > ? ORDER BY found_at", (since,)).fetchall()
        stats = dbm.stats(con, 55)
    items = [item(r) for r in rows]
    items = [i for i in items if i["score"] >= (20 if i["region"] == "iran" else min_score)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    files = []
    for n in range(0, len(items), chunk):
        path = out / f"c{stamp}-{n // chunk}.json"
        path.write_text(json.dumps({"created": stamp, "items": items[n:n + chunk]}, ensure_ascii=False), encoding="utf-8")
        files.append(str(path))
    meta = {"lastRun": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scannedToday": stats["scanned_today"],
            "newItems": len(items), "iran": sum(i["region"] == "iran" for i in items),
            "intl": sum(i["region"] == "intl" for i in items)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"files": files, "meta": str(out / "meta.json"), **meta}
