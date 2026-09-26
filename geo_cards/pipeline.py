"""Ask → find names → count → save data.json → slides, reel and texts."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import design, engines, extract, render, texts
from .jalali import jalali_label
from .settings import OUTPUT_DIR


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.replace("‌", " ")).strip()
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:limit].strip("-") or "question"


def next_number() -> int:
    """Running number of the series (سؤال روز #N)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "series.json"
    last = 0
    if path.exists():
        try:
            last = int(json.loads(path.read_text(encoding="utf-8")).get("last", 0))
        except (ValueError, json.JSONDecodeError):
            last = 0
    path.write_text(json.dumps({"last": last + 1}), encoding="utf-8")
    return last + 1


def _search_mode(answers: list):
    modes = {answer.web_search for answer in answers}
    return modes.pop() if len(modes) == 1 else False


def ask(question: dict, config: dict, *, import_path=None, log=print) -> list:
    if import_path:
        answers = engines.load_imported(Path(import_path))
        log(f"{len(answers)} جواب از فایل خوانده شد")
    else:
        runs = int(question.get("runs") or config.get("runs") or 10)
        answers = engines.ask_all(question["text"], config, runs, log=log)
    if not answers:
        raise RuntimeError("هیچ جوابی به دست نیامد.")
    return answers


def build_data(question: dict, answers: list, config: dict, number: int, log=print) -> dict:
    names = extract.extract_all(question["text"], answers, config, log=log)
    groups = {}
    for answer, found in zip(answers, names):
        groups.setdefault(answer.label, []).append((answer, found))
    results = []
    for label, pairs in groups.items():
        group_answers = [answer for answer, _ in pairs]
        results.append({
            "label": label,
            "model": group_answers[0].model,
            "web_search": _search_mode(group_answers),
            "runs": len(pairs),
            "entities": extract.aggregate([found for _, found in pairs]),
            "sources": extract.aggregate_sources(group_answers),
        })
    category_name = question.get("category") or "business"
    category = (config.get("categories") or {}).get(category_name) or {}
    today = date.today()
    return {
        "id": question.get("id"),
        "number": number,
        "question": question["text"],
        "category": category_name,
        "city": question.get("city") or "",
        "mask_names": bool(question.get("mask", category.get("mask_names", False))),
        "date": today.isoformat(),
        "date_fa": jalali_label(today),
        "results": results,
        "sources_all": extract.aggregate_sources(answers),
        "answers": [dict(asdict(answer), names=found) for answer, found in zip(answers, names)],
    }


def build_outputs(folder: Path, data: dict, config: dict, *, music=None, log=print) -> None:
    feed_size, story_size = design.SIZES["feed"], design.SIZES["story"]
    jobs = [(page, folder / "post" / f"{name}.png", feed_size)
            for name, page in design.build_slides(data, config, "feed")]
    story = [(page, folder / "story" / f"{name}.png", story_size)
             for name, page in design.build_slides(data, config, "story")]
    jobs += story
    if data.get("mask_names"):
        # unblurred results, only for sending privately to the people in them
        jobs += [(page, folder / "private" / f"{name}.png", feed_size)
                 for name, page in design.build_slides(data, config, "feed", mask=False) if "results" in name]
    log("ساخت تصویرها…")
    render.render_pngs(jobs, renderer=config.get("renderer") or "auto", log=log)
    (folder / "caption.txt").write_text(texts.instagram_caption(data, config), encoding="utf-8")
    (folder / "linkedin.txt").write_text(texts.linkedin_post(data, config), encoding="utf-8")
    (folder / "virgool.md").write_text(texts.virgool_post(data, config), encoding="utf-8")
    seconds = float(config.get("reel_seconds_per_slide") or 3)
    if render.make_reel([png for _, png, _ in story], folder / "reel.mp4", seconds, music, log=log):
        log("✓ ریلز ساخته شد")


def run_question(question: dict, config: dict, *, import_path=None, music=None, log=print) -> Path:
    answers = ask(question, config, import_path=import_path, log=log)
    number = next_number()
    data = build_data(question, answers, config, number, log=log)
    folder = OUTPUT_DIR / f"{data['date']}-{number:03d}-{slugify(question['text'])}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    build_outputs(folder, data, config, music=music, log=log)
    return folder


def rerender(folder: Path, config: dict, *, music=None, log=print) -> None:
    """After editing data.json (a wrong name, a merge) or the design, rebuild without asking again."""
    folder = folder.expanduser().resolve()
    data = json.loads((folder / "data.json").read_text(encoding="utf-8"))
    build_outputs(folder, data, config, music=music, log=log)


def roundup(config: dict, since=None) -> Path:
    items = []
    for path in sorted(OUTPUT_DIR.glob("*/data.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if since and data.get("date", "") < since:
            continue
        items.append(data)
    if not items:
        raise RuntimeError("هنوز هیچ خروجی‌ای برای جمع‌بندی نیست.")
    items.sort(key=lambda d: d.get("number") or 0)
    out = OUTPUT_DIR / f"roundup-{date.today().isoformat()}.md"
    out.write_text(texts.roundup(items, config), encoding="utf-8")
    return out
