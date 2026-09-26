"""CLI: python -m geo_cards <command>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
from .settings import load_config, load_questions


def _by_id(questions: list) -> dict:
    return {int(q["id"]): q for q in questions if q.get("id") is not None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m geo_cards",
                                     description="سؤال از هوش مصنوعی، شمارش اسم‌ها و ساخت پست آماده‌ی انتشار")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="فهرست سؤال‌ها")

    run = sub.add_parser("run", help="یک سؤال: پرسیدن، طراحی و خروجی")
    run.add_argument("--id", type=int, help="شماره‌ی سؤال در questions.yaml")
    run.add_argument("--q", help="متن سؤال دلخواه")
    run.add_argument("--category", default="business", help="medical | business | education | local")
    run.add_argument("--city", default="")
    run.add_argument("--runs", type=int, help="تعداد تکرار؛ پیش‌فرض از config.yaml")
    run.add_argument("--import", dest="import_path", help="فایل جواب‌ها (json یا txt) به‌جای API")
    run.add_argument("--music", help="فایل آهنگ برای ریلز (اختیاری)")

    week = sub.add_parser("week", help="چند سؤال پشت سر هم")
    week.add_argument("--start", type=int, required=True)
    week.add_argument("--count", type=int, default=7)
    week.add_argument("--music")

    again = sub.add_parser("render", help="ساخت دوباره‌ی تصویرها و متن‌ها از data.json")
    again.add_argument("folder")
    again.add_argument("--music")

    summary = sub.add_parser("roundup", help="گزارش جمع‌بندی برای ویرگول و خبرنامه‌ی لینکدین")
    summary.add_argument("--since", help="از این تاریخ میلادی، مثلا 2026-10-01")

    args = parser.parse_args(argv)
    config = load_config()
    try:
        if args.cmd == "list":
            for question in load_questions():
                print(f"{question['id']:>3}  {question.get('category', ''):<9}  {question['text']}")
        elif args.cmd == "run":
            if args.id:
                question = _by_id(load_questions()).get(args.id)
                if not question:
                    parser.error(f"سؤال {args.id} در questions.yaml نیست")
                question = dict(question)
            elif args.q:
                question = {"text": args.q, "category": args.category, "city": args.city}
            else:
                parser.error("--id یا --q لازم است")
            if args.runs:
                question["runs"] = args.runs
            folder = pipeline.run_question(question, config, import_path=args.import_path, music=args.music)
            print(f"\n✓ آماده است: {folder}")
        elif args.cmd == "week":
            questions = _by_id(load_questions())
            for qid in range(args.start, args.start + args.count):
                if qid not in questions:
                    print(f"– سؤال {qid} نیست")
                    continue
                try:
                    folder = pipeline.run_question(dict(questions[qid]), config, music=args.music)
                    print(f"✓ {qid}: {folder}")
                except Exception as exc:
                    print(f"✗ {qid}: {exc}")
        elif args.cmd == "render":
            pipeline.rerender(Path(args.folder), config, music=args.music)
            print("✓ دوباره ساخته شد")
        elif args.cmd == "roundup":
            print(f"✓ {pipeline.roundup(config, since=args.since)}")
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
