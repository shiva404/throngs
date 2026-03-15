"""Protocol interfaces for pluggable engine implementations.

Each cognitive engine has a corresponding Protocol that defines the minimal
interface the graph nodes depend on.  The concrete engines in ``frustration/``,
``motor/``, ``hesitation/``, ``distraction/``, ``memory/``, and ``persona/``
already satisfy these protocols — no changes needed.

To swap in a custom implementation, write a class that implements the relevant
Protocol and register it via ``SWARM_*_ENGINE`` env vars (see config.py).
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from throngs.schemas import (
    A11yElement,
    ActionLog,
    ConsolidatedMemory,
    DistractionEvent,
    FrustrationMetrics,
    HesitationEvent,
    MotorErrorEvent,
    PersonaDNA,
    VisualSignal,
)


# ---------------------------------------------------------------------------
# Frustration
# ---------------------------------------------------------------------------

@runtime_checkable
class FrustrationStrategy(Protocol):
    """Computes cognitive frustration metrics for a given page state."""

    def reset(self) -> None: ...

    def calculate(
        self,
        persona: PersonaDNA,
        a11y_elements: list[A11yElement],
        visible_text: str,
        current_url: str,
        last_action_type: str,
        last_action_target: str,
        cumulative_frustration: float,
        visual_overload: Any | None,
    ) -> FrustrationMetrics: ...

    def should_rage_quit(self, frustration: float, persona: PersonaDNA) -> bool: ...


# ---------------------------------------------------------------------------
# Motor Errors
# ---------------------------------------------------------------------------

@runtime_checkable
class MotorStrategy(Protocol):
    """Simulates human motor imprecision — misclicks, typos, proximity anxiety."""

    def apply_click_scatter(
        self,
        target_el: A11yElement,
        all_elements: list[A11yElement],
        motor_precision: float,
        viewport_width: int,
        viewport_height: int,
        device: str,
    ) -> tuple[float, float, str, bool]: ...

    def inject_typos(self, text: str, typo_rate: float) -> tuple[str, bool]: ...

    def check_proximity_anxiety(
        self,
        target_el: A11yElement,
        all_elements: list[A11yElement],
        device: str,
    ) -> bool: ...

    def create_motor_event(
        self,
        error_variant: str,
        intended_element_id: str,
        intended_coords: tuple[float, float],
        actual_coords: tuple[float, float],
        actual_element_id: str,
        motor_precision_applied: float,
        original_text: str = "",
        mutated_text: str = "",
        resulting_behavior: str = "PROCEEDED",
    ) -> MotorErrorEvent: ...


# ---------------------------------------------------------------------------
# Hesitation / Risk Aversion
# ---------------------------------------------------------------------------

@runtime_checkable
class HesitationStrategy(Protocol):
    """Gates high-stakes actions with risk-aversion checks."""

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
    ) -> bool: ...

    async def analyze_risk(
        self,
        element_name: str,
        element_role: str = "",
        page_url: str = "",
        goal: str = "",
        nearby_elements: list[str] | None = None,
    ) -> dict: ...

    def build_hesitation_prompt(
        self,
        element_name: str,
        risk_tolerance: int,
        risk_analysis: dict | None = None,
    ) -> str: ...

    def create_hesitation_event(
        self,
        element_name: str,
        risk_tolerance: int,
        verification_prompt_injected: bool = True,
        verification_successful: bool = False,
        resulting_behavior: str = "PROCEEDED",
    ) -> HesitationEvent: ...


# ---------------------------------------------------------------------------
# Distraction
# ---------------------------------------------------------------------------

@runtime_checkable
class DistractionStrategy(Protocol):
    """Contextual interruption engine — the "Chaos Monkey"."""

    def should_trigger_interruption(
        self,
        action_count: int,
        interruption_probability: float,
    ) -> bool: ...

    def detect_squirrel(
        self,
        visual_signals: list[VisualSignal],
        goal: str,
    ) -> VisualSignal | None: ...

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
    ) -> dict: ...

    def create_distraction_event(
        self,
        variant: str,
        pre_url: str,
        memory_wiped: int,
        narrative: str = "",
        feedback: str = "",
        state_preserved_by_app: bool = False,
        context_recovered_by_agent: bool = False,
        resulting_action: str = "",
        sim_time_away_minutes: float = 0.0,
    ) -> DistractionEvent: ...


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@runtime_checkable
class MemoryBackend(Protocol):
    """Cognitive memory store with sleep-cycle consolidation and decay-aware recall."""

    async def run_sleep_cycle(
        self,
        persona_id: str,
        goal: str,
        action_log: list[ActionLog],
        outcome: str,
        persona_description: str = "",
    ) -> ConsolidatedMemory | None: ...

    def recall(
        self,
        persona_id: str,
        goal: str,
        usage_frequency: Any = None,
        top_k: int = 5,
    ) -> list[tuple[ConsolidatedMemory, float, str]]: ...

    def build_memory_prompt(
        self,
        persona_id: str,
        goal: str,
        usage_frequency: Any = None,
    ) -> str: ...
