"""HTML slides for Instagram: feed 4:5 (1080×1350) and story/reel 9:16 (1080×1920)."""
from __future__ import annotations

import base64
import hashlib
import html
import random
from pathlib import Path
from string import Template

from .jalali import fa
from .settings import FONTS_DIR, PKG_DIR

SIZES = {"feed": (1080, 1350), "story": (1080, 1920)}
# Top and bottom padding; the story size leaves room for Instagram's own buttons
PADDING = {"feed": (84, 70), "story": (260, 360)}
DEFAULT_THEME = {
    "bg": "#0B1020", "surface": "#151C36", "text": "#F5F7FF", "muted": "#9AA3C7",
    "accent": "#FF5A36", "accent_text": "#FFFFFF", "font_family": "Vazirmatn",
}
_FA_LETTERS = "ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"
_MASK_PREFIXES = ("دکتر", "دكتر", "پروفسور", "کلینیک", "مرکز", "مطب")
_LETTER_LABELS = ("الف", "ب", "پ", "ت", "ث", "ج", "چ", "ح", "خ", "د")
_WEIGHTS = {"thin": 100, "extralight": 200, "light": 300, "regular": 400, "medium": 500,
            "semibold": 600, "bold": 700, "extrabold": 800, "black": 900}
_FONT_TYPES = {".woff2": ("font/woff2", "woff2"), ".woff": ("font/woff", "woff"),
               ".ttf": ("font/ttf", "truetype"), ".otf": ("font/otf", "opentype")}

CSS = Template("""
$font_css
:root{--bg:$bg;--surface:$surface;--text:$text;--muted:$muted;--accent:$accent;--accent-text:$accent_text}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:${w}px;height:${h}px;background:var(--bg);overflow:hidden}
body{font-family:'$family','Vazir',Tahoma,sans-serif;color:var(--text);-webkit-font-smoothing:antialiased}
.slide{position:relative;width:${w}px;height:${h}px;padding:${pt}px 88px ${pb}px;display:flex;flex-direction:column;gap:28px;overflow:hidden}
.glow{position:absolute;width:900px;height:900px;border-radius:50%;background:radial-gradient(circle,var(--accent) 0%,transparent 65%);opacity:.16;top:-430px;left:-380px}
.mark{position:absolute;left:-20px;bottom:-200px;font-size:760px;font-weight:900;line-height:1;opacity:.045}
.top{display:flex;justify-content:space-between;align-items:center;position:relative}
.badge{background:var(--accent);color:var(--accent-text);border-radius:999px;padding:10px 28px;font-size:30px;font-weight:800}
.page{color:var(--muted);font-size:28px;font-weight:700}
.main{flex:1;display:flex;flex-direction:column;justify-content:center;gap:32px;position:relative;min-height:0}
.kicker{color:var(--accent);font-size:40px;font-weight:800}
.question{font-weight:900;line-height:1.4}
.sub{color:var(--muted);font-size:40px;line-height:1.7;font-weight:500}
.title{font-size:60px;font-weight:900;line-height:1.35}
.note{color:var(--muted);font-size:30px;line-height:1.6}
.list{display:flex;flex-direction:column;gap:20px}
.row{display:flex;align-items:center;gap:26px;background:var(--surface);border-radius:26px;padding:20px 28px}
.rank{flex:0 0 64px;height:64px;border-radius:50%;background:var(--accent);color:var(--accent-text);display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:900}
.info{flex:1;min-width:0;display:flex;flex-direction:column;gap:12px}
.name{font-size:38px;line-height:1.35;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.blur{filter:blur(10px)}
.bar{height:12px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden}
.bar span{display:block;height:100%;border-radius:999px;background:var(--accent)}
.count{flex:0 0 auto;font-size:32px;font-weight:800}
.domain{flex:1;min-width:0;font-size:38px;font-weight:700;direction:ltr;text-align:right;unicode-bidi:isolate;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tips{display:flex;flex-direction:column;gap:26px;list-style:none;counter-reset:tip}
.tips li{counter-increment:tip;display:flex;gap:24px;align-items:flex-start;background:var(--surface);border-radius:26px;padding:28px 30px;font-size:38px;line-height:1.6;font-weight:600}
.tips li::before{content:counter(tip, persian);flex:0 0 60px;height:60px;border-radius:50%;background:var(--accent);color:var(--accent-text);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:32px}
.cta{background:var(--surface);border:3px solid var(--accent);border-radius:34px;padding:44px 42px;display:flex;flex-direction:column;gap:20px}
.cta .big{font-size:50px;font-weight:900;line-height:1.5}
.cta .small{font-size:38px;color:var(--muted);line-height:1.6}
.empty{font-size:44px;line-height:1.7;color:var(--muted)}
.swipe{color:var(--accent);font-weight:800;font-size:34px;position:relative}
.logo{height:72px;align-self:flex-start}
.foot{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;border-top:2px solid rgba(255,255,255,.1);padding-top:24px;color:var(--muted);font-size:25px;line-height:1.6;position:relative}
.foot .handle{direction:ltr;unicode-bidi:isolate;font-weight:800;color:var(--text);font-size:30px;white-space:nowrap}
""")


def font_css(family: str) -> str:
    """Embed local fonts (assets/fonts) so the slides never depend on the internet."""
    rules = []
    if FONTS_DIR.exists():
        files = [p for p in sorted(FONTS_DIR.iterdir()) if p.suffix.lower() in _FONT_TYPES]
        wanted = family.lower().replace(" ", "")
        matching = [p for p in files if p.stem.lower().replace(" ", "").startswith(wanted)]
        for path in matching or files:
            kind = _FONT_TYPES[path.suffix.lower()]
            stem = path.stem.lower().replace("-", "").replace("_", "")
            if "wght" in stem or "variable" in stem:
                weight = "100 900"
            else:
                weight = next((str(value) for name, value in sorted(_WEIGHTS.items(), key=lambda kv: -len(kv[0]))
                               if name in stem), "400")
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            rules.append(f"@font-face{{font-family:'{family}';src:url(data:{kind[0]};base64,{data}) "
                         f"format('{kind[1]}');font-weight:{weight};font-display:block}}")
    if not rules:
        rules.append("@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;800;900&display=block');")
    return "\n".join(rules)


def category_cfg(data: dict, config: dict) -> dict:
    categories = config.get("categories") or {}
    return categories.get(data.get("category")) or categories.get("business") or {}


def method_line(data: dict) -> str:
    """«۱۰ بار پرسش از ChatGPT با جستجوی وب · ۴ مهر ۱۴۰۵»"""
    parts = []
    for result in data.get("results") or []:
        mode = result.get("web_search")
        how = "با جستجوی وب" if mode is True else ("در اپ" if mode is None else "بدون جستجوی وب")
        parts.append(f"{fa(result['runs'])} بار پرسش از {result['label']} {how}")
    return " و ".join(parts) + f" · {data.get('date_fa', '')}"


def letter_label(index: int, word: str) -> str:
    """Name shown instead of a hidden one in text posts, e.g. «پزشک الف»."""
    letter = _LETTER_LABELS[index] if index < len(_LETTER_LABELS) else fa(index + 1)
    return f"{word} {letter}"


def mask_text(name: str) -> str:
    """Same-length random letters (stable per name), so the blur hides nothing real."""
    rnd = random.Random(hashlib.md5(name.encode("utf-8")).hexdigest())
    return "".join(ch if ch.isspace() else rnd.choice(_FA_LETTERS) for ch in name)


def _name_html(name: str, masked: bool) -> str:
    if not masked:
        return f"<bdi>{html.escape(name)}</bdi>"
    words = name.split()
    prefix = words[0] if words and words[0] in _MASK_PREFIXES else ""
    rest = name[len(prefix):].strip() if prefix else name
    shown = f"{html.escape(prefix)} " if prefix else ""
    return f"{shown}<span class='blur'>{html.escape(mask_text(rest or name))}</span>"


def _question_size(text: str, size: str) -> int:
    base = 92 if size == "feed" else 100
    length = len(text)
    if length > 70:
        return base - 30
    if length > 50:
        return base - 18
    if length > 35:
        return base - 8
    return base


def _logo_html(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = PKG_DIR / path
    if not path.exists():
        return ""
    mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"<img class='logo' src='data:{mime};base64,{data}' alt=''>"


def _hook(data: dict, size: str) -> str:
    runs = fa(sum(result["runs"] for result in data["results"]))
    labels = " و ".join(html.escape(result["label"]) for result in data["results"])
    return ("<div class='main'>"
            "<div class='kicker'>از هوش مصنوعی پرسیدیم</div>"
            f"<div class='question' style='font-size:{_question_size(data['question'], size)}px'>"
            f"«{html.escape(data['question'])}»</div>"
            f"<div class='sub'>{runs} بار از {labels} پرسیدیم. ببینید اسم چه کسانی آمد.</div>"
            "</div><div class='swipe'>ورق بزنید ←</div>")


def _results(result: dict, config: dict, masked: bool) -> str:
    top_n = int(config.get("top_n") or 5)
    runs = result["runs"]
    rows = []
    for index, entity in enumerate(result["entities"][:top_n], 1):
        width = max(4, round(100 * entity["count"] / runs)) if runs else 0
        rows.append("<div class='row'>"
                    f"<div class='rank'>{fa(index)}</div>"
                    f"<div class='info'><div class='name'>{_name_html(entity['name'], masked)}</div>"
                    f"<div class='bar'><span style='width:{width}%'></span></div></div>"
                    f"<div class='count'>{fa(entity['count'])} از {fa(runs)}</div></div>")
    if rows:
        body = "<div class='list'>" + "".join(rows) + "</div>"
    else:
        body = "<div class='empty'>در هیچ‌کدام از جواب‌ها اسم مشخصی نیامد. این جایگاه هنوز خالی است.</div>"
    note = "اسم‌ها عمدا تار شده است. " if masked else ""
    return ("<div class='main'>"
            f"<div class='title'>جواب {html.escape(result['label'])}</div>"
            f"<div class='note'>{note}عدد یعنی این اسم در چند جواب از {fa(runs)} جواب آمد.</div>"
            f"{body}</div>")


def _sources(sources: list, results: list) -> str:
    total = sum(result["runs"] for result in results)
    rows = "".join("<div class='row'>"
                   f"<div class='domain'>{html.escape(source['domain'])}</div>"
                   f"<div class='count'>در {fa(source['count'])} جواب</div></div>"
                   for source in sources[:6])
    return ("<div class='main'>"
            "<div class='title'>این اسم‌ها از کجا آمدند؟</div>"
            f"<div class='note'>سایت‌هایی که هوش مصنوعی در این {fa(total)} جواب به آن‌ها ارجاع داد</div>"
            f"<div class='list'>{rows}</div></div>")


def _tips(category: dict) -> str:
    tips = (category.get("tips") or [])[:3]
    items = "".join(f"<li>{html.escape(tip)}</li>" for tip in tips)
    return ("<div class='main'>"
            f"<div class='title'>اسم شما نیامد؟ از این {fa(len(tips))} کار شروع کنید</div>"
            f"<ol class='tips'>{items}</ol></div>")


def _cta(brand: dict) -> str:
    keyword = html.escape(brand.get("dm_keyword") or "تست")
    link_text = html.escape(brand.get("cta_link_text") or "تست رایگان: لینک در بیو")
    return ("<div class='main'>"
            "<div class='title'>اسم شما آمد؟</div>"
            "<div class='cta'>"
            f"<div class='big'>{link_text}</div>"
            f"<div class='small'>یا در دایرکت بنویسید «{keyword}»</div></div>"
            "<div class='sub'>فردا یک حوزه‌ی دیگر را می‌پرسیم. حوزه‌ی خودتان را کامنت کنید.</div>"
            f"{_logo_html(brand.get('logo') or '')}</div>")


def _page(body: str, size: str, config: dict) -> str:
    width, height = SIZES[size]
    top, bottom = PADDING[size]
    theme = {**DEFAULT_THEME, **(config.get("theme") or {})}
    css = CSS.substitute(
        font_css=font_css(theme["font_family"]), family=theme["font_family"],
        w=width, h=height, pt=top, pb=bottom,
        **{key: theme[key] for key in ("bg", "surface", "text", "muted", "accent", "accent_text")},
    )
    return ("<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
            f"<style>{css}</style></head><body><div class='slide'>{body}</div></body></html>")


def build_slides(data: dict, config: dict, size: str = "feed", mask=None) -> list:
    """[(file name, html)] for one post, in publishing order."""
    brand = config.get("brand") or {}
    masked = bool(data.get("mask_names")) if mask is None else mask
    series = f"{brand.get('series_title') or 'سؤال روز'} · #{fa(data.get('number') or '')}"
    parts = [("hook", _hook(data, size))]
    for index, result in enumerate(data["results"], 1):
        parts.append((f"results-{index}", _results(result, config, masked)))
    if data.get("sources_all"):
        parts.append(("sources", _sources(data["sources_all"], data["results"])))
    parts.append(("tips", _tips(category_cfg(data, config))))
    parts.append(("cta", _cta(brand)))

    method = html.escape(method_line(data))
    handle = html.escape(brand.get("handle") or "")
    total = len(parts)
    slides = []
    for index, (name, inner) in enumerate(parts, 1):
        mark = "<div class='mark'>؟</div>" if name == "hook" else ""
        body = ("<div class='glow'></div>" + mark
                + f"<div class='top'><div class='badge'>{html.escape(series)}</div>"
                  f"<div class='page'>{fa(index)} / {fa(total)}</div></div>"
                + inner
                + f"<div class='foot'><div>{method}</div><div class='handle'>{handle}</div></div>")
        slides.append((f"{index:02d}-{name}", _page(body, size, config)))
    return slides
