"""Risk Aversion / Hesitation Engine.

Spec: 5_Throngs - Human Flaws & Environmental Constraints Module.md (Phase 1)

Intercepts high-stakes actions before execution, forcing the agent to
verify totals/recipients based on the persona's risk_tolerance.

Two detection modes:
  1. **Regex fast-path** — known high-stakes keywords (instant, no LLM call).
  2. **LLM analysis** — dynamically evaluates any element + page context to
     classify risk level.  Enabled via ``settings.hesitation_llm_enabled``.

The LLM assigns a risk_level (1-10) which is compared against the persona's
risk_tolerance.  When risk_level > risk_tolerance, hesitation fires.
Results are cached per (element_name, page_url) to avoid repeated LLM calls.
"""
from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

from throngs.schemas import HesitationEvent

logger = logging.getLogger(__name__)

# Regex patterns that identify obviously high-stakes actions (fast-path, no LLM needed)
HIGH_STAKES_PATTERNS = re.compile(
    r"\b(pay|submit|delete|transfer|file\s+tax|payroll|wire|void|refund"
    r"|cancel\s+subscription)\b",
    re.IGNORECASE,
)

_RISK_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "is_high_stakes": {
            "type": "boolean",
            "description": "True if this action could cause financial, data-loss, or irreversible consequences.",
        },
        "risk_level": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": (
                "1 = trivially safe (navigating, viewing). "
                "5 = moderate (editing data, changing settings). "
                "8 = high (financial transactions, deleting records). "
                "10 = critical (irreversible financial action, bulk delete)."
            ),
        },
        "risk_category": {
            "type": "string",
            "description": "Category: financial, data_loss, account_change, privacy, irreversible, safe.",
        },
        "reasoning": {
            "type": "string",
            "description": "One-sentence explanation of why this action is or is not high-stakes.",
        },
    },
    "required": ["is_high_stakes", "risk_level", "risk_category", "reasoning"],
}

_RISK_ANALYSIS_PROMPT = """\
You are a UX risk analyst. Determine whether the following UI action is \
high-stakes (could cause financial loss, data deletion, irreversible changes, \
or sensitive account modifications).

Element being clicked:
  Name: "{element_name}"
  Role: {element_role}

Page context:
  URL: {page_url}
  Goal: {goal}
  Nearby elements: {nearby_elements}

Classify the risk. Consider:
- Financial actions: payments, transfers, invoices, refunds, payroll, taxes, totals, amounts
- Data actions: delete, remove, clear, void, cancel, revoke
- Account actions: change password, deactivate, unsubscribe, close account
- Irreversible: anything that cannot be undone easily
- Context matters: "total amount" on an invoice page is high-stakes; "total" on a dashboard is not

Respond with ONLY valid JSON matching this schema:
{schema}
"""


class HesitationEngine:
    """Determines whether a persona should hesitate before a high-stakes action.

    Detection pipeline:
      1. Regex fast-path — known keywords trigger immediately (risk_level=8).
      2. LLM analysis — dynamically classifies risk for any element + context.
      3. Risk gating — compare detected risk_level against persona's risk_tolerance.

    Risk tolerance controls the final gate:
    - risk_level > risk_tolerance + 2: always hesitate
    - risk_level > risk_tolerance:     50% chance of hesitation
    - risk_level <= risk_tolerance:    no hesitation
    """

    def __init__(
        self,
        llm: Any | None = None,
        random_seed: int | None = None,
    ) -> None:
        self._rng = random.Random(random_seed)
        self._llm = llm
        self._cache: dict[tuple[str, str], dict] = {}

    def set_llm(self, llm: Any) -> None:
        """Attach or replace the LLM instance (allows lazy initialization)."""
        self._llm = llm

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def should_hesitate(
        self,
        element_name: str,
        action_type: str,
        risk_tolerance: int,
        *,
        element_role: str = "",
        page_url: str = "",
        goal: str = "",
        nearby_elements: list[str] | None = None,
    ) -> bool:
        """Check whether the agent should pause before this action.

        Parameters
        ----------
        element_name:
            The accessible name / label of the target element.
        action_type:
            The action string (e.g. ``"click"``, ``"type"``).
        risk_tolerance:
            Persona's risk tolerance (1–10).  Lower values → more cautious.
        element_role:
            The ARIA role of the element (e.g. "button", "link").
        page_url:
            Current page URL for context.
        goal:
            The agent's current goal for context.
        nearby_elements:
            Names of adjacent interactive elements for context.

        Returns
        -------
        bool
            True if the agent should hesitate and verify before proceeding.
        """
        if action_type.lower() != "click":
            return False

        analysis = await self.analyze_risk(
            element_name=element_name,
            element_role=element_role,
            page_url=page_url,
            goal=goal,
            nearby_elements=nearby_elements,
        )

        risk_level = analysis.get("risk_level", 0)
        is_high_stakes = analysis.get("is_high_stakes", False)

        if not is_high_stakes and risk_level < 5:
            return False

        return self._apply_risk_gate(risk_level, risk_tolerance, element_name)

    async def analyze_risk(
        self,
        element_name: str,
        element_role: str = "",
        page_url: str = "",
        goal: str = "",
        nearby_elements: list[str] | None = None,
    ) -> dict:
        """Analyze the risk level of an action on an element.

        Returns a dict with: is_high_stakes, risk_level, risk_category, reasoning, source.
        """
        # Fast-path: regex match on known high-stakes keywords
        if HIGH_STAKES_PATTERNS.search(element_name):
            return {
                "is_high_stakes": True,
                "risk_level": 8,
                "risk_category": "financial",
                "reasoning": f"Element name '{element_name}' matches known high-stakes keyword pattern.",
                "source": "regex",
            }

        # LLM analysis (if available and enabled)
        from throngs.config import settings
        if settings.hesitation_llm_enabled and self._llm is not None:
            cache_key = (element_name.lower().strip(), page_url)
            if cache_key in self._cache:
                return self._cache[cache_key]

            try:
                result = await self._call_llm_risk_analysis(
                    element_name=element_name,
                    element_role=element_role,
                    page_url=page_url,
                    goal=goal,
                    nearby_elements=nearby_elements or [],
                )
                result["source"] = "llm"
                self._cache[cache_key] = result
                logger.info(
                    "LLM risk analysis for '%s': risk_level=%d, category=%s, reason=%s",
                    element_name,
                    result.get("risk_level", 0),
                    result.get("risk_category", ""),
                    result.get("reasoning", "")[:100],
                )
                return result
            except Exception as exc:
                logger.warning("LLM risk analysis failed, falling back to safe: %s", exc)

        return {
            "is_high_stakes": False,
            "risk_level": 2,
            "risk_category": "safe",
            "reasoning": "No regex match and LLM analysis unavailable.",
            "source": "fallback",
        }

    def _apply_risk_gate(
        self, risk_level: int, risk_tolerance: int, element_name: str
    ) -> bool:
        """Apply the probabilistic gate based on risk_level vs risk_tolerance.

        - risk_level > risk_tolerance + 2: always hesitate (clearly beyond comfort zone)
        - risk_level > risk_tolerance:     50% chance (borderline discomfort)
        - risk_level <= risk_tolerance:    no hesitation (within comfort zone)
        """
        if risk_level > risk_tolerance + 2:
            logger.info(
                "Hesitation triggered (risk_level=%d >> tolerance=%d) for element: '%s'",
                risk_level, risk_tolerance, element_name,
            )
            return True

        if risk_level > risk_tolerance:
            triggered = self._rng.random() < 0.5
            if triggered:
                logger.info(
                    "Hesitation triggered (risk_level=%d > tolerance=%d, coin flip) for element: '%s'",
                    risk_level, risk_tolerance, element_name,
                )
            return triggered

        return False

    # ------------------------------------------------------------------
    # LLM risk classification
    # ------------------------------------------------------------------

    async def _call_llm_risk_analysis(
        self,
        element_name: str,
        element_role: str,
        page_url: str,
        goal: str,
        nearby_elements: list[str],
    ) -> dict:
        """Call the LLM to classify the risk level of an element action."""
        from langchain_core.messages import HumanMessage

        nearby_str = ", ".join(nearby_elements[:8]) if nearby_elements else "none"
        prompt = _RISK_ANALYSIS_PROMPT.format(
            element_name=element_name,
            element_role=element_role or "unknown",
            page_url=page_url or "unknown",
            goal=goal or "general browsing",
            nearby_elements=nearby_str,
            schema=json.dumps(_RISK_ANALYSIS_SCHEMA, indent=2),
        )

        response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        content = getattr(response, "content", "") or ""
        if not isinstance(content, str):
            content = str(content)

        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        parsed = json.loads(content.strip())
        return {
            "is_high_stakes": bool(parsed.get("is_high_stakes", False)),
            "risk_level": max(1, min(10, int(parsed.get("risk_level", 2)))),
            "risk_category": str(parsed.get("risk_category", "safe")),
            "reasoning": str(parsed.get("reasoning", "")),
        }

    # ------------------------------------------------------------------
    # Prompt and event builders
    # ------------------------------------------------------------------

    def build_hesitation_prompt(
        self,
        element_name: str,
        risk_tolerance: int,
        risk_analysis: dict | None = None,
    ) -> str:
        """Build an injected warning prompt for the agent when hesitation fires."""
        category = ""
        if risk_analysis:
            cat = risk_analysis.get("risk_category", "")
            level = risk_analysis.get("risk_level", 0)
            reason = risk_analysis.get("reasoning", "")
            category = f" (Risk: {cat}, level {level}/10. {reason})"

        return (
            f"⚠️ HESITATION TRIGGERED: You are about to click '{element_name}'.{category} "
            f"This appears to be a high-stakes action. Before proceeding, "
            f"carefully look at the page for: total amounts, recipient names, "
            f"confirmation dialogs. If you cannot clearly see these details, "
            f"abandon this action."
        )

    def create_hesitation_event(
        self,
        element_name: str,
        risk_tolerance: int,
        verification_prompt_injected: bool = True,
        verification_successful: bool = False,
        resulting_behavior: str = "PROCEEDED",
    ) -> HesitationEvent:
        """Construct a :class:`HesitationEvent` from hesitation results."""
        return HesitationEvent(
            trigger_phrase=element_name,
            risk_tolerance=risk_tolerance,
            verification_prompt_injected=verification_prompt_injected,
            verification_successful=verification_successful,
            resulting_behavior=resulting_behavior,
        )

    def clear_cache(self) -> None:
        """Clear the LLM analysis cache (useful between sessions)."""
        self._cache.clear()
