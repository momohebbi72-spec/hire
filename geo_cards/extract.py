"""Find the names each answer recommends, merge spelling variants, count presence."""
from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from urllib.parse import urlparse

from . import engines
from .settings import env

PROMPT = (
    "Below is an AI assistant's answer to a user's question.\n"
    "List every specific entity the answer names as a recommendation or option for the question: "
    "people (doctors, consultants, teachers), clinics, companies, brands, online stores, websites, apps, "
    "institutes, hotels, cafes and other venues.\n"
    "Do not list directories or booking/search platforms that are only suggested as places to look "
    "(for example Paziresh24, Doctoreto, Nobat, Google Maps, Divar), and do not list generic advice.\n"
    "Copy each name exactly as it is written in the answer. Keep the order of appearance. No duplicates.\n"
    'Return only JSON: {"entities": ["name 1", "name 2"]}\n\n'
    "Question: <<Q>>\n\nAnswer:\n<<A>>"
)

_ARABIC = str.maketrans({"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا",
                         "إ": "ا", "آ": "ا", "ؤ": "و", "‌": " ", "ـ": ""})
_LIST_ITEM = re.compile(r"^\s*(?:[-*•●▪]|\d{1,2}[.)\-]|[۰-۹]{1,2}[.)\-])\s*(.+)$")
_SPLIT = re.compile(r"\s[–—-]\s|[:：]|\(|（|،")


def _basic(text: str) -> str:
    text = (text or "").translate(_ARABIC)
    text = re.sub(r"[ً-ٰٟ]", "", text).lower()
    return re.sub(r"[^\w\s]", " ", text)


# Titles and generic words that should not decide whether two names are the same
_DROP = {_basic(word).strip() for word in (
    "دکتر", "dr", "پروفسور", "prof", "جناب", "خانم", "آقای", "کلینیک", "مطب", "مرکز", "موسسه",
    "مؤسسه", "فروشگاه", "آموزشگاه", "شرکت", "برند", "سایت", "وبسایت", "اپ", "اپلیکیشن",
    "هتل", "کافه", "رستوران", "گروه", "the")}


def name_key(name: str) -> str:
    words = _basic(name).split()
    kept = [word for word in words if word not in _DROP]
    return " ".join(kept or words)


def _prompt(question: str, text: str) -> str:
    return PROMPT.replace("<<Q>>", question).replace("<<A>>", text[:12000])


def _parse(raw: str) -> list:
    raw = (raw or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", raw, re.S)
        data = json.loads(match.group(0)) if match else {}
    items = data.get("entities") if isinstance(data, dict) else data
    names = []
    for item in items or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def extract_heuristic(text: str) -> list:
    """Fallback without any API: take the head of each list item."""
    names = []
    for line in (text or "").splitlines():
        match = _LIST_ITEM.match(line)
        if not match:
            continue
        item = re.sub(r"[*_`#]+", "", match.group(1))
        item = _SPLIT.split(item, maxsplit=1)[0].strip(" .،؛:-–—")
        if 2 <= len(item) <= 60 and item not in names:
            names.append(item)
    return names


def extract_names(question: str, text: str, config: dict, log=print) -> list:
    if env("OPENAI_API_KEY"):
        try:
            client = engines.openai_client(timeout=90)
            resp = client.chat.completions.create(
                model=config.get("extract_model") or "gpt-4.1-mini",
                messages=[{"role": "user", "content": _prompt(question, text)}],
                response_format={"type": "json_object"},
            )
            return _parse(resp.choices[0].message.content)
        except Exception as exc:
            log(f"⚠ استخراج اسم با OpenAI نشد: {exc}")
    if env("GEMINI_API_KEY"):
        try:
            data = engines.gemini_generate(_prompt(question, text),
                                           config.get("extract_model_gemini") or "gemini-2.5-flash",
                                           json_mode=True)
            return _parse(engines.gemini_text(data))
        except Exception as exc:
            log(f"⚠ استخراج اسم با Gemini نشد: {exc}")
    return extract_heuristic(text)


def extract_all(question: str, answers: list, config: dict, log=print) -> list:
    """One list of names per answer, in the same order as the answers."""
    workers = max(1, int(config.get("parallel") or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda answer: extract_names(question, answer.text, config, log), answers))


def _find_cluster(clusters: list, key: str, threshold: float):
    best, best_ratio = None, 0.0
    for cluster in clusters:
        if cluster["key"] == key:
            return cluster
        ratio = SequenceMatcher(None, cluster["key"], key).ratio()
        if ratio > best_ratio:
            best, best_ratio = cluster, ratio
    return best if best_ratio >= threshold else None


def aggregate(names_per_answer: list, threshold: float = 0.86) -> list:
    """How many answers mention each entity (a name counts once per answer)."""
    clusters = []
    for index, names in enumerate(names_per_answer):
        for position, name in enumerate(names, 1):
            key = name_key(name)
            if not key:
                continue
            cluster = _find_cluster(clusters, key, threshold)
            if cluster is None:
                cluster = {"key": key, "variants": Counter(), "answers": set(), "positions": []}
                clusters.append(cluster)
            cluster["variants"][name] += 1
            if index not in cluster["answers"]:
                cluster["answers"].add(index)
                cluster["positions"].append(position)
    total = len(names_per_answer)
    out = [{
        "name": cluster["variants"].most_common(1)[0][0],
        "count": len(cluster["answers"]),
        "rate": round(len(cluster["answers"]) / total, 3) if total else 0,
        "avg_position": round(sum(cluster["positions"]) / len(cluster["positions"]), 2),
        "variants": sorted(cluster["variants"]),
    } for cluster in clusters]
    out.sort(key=lambda item: (-item["count"], item["avg_position"]))
    return out


def domain_of(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    host = (urlparse(value).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def aggregate_sources(answers: list, limit: int = 8) -> list:
    """How many answers cite each website."""
    counter = Counter()
    for answer in answers:
        domains = {domain_of(source) for source in answer.sources}
        counter.update(d for d in domains if "." in d and "vertexaisearch" not in d)
    total = len(answers)
    return [{"domain": domain, "count": count, "rate": round(count / total, 3) if total else 0}
            for domain, count in counter.most_common(limit)]
