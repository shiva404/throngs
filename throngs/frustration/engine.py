from __future__ import annotations

import logging
import math
import re
from collections import Counter

from throngs.config import settings
from throngs.schemas import A11yElement, FrustrationMetrics, PersonaDNA, VisualOverloadInfo

logger = logging.getLogger(__name__)

CLUTTER_THRESHOLD = 80
CLUTTER_MULTIPLIER = 1.1
JARGON_PENALTY_PER_HIT = 0.6
FRIENDLY_RELIEF_PER_HIT = 1.0
LOOP_PENALTY = 4.0
LOOP_WINDOW = 5
LOOP_REPEAT_TRIGGER = 3
PROGRESS_DECAY = 0.80
MAX_STEP_DELTA = 6.0
FAMILIARITY_DECAY = 0.55


class FrustrationEngine:
    """Calculates dynamic frustration scores based on cognitive load heuristics."""

    def __init__(self) -> None:
        self._url_history: list[str] = []
        self._action_history: list[tuple[str, str, str]] = []
        self._page_visit_count: dict[str, int] = {}

    def reset(self) -> None:
        self._url_history.clear()
        self._action_history.clear()
        self._page_visit_count.clear()

    def calculate(
        self,
        persona: PersonaDNA,
        a11y_elements: list[A11yElement],
        visible_text: str,
        current_url: str,
        base_frustration: float = 0.0,
        visual_overload: VisualOverloadInfo | None = None,
        last_action_type: str = "",
        last_element_id: str = "",
    ) -> FrustrationMetrics:
        node_count = len(a11y_elements)

        # Logarithmic clutter curve — softens the impact of large element counts.
        # log2(100/80+1) ≈ 0.52 vs the old linear formula that jumped straight to 4.0
        raw_ratio = node_count / CLUTTER_THRESHOLD
        visual_clutter = math.log2(raw_ratio + 1) * 2.0
        cog_multiplier = CLUTTER_MULTIPLIER if node_count > CLUTTER_THRESHOLD else 1.0

        # Same-page familiarity: repeated views of the same URL reduce clutter
        # contribution — the user's eyes adapt to the layout.
        self._page_visit_count[current_url] = self._page_visit_count.get(current_url, 0) + 1
        visits = self._page_visit_count[current_url]
        familiarity_discount = 1.0
        if visits > 1:
            familiarity_discount = FAMILIARITY_DECAY ** (visits - 1)

        jargon_hits = _count_jargon_hits(visible_text, persona.trigger_words)
        jargon_penalty = jargon_hits * JARGON_PENALTY_PER_HIT

        friendly_hits = _count_jargon_hits(visible_text, persona.friendly_words)
        friendly_relief = friendly_hits * FRIENDLY_RELIEF_PER_HIT

        prev_url = self._url_history[-1] if self._url_history else None
        self._url_history.append(current_url)
        self._action_history.append((current_url, last_action_type, last_element_id))
        loop_pen = _detect_action_loops(self._action_history)

        overload_spike = 0.0
        if visual_overload and visual_overload.overload_triggered:
            overload_spike = settings.visual_overload_frustration_spike

        navigated = prev_url is not None and prev_url != current_url
        progress_relief = 0.5 if navigated else 0.0

        raw_delta = (
            (visual_clutter * cog_multiplier * familiarity_discount)
            + jargon_penalty
            + loop_pen
            + overload_spike
            - friendly_relief
            - progress_relief
        )

        inverse_tech = (11 - persona.tech_literacy) / 10.0
        tech_scaling = 1.0 + (inverse_tech * 0.3)
        scaled_delta = raw_delta * tech_scaling
        final_delta = max(min(scaled_delta, MAX_STEP_DELTA), 0.0)

        carried = base_frustration
        if navigated:
            carried *= PROGRESS_DECAY

        total = carried + final_delta

        reasons: list[str] = []
        if visual_clutter * cog_multiplier * familiarity_discount > 1.5:
            reasons.append(
                f"Page has {node_count} interactive elements (clutter={visual_clutter:.1f})"
            )
        if familiarity_discount < 1.0:
            reasons.append(
                f"Seen this page {visits}x — familiarity reduces clutter by {(1 - familiarity_discount) * 100:.0f}%"
            )
        if jargon_hits > 0:
            reasons.append(f"{jargon_hits} jargon trigger word(s) detected (+{jargon_penalty:.1f})")
        if friendly_hits > 0:
            reasons.append(f"{friendly_hits} friendly word(s) easing frustration (-{friendly_relief:.1f})")
        if loop_pen > 0:
            reasons.append(f"Action loop detected — same action on same element repeated in last {LOOP_WINDOW} steps (+{loop_pen:.1f})")
        if overload_spike > 0:
            reasons.append(f"Visual overload triggered (+{overload_spike:.1f})")
        if navigated:
            reasons.append(f"Navigated to new page — progress relief (-{progress_relief:.1f}), carried frustration decayed to {carried:.1f}")
        if final_delta < scaled_delta:
            reasons.append(f"Per-step delta capped from {scaled_delta:.1f} to {MAX_STEP_DELTA}")

        metrics = FrustrationMetrics(
            visual_clutter_score=round(visual_clutter * familiarity_discount, 2),
            interactable_node_count=node_count,
            cognitive_load_multiplier=round(cog_multiplier, 2),
            jargon_density=round(jargon_hits / max(len(visible_text.split()), 1), 4),
            jargon_penalty=round(jargon_penalty, 2),
            friendly_relief=round(friendly_relief, 2),
            loop_penalty=round(loop_pen, 2),
            visual_overload_spike=round(overload_spike, 2),
            familiarity_discount=round(familiarity_discount, 3),
            page_visit_count=visits,
            tech_scaling_factor=round(tech_scaling, 3),
            progress_relief=round(progress_relief, 2),
            raw_delta=round(raw_delta, 2),
            capped_delta=round(final_delta, 2),
            carried_frustration=round(carried, 2),
            total_frustration=round(total, 2),
            reasoning=reasons,
        )

        logger.debug(
            "Frustration: total=%.2f (carried=%.2f, delta=%.2f [raw=%.2f], clutter=%.2f, "
            "familiarity=%.2f, jargon=%.2f, friendly=-%.2f, loop=%.2f, overload=%.2f, "
            "progress=-%.2f, tech_scale=%.2f) | reasons=%s",
            metrics.total_frustration,
            carried,
            final_delta,
            raw_delta,
            visual_clutter,
            familiarity_discount,
            jargon_penalty,
            friendly_relief,
            loop_pen,
            overload_spike,
            progress_relief,
            tech_scaling,
            "; ".join(reasons),
        )
        return metrics

    def should_rage_quit(self, frustration: float, persona: PersonaDNA) -> bool:
        return frustration >= persona.patience_budget


def _count_jargon_hits(text: str, words: list[str]) -> int:
    if not words or not text:
        return 0
    text_lower = text.lower()
    return sum(
        len(re.findall(re.escape(w.lower()), text_lower))
        for w in words
    )


def _detect_action_loops(history: list[tuple[str, str, str]]) -> float:
    """Detect true loops: the same (url, action_type, element_id) repeated.

    Form-filling on the same URL with different elements is NOT a loop.
    Only penalise when the exact same action on the exact same element
    repeats LOOP_REPEAT_TRIGGER times within the last LOOP_WINDOW steps.
    """
    if len(history) < LOOP_WINDOW:
        return 0.0
    recent = history[-LOOP_WINDOW:]
    counts = Counter(recent)
    most_common_count = counts.most_common(1)[0][1]
    if most_common_count >= LOOP_REPEAT_TRIGGER:
        return LOOP_PENALTY
    return 0.0
