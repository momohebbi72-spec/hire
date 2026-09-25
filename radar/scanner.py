"""Scan pipeline: sources → collect → normalise → de-duplicate → score → store."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, List, Optional

from . import db as dbm
from . import sync
from .config_store import effective_runner, load_sources, read_profile_data
from .profile import compile_term, load_profile
from .scoring import score_item
from .settings import runner
from .sources import FETCHERS, SourceConfig
from .textutil import normalize, now_iso, parse_iso


def _fetch(src: SourceConfig, limit: int):
    stype = FETCHERS.get(src.type)
    if stype is None:
        return src, [], f"Unknown source type: {src.type}"
    if not stype.available:
        return src, [], "این کانکتور هنوز فعال نیست (آماده برای اتصال در آینده)"
    try:
        return src, stype.fetch(src, limit), None
    except Exception as exc:  # one broken source must not stop the scan
        return src, [], friendly_error(exc)


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    if name in ("ReadTimeout", "ConnectTimeout", "Timeout"):
        return "سایت در ۴۵ ثانیه جواب نداد (دو بار امتحان شد). اگر VPN روشن است خاموشش کن و دوباره اسکن کن."
    if name in ("ConnectionError", "SSLError", "ProxyError"):
        return "اتصال به سایت برقرار نشد — اینترنت/VPN را بررسی کن (سایت‌های ایرانی فقط با IP ایران باز می‌شوند)."
    if name == "HTTPError" and " 403 " in f" {exc} ":
        return "سایت دسترسی را بست (403) — احتمالا به‌خاطر VPN یا IP خارج از ایران."
    return f"{name}: {exc}"[:300]


def runs_here(src: SourceConfig) -> bool:
    """Iranian sites only work from an Iranian IP (Mac); LinkedIn/Telegram only from abroad (GitHub).

    Without GitHub sync everything runs on this machine.
    """
    where = effective_runner(src)
    if where == "both" or not sync.configured():
        return True
    return where == runner()


def is_due(src: SourceConfig, runtime: dict, now: datetime) -> bool:
    if not src.enabled or src.frequency_hours <= 0:
        return False
    last = parse_iso((runtime.get(src.id) or {}).get("last_run"))
    return last is None or now - last >= timedelta(hours=src.frequency_hours) - timedelta(minutes=10)


def _keyword_filter(src: SourceConfig, items):
    stype = FETCHERS.get(src.type)
    if not src.keywords or not stype or stype.keyword_mode != "filter":
        return items
    pats = [p for p in (compile_term(k) for k in src.keywords) if p]
    return [it for it in items if any(p.search(normalize(it.text())) for p in pats)]


def select_sources(source_ids: Optional[Iterable[str]] = None, due_only: bool = False) -> List[SourceConfig]:
    sources = load_sources()
    with dbm.get_db() as con:
        dbm.sync_sources(con, sources)
        runtime = dbm.source_runtime(con)
    if source_ids is not None:
        wanted = set(source_ids)
        return [s for s in sources if s.id in wanted]  # explicit test: run even if disabled / other runner
    now = datetime.now(timezone.utc)
    chosen = [s for s in sources if s.enabled and runs_here(s)]
    return [s for s in chosen if is_due(s, runtime, now)] if due_only else chosen


def run_scan(source_ids: Optional[Iterable[str]] = None, due_only: bool = False,
             log: Callable[[str], None] = print) -> dict:
    profile = load_profile()
    cutoff = datetime.now(timezone.utc) - timedelta(days=profile.max_age_days)
    sources = select_sources(source_ids, due_only)
    summary = {"fetched": 0, "new": 0, "updated": 0, "high": 0, "errors": 0, "sources": []}
    if not sources:
        log("No sources due.")
        return summary

    with dbm.get_db() as con:
        dbm.save_profile_snapshot(con, read_profile_data())
        scan_id = con.execute("INSERT INTO scans(started_at, runner) VALUES (?,?)", (now_iso(), runner())).lastrowid
        con.commit()

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(_fetch, src, profile.per_source_limit) for src in sources]
            for future in as_completed(futures):
                src, items, error = future.result()
                items = _keyword_filter(src, items)
                new_here = 0
                for item in items:
                    if not item.title:
                        continue
                    posted = parse_iso(item.posted_at)
                    if posted and posted < cutoff:
                        continue
                    item.source = src.name
                    item.source_type = src.type
                    summary["fetched"] += 1
                    if src.type in ("websearch", "site_search", "linkedin_posts", "instagram"):
                        dbm.record_discovery(con, item.url, item.title)
                    result = score_item(item, profile)
                    kind, _ = dbm.upsert_opportunity(con, item, result, source_id=src.id, origin=runner())
                    if kind == "new":
                        new_here += 1
                        summary["high"] += result.score >= profile.min_score
                    else:
                        summary["updated"] += 1
                summary["new"] += new_here
                summary["errors"] += bool(error)
                con.execute(
                    "UPDATE sources SET last_run=?, last_count=?, last_new=?, last_error=?, "
                    "total_found=COALESCE(total_found,0)+? WHERE id=?",
                    (now_iso(), len(items), new_here, error, new_here, src.id),
                )
                con.commit()
                summary["sources"].append({"name": src.name, "items": len(items), "new": new_here, "error": error})
                log(f"  {'✗' if error else '✓'} {src.name}: {len(items)} items, {new_here} new"
                    + (f" — {error}" if error else ""))

        con.execute(
            "UPDATE scans SET finished_at=?, fetched=?, new=?, updated=?, high=?, errors=? WHERE id=?",
            (now_iso(), summary["fetched"], summary["new"], summary["updated"], summary["high"],
             summary["errors"], scan_id),
        )
        con.commit()
    log(f"Scan done: {summary['fetched']} checked, {summary['new']} new, {summary['updated']} duplicates merged, "
        f"{summary['high']} strong matches, {summary['errors']} errors")
    return summary


def rescore_all() -> int:
    """Re-apply the current profile to every stored opportunity."""
    profile = load_profile()
    with dbm.get_db() as con:
        rows = con.execute("SELECT * FROM opportunities").fetchall()
        for row in rows:
            dbm.update_score(con, row["id"], score_item(dbm.item_from_row(row), profile))
        con.commit()
    return len(rows)
