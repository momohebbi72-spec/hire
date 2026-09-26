"""Ask AI assistants the same question several times.

Engines: OpenAI (Responses API + web search), Gemini (Google Search grounding),
Perplexity (sonar), or answers you copied yourself from the ChatGPT app (import).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .settings import env

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
TIMEOUT = 120
_URL_RE = re.compile(r"https?://[^\s)\]»،]+")


@dataclass
class Answer:
    engine: str
    label: str
    model: str
    # True = with web search, False = without, None = unknown (copied from the app)
    web_search: object
    text: str
    sources: list = field(default_factory=list)


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _dedupe(items) -> list:
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _looks_like_domain(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", (text or "").strip()))


# ── OpenAI ──

def openai_client(timeout: int = TIMEOUT):
    from openai import OpenAI  # lazy: the rest of the tool works without the package

    return OpenAI(api_key=env("OPENAI_API_KEY"), base_url=env("OPENAI_BASE_URL") or None, timeout=timeout)


def _openai_text_and_urls(resp) -> tuple:
    text = (_get(resp, "output_text") or "").strip()
    urls, parts = [], []
    for item in _get(resp, "output") or []:
        if _get(item, "type") != "message":
            continue
        for part in _get(item, "content") or []:
            if _get(part, "type") == "output_text":
                parts.append(_get(part, "text") or "")
            for ann in _get(part, "annotations") or []:
                if _get(ann, "type") == "url_citation" and _get(ann, "url"):
                    urls.append(_get(ann, "url"))
    return (text or "\n".join(parts).strip()), _dedupe(urls)


def ask_openai(question: str, cfg: dict) -> Answer:
    client = openai_client()
    model = cfg.get("model") or "gpt-5-mini"
    label = cfg.get("label") or "ChatGPT"
    if cfg.get("web_search", True):
        last_error = None
        # "web_search" is the current tool name; older models and gateways only know the preview one
        for tool_type in ("web_search", "web_search_preview"):
            tool = {"type": tool_type}
            if cfg.get("user_location"):
                tool["user_location"] = {"type": "approximate", **cfg["user_location"]}
            try:
                resp = client.responses.create(model=model, input=question, tools=[tool])
            except Exception as exc:
                last_error = exc
                continue
            text, urls = _openai_text_and_urls(resp)
            return Answer("openai", label, model, True, text, urls)
        if not cfg.get("fallback_without_search"):
            raise RuntimeError(f"جستجوی وب کار نکرد: {last_error}")
    resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": question}])
    return Answer("openai", label, model, False, (resp.choices[0].message.content or "").strip(), [])


# ── Gemini ──

def gemini_generate(prompt: str, model: str, *, search: bool = False, json_mode: bool = False) -> dict:
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    resp = requests.post(GEMINI_URL.format(model=model), json=body, timeout=TIMEOUT,
                         headers={"x-goog-api-key": env("GEMINI_API_KEY")})
    resp.raise_for_status()
    return resp.json()


def gemini_text(data: dict) -> str:
    candidate = (data.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()


def ask_gemini(question: str, cfg: dict) -> Answer:
    model = cfg.get("model") or "gemini-2.5-flash"
    search = bool(cfg.get("web_search", True))
    data = gemini_generate(question, model, search=search)
    candidate = (data.get("candidates") or [{}])[0]
    urls = []
    for chunk in (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []:
        web = chunk.get("web") or {}
        title, uri = (web.get("title") or "").strip(), web.get("uri") or ""
        # grounding links are Google redirects; the title is usually the source domain
        if _looks_like_domain(title):
            urls.append(title)
        elif uri and "vertexaisearch" not in uri:
            urls.append(uri)
    return Answer("gemini", cfg.get("label") or "Gemini", model, search, gemini_text(data), _dedupe(urls))


# ── Perplexity ──

def ask_perplexity(question: str, cfg: dict) -> Answer:
    model = cfg.get("model") or "sonar"
    resp = requests.post(PERPLEXITY_URL, timeout=TIMEOUT,
                         headers={"Authorization": f"Bearer {env('PERPLEXITY_API_KEY')}"},
                         json={"model": model, "messages": [{"role": "user", "content": question}]})
    resp.raise_for_status()
    data = resp.json()
    message = (data.get("choices") or [{}])[0].get("message") or {}
    text = re.sub(r"\[\d+\]", "", message.get("content") or "").strip()
    urls = list(data.get("citations") or [])
    urls += [item.get("url") for item in data.get("search_results") or [] if isinstance(item, dict)]
    return Answer("perplexity", cfg.get("label") or "Perplexity", model, True, text, _dedupe(urls))


ENGINES = {
    "openai": ("OPENAI_API_KEY", ask_openai),
    "gemini": ("GEMINI_API_KEY", ask_gemini),
    "perplexity": ("PERPLEXITY_API_KEY", ask_perplexity),
}


def active_engines(config: dict, log=print) -> list:
    out = []
    for name, ecfg in (config.get("engines") or {}).items():
        if name not in ENGINES or not (ecfg or {}).get("enabled"):
            continue
        key_name = ENGINES[name][0]
        if not env(key_name):
            log(f"⚠ {key_name} خالی است؛ {name} کنار گذاشته شد")
            continue
        out.append((name, ecfg))
    return out


def ask_all(question: str, config: dict, runs: int, log=print) -> list:
    engines = active_engines(config, log)
    if not engines:
        raise RuntimeError("هیچ موتور فعالی با کلید API نیست. کلید را در .env بگذار یا جواب‌ها را با --import بده.")
    answers = []
    workers = max(1, int(config.get("parallel") or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ENGINES[name][1], question, ecfg): name
                   for name, ecfg in engines for _ in range(runs)}
        for future in as_completed(futures):
            name = futures[future]
            try:
                answer = future.result()
            except Exception as exc:
                log(f"✗ {name}: {exc}")
                continue
            if answer.text:
                answers.append(answer)
                log(f"✓ {name}: جواب {len(answers)}")
    return answers


# ── Answers you pasted yourself ──

def load_imported(path: Path, label: str = "ChatGPT") -> list:
    """JSON ({"label", "model", "web_search", "answers": [{"text", "sources"}]})
    or a text file with answers separated by a line containing only ---"""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        label = data.get("label") or label
        model = data.get("model") or ""
        search = data.get("web_search")
        items = data.get("answers") or []
    else:
        model, search = "app", None
        items = re.split(r"(?m)^\s*-{3,}\s*$", raw)
    out = []
    for item in items:
        if isinstance(item, str):
            item = {"text": item}
        text = (item.get("text") or "").strip()
        if not text:
            continue
        sources = list(item.get("sources") or []) or _URL_RE.findall(text)
        out.append(Answer("import", label, model, search, text, _dedupe(sources)))
    return out
