"""Cognitive Memory Store — four-phase biological memory system.

Orchestrates all four phases of the Cognitive Memory Subsystem:

Phase 1 (Hippocampus)  — ShortTermBuffer captures raw interaction events.
Phase 2 (Sleep Cycle)  — LLM consolidation of raw events into heuristics.
Phase 3 (Neocortex)    — ChromaDB long-term vault with semantic retrieval.
Phase 4 (Forgetting)   — Ebbinghaus decay applied at retrieval time.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb

from throngs.config import settings
from throngs.llm import create_llm_for_task


def _sim_now() -> datetime:
    try:
        from throngs.time.clock import get_clock
        return get_clock().now()
    except (RuntimeError, ImportError):
        return datetime.utcnow()
from throngs.memory.buffer import ShortTermBuffer
from throngs.memory.decay import MemoryDecayEngine
from throngs.schemas import ActionLog, ConsolidatedMemory, UsageFrequency

logger = logging.getLogger(__name__)


CONSOLIDATION_PROMPT = """\
You are a memory consolidation engine for a simulated user-testing system.

A simulated user persona just completed a session trying to accomplish a goal \
inside a web application.  Below is the raw chronological log of every action \
they took, including frustration scores and internal thoughts.

PERSONA: {persona_desc}
GOAL: {goal}
OUTCOME: {outcome}

--- RAW INTERACTION LOG ---
{raw_log}
--- END LOG ---

Your job is to distill this raw log into a single consolidated memory, the \
way a human brain consolidates experiences during sleep.

Return ONLY valid JSON with these exact keys:
{{
  "goal_context": "<1-2 sentence summary of what the persona was trying to achieve>",
  "muscle_memory_rule": "<single-sentence heuristic describing the successful navigation path, or the best attempt if the task failed. Be specific about UI elements and menu paths.>",
  "emotional_scar": "<the specific UI element or interaction that caused the highest spike in frustration — include the element name/id and why it was painful>"
}}

Do NOT wrap the JSON in markdown code fences.  Return raw JSON only.
"""


class CognitiveMemoryStore:
    """Four-phase cognitive memory system for simulated user agents."""

    COLLECTION_NAME = "cognitive_memory"

    def __init__(
        self,
        persist_dir: str | None = None,
        consolidation_llm: Any | None = None,
    ) -> None:
        persist = persist_dir or settings.chromadb_persist_dir
        Path(persist).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=persist)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._buffer = ShortTermBuffer()
        self._decay = MemoryDecayEngine()
        self._consolidation_llm = consolidation_llm
        logger.info("Cognitive memory store initialized at %s", persist)

    # ------------------------------------------------------------------
    # Phase 1 — Short-Term Buffer (Hippocampus)
    # ------------------------------------------------------------------

    def buffer_session(
        self,
        persona_id: str,
        goal: str,
        action_log: list[ActionLog],
    ) -> None:
        """Capture a full session's raw events into the short-term buffer."""
        self._buffer.record_events(persona_id, goal, action_log)

    # ------------------------------------------------------------------
    # Phase 2 — Sleep Cycle (Memory Consolidation)
    # ------------------------------------------------------------------

    async def run_sleep_cycle(
        self,
        persona_id: str,
        goal: str,
        action_log: list[ActionLog],
        outcome: str,
        persona_description: str = "",
    ) -> ConsolidatedMemory | None:
        """Consolidate a session's raw events into a long-term memory.

        1. Buffer the raw events  (Phase 1)
        2. Consolidate via LLM    (Phase 2)
        3. Save to vector DB      (Phase 3)
        4. Clear the buffer
        """
        self._buffer.record_events(persona_id, goal, action_log)
        raw_events = self._buffer.get_session(persona_id, goal)

        if not raw_events:
            logger.warning("No events to consolidate for persona=%s", persona_id)
            return None

        consolidated = await self._consolidate(
            persona_id=persona_id,
            goal=goal,
            raw_events=raw_events,
            outcome=outcome,
            persona_description=persona_description,
        )

        if consolidated:
            self._save_to_vault(consolidated)

        self._buffer.clear_session(persona_id, goal)
        return consolidated

    async def _consolidate(
        self,
        persona_id: str,
        goal: str,
        raw_events: list[dict[str, Any]],
        outcome: str,
        persona_description: str,
    ) -> ConsolidatedMemory | None:
        """Use a fast LLM to distill raw events into a heuristic memory."""
        raw_log = self._format_raw_log(raw_events)

        prompt_text = CONSOLIDATION_PROMPT.format(
            persona_desc=persona_description or "Unknown persona",
            goal=goal,
            outcome=outcome,
            raw_log=raw_log,
        )

        llm = self._get_consolidation_llm()

        try:
            from langchain_core.messages import HumanMessage

            response = await llm.ainvoke([HumanMessage(content=prompt_text)])
            raw_json = response.content.strip()
            if raw_json.startswith("```"):
                raw_json = raw_json.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(raw_json)

            memory = ConsolidatedMemory(
                persona_id=persona_id,
                goal_context=parsed.get("goal_context", goal),
                muscle_memory_rule=parsed.get("muscle_memory_rule", ""),
                emotional_scar=parsed.get("emotional_scar", ""),
                outcome=outcome,
                last_accessed=_sim_now(),
                memory_strength=1.0,
            )
            logger.info(
                "Consolidated memory for persona=%s: rule='%s'",
                persona_id,
                memory.muscle_memory_rule[:80],
            )
            return memory

        except Exception as e:
            logger.error("Sleep cycle consolidation failed: %s", e)
            return self._fallback_consolidation(
                persona_id, goal, raw_events, outcome
            )

    def _fallback_consolidation(
        self,
        persona_id: str,
        goal: str,
        raw_events: list[dict[str, Any]],
        outcome: str,
    ) -> ConsolidatedMemory:
        """Deterministic fallback when the LLM consolidation fails."""
        path_elements = [
            ev["target_element_id"]
            for ev in raw_events
            if ev.get("target_element_id")
        ]
        path_desc = " -> ".join(path_elements) if path_elements else "unknown path"

        worst_event = max(raw_events, key=lambda e: e.get("frustration_score", 0))
        scar = (
            f"Element '{worst_event.get('target_element_id', '?')}' at "
            f"{worst_event.get('url', '?')} "
            f"(frustration={worst_event.get('frustration_score', 0):.1f})"
        )

        rule = f"Navigate via: {path_desc}" if outcome == "success" else (
            f"Attempted path: {path_desc} (failed after {len(raw_events)} steps)"
        )

        return ConsolidatedMemory(
            persona_id=persona_id,
            goal_context=goal,
            muscle_memory_rule=rule,
            emotional_scar=scar,
            outcome=outcome,
            last_accessed=_sim_now(),
            memory_strength=1.0,
        )

    @staticmethod
    def _format_raw_log(events: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for ev in events:
            lines.append(
                f"[Step {ev.get('step', '?')}] "
                f"{ev.get('action_type', '?')} on '{ev.get('target_element_id', '-')}' "
                f"at {ev.get('url', '?')} | "
                f"frustration={ev.get('frustration_score', 0):.1f} | "
                f"emotion={ev.get('emotional_state', '?')} | "
                f"thought: {ev.get('internal_monologue', '')[:120]}"
            )
        return "\n".join(lines)

    def _get_consolidation_llm(self) -> Any:
        if self._consolidation_llm is not None:
            return self._consolidation_llm
        self._consolidation_llm = create_llm_for_task("consolidation")
        return self._consolidation_llm

    # ------------------------------------------------------------------
    # Phase 3 — Neocortex (Long-Term Vault)
    # ------------------------------------------------------------------

    def _save_to_vault(self, memory: ConsolidatedMemory) -> None:
        """Persist a consolidated memory into the vector database."""
        doc_text = (
            f"Goal: {memory.goal_context}\n"
            f"Rule: {memory.muscle_memory_rule}\n"
            f"Scar: {memory.emotional_scar}"
        )
        metadata = {
            "persona_id": memory.persona_id,
            "goal_context": memory.goal_context,
            "muscle_memory_rule": memory.muscle_memory_rule,
            "emotional_scar": memory.emotional_scar,
            "outcome": memory.outcome,
            "last_accessed": memory.last_accessed.isoformat(),
            "memory_strength": memory.memory_strength,
        }
        self._collection.upsert(
            ids=[memory.id],
            documents=[doc_text],
            metadatas=[metadata],
        )
        logger.info(
            "Saved to vault: persona=%s goal='%s'",
            memory.persona_id,
            memory.goal_context[:60],
        )

    # ------------------------------------------------------------------
    # Phase 3 + 4 — Retrieval with Decay
    # ------------------------------------------------------------------

    def recall(
        self,
        persona_id: str,
        goal: str,
        usage_frequency: UsageFrequency = UsageFrequency.WEEKLY,
        top_k: int = 5,
    ) -> list[tuple[ConsolidatedMemory, float, str]]:
        """Retrieve relevant memories with decay applied.

        Returns a list of (memory, current_strength, recall_state) tuples.
        Forgotten memories (M < 0.4) are excluded entirely.
        Successfully recalled memories get their ``last_accessed`` reinforced.
        """
        results = self._collection.query(
            query_texts=[f"Goal: {goal}"],
            n_results=top_k,
            where={"persona_id": persona_id},
        )

        recalled: list[tuple[ConsolidatedMemory, float, str]] = []

        if not results or not results["metadatas"]:
            return recalled

        for i, meta in enumerate(results["metadatas"][0]):
            last_accessed = datetime.fromisoformat(meta["last_accessed"])
            strength = self._decay.current_strength(
                last_accessed=last_accessed,
                usage_frequency=usage_frequency,
            )
            recall_state = self._decay.classify_recall(strength)

            if recall_state == "forgotten":
                continue

            memory = ConsolidatedMemory(
                id=results["ids"][0][i],
                persona_id=meta["persona_id"],
                goal_context=meta.get("goal_context", ""),
                muscle_memory_rule=meta.get("muscle_memory_rule", ""),
                emotional_scar=meta.get("emotional_scar", ""),
                outcome=meta.get("outcome", ""),
                last_accessed=last_accessed,
                memory_strength=strength,
            )
            recalled.append((memory, strength, recall_state))

            self._reinforce(results["ids"][0][i])

        return recalled

    def _reinforce(self, memory_id: str) -> None:
        """Reset last_accessed to now — successful recall reinforces memory."""
        now = _sim_now()
        self._collection.update(
            ids=[memory_id],
            metadatas=[{"last_accessed": now.isoformat(), "memory_strength": 1.0}],
        )

    # ------------------------------------------------------------------
    # Prompt builder (used by agent initialisation)
    # ------------------------------------------------------------------

    def build_memory_prompt(
        self,
        persona_id: str,
        goal: str,
        usage_frequency: UsageFrequency = UsageFrequency.WEEKLY,
    ) -> str:
        """Build a decay-aware memory fragment for the agent's system prompt."""
        recalled = self.recall(persona_id, goal, usage_frequency)

        if not recalled:
            return "You have no prior experience with this task."

        lines: list[str] = []

        for memory, strength, state in recalled:
            if state == "perfect":
                lines.append(
                    f"  - You clearly remember: {memory.muscle_memory_rule}"
                )
                if memory.emotional_scar:
                    lines.append(
                        f"    (Warning: {memory.emotional_scar})"
                    )
            elif state == "fuzzy":
                hint = self._decay.obfuscate_rule(memory.muscle_memory_rule)
                lines.append(f"  - {hint}")

        if not lines:
            return "You have no prior experience with this task."

        header = "You have memories of attempting this before:"
        return "\n".join([header, *lines])
