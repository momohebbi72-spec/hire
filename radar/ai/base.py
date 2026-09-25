"""AIProvider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class Analysis:
    summary: str
    explanation: str
    next_action: str
    highlights: List[str] = field(default_factory=list)
    provider: str = "rules"


class AIProvider(ABC):
    """Every provider receives an opportunity dict (a DB row as dict) and the parsed Profile."""

    name = "base"

    @abstractmethod
    def summarize_opportunity(self, opp: dict) -> str:
        """2–3 sentence summary of the posting."""

    @abstractmethod
    def explain_match(self, opp: dict, profile) -> str:
        """Why this opportunity fits (or doesn't) the profile."""

    def analyze_opportunity(self, opp: dict, profile) -> Analysis:
        """Full analysis; providers may override to do it in one model call."""
        return Analysis(
            summary=self.summarize_opportunity(opp),
            explanation=self.explain_match(opp, profile),
            next_action=self.next_action(opp),
            provider=self.name,
        )

    def next_action(self, opp: dict) -> str:
        return ""
