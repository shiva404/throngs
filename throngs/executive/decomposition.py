"""
Phase 3 Level 2: Task Decomposition (How to do it).

Breaks the software portion of the macro-goal into ordered sub-tasks for
execution handoff to the Perception Layer. Spec: Section 3 Level 2.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


DECOMPOSE_PROMPT = """\
Given this software goal for a user in a web application, list 3–8 concrete sub-tasks in order.
Each sub-task should be one short sentence (e.g. "Open the app", "Navigate to Invoices", "Find the Smith invoice").
Output ONLY a JSON array of strings, e.g. ["Open the app", "Go to Invoices", "Check Smith invoice status"].
Goal: {goal}
"""


def decompose_goal(macro_goal: str, llm: Any) -> list[str]:
    """
    Phase 3 Level 2: Break the software goal into ordered sub-tasks for execution handoff.

    Returns a list of sub-task strings that can be passed to the Perception Layer.
    The existing graph already executes step-by-step; this is for optional pre-planning or logging.
    """
    from langchain_core.messages import HumanMessage

    prompt = DECOMPOSE_PROMPT.format(goal=macro_goal)
    response = llm.invoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", "") or (response if isinstance(response, str) else "")
    if not isinstance(content, str):
        content = str(content)
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        )
    try:
        steps = json.loads(content)
        if isinstance(steps, list) and all(isinstance(s, str) for s in steps):
            return [s.strip() for s in steps if s.strip()]
    except json.JSONDecodeError:
        logger.warning("Task decomposition response was not valid JSON; returning single-step.")
    return [macro_goal]
