"""Build a JSON-serializable agent state snapshot for the real-time dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def build_snapshot(state_dict: dict[str, Any], node_name: str = "") -> dict[str, Any]:
    """
    Build a snapshot dict from the graph state dict for SSE/UI.

    Truncates long text and ensures all values are JSON-serializable.
    """
    persona = state_dict.get("persona") or {}
    llm_raw = state_dict.get("llm_response") or {}
    action_log = state_dict.get("action_log") or []

    def _to_dict(obj: Any) -> dict:
        """Normalize Pydantic model or dict to dict for .get() access."""
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "__dict__"):
            return getattr(obj, "__dict__", {})
        return {}

    llm = _to_dict(llm_raw)
    thought = ""
    emotional_state = ""
    action_type = ""
    target_element_id = ""
    target_element_name = ""

    def _str_action(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v[:50]
        if hasattr(v, "value"):
            return getattr(v, "value", str(v))
        return str(v)

    if llm:
        thought = (llm.get("internal_monologue") or "")[:800]
        emotional_state = (llm.get("emotional_state") or "")[:200]
        action_type = _str_action(llm.get("action_type"))
        target_element_id = (llm.get("target_element_id") or "")[:80]

    distraction_variant: str | None = None
    if action_log:
        last_raw = action_log[-1] if action_log else {}
        last = _to_dict(last_raw)
        if last:
            if not thought:
                thought = (last.get("internal_monologue") or "")[:800]
                emotional_state = (last.get("emotional_state") or "")[:200]
                action_type = _str_action(last.get("action_type"))
                target_element_id = (last.get("target_element_id") or "")[:80]
                target_element_name = (last.get("target_element_name") or "")[:120]
            # Surface last distraction for street UI (phone ring / email animation)
            dist = last.get("distraction")
            if dist:
                d = _to_dict(dist)
                distraction_variant = (d.get("variant") or "")[:32] or None

    persona_name = (persona.get("name") or "Agent") if isinstance(persona, dict) else "Agent"
    patience_budget = 50
    if isinstance(persona, dict) and "patience_budget" in persona:
        patience_budget = int(persona["patience_budget"]) or 50

    memory_prompt = (state_dict.get("memory_prompt") or "")[:1200]
    session_notes = (state_dict.get("session_notes") or "")[:800]

    # Global sim time from runner's clock so dashboard street UI stays in sync
    sim_minute_of_day: int | None = None
    sim_day_num: int | None = None
    try:
        from throngs.time.clock import get_clock
        sim_now = get_clock().now()
        sim_start = get_clock().sim_start
        sim_minute_of_day = sim_now.hour * 60 + sim_now.minute
        sim_day_num = max(1, (sim_now.date() - sim_start.date()).days + 1)
    except (RuntimeError, AttributeError):
        pass

    out = {
        "event": "agent_state",
        "node": node_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": (state_dict.get("run_id") or "")[:64],
        "persona_name": persona_name,
        "goal": (state_dict.get("goal") or "")[:300],
        "step": int(state_dict.get("step") or 0),
        "max_steps": int(state_dict.get("max_steps") or 100),
        "current_url": (state_dict.get("current_url") or "")[:500],
        "page_title": (state_dict.get("page_title") or "")[:200],
        "thought": thought,
        "emotional_state": emotional_state,
        "action_type": action_type,
        "target_element_id": target_element_id,
        "target_element_name": target_element_name,
        "frustration": round(float(state_dict.get("cumulative_frustration") or 0), 2),
        "patience_budget": patience_budget,
        "memory_snapshot": memory_prompt,
        "session_notes": session_notes,
        "outcome": (state_dict.get("outcome") or "")[:32],
        "error": (state_dict.get("error") or "")[:200],
        "clutter_rating": _get_clutter(state_dict, llm),
    }
    if distraction_variant is not None:
        out["distraction_variant"] = distraction_variant
    if sim_minute_of_day is not None:
        out["sim_minute_of_day"] = sim_minute_of_day
    if sim_day_num is not None:
        out["sim_day_num"] = sim_day_num
    return out


def _get_clutter(state_dict: Any, llm: dict) -> int:
    if isinstance(llm, dict) and "perceived_clutter_rating" in llm:
        return int(llm["perceived_clutter_rating"])
    return 0
