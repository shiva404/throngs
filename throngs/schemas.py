from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field


def _sim_now() -> datetime:
    try:
        from throngs.time.clock import get_clock
        return get_clock().now()
    except (RuntimeError, ImportError):
        return datetime.utcnow()


class UsageFrequency(str, Enum):
    """How often a persona uses the application — drives memory decay rate."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class PerceptionLevel(str, Enum):
    """Controls which visual-perception phases are active.

    Each successive level includes all prior phases.
    """

    BASIC = "basic"        # Original a11y-only perception
    DOM = "dom"            # Phase 1: + enhanced DOM scraping (size/contrast/color)
    SALIENCY = "saliency"  # Phase 1+2: + saliency heatmap
    HYBRID = "hybrid"      # Phase 1+2+3: + True Visibility Score + blindspot filter
    FULL = "full"          # Phase 1+2+3+4: + cognitive overload detection


class PersonaDNA(BaseModel):
    """Persona archetype configuration — the 'DNA Card' for a simulated user."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    domain_literacy: int = Field(ge=1, le=10)
    tech_literacy: int = Field(ge=1, le=10)
    patience_budget: int = Field(gt=0)
    usage_frequency: UsageFrequency = UsageFrequency.WEEKLY
    trigger_words: list[str] = Field(default_factory=list)
    friendly_words: list[str] = Field(default_factory=list)
    # Motor / physical interaction characteristics
    motor_precision: float = Field(default=0.95, ge=0.0, le=1.0)  # 0.95 = desktop, 0.65 = mobile
    risk_tolerance: int = Field(default=5, ge=1, le=10)  # low = hesitates on financial actions
    typo_rate: float = Field(default=0.05, ge=0.0, le=1.0)  # probability of typo per keystroke batch
    usage_device: str = "desktop"  # "desktop" or "mobile"
    interruption_probability: float = Field(default=0.05, ge=0.0, le=1.0)  # chaos monkey trigger rate per action


class LoginCredentials(BaseModel):
    """Login credentials assigned to a persona for authenticated testing."""

    email: str
    password: str
    company_id: str = ""
    notes: str = ""


class MotorErrorEvent(BaseModel):
    """Records a motor error simulation event."""

    event_type: str = "MOTOR_ERROR_SIMULATION"
    error_variant: str  # "FAT_FINGER_MISCLICK" | "TYPO_INJECTION" | "PROXIMITY_ANXIETY"
    intended_element_id: str = ""
    intended_coords: tuple[float, float] = (0.0, 0.0)
    actual_coords: tuple[float, float] = (0.0, 0.0)
    actual_element_id: str = ""  # element actually clicked (if misclick)
    motor_precision_applied: float = 0.0
    original_text: str = ""
    mutated_text: str = ""
    recovery_ux_present: bool = False
    resulting_behavior: str = ""  # "PROCEEDED" | "FRUSTRATION_QUIT" | "RECOVERED"


class HesitationEvent(BaseModel):
    """Records a risk-aversion hesitation event."""

    event_type: str = "HESITATION_EVENT"
    trigger_phrase: str = ""
    risk_tolerance: int = 5
    verification_prompt_injected: bool = False
    verification_successful: bool = False
    resulting_behavior: str = ""  # "PROCEEDED" | "ABANDON_TASK"


class DistractionEvent(BaseModel):
    """Records a contextual distraction event."""

    event_type: str = "CONTEXTUAL_DISTRACTION"
    distraction_variant: str  # "COFFEE_BREAK" | "TAB_SWITCH" | "POPUP_SQUIRREL"
    pre_interruption_url: str = ""
    memory_entries_wiped: int = 0
    narrative: str = ""
    state_preserved_by_app: bool = False
    context_recovered_by_agent: bool = False
    resulting_action: str = ""
    system_feedback_log: str = ""
    sim_time_away_minutes: float = 0.0


class SignalSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUCCESS = "success"


class VisualSignal(BaseModel):
    """A visual feedback signal detected on the page (alert, validation error, toast, etc.)."""

    signal_type: str = ""
    severity: SignalSeverity = SignalSeverity.INFO
    message: str = ""
    source_element: str = ""
    bounding_box: dict[str, float] = Field(default_factory=dict)


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    HOVER = "hover"
    GIVE_UP = "give_up"
    INTERRUPTED = "interrupted"


class LLMResponse(BaseModel):
    """Structured output the LLM must return at each reasoning step."""

    internal_monologue: str
    perceived_clutter_rating: int = Field(ge=1, le=10)
    emotional_state: str
    action_type: ActionType
    target_element_id: str = ""
    input_text: str = ""
    task_completed: bool = False
    session_notes: str = ""


class A11yElement(BaseModel):
    """A single element from the Accessibility tree, enriched with visual data.

    When the perception level is ≥ DOM the Retina layer populates the physical
    and saliency fields.  At HYBRID+ elements that fall below the blindspot
    threshold have ``passed_blindspot`` set to False and are scrubbed from the
    LLM context — the agent literally does not know they exist.
    """

    element_id: str
    role: str
    name: str
    x: float
    y: float
    width: float
    height: float
    value: str = ""
    children_count: int = 0
    # Phase 1 — Physical / style properties
    contrast_ratio: float = 0.0
    text_color: str = ""
    bg_color: str = ""
    opacity: float = 1.0
    semantic_color: str = ""
    size_penalty: float = 0.0
    contrast_penalty: float = 0.0
    # Phase 2+3 — Saliency / visibility
    saliency_intensity: float = 0.0
    true_visibility_score: float = 100.0
    passed_blindspot: bool = True
    # Flags
    visual_flags: list[str] = Field(default_factory=list)


class VisualOverloadInfo(BaseModel):
    """Phase 4 — Visual Cognitive Overload detection results."""

    high_saliency_pct: float = 0.0
    overload_triggered: bool = False
    top_distractor: str = ""
    distraction_note: str = ""


class FrustrationMetrics(BaseModel):
    """Calculated frustration metrics for the current viewport.

    All sub-scores are exposed so product can trace exactly *why*
    frustration changed at each step.
    """

    visual_clutter_score: float = 0.0
    interactable_node_count: int = 0
    cognitive_load_multiplier: float = 1.0
    jargon_density: float = 0.0
    jargon_penalty: float = 0.0
    friendly_relief: float = 0.0
    loop_penalty: float = 0.0
    visual_overload_spike: float = 0.0
    familiarity_discount: float = 1.0
    page_visit_count: int = 1
    tech_scaling_factor: float = 1.0
    progress_relief: float = 0.0
    raw_delta: float = 0.0
    capped_delta: float = 0.0
    carried_frustration: float = 0.0
    total_frustration: float = 0.0
    reasoning: list[str] = Field(default_factory=list)


class ActionLog(BaseModel):
    """Record of a single action taken during simulation.

    Extended with frustration breakdown and visual observations so product
    can trace exactly what happened and why at every step.
    """

    step: int
    timestamp: datetime = Field(default_factory=_sim_now)
    url: str
    page_title: str = ""
    action_type: ActionType
    target_element_id: str = ""
    target_element_name: str = ""
    target_element_role: str = ""
    input_text: str = ""
    x: float = 0.0
    y: float = 0.0
    # LLM reasoning
    frustration_score: float = 0.0
    emotional_state: str = ""
    internal_monologue: str = ""
    perceived_clutter_rating: int = 0
    task_completed: bool = False
    screenshot_path: str = ""
    # Frustration breakdown
    frustration_breakdown: FrustrationMetrics | None = None
    frustration_reasoning: list[str] = Field(default_factory=list)
    # Visual observations
    visual_overload: VisualOverloadInfo | None = None
    interactable_element_count: int = 0
    viewport_coverage_pct: float = 0.0
    # Working memory
    session_notes: str = ""
    # Page signals (alerts, validation errors, toasts)
    visual_signals: list[VisualSignal] = Field(default_factory=list)
    # Motor / hesitation / distraction events for this action step
    motor_error: MotorErrorEvent | None = None
    hesitation: HesitationEvent | None = None
    distraction: DistractionEvent | None = None


class MemoryRecord(BaseModel):
    """Episodic memory of a past task attempt (legacy — see ConsolidatedMemory)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona_id: str
    goal: str
    outcome: str  # "success" | "failure"
    final_url: str = ""
    successful_path: list[str] = Field(default_factory=list)
    total_steps: int = 0
    timestamp: datetime = Field(default_factory=_sim_now)
    notes: str = ""


class ConsolidatedMemory(BaseModel):
    """Long-term memory node produced by the Sleep Cycle consolidation.

    Phase 3 (Neocortex) node schema: stores the heuristic output of
    Phase 2 (Sleep Cycle) consolidation alongside decay metadata for
    Phase 4 (Forgetting Curve) retrieval.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona_id: str
    goal_context: str
    muscle_memory_rule: str
    emotional_scar: str
    outcome: str = ""  # "success" | "failure"
    last_accessed: datetime = Field(default_factory=_sim_now)
    memory_strength: float = 1.0


class SimulationResult(BaseModel):
    """Final result of a single agent simulation run."""

    persona: PersonaDNA
    goal: str
    start_url: str
    outcome: str
    total_steps: int
    total_frustration: float
    action_log: list[ActionLog] = Field(default_factory=list)
    final_url: str = ""
    duration_seconds: float = 0.0


class SwarmReport(BaseModel):
    """Aggregated report from a full swarm run across multiple personas."""

    goal: str
    start_url: str
    total_agents: int
    results: list[SimulationResult] = Field(default_factory=list)
    discoverability_rate: float = 0.0
    avg_steps_to_discovery: float = 0.0
    avg_frustration: float = 0.0
    primary_friction_points: list[str] = Field(default_factory=list)
    report_markdown: str = ""


# ---------------------------------------------------------------------------
# Throng relations: one throng can depend on another in a role (accountant,
# supplier, delivery, etc.). E.g. Furniture Retail has Throng-Y as accountant,
# Throng-Z as delivery; Throng-Z has Throng-Y as accountant, Throng-A as
# vehicle owner, Throng-B as parking vendor.
# ---------------------------------------------------------------------------


class ThrongRole(str, Enum):
    """Role one throng plays for another (provider → owner)."""

    ACCOUNTANT = "accountant"
    ADMIN = "admin"
    ASSISTANT = "assistant"
    BOOKKEEPER = "bookkeeper"
    SUPPLIER = "supplier"
    VENDOR = "vendor"
    DELIVERY = "delivery"
    VEHICLE_OWNER = "vehicle_owner"
    PARKING_VENDOR = "parking_vendor"
    CLIENT = "client"
    CUSTOMER = "customer"
    OTHER = "other"


class ThrongRef(BaseModel):
    """A throng in the relationship graph (business entity; may be tied to a persona)."""

    id: str = Field(description="Unique throng id (e.g. FurnitureRetail, ThrongY)")
    label: str = Field(default="", description="Human-readable label")
    persona_id: Optional[str] = Field(default=None, description="Persona name this throng is played by, if any")


class ThrongRelationship(BaseModel):
    """Owner depends on provider in the given role. E.g. owner=FurnitureRetail, role=accountant, provider=ThrongY."""

    owner_id: str = Field(description="Throng that receives the role (the one who 'has' the other)")
    role: ThrongRole = Field(description="Role the provider plays for the owner")
    provider_id: str = Field(description="Throng that provides the role (accountant, supplier, etc.)")


class ThrongGraphConfig(BaseModel):
    """Config for loading a throng relationship graph (JSON/YAML)."""

    throngs: list[ThrongRef] = Field(default_factory=list, description="All throngs in the graph")
    relationships: list[ThrongRelationship] = Field(
        default_factory=list,
        description="Directed edges: owner_id depends on provider_id in role",
    )
