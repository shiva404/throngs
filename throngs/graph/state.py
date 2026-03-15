from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from throngs.schemas import (
    A11yElement,
    ActionLog,
    ConsolidatedMemory,
    DistractionEvent,
    FrustrationMetrics,
    HesitationEvent,
    LLMResponse,
    LoginCredentials,
    MotorErrorEvent,
    PersonaDNA,
    VisualOverloadInfo,
    VisualSignal,
)


class AgentState(BaseModel):
    """LangGraph state for a single agent simulation run."""

    persona: PersonaDNA
    goal: str
    start_url: str
    current_url: str = ""

    # Multi-goal workflow: ordered list of business tasks.
    # Items are either plain strings (legacy) or dicts with "description" + "software_type" keys.
    goal_chain: list = Field(default_factory=list)
    current_goal_index: int = 0

    # Multi-app workspace — which software is currently open in the browser
    software_registry: dict = Field(default_factory=dict)    # serialized SoftwareRegistry
    active_software_type: str = ""                           # "accounting", "email", "primary"
    active_software_url: str = ""                            # URL of the active app

    step: int = 0
    max_steps: int = 100

    # Perception
    screenshot_b64: str = ""
    screenshot_path: str = ""
    a11y_elements: list[A11yElement] = Field(default_factory=list)
    visible_text: str = ""
    page_title: str = ""

    # Frustration
    frustration_metrics: FrustrationMetrics = Field(
        default_factory=FrustrationMetrics
    )
    cumulative_frustration: float = 0.0

    # Visual perception (Phase 4)
    visual_overload: VisualOverloadInfo = Field(
        default_factory=VisualOverloadInfo
    )

    # Page signals (alerts, validation errors, toasts, banners)
    visual_signals: list[VisualSignal] = Field(default_factory=list)

    # LLM
    llm_response: LLMResponse | None = None

    # Memory
    past_memories: list[ConsolidatedMemory] = Field(default_factory=list)
    memory_prompt: str = ""

    # Within-session working memory — accumulated by the LLM each step
    session_notes: str = ""

    # Logging
    action_log: list[ActionLog] = Field(default_factory=list)

    # Authentication
    credentials: LoginCredentials | None = None
    login_completed: bool = False
    login_redirect: bool = False

    # Profile-setup skip (phone number, passkey, recovery prompts, etc.)
    profile_setup_skipped: bool = False
    profile_setup_redirect: bool = False

    # Distraction / chaos monkey state
    distraction_memory_wipe_pending: bool = False
    distraction_context_prompt: str = ""

    # Motor / hesitation / distraction event logs
    motor_error_log: list[MotorErrorEvent] = Field(default_factory=list)
    hesitation_log: list[HesitationEvent] = Field(default_factory=list)
    distraction_log: list[DistractionEvent] = Field(default_factory=list)

    # Session
    run_id: str = ""
    session_dir: str = ""
    outcome: str = ""  # "", "success", "failure"
    error: str = ""

    @property
    def sim_time(self) -> datetime:
        try:
            from throngs.time.clock import get_clock
            return get_clock().now()
        except (RuntimeError, ImportError):
            return datetime.utcnow()
