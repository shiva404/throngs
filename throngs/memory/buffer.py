"""Phase 1 — The Waking State (Short-Term Buffer / Hippocampus).

Captures every raw interaction during an active simulation run as an
unstructured chronological log.  Data lives in-memory and is wiped after
the Sleep Cycle (Phase 2) processes it.

The current implementation uses a plain Python dict.  The interface is
designed so that a Redis-backed implementation can be swapped in later
without changing callers.
"""

from __future__ import annotations

import logging
from typing import Any

from throngs.schemas import ActionLog

logger = logging.getLogger(__name__)


class ShortTermBuffer:
    """In-memory short-term event buffer — one session log per persona+goal."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _key(persona_id: str, goal: str) -> str:
        return f"{persona_id}::{goal}"

    def record_events(
        self,
        persona_id: str,
        goal: str,
        action_log: list[ActionLog],
    ) -> None:
        """Store a full session's raw interaction events."""
        key = self._key(persona_id, goal)
        self._sessions[key] = [
            {
                "step": log.step,
                "timestamp": log.timestamp.isoformat(),
                "url": log.url,
                "action_type": log.action_type.value,
                "target_element_id": log.target_element_id,
                "input_text": log.input_text,
                "frustration_score": log.frustration_score,
                "emotional_state": log.emotional_state,
                "internal_monologue": log.internal_monologue,
            }
            for log in action_log
        ]
        logger.debug(
            "Buffered %d events for persona=%s goal='%s'",
            len(action_log),
            persona_id,
            goal,
        )

    def get_session(self, persona_id: str, goal: str) -> list[dict[str, Any]]:
        """Retrieve the raw event log for a given session."""
        return self._sessions.get(self._key(persona_id, goal), [])

    def clear_session(self, persona_id: str, goal: str) -> None:
        """Wipe the short-term buffer after consolidation."""
        key = self._key(persona_id, goal)
        self._sessions.pop(key, None)
        logger.debug("Cleared buffer for persona=%s goal='%s'", persona_id, goal)
