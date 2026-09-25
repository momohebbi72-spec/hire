"""Optional AI layer.

The app works fully without AI: `RuleBasedProvider` is the default and needs no
API key. To plug in a model later, implement `AIProvider` and select it with the
AI_PROVIDER environment variable (openai | claude | gemini | local).
"""
from __future__ import annotations

from .base import AIProvider, Analysis  # noqa: F401
from .providers import get_provider  # noqa: F401
