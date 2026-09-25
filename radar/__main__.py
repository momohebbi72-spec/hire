"""CLI:  python -m radar [serve|tick|scan|report|sheet|sync|rescore|daily]"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import db as dbm


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="radar", description="Personal Opportunity Radar")
    sub = parser.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="run the local dashboard (default)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    serve.add_argument("--no-browser", action="store_true")

    tick = sub.add_parser("tick", help="do everything that is due: sync, scan, sheet, report (for schedulers)")
    tick.add_argument("--force", action="store_true", help="scan all sources and send the report now")
    sub.add_parser("daily", help="same as: tick --force")

    scan = sub.add_parser("scan", help="scan sources")
    scan.add_argument("--source", action="append", help="source id (repeatable); default = all enabled here")
    scan.add_argument("--due", action="store_true", help="only sources whose frequency is due")

    report = sub.add_parser("report", help="send the e-mail / Telegram report now (+ Excel)")
    report.add_argument("--all", action="store_true", help="include already-reported matches")
    report.add_argument("--no-mark", action="store_true", help="do not mark items as reported")

    sub.add_parser("sheet", help="push new matches to Google Sheets")
    sync_p = sub.add_parser("sync", help="GitHub sync")
    sync_p.add_argument("action", choices=["pull", "push", "config-push", "config-pull"])
    sub.add_parser("rescore", help="re-score all stored opportunities with the current profile")
    imp = sub.add_parser("import-json", help="import opportunities from a JSON list (e.g. collected by an assistant)")
    imp.add_argument("path")
    imp.add_argument("--source", default="Web search")

    args = parser.parse_args(argv)
    if args.cmd is None:
        args = parser.parse_args(["serve"])
    dbm.init_db()

    if args.cmd == "serve":
        from .web import main as serve_main

        serve_main(args.host, args.port, open_browser=not args.no_browser)
        return 0
    if args.cmd in ("tick", "daily"):
        from .scheduler import tick as run_tick

        out = run_tick(force=args.cmd == "daily" or args.force)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.cmd == "scan":
        from .scanner import run_scan

        run_scan(source_ids=args.source, due_only=args.due)
        return 0
    if args.cmd == "report":
        from .report import deliver_report

        out = deliver_report(mark=not args.no_mark, include_reported=args.all)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "sheet":
        from .exporters import sync_google_sheet
        from .profile import load_profile

        with dbm.get_db() as con:
            print("Google Sheet:", sync_google_sheet(con, load_profile().min_score))
        return 0
    if args.cmd == "sync":
        from . import sync

        fn = {"pull": sync.pull_items, "push": sync.push_items, "config-push": sync.push_config,
              "config-pull": sync.pull_config}[args.action]
        print(fn())
        return 0
    if args.cmd == "import-json":
        from .profile import load_profile
        from .scoring import score_item
        from .sources.base import Item

        rows = json.load(open(args.path, encoding="utf-8"))
        profile = load_profile()
        counts = {"new": 0, "updated": 0}
        with dbm.get_db() as con:
            for r in rows:
                if not r.get("title"):
                    continue
                item = Item(title=r["title"], url=r.get("url", ""), company=r.get("company", ""),
                            location=r.get("location", ""), description=r.get("description", ""),
                            posted_at=r.get("posted_at"), job_type=r.get("job_type", ""),
                            source=r.get("source") or args.source, source_type=r.get("source_type") or "websearch",
                            external_id=r.get("url") or r["title"])
                kind, _ = dbm.upsert_opportunity(con, item, score_item(item, profile),
                                                 source_id=r.get("source_id", "assistant"), origin="cloud")
                counts[kind] += 1
                if item.url:
                    dbm.record_discovery(con, item.url, item.title)
            con.commit()
        print(json.dumps(counts))
        return 0
    if args.cmd == "rescore":
        from .scanner import rescore_all

        print(f"Re-scored {rescore_all()} opportunities")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
