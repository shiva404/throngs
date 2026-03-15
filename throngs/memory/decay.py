"""Phase 4 — The Forgetting Curve (Memory Decay Engine).

Implements the Ebbinghaus exponential decay formula so that agents
realistically forget UI paths they have not used recently:

    M = M₀ × e^(−k·t)

Where:
    M  — current memory strength
    M₀ — initial strength (always 1.0 after consolidation)
    k  — decay rate (determined by persona usage frequency)
    t  — days elapsed since the memory was last accessed

Threshold logic (Recall States):
    M > 0.7   → Perfect Recall  — inject exact muscle_memory_rule
    0.4 ≤ M ≤ 0.7 → Fuzzy Recall — inject a partially obfuscated hint
    M < 0.4   → Forgotten       — block memory entirely
"""

from __future__ import annotations

import math
from datetime import datetime

from throngs.config import settings
from throngs.schemas import UsageFrequency


class MemoryDecayEngine:
    """Calculates memory strength at retrieval time using exponential decay."""

    DECAY_RATES: dict[UsageFrequency, float] = {
        UsageFrequency.DAILY: settings.decay_rate_daily,
        UsageFrequency.WEEKLY: settings.decay_rate_weekly,
        UsageFrequency.MONTHLY: settings.decay_rate_monthly,
        UsageFrequency.QUARTERLY: settings.decay_rate_quarterly,
    }

    def get_decay_rate(self, usage_frequency: UsageFrequency) -> float:
        return self.DECAY_RATES.get(usage_frequency, settings.decay_rate_weekly)

    @staticmethod
    def days_since(timestamp: datetime) -> float:
        try:
            from throngs.time.clock import get_clock
            now = get_clock().now()
        except (RuntimeError, ImportError):
            now = datetime.utcnow()
        delta = now - timestamp
        return max(delta.total_seconds() / 86_400.0, 0.0)

    def calculate_strength(
        self,
        initial_strength: float,
        decay_rate: float,
        days_elapsed: float,
    ) -> float:
        """M = M₀ × e^(−k·t)"""
        return initial_strength * math.exp(-decay_rate * days_elapsed)

    def current_strength(
        self,
        last_accessed: datetime,
        usage_frequency: UsageFrequency,
        initial_strength: float = 1.0,
    ) -> float:
        k = self.get_decay_rate(usage_frequency)
        t = self.days_since(last_accessed)
        return self.calculate_strength(initial_strength, k, t)

    @staticmethod
    def classify_recall(strength: float) -> str:
        """Return the recall state for a given memory strength."""
        if strength > settings.memory_perfect_recall_threshold:
            return "perfect"
        if strength >= settings.memory_fuzzy_recall_threshold:
            return "fuzzy"
        return "forgotten"

    @staticmethod
    def obfuscate_rule(muscle_memory_rule: str) -> str:
        """Produce a vague, partially obfuscated hint for fuzzy recall.

        Instead of the precise rule the agent gets a fragmented version,
        e.g. "You vaguely remember something about navigating to a settings
        area, but the exact steps are unclear."
        """
        words = muscle_memory_rule.split()
        if len(words) <= 4:
            return (
                f'You vaguely remember something about "{muscle_memory_rule}", '
                "but the details are hazy."
            )

        visible_fragment = " ".join(words[: len(words) // 3])
        return (
            f'You vaguely remember: "{visible_fragment} ..." — '
            "but the remaining steps are unclear and you are not fully confident."
        )
