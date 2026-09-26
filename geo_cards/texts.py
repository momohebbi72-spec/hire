"""Instagram caption, LinkedIn post, Virgool draft and the monthly roundup.

Latin words (ChatGPT, domains, model names) are kept at the end of a line or followed by a
Persian word, never by punctuation, so right-to-left apps show them in the right place.
"""
from __future__ import annotations

from collections import Counter

from .design import category_cfg, letter_label, method_line
from .jalali import fa

DEFAULT_TAGS = ("هوش_مصنوعی", "جئو", "چت_جی_پی_تی", "سئو")


def _name(entity: dict, index: int, masked: bool, category: dict) -> str:
    return letter_label(index, category.get("entity_word") or "گزینه") if masked else entity["name"]


def _models(data: dict) -> list:
    models = sorted({r.get("model") for r in data["results"] if r.get("model") and r.get("model") != "app"})
    return [f"مدل: {model}" for model in models]


def hashtags(data: dict, config: dict) -> str:
    category = category_cfg(data, config)
    tags = list(config.get("hashtags") or DEFAULT_TAGS) + list(category.get("hashtags") or [])
    if data.get("city"):
        tags.append(data["city"].replace(" ", "_"))
    seen = []
    for tag in tags:
        tag = str(tag).lstrip("#")
        if tag and tag not in seen:
            seen.append(tag)
    return " ".join(f"#{tag}" for tag in seen)


def instagram_caption(data: dict, config: dict) -> str:
    brand = config.get("brand") or {}
    category = category_cfg(data, config)
    result = data["results"][0]
    runs, masked, entities = result["runs"], bool(data.get("mask_names")), result["entities"]
    lines = [f"«{data['question']}»", f"این سؤال را {fa(runs)} بار از {result['label']} پرسیدیم.", ""]
    if entities:
        top = entities[0]
        lines.append(f"بیشترین حضور: {fa(top['count'])} بار از {fa(runs)} برای {_name(top, 0, masked, category)}")
        lines.append(f"تعداد اسم‌های مختلف در جواب‌ها: {fa(len(entities))}")
    else:
        lines.append("در هیچ جوابی اسم مشخصی نیامد. این جایگاه هنوز خالی است.")
    if masked:
        lines += ["", "اسم‌ها عمدا تار شده است. اگر در این حوزه کار می‌کنید و نتیجه‌ی خودتان را می‌خواهید، دایرکت بدهید."]
    sources = data.get("sources_all") or []
    if sources:
        lines += ["", "سایت‌هایی که بیشتر به آن‌ها ارجاع شد:"] + [f"• {s['domain']}" for s in sources[:5]]
    lines += ["", "اسم شما آمد؟", brand.get("cta_link_text") or "تست رایگان: لینک در بیو",
              f"یا در دایرکت بنویسید «{brand.get('dm_keyword') or 'تست'}»",
              "حوزه‌ی بعدی را کامنت کنید.", "",
              f"روش: {method_line(data)}", *_models(data), "", hashtags(data, config)]
    return "\n".join(lines).strip() + "\n"


def linkedin_post(data: dict, config: dict) -> str:
    category = category_cfg(data, config)
    result = data["results"][0]
    runs, masked, entities = result["runs"], bool(data.get("mask_names")), result["entities"]
    lines = [f"«{data['question']}» را {fa(runs)} بار از {result['label']} پرسیدم.", "", "نتیجه:"]
    for index, entity in enumerate(entities[:5]):
        lines.append(f"{fa(index + 1)}. {fa(entity['count'])} بار از {fa(runs)}: {_name(entity, index, masked, category)}")
    if not entities:
        lines.append("هیچ اسم مشخصی نیامد.")
    sources = data.get("sources_all") or []
    if sources:
        lines += ["", "این سایت‌ها منبع جواب‌ها بودند:"] + [f"• {s['domain']}" for s in sources[:3]]
    lines += ["", "[یک جمله برداشت خودت از این نتیجه]", "",
              "اگر می‌خواهید بدانید اسم کسب‌وکار شما چند بار آمده، زیر همین پست بنویسید «تست».", "",
              f"روش: {method_line(data)}", "", "#هوش_مصنوعی #جئو #GEO"]
    return "\n".join(lines).strip() + "\n"


def virgool_post(data: dict, config: dict) -> str:
    brand = config.get("brand") or {}
    category = category_cfg(data, config)
    masked = bool(data.get("mask_names"))
    first = data["results"][0]
    out = [f"# {data['question']} از نگاه هوش مصنوعی", "", f"> {method_line(data)}", "",
           "## روش", "",
           f"این سؤال را {fa(first['runs'])} بار از {first['label']} پرسیدیم و شمردیم هر اسم در چند جواب آمد. "
           "جواب هوش مصنوعی هر بار کمی فرق می‌کند؛ برای همین به‌جای یک اسکرین‌شات، تعداد را گزارش می‌کنیم.", ""]
    if masked:
        out += ["اسم‌ها در این گزارش با حرف مشخص شده‌اند و اسم واقعی منتشر نمی‌شود.", ""]
    for result in data["results"]:
        out += [f"## جواب {result['label']}", "", "| رتبه | نام | حضور |", "|---|---|---|"]
        for index, entity in enumerate(result["entities"][:10]):
            out.append(f"| {fa(index + 1)} | {_name(entity, index, masked, category)} | "
                       f"{fa(entity['count'])} از {fa(result['runs'])} |")
        if not result["entities"]:
            out.append("| — | اسم مشخصی نیامد | — |")
        out.append("")
    sources = data.get("sources_all") or []
    if sources:
        out += ["## هوش مصنوعی به کدام سایت‌ها ارجاع داد", "", "| سایت | تعداد جواب |", "|---|---|"]
        out += [f"| {s['domain']} | {fa(s['count'])} |" for s in sources]
        out.append("")
    tips = category.get("tips") or []
    if tips:
        out += ["## اگر اسم شما نیامد", ""] + [f"- {tip}" for tip in tips] + [""]
    out += ["## درباره‌ی این سری", "",
            "هر روز یک سؤال واقعی را از هوش مصنوعی می‌پرسیم و نتیجه را منتشر می‌کنیم."]
    if brand.get("tool_url"):
        out += ["", "تست رایگان اسم شما:", "", brand["tool_url"]]
    return "\n".join(out).strip() + "\n"


def roundup(items: list, config: dict) -> str:
    """Monthly article for Virgool and the LinkedIn newsletter, built from many data.json files."""
    brand = config.get("brand") or {}
    out = ["# هوش مصنوعی درباره‌ی بازار ایران چه می‌گوید", "",
           f"جمع‌بندی {fa(len(items))} سؤال که هر کدام چند بار از هوش مصنوعی پرسیده شد.", "",
           "## خلاصه‌ی سؤال‌ها", "", "| سؤال | بیشترین حضور | تعداد اسم‌ها |", "|---|---|---|"]
    domain_questions = Counter()
    for data in items:
        result = data["results"][0]
        entities = result["entities"]
        category = category_cfg(data, config)
        if entities:
            top = f"{_name(entities[0], 0, bool(data.get('mask_names')), category)} — {fa(entities[0]['count'])} از {fa(result['runs'])}"
        else:
            top = "هیچ‌کس"
        out.append(f"| {data['question']} | {top} | {fa(len(entities))} |")
        domain_questions.update({s["domain"] for s in data.get("sources_all") or []})
    if domain_questions:
        out += ["", "## سایت‌هایی که هوش مصنوعی بیشتر از همه به آن‌ها ارجاع داد", "",
                "| سایت | در چند سؤال |", "|---|---|"]
        out += [f"| {domain} | {fa(count)} از {fa(len(items))} |" for domain, count in domain_questions.most_common(15)]
    out += ["", "## برداشت‌ها", "", "- [برداشت ۱]", "- [برداشت ۲]", "- [برداشت ۳]"]
    if brand.get("tool_url"):
        out += ["", "تست رایگان اسم شما:", "", brand["tool_url"]]
    return "\n".join(out).strip() + "\n"
