"""Fetch every enabled source, score items and store the new ones."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from . import db as dbm
from .profile import load_profile
from .scoring import score_item
from .sources import FETCHERS
from .textutil import now_iso, parse_iso


def _fetch(src: dict, limit: int):
    stype = FETCHERS.get(src["type"])
    if stype is None:
        return src, [], f"Unknown source type: {src['type']}"
    try:
        return src, stype.fetch(src["target"] or "", limit), None
    except Exception as exc:  # one broken source must not stop the scan
        return src, [], f"{type(exc).__name__}: {exc}"[:300]


def run_scan(source_ids: Optional[Iterable[int]] = None, log: Callable[[str], None] = print) -> dict:
    profile = load_profile()
    cutoff = datetime.now(timezone.utc) - timedelta(days=profile.max_age_days)
    summary = {"fetched": 0, "new": 0, "high": 0, "errors": 0, "sources": []}

    with dbm.get_db() as con:
        started = now_iso()
        scan_id = con.execute("INSERT INTO scans(started_at) VALUES (?)", (started,)).lastrowid
        con.commit()

        rows = [dict(r) for r in con.execute("SELECT * FROM sources WHERE enabled=1 ORDER BY id")]
        if source_ids is not None:
            wanted = {int(i) for i in source_ids}
            rows = [dict(r) for r in con.execute("SELECT * FROM sources ORDER BY id") if r["id"] in wanted]

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_fetch, src, profile.per_source_limit) for src in rows]
            for future in as_completed(futures):
                src, items, error = future.result()
                new_here = 0
                for item in items:
                    if not item.title:
                        continue
                    posted = parse_iso(item.posted_at)
                    if posted and posted < cutoff:
                        continue
                    item.source = src["name"]
                    item.source_type = src["type"]
                    summary["fetched"] += 1
                    result = score_item(item, profile)
                    if dbm.insert_opportunity(con, item, result):
                        new_here += 1
                        if result.score >= profile.min_score:
                            summary["high"] += 1
                summary["new"] += new_here
                if error:
                    summary["errors"] += 1
                con.execute(
                    "UPDATE sources SET last_run=?, last_count=?, last_error=? WHERE id=?",
                    (now_iso(), len(items), error, src["id"]),
                )
                con.commit()
                summary["sources"].append({"name": src["name"], "items": len(items), "new": new_here, "error": error})
                log(f"  {'✗' if error else '✓'} {src['name']}: {len(items)} items, {new_here} new" + (f" — {error}" if error else ""))

        con.execute(
            "UPDATE scans SET finished_at=?, fetched=?, new=?, high=?, errors=? WHERE id=?",
            (now_iso(), summary["fetched"], summary["new"], summary["high"], summary["errors"], scan_id),
        )
        con.commit()
    log(f"Scan done: {summary['fetched']} checked, {summary['new']} new, {summary['high']} good matches, {summary['errors']} errors")
    return summary


def rescore_all() -> int:
    """Re-apply the current profile to every stored opportunity."""
    profile = load_profile()
    with dbm.get_db() as con:
        rows = con.execute("SELECT * FROM opportunities").fetchall()
        for row in rows:
            result = score_item(dbm.item_from_row(row), profile)
            con.execute(
                "UPDATE opportunities SET score=?, reasons=?, category=? WHERE id=?",
                (result.score, json.dumps(result.reasons, ensure_ascii=False), result.category, row["id"]),
            )
        con.commit()
    return len(rows)
