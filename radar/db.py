"""SQLite storage.

Tables: profile · sources · opportunities · matches · statuses · status_history ·
settings · email_logs · scans · discovered_sites
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Iterator, List, Optional, Tuple

from .settings import DB_PATH
from .sources.base import Item
from .textutil import now_iso

STATUSES = ["New", "Saved", "Contacted", "Applied", "Ignored", "Won", "Rejected"]
STATUS_FA = {
    "New": "جدید",
    "Saved": "ذخیره‌شده",
    "Contacted": "تماس گرفته‌شد",
    "Applied": "اپلای شد",
    "Ignored": "نادیده",
    "Won": "موفق",
    "Rejected": "رد شد",
}
CLOSED = ("Ignored", "Rejected")

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sources(
    id TEXT PRIMARY KEY,
    name TEXT, type TEXT, target TEXT, keywords TEXT DEFAULT '[]',
    frequency_hours INTEGER DEFAULT 24, enabled INTEGER DEFAULT 1, runner TEXT,
    last_run TEXT, last_count INTEGER, last_new INTEGER, last_error TEXT, total_found INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS opportunities(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT UNIQUE NOT NULL,
    fingerprint TEXT,
    title TEXT NOT NULL,
    company TEXT DEFAULT '',
    source TEXT DEFAULT '',
    source_id TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    url TEXT DEFAULT '',
    location TEXT DEFAULT '',
    category TEXT DEFAULT '',
    remote_type TEXT DEFAULT 'Unknown',
    opp_type TEXT DEFAULT 'Job',
    job_type TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    skills TEXT DEFAULT '[]',
    keywords TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    posted_at TEXT,
    found_at TEXT NOT NULL,
    last_seen_at TEXT,
    seen_count INTEGER DEFAULT 1,
    also_on TEXT DEFAULT '[]',
    origin TEXT DEFAULT 'local',
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
CREATE TABLE IF NOT EXISTS matches(
    opportunity_id INTEGER PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
    score INTEGER, skill_points INTEGER, keyword_points INTEGER, type_points INTEGER,
    location_points INTEGER, preference_points INTEGER, reasons TEXT, computed_at TEXT
);
CREATE TABLE IF NOT EXISTS statuses(
    name TEXT PRIMARY KEY, label_fa TEXT, position INTEGER
);
CREATE TABLE IF NOT EXISTS status_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER, status TEXT, note TEXT, changed_at TEXT
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS email_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT, local_date TEXT, channel TEXT, recipients TEXT, subject TEXT,
    items INTEGER, status TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS scans(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, finished_at TEXT, runner TEXT,
    fetched INTEGER DEFAULT 0, new INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
    high INTEGER DEFAULT 0, errors INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS discovered_sites(
    domain TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, hits INTEGER DEFAULT 1,
    sample_url TEXT, sample_title TEXT, dismissed INTEGER DEFAULT 0
);
"""

_OPP_COLUMNS = {
    "source_id": "TEXT DEFAULT ''", "remote_type": "TEXT DEFAULT 'Unknown'", "opp_type": "TEXT DEFAULT 'Job'",
    "skills": "TEXT DEFAULT '[]'", "keywords": "TEXT DEFAULT '[]'", "last_seen_at": "TEXT",
    "seen_count": "INTEGER DEFAULT 1", "also_on": "TEXT DEFAULT '[]'", "origin": "TEXT DEFAULT 'local'",
}

_ready = False


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _columns(con, table: str) -> List[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _migrate(con) -> None:
    """Upgrade a v1 database in place."""
    cols = _columns(con, "sources")
    if cols and "keywords" not in cols:
        con.execute("DROP TABLE sources")  # v1 kept sources in the DB; config now lives in YAML
    if _columns(con, "opportunities"):
        existing = _columns(con, "opportunities")
        for name, ddl in _OPP_COLUMNS.items():
            if name not in existing:
                con.execute(f"ALTER TABLE opportunities ADD COLUMN {name} {ddl}")
        con.execute("UPDATE opportunities SET status='Ignored' WHERE status='Archived'")
    scan_cols = _columns(con, "scans")
    for name, ddl in (("runner", "TEXT"), ("updated", "INTEGER DEFAULT 0")):
        if scan_cols and name not in scan_cols:
            con.execute(f"ALTER TABLE scans ADD COLUMN {name} {ddl}")


def init_db() -> None:
    global _ready
    con = _connect()
    try:
        _migrate(con)
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT OR REPLACE INTO statuses(name, label_fa, position) VALUES (?,?,?)",
            [(s, STATUS_FA[s], i) for i, s in enumerate(STATUSES)],
        )
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


def _j(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _load(value) -> list:
    try:
        return json.loads(value or "[]")
    except ValueError:
        return []


# ---------------------------------------------------------------- settings
def get_setting(con, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(con, key: str, value: str) -> None:
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (key, str(value)))
    con.commit()


def save_profile_snapshot(con, data: dict) -> None:
    con.execute("INSERT OR REPLACE INTO profile(id, data, updated_at) VALUES (1,?,?)",
                (json.dumps(data, ensure_ascii=False), now_iso()))
    con.commit()


# ----------------------------------------------------------------- sources
def sync_sources(con, sources) -> None:
    """Mirror YAML source config into the DB (runtime stats are kept)."""
    ids = []
    for s in sources:
        ids.append(s.id)
        con.execute(
            """INSERT INTO sources(id, name, type, target, keywords, frequency_hours, enabled, runner)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, type=excluded.type, target=excluded.target,
                   keywords=excluded.keywords, frequency_hours=excluded.frequency_hours,
                   enabled=excluded.enabled, runner=excluded.runner""",
            (s.id, s.name, s.type, s.target, _j(s.keywords), s.frequency_hours, int(s.enabled), s.runner),
        )
    if ids:
        con.execute(f"DELETE FROM sources WHERE id NOT IN ({','.join('?' * len(ids))})", ids)
    con.commit()


def source_runtime(con) -> dict:
    return {r["id"]: dict(r) for r in con.execute("SELECT * FROM sources")}


# ----------------------------------------------------------- opportunities
def upsert_opportunity(con, item: Item, result, *, source_id: str = "", origin: str = "local",
                       status: str = "New", notes: str = "", uid: Optional[str] = None) -> Tuple[str, Optional[int]]:
    """Insert a new opportunity or update the existing duplicate. Returns ('new'|'updated', id)."""
    now = now_iso()
    uid = uid or item.uid()
    fp = item.fingerprint()
    row = con.execute("SELECT * FROM opportunities WHERE uid=?", (uid,)).fetchone()
    if row is None and fp:
        row = con.execute("SELECT * FROM opportunities WHERE fingerprint=?", (fp,)).fetchone()

    if row is not None:
        also_on = _load(row["also_on"])
        if item.source and item.source != row["source"] and item.source not in also_on:
            also_on.append(item.source)
        richer = len(item.description or "") > len(row["description"] or "")
        fields = {
            "last_seen_at": now,
            "seen_count": (row["seen_count"] or 1) + 1,
            "also_on": _j(also_on),
            "salary": row["salary"] or item.salary or "",
            "posted_at": row["posted_at"] or item.posted_at,
            "location": row["location"] or item.location or "",
            "company": row["company"] or item.company or "",
        }
        if richer:
            fields.update(description=item.description, score=result.score, reasons=_j(result.reasons),
                          category=result.category, remote_type=result.remote_type, opp_type=result.opp_type,
                          skills=_j(result.skills), keywords=_j(result.keywords))
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE opportunities SET {sets} WHERE id=?", (*fields.values(), row["id"]))
        if richer:
            _save_match(con, row["id"], result)
        return "updated", row["id"]

    cur = con.execute(
        """INSERT INTO opportunities(uid, fingerprint, title, company, source, source_id, source_type, url,
               location, category, remote_type, opp_type, job_type, salary, tags, skills, keywords, description,
               posted_at, found_at, last_seen_at, origin, score, reasons, status, notes, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            uid, fp, item.title.strip()[:300], item.company or "", item.source, source_id, item.source_type,
            item.url or "", item.location or "", result.category, result.remote_type, result.opp_type,
            item.job_type or "", item.salary or "", _j([t for t in item.tags if t]), _j(result.skills),
            _j(result.keywords), item.description or "", item.posted_at, now, now, origin, result.score,
            _j(result.reasons), status, notes, now,
        ),
    )
    _save_match(con, cur.lastrowid, result)
    return "new", cur.lastrowid


def _save_match(con, oid: int, result) -> None:
    bd = result.breakdown or {}
    con.execute(
        """INSERT OR REPLACE INTO matches(opportunity_id, score, skill_points, keyword_points, type_points,
               location_points, preference_points, reasons, computed_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (oid, result.score, bd.get("skills", 0), bd.get("keywords", 0), bd.get("type", 0),
         bd.get("location", 0), bd.get("preference", 0), _j(result.reasons), now_iso()),
    )


def update_score(con, oid: int, result) -> None:
    con.execute(
        "UPDATE opportunities SET score=?, reasons=?, category=?, remote_type=?, opp_type=?, skills=?, keywords=? "
        "WHERE id=?",
        (result.score, _j(result.reasons), result.category, result.remote_type, result.opp_type,
         _j(result.skills), _j(result.keywords), oid),
    )
    _save_match(con, oid, result)


def set_status(con, oid: int, status: str, note: str = "") -> None:
    now = now_iso()
    con.execute("UPDATE opportunities SET status=?, updated_at=? WHERE id=?", (status, now, oid))
    con.execute("INSERT INTO status_history(opportunity_id, status, note, changed_at) VALUES (?,?,?,?)",
                (oid, status, note, now))
    con.commit()


def item_from_row(row) -> Item:
    return Item(
        title=row["title"], url=row["url"], company=row["company"], location=row["location"],
        description=row["description"], posted_at=row["posted_at"], job_type=row["job_type"],
        salary=row["salary"], tags=_load(row["tags"]), source=row["source"], source_type=row["source_type"],
    )


def opp_dict(row) -> dict:
    d = dict(row)
    for key in ("reasons", "skills", "keywords", "also_on", "tags"):
        d[f"{key}_list"] = _load(d.get(key))
    return d


def record_discovery(con, url: str, title: str) -> None:
    from urllib.parse import urlparse

    domain = urlparse(url or "").netloc.lower().replace("www.", "")
    if not domain:
        return
    now = now_iso()
    con.execute(
        """INSERT INTO discovered_sites(domain, first_seen, last_seen, hits, sample_url, sample_title)
           VALUES (?,?,?,1,?,?)
           ON CONFLICT(domain) DO UPDATE SET last_seen=excluded.last_seen, hits=hits+1""",
        (domain, now, now, url, title[:200]),
    )


# ------------------------------------------------------------------- stats
def stats(con, min_score: int) -> dict:
    today = date.today().isoformat()
    one = lambda sql, *p: con.execute(sql, p).fetchone()[0]  # noqa: E731
    by_status = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM opportunities GROUP BY status")}
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    best = [dict(r) for r in con.execute(
        """SELECT source, COUNT(*) AS total, SUM(score >= ?) AS strong, ROUND(AVG(score)) AS avg_score
           FROM opportunities WHERE found_at >= ? GROUP BY source
           ORDER BY strong DESC, avg_score DESC LIMIT 6""", (min_score, since))]
    return {
        "total": one("SELECT COUNT(*) FROM opportunities"),
        "scanned_today": one("SELECT COALESCE(SUM(fetched),0) FROM scans WHERE substr(started_at,1,10)=?", today),
        "new_today": one("SELECT COUNT(*) FROM opportunities WHERE substr(found_at,1,10)=?", today),
        "high": one("SELECT COUNT(*) FROM opportunities WHERE score>=? AND status NOT IN (?,?)", min_score, *CLOSED),
        "high_today": one("SELECT COUNT(*) FROM opportunities WHERE score>=? AND substr(found_at,1,10)=?",
                          min_score, today),
        "saved": by_status.get("Saved", 0),
        "applied": by_status.get("Applied", 0),
        "contacted": by_status.get("Contacted", 0),
        "won": by_status.get("Won", 0),
        "by_status": by_status,
        "best_sources": best,
    }


# ---------------------------------------------------------------- sync I/O
def export_items(con, since_iso: str, origin: Optional[str] = None) -> List[dict]:
    sql = "SELECT * FROM opportunities WHERE found_at >= ?"
    params: list = [since_iso]
    if origin:
        sql += " AND origin = ?"
        params.append(origin)
    sql += " ORDER BY id"
    keys = ("title", "url", "company", "location", "description", "posted_at", "job_type", "salary",
            "source", "source_type", "source_id", "found_at")
    out = []
    for r in con.execute(sql, params):
        d = {k: r[k] for k in keys}
        d["tags"] = _load(r["tags"])
        d["uid"] = r["uid"]
        out.append(d)
    return out


def export_status_updates(con, since_iso: str) -> dict:
    return {r["uid"]: r["status"] for r in con.execute(
        "SELECT uid, status FROM opportunities WHERE status != 'New' AND updated_at >= ?", (since_iso,))}


def apply_status_updates(con, updates: dict) -> int:
    changed = 0
    for uid, status in (updates or {}).items():
        if status in STATUSES:
            changed += con.execute("UPDATE opportunities SET status=? WHERE uid=? AND status != ?",
                                   (status, uid, status)).rowcount
    con.commit()
    return changed
