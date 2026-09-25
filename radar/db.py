"""SQLite storage: opportunities (personal CRM), sources and scan history."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Iterator, Optional

import yaml

from .settings import DB_PATH, SOURCES_PATH, env
from .sources.base import Item
from .textutil import now_iso

STATUSES = ["New", "Saved", "Contacted", "Applied", "Won", "Rejected", "Archived"]
STATUS_FA = {
    "New": "جدید",
    "Saved": "ذخیره‌شده",
    "Contacted": "تماس گرفته‌شد",
    "Applied": "اپلای شد",
    "Won": "موفق",
    "Rejected": "رد شد",
    "Archived": "بایگانی",
}
CLOSED = ("Rejected", "Archived")

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT UNIQUE NOT NULL,
    fingerprint TEXT,
    title TEXT NOT NULL,
    company TEXT DEFAULT '',
    source TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    url TEXT DEFAULT '',
    location TEXT DEFAULT '',
    category TEXT DEFAULT '',
    job_type TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    posted_at TEXT,
    found_at TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    reasons TEXT DEFAULT '[]',
    status TEXT DEFAULT 'New',
    notes TEXT DEFAULT '',
    updated_at TEXT,
    reported INTEGER DEFAULT 0,
    synced INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_opp_fingerprint ON opportunities(fingerprint);
CREATE INDEX IF NOT EXISTS idx_opp_score ON opportunities(score);
CREATE INDEX IF NOT EXISTS idx_opp_found ON opportunities(found_at);
CREATE TABLE IF NOT EXISTS sources(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    target TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    last_run TEXT,
    last_count INTEGER,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS scans(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    fetched INTEGER DEFAULT 0,
    new INTEGER DEFAULT 0,
    high INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0
);
"""

_ready = False


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    global _ready
    con = _connect()
    try:
        con.executescript(SCHEMA)
        sync_sources_from_yaml(con)
        con.commit()
    finally:
        con.close()
    _ready = True


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    if not _ready:
        init_db()
    con = _connect()
    try:
        yield con
    finally:
        con.close()


def sync_sources_from_yaml(con: sqlite3.Connection) -> None:
    """Add sources from config/sources.yaml that are not in the DB yet.

    With RADAR_SOURCES_MODE=yaml (used by GitHub Actions) the `enabled` flag
    in the YAML file is also applied to existing sources.
    """
    if not SOURCES_PATH.exists():
        return
    data = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
    yaml_mode = env("RADAR_SOURCES_MODE").lower() == "yaml"
    for src in data.get("sources") or []:
        stype = str(src.get("type") or "").strip()
        target = str(src.get("target") or "").strip()
        if not stype:
            continue
        enabled = 1 if src.get("enabled", True) else 0
        row = con.execute("SELECT id FROM sources WHERE type=? AND target=?", (stype, target)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO sources(name, type, target, enabled) VALUES (?,?,?,?)",
                (str(src.get("name") or stype), stype, target, enabled),
            )
        elif yaml_mode:
            con.execute("UPDATE sources SET enabled=? WHERE id=?", (enabled, row["id"]))


def insert_opportunity(con, item: Item, result, status: str = "New", notes: str = "") -> Optional[int]:
    """Insert if unseen; returns new row id or None for duplicates."""
    uid = item.uid()
    if con.execute("SELECT 1 FROM opportunities WHERE uid=?", (uid,)).fetchone():
        return None
    fp = item.fingerprint()
    if fp and con.execute("SELECT 1 FROM opportunities WHERE fingerprint=?", (fp,)).fetchone():
        return None
    now = now_iso()
    cur = con.execute(
        """INSERT INTO opportunities(uid, fingerprint, title, company, source, source_type, url, location,
               category, job_type, salary, tags, description, posted_at, found_at, score, reasons,
               status, notes, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            uid, fp, item.title.strip()[:300], item.company or "", item.source, item.source_type,
            item.url or "", item.location or "", result.category, item.job_type or "", item.salary or "",
            json.dumps([t for t in item.tags if t], ensure_ascii=False), item.description or "",
            item.posted_at, now, result.score, json.dumps(result.reasons, ensure_ascii=False),
            status, notes, now,
        ),
    )
    return cur.lastrowid


def item_from_row(row) -> Item:
    try:
        tags = json.loads(row["tags"] or "[]")
    except ValueError:
        tags = []
    return Item(
        title=row["title"], url=row["url"], company=row["company"], location=row["location"],
        description=row["description"], posted_at=row["posted_at"], job_type=row["job_type"],
        salary=row["salary"], tags=tags, source=row["source"], source_type=row["source_type"],
    )


def opp_dict(row) -> dict:
    d = dict(row)
    try:
        d["reasons_list"] = json.loads(d.get("reasons") or "[]")
    except ValueError:
        d["reasons_list"] = []
    return d


def stats(con, min_score: int) -> dict:
    today = date.today().isoformat()
    one = lambda sql, *p: con.execute(sql, p).fetchone()[0]  # noqa: E731
    by_status = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM opportunities GROUP BY status")}
    return {
        "total": one("SELECT COUNT(*) FROM opportunities"),
        "new_today": one("SELECT COUNT(*) FROM opportunities WHERE substr(found_at,1,10)=?", today),
        "high": one(
            "SELECT COUNT(*) FROM opportunities WHERE score>=? AND status NOT IN (?,?)", min_score, *CLOSED
        ),
        "in_progress": by_status.get("Contacted", 0) + by_status.get("Applied", 0),
        "by_status": by_status,
    }
