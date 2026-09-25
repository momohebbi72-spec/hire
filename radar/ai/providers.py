"""Providers: rule-based (default, offline) + placeholders for future LLM providers."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..settings import env
from ..textutil import parse_iso
from .base import AIProvider, Analysis


class RuleBasedProvider(AIProvider):
    """No model, no API key — uses the matching engine's output."""

    name = "rules"

    def summarize_opportunity(self, opp: dict) -> str:
        text = re.sub(r"\s+", " ", opp.get("description") or "").strip()
        if not text:
            return "توضیحاتی برای این فرصت ثبت نشده؛ لینک آگهی را باز کنید."
        sentences = re.split(r"(?<=[.!؟?])\s+", text)
        summary = " ".join(sentences[:3])
        return summary[:420] + ("…" if len(summary) > 420 else "")

    def explain_match(self, opp: dict, profile) -> str:
        reasons = opp.get("reasons_list") or []
        good = [r[2:] for r in reasons if r.startswith("✓")]
        bad = [r[2:] for r in reasons if r.startswith(("✗", "⚠"))]
        score = opp.get("score") or 0
        level = "بسیار مناسب" if score >= 80 else "مناسب" if score >= profile.min_score else "کم‌ارتباط"
        parts = [f"امتیاز {score}% — {level}."]
        if good:
            parts.append("نقاط تطابق: " + "، ".join(good[:8]) + ".")
        if bad:
            parts.append("نکات منفی: " + "، ".join(bad) + ".")
        missing = [s.label for s in profile.skills[:6] if s.label not in (opp.get("skills_list") or [])]
        if missing and score >= profile.min_score:
            parts.append("مهارت‌هایی که در آگهی نیامده ولی می‌توانی برجسته کنی: " + "، ".join(missing[:4]) + ".")
        return " ".join(parts)

    def next_action(self, opp: dict) -> str:
        status, score = opp.get("status") or "New", opp.get("score") or 0
        freelance = (opp.get("opp_type") or "") == "Freelance"
        updated = parse_iso(opp.get("updated_at"))
        idle = (datetime.now(timezone.utc) - updated).days if updated else 0
        if status == "New":
            if score >= 80:
                return ("همین امروز یک پروپوزال کوتاه با ۲ نمونه‌کار سئو بفرست." if freelance
                        else "همین امروز اپلای کن؛ رزومه را با کلمات کلیدی آگهی هماهنگ کن.")
            return "بررسی کن؛ اگر مناسب بود «ذخیره» کن، وگرنه «نادیده» بگیر."
        if status == "Saved":
            return "رزومه/پروپوزال را برای این فرصت شخصی‌سازی کن و ارسال کن."
        if status in ("Contacted", "Applied"):
            return "پیگیری کن — ۵ روز از آخرین تغییر گذشته." if idle >= 5 else "منتظر پاسخ بمان؛ ۵ روز بعد پیگیری کن."
        if status == "Won":
            return "یادداشت مبلغ و شرایط همکاری را کامل کن."
        return ""


class _FutureProvider(RuleBasedProvider):
    """Placeholder: falls back to rules until the real integration is written."""

    env_key = ""

    def analyze_opportunity(self, opp: dict, profile) -> Analysis:
        analysis = super().analyze_opportunity(opp, profile)
        analysis.provider = f"{self.name} (not connected yet → rules)"
        return analysis


class OpenAIProvider(_FutureProvider):
    name, env_key = "openai", "OPENAI_API_KEY"


class ClaudeProvider(_FutureProvider):
    name, env_key = "claude", "ANTHROPIC_API_KEY"


class GeminiProvider(_FutureProvider):
    name, env_key = "gemini", "GEMINI_API_KEY"


class LocalLLMProvider(_FutureProvider):
    """e.g. Ollama on http://localhost:11434 — works offline and inside Iran."""

    name, env_key = "local", "LOCAL_LLM_URL"


PROVIDERS = {p.name: p for p in (RuleBasedProvider, OpenAIProvider, ClaudeProvider, GeminiProvider, LocalLLMProvider)}


def get_provider() -> AIProvider:
    return PROVIDERS.get(env("AI_PROVIDER", "rules").lower(), RuleBasedProvider)()
