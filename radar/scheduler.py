"""Scheduler: one `tick()` does everything that is due.

Called by:
  • the dashboard's background thread (every 5 minutes while it is open)
  • launchd on the Mac (hourly, even when the dashboard is closed)
  • GitHub Actions (hourly cron)

Order: pull other side → scan due sources → push results → Google Sheet → report if due.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from . import db as dbm
from . import sync
from .config_store import load_settings
from .exporters import sync_google_sheet
from .profile import load_profile
from .report import deliver_report, report_due
from .scanner import run_scan
from .settings import DATA_DIR, runner

_lock = threading.Lock()


class _FileLock:
    """Cross-process lock so launchd and the dashboard never tick at the same time."""

    def __init__(self, path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            import fcntl

            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # Windows: best effort
            pass
        except OSError:
            self.fh.close()
            raise RuntimeError("another tick is running")
        return self

    def __exit__(self, *exc):
        self.fh.close()


def tick(force: bool = False, log: Callable[[str], None] = print) -> dict:
    out = {"runner": runner()}
    if not _lock.acquire(blocking=False):
        return {"skipped": "tick already running"}
    try:
        with _FileLock(DATA_DIR / ".tick.lock"):
            if sync.configured():
                out["pull"] = _safe(sync.pull_items)
                log(f"sync pull: {out['pull']}")
            summary = run_scan(due_only=not force, log=log)
            out["scan"] = {k: summary[k] for k in ("fetched", "new", "updated", "high", "errors")}
            if sync.configured() and (summary["sources"] or runner() == "local"):
                out["push"] = _safe(sync.push_items)
                log(f"sync push: {out['push']}")
            sender = str(load_settings()["report"].get("sender") or "cloud")
            if sender == runner() or not sync.configured():
                with dbm.get_db() as con:
                    out["sheet"] = _safe(sync_google_sheet, con, load_profile().min_score)
                    due = force or report_due(con)
                log(f"google sheet: {out['sheet']}")
                if due:
                    out["report"] = deliver_report()
                    log(f"report: {out['report']}")
    except RuntimeError as exc:
        out["skipped"] = str(exc)
    finally:
        _lock.release()
    return out


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"[:300]


class BackgroundScheduler(threading.Thread):
    """Runs tick() every `interval` seconds inside the dashboard process."""

    def __init__(self, interval: int = 300):
        super().__init__(daemon=True)
        self.interval = interval
        self.last: Optional[dict] = None

    def enabled(self) -> bool:
        with dbm.get_db() as con:
            return dbm.get_setting(con, "scheduler_enabled", "1") == "1"

    def run(self):
        time.sleep(20)
        while True:
            if self.enabled() and os.environ.get("RADAR_DISABLE_SCHEDULER") != "1":
                self.last = tick(log=lambda msg: None)
            time.sleep(self.interval)
