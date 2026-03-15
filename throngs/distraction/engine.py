"""Contextual Distraction & State Management Engine — the "Chaos Monkey".

Spec: 08_Throngs - Contextual Distraction & State Management.md

Phase 1 — Coffee Break (Temporal Interruption & Memory Wipe)
Phase 2 — Tab Switch (Concurrent State / Cross-Tab Testing)
Phase 3 — Squirrel! (In-App Distraction via popup/banner detection)

When an LLM is provided, distractions are generated contextually based on
the persona's life/work context, what they're doing on the page, and the
visual environment.  Falls back to template prompts when no LLM is available.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any

from throngs.schemas import DistractionEvent, PersonaDNA, VisualSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompt for contextual distraction generation
# ---------------------------------------------------------------------------
_DISTRACTION_GENERATION_PROMPT = """\
You are the "Chaos Monkey" for a UX testing system.  Your job is to invent a
realistic real-world interruption that would plausibly happen to this specific
person, RIGHT NOW, while they are in the middle of a task on a web app.

PERSONA:
  Name: {persona_name}
  Description: {persona_description}
  Tech literacy: {tech_literacy}/10
  Domain literacy: {domain_literacy}/10
  Device: {device}

CURRENT ENVIRONMENT:
  App page: {page_title} ({current_url})
  Goal they are working on: {goal}
  Step: {step}
  What they just did: {last_action}
  Visible alerts/signals: {signals_summary}

RULES:
- The distraction MUST fit who this person is.  A bakery owner gets a call
  from a supplier. A startup founder gets a Slack ping from an investor.
  A new hire gets pulled into a meeting by their manager. A plumber on mobile
  gets a customer call about a leaky pipe.
- Pick one of these variants: COFFEE_BREAK, TAB_SWITCH, or POPUP_SQUIRREL.
  - COFFEE_BREAK: they physically leave the screen (phone call, meeting,
    bathroom, lunch, colleague). They come back after 5-45 minutes.
  - TAB_SWITCH: they switch to another tab/app without leaving their desk
    (checking email, Slack, a spreadsheet, a reference doc). 1-5 minutes.
  - POPUP_SQUIRREL: something ON the page steals their attention (a banner,
    promo, notification badge, chat bubble). Seconds, but breaks their flow.
- The re-orientation prompt must force them to reconstruct their context from
  the screen alone — no hand-holding.  Mention what they might see on screen
  (headers, breadcrumbs, form fields, URL) but do NOT tell them the answer.
- Memory wipe: COFFEE_BREAK wipes 3-5 lines, TAB_SWITCH 1-3, SQUIRREL 0-2.

Return ONLY valid JSON:
{{
  "variant": "COFFEE_BREAK" | "TAB_SWITCH" | "POPUP_SQUIRREL",
  "narrative": "<2-3 sentences describing what happened, in character — e.g. 'Your phone rang — it was your biggest client asking about an overdue invoice. You spent 20 minutes on the call reassuring them.'>",
  "reorientation_prompt": "<The prompt injected into the agent. Starts with an emoji. Describes the interruption in 2nd person, then instructs them to re-orient from visible screen cues ONLY. 3-5 sentences.>",
  "memory_wipe_lines": <int 0-5>,
  "estimated_away_minutes": <int>
}}
"""

# ---------------------------------------------------------------------------
# Fallback templates (used when no LLM is available)
# ---------------------------------------------------------------------------
_FALLBACK_COFFEE_BREAK = [
    (
        "☕ COFFEE BREAK: You stepped away for a phone call (~20 min). "
        "You've just sat back down. Based ONLY on what you can see right now — "
        "the page header, breadcrumbs, active form fields, URL, and any "
        "unsaved data — figure out where you are and what you were doing. "
        "Do NOT rely on your recent action history; treat it as hazy."
    ),
    (
        "☕ INTERRUPTION: A colleague stopped by your desk to chat for 15 minutes. "
        "You're now looking at your screen again. The page is still open but "
        "you've lost your train of thought. Read the screen carefully — "
        "headers, form state, any error messages — and piece together what "
        "you were in the middle of."
    ),
    (
        "☕ LUNCH BREAK: You went to grab lunch and came back after 45 minutes. "
        "The screen might have timed out or refreshed. Check if your data is "
        "still there. Look at the URL, page title, form fields, and any session "
        "warnings to understand your current state."
    ),
]

_FALLBACK_TAB_SWITCH = [
    (
        "🔀 TAB SWITCH: You switched to another browser tab to look something "
        "up. You've now switched back. Check if the page is still in the same "
        "state — did any form data get lost? Re-orient and continue."
    ),
]

_FALLBACK_SQUIRREL = [
    (
        '🐿️ DISTRACTED! A {element_desc} just caught your eye: "{message}". '
        "Now refocus — where were you? What were you trying to do?"
    ),
]

_FALLBACK_CUSTOMER_ARRIVAL = (
    "🛒 CUSTOMER AT THE COUNTER: You were just in the middle of something on the computer "
    "when a customer came up to the counter ready to pay. You spent a few minutes ringing "
    "them up, taking their payment, and getting them on their way. You're back at the screen "
    "now — check where you were and continue what you were doing."
)


class DistractionEngine:
    """LLM-driven contextual distraction engine.

    When an LLM is provided, generates persona-aware, environment-aware
    interruption scenarios.  Falls back to templates otherwise.
    """

    def __init__(
        self,
        llm: Any | None = None,
        random_seed: int | None = None,
    ) -> None:
        self._llm = llm
        self._rng = random.Random(random_seed)

    # ------------------------------------------------------------------
    # Trigger logic
    # ------------------------------------------------------------------

    def should_trigger_interruption(
        self,
        action_count: int,
        interruption_probability: float,
    ) -> bool:
        triggered = self._rng.random() < interruption_probability
        if triggered:
            logger.info(
                "Distraction triggered at action step %d (p=%.2f)",
                action_count,
                interruption_probability,
            )
        return triggered

    def detect_squirrel(
        self,
        visual_signals: list[VisualSignal],
        goal: str,
    ) -> VisualSignal | None:
        if not visual_signals:
            return None

        goal_words = {w.lower() for w in goal.split() if len(w) > 3}

        candidates: list[VisualSignal] = []
        for sig in visual_signals:
            if sig.severity.value in ("error", "warning"):
                continue
            msg_lower = sig.message.lower()
            if any(w in msg_lower for w in goal_words):
                continue
            is_popup = sig.signal_type in (
                "dialog", "toast", "banner", "css_info", "css_success",
            )
            if is_popup and len(sig.message) > 10:
                candidates.append(sig)

        return self._rng.choice(candidates) if candidates else None

    # ------------------------------------------------------------------
    # Variant selection
    # ------------------------------------------------------------------

    def select_variant(
        self,
        visual_signals: list[VisualSignal] | None = None,
        goal: str = "",
        step: int = 0,
    ) -> tuple[str, VisualSignal | None]:
        squirrel_signal = None
        if visual_signals:
            squirrel_signal = self.detect_squirrel(visual_signals, goal)

        if squirrel_signal is not None:
            return "POPUP_SQUIRREL", squirrel_signal
        if self._rng.random() < 0.3:
            return "TAB_SWITCH", None
        return "COFFEE_BREAK", None

    # ------------------------------------------------------------------
    # LLM-driven distraction generation
    # ------------------------------------------------------------------

    async def generate_distraction(
        self,
        persona: PersonaDNA,
        goal: str,
        current_url: str,
        page_title: str,
        step: int,
        last_action_summary: str,
        visual_signals: list[VisualSignal] | None = None,
        squirrel_signal: VisualSignal | None = None,
    ) -> dict:
        """Generate a contextual distraction using the LLM.

        Returns a dict with keys: variant, narrative, reorientation_prompt,
        memory_wipe_lines, estimated_away_minutes.

        Falls back to template generation if the LLM is unavailable or fails.
        """
        signals_summary = "None"
        if visual_signals:
            sig_lines = [
                f"[{s.severity.value}] {s.message[:80]}"
                for s in visual_signals[:5]
            ]
            signals_summary = "; ".join(sig_lines)

        if self._llm is None:
            return self._generate_fallback(
                persona, goal, squirrel_signal,
            )

        prompt_text = _DISTRACTION_GENERATION_PROMPT.format(
            persona_name=persona.name,
            persona_description=persona.description,
            tech_literacy=persona.tech_literacy,
            domain_literacy=persona.domain_literacy,
            device=getattr(persona, "usage_device", "desktop"),
            page_title=page_title,
            current_url=current_url,
            goal=goal,
            step=step,
            last_action=last_action_summary or "navigating the interface",
            signals_summary=signals_summary,
        )

        try:
            from langchain_core.messages import HumanMessage

            response = await self._llm.ainvoke([HumanMessage(content=prompt_text)])
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(raw)

            variant = parsed.get("variant", "COFFEE_BREAK")
            if variant not in ("COFFEE_BREAK", "TAB_SWITCH", "POPUP_SQUIRREL"):
                variant = "COFFEE_BREAK"

            result = {
                "variant": variant,
                "narrative": parsed.get("narrative", ""),
                "reorientation_prompt": parsed.get("reorientation_prompt", ""),
                "memory_wipe_lines": int(parsed.get("memory_wipe_lines", 3)),
                "estimated_away_minutes": int(parsed.get("estimated_away_minutes", 10)),
            }
            logger.info(
                "LLM-generated %s distraction for %s: %s",
                result["variant"],
                persona.name,
                result["narrative"][:120],
            )
            return result

        except Exception as e:
            logger.warning(
                "LLM distraction generation failed for %s, falling back to templates: %s",
                persona.name,
                e,
            )
            return self._generate_fallback(persona, goal, squirrel_signal)

    def _generate_fallback(
        self,
        persona: PersonaDNA,
        goal: str,
        squirrel_signal: VisualSignal | None = None,
        variant: str | None = None,
    ) -> dict:
        """Template-based fallback when LLM is unavailable."""
        if variant == "CUSTOMER_ARRIVAL":
            return {
                "variant": "CUSTOMER_ARRIVAL",
                "narrative": f"A customer arrived at {persona.name}'s counter ready to pay.",
                "reorientation_prompt": _FALLBACK_CUSTOMER_ARRIVAL,
                "memory_wipe_lines": self._rng.randint(2, 4),
                "estimated_away_minutes": self._rng.randint(5, 15),
            }

        if squirrel_signal is not None:
            template = self._rng.choice(_FALLBACK_SQUIRREL)
            prompt = template.format(
                element_desc=squirrel_signal.signal_type.replace("_", " "),
                message=squirrel_signal.message[:200],
            )
            return {
                "variant": "POPUP_SQUIRREL",
                "narrative": f"A {squirrel_signal.signal_type} distracted {persona.name}.",
                "reorientation_prompt": prompt,
                "memory_wipe_lines": self._rng.randint(0, 2),
                "estimated_away_minutes": 0,
            }

        if self._rng.random() < 0.3:
            prompt = self._rng.choice(_FALLBACK_TAB_SWITCH)
            return {
                "variant": "TAB_SWITCH",
                "narrative": f"{persona.name} switched to another tab briefly.",
                "reorientation_prompt": prompt,
                "memory_wipe_lines": self._rng.randint(1, 3),
                "estimated_away_minutes": self._rng.randint(1, 5),
            }

        prompt = self._rng.choice(_FALLBACK_COFFEE_BREAK)
        return {
            "variant": "COFFEE_BREAK",
            "narrative": f"{persona.name} stepped away from the screen.",
            "reorientation_prompt": prompt,
            "memory_wipe_lines": self._rng.randint(3, 5),
            "estimated_away_minutes": self._rng.randint(10, 30),
        }

    # ------------------------------------------------------------------
    # Legacy sync API — kept for non-async callers (debug server, tests)
    # ------------------------------------------------------------------

    def build_reorientation_prompt(
        self,
        variant: str,
        squirrel_signal: VisualSignal | None = None,
    ) -> str:
        if variant == "CUSTOMER_ARRIVAL":
            return _FALLBACK_CUSTOMER_ARRIVAL
        if variant == "POPUP_SQUIRREL" and squirrel_signal is not None:
            template = self._rng.choice(_FALLBACK_SQUIRREL)
            return template.format(
                element_desc=squirrel_signal.signal_type.replace("_", " "),
                message=squirrel_signal.message[:200],
            )
        if variant == "TAB_SWITCH":
            return self._rng.choice(_FALLBACK_TAB_SWITCH)
        return self._rng.choice(_FALLBACK_COFFEE_BREAK)

    def build_coffee_break_prompt(self) -> str:
        return self._rng.choice(_FALLBACK_COFFEE_BREAK)

    def get_memory_wipe_count(self, variant: str, notes_line_count: int) -> int:
        if variant == "COFFEE_BREAK":
            return min(notes_line_count, self._rng.randint(3, 5))
        if variant == "TAB_SWITCH":
            return min(notes_line_count, self._rng.randint(1, 3))
        if variant == "POPUP_SQUIRREL":
            return min(notes_line_count, self._rng.randint(0, 2))
        return 0

    # ------------------------------------------------------------------
    # Event creation
    # ------------------------------------------------------------------

    def create_distraction_event(
        self,
        variant: str,
        pre_url: str,
        memory_wiped: int,
        feedback: str,
        narrative: str = "",
        state_preserved_by_app: bool = False,
        context_recovered_by_agent: bool = False,
        resulting_action: str = "",
        sim_time_away_minutes: float = 0.0,
    ) -> DistractionEvent:
        return DistractionEvent(
            distraction_variant=variant,
            pre_interruption_url=pre_url,
            memory_entries_wiped=memory_wiped,
            state_preserved_by_app=state_preserved_by_app,
            context_recovered_by_agent=context_recovered_by_agent,
            resulting_action=resulting_action,
            system_feedback_log=feedback,
            narrative=narrative,
            sim_time_away_minutes=sim_time_away_minutes,
        )
