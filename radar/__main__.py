"""CLI:  python -m radar [serve|scan|report|sheet|daily|rescore]"""
from __future__ import annotations

import argparse
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

    scan = sub.add_parser("scan", help="fetch all enabled sources")
    scan.add_argument("--report", action="store_true", help="send the report afterwards")

    report = sub.add_parser("report", help="send e-mail / Telegram report (+ Excel)")
    report.add_argument("--all", action="store_true", help="include already-reported matches")
    report.add_argument("--no-mark", action="store_true", help="do not mark items as reported")

    sub.add_parser("sheet", help="push new matches to Google Sheets")
    sub.add_parser("daily", help="scan + report + sheet (for cron / GitHub Actions)")
    sub.add_parser("rescore", help="re-score all stored opportunities with the current profile")

    args = parser.parse_args(argv)
    if args.cmd is None:
        args = parser.parse_args(["serve"])

    dbm.init_db()

    if args.cmd == "serve":
        from .web import main as serve_main

        serve_main(args.host, args.port, open_browser=not args.no_browser)
        return 0

    if args.cmd == "rescore":
        from .scanner import rescore_all

        print(f"Re-scored {rescore_all()} opportunities")
        return 0

    if args.cmd == "sheet":
        from .exporters import sync_google_sheet
        from .profile import load_profile

        with dbm.get_db() as con:
            print("Google Sheet:", sync_google_sheet(con, load_profile().min_score))
        return 0

    from .report import deliver_report
    from .scanner import run_scan

    if args.cmd in ("scan", "daily"):
        summary = run_scan()
        if summary["sources"] and summary["errors"] == len(summary["sources"]):
            print("All sources failed — check network access.", file=sys.stderr)
        if args.cmd == "scan" and not args.report:
            return 0

    if args.cmd == "report":
        out = deliver_report(mark=not args.no_mark, include_reported=args.all, sheet=False)
    else:
        out = deliver_report(sheet=args.cmd == "daily")
    print(f"Report: {out['matches']} matches → {out['xlsx']}")
    for channel, result in out["results"].items():
        print(f"  {channel}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
