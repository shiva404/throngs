from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

def _lazy_run_id() -> str:
    """Generate a unique run ID. Called at first access, not at import time."""
    return "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


# Legacy module-level run_id — used by default output paths.
# Prefer generating per-run IDs via runner._make_run_id() instead.
run_id: str = _lazy_run_id()

# Task names for LLM assignment (used by create_llm_for_task)
LLMTask = Literal[
    "goal_synthesis",   # Executive Level 1 — fast, text-only
    "reason",          # Graph reason node — vision + complex UI reasoning
    "report",          # Analytics — summarization, text
    "task_decomposition",  # Executive Level 2 — fast, text
    "consolidation",   # Memory sleep cycle — fast, text
    "hesitation",      # Risk analysis for high-stakes action gating — fast, text
    "distraction",     # Contextual distraction generation — persona-aware
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SWARM_",
        case_sensitive=False,
    )

    # Local LLM endpoint (only option)
    local_base_url: str = "http://localhost:4000"
    local_model: str = "local-gpt-oss"
    local_vision_model: str = "local-gpt-oss"
    local_api_key: Optional[str] = "no-key-required"

    # Per-task model overrides (optional). If unset, default for that task is used.
    model_goal_synthesis: Optional[str] = "local-gpt-oss"
    model_reason: Optional[str] = "local-gpt-oss" # Vision-capable model for reasoning tasks
    model_report: Optional[str] = "local-gpt-oss"
    model_task_decomposition: Optional[str] = "local-gpt-oss"

    # Default "fast" model for lightweight tasks (synthesis, decomposition)
    local_model_fast: str = "local-gpt-oss"

    max_concurrent_agents: int = 10
    browser_headless: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720
    page_settle_seconds: float = 4.0
    post_action_wait_seconds: float = 2.0

    chromadb_persist_dir: str = "./chroma_data"

    # Visual Perception — Retina layer
    perception_level: str = "basic"  # basic | dom | saliency | hybrid | full
    visual_signals_enabled: bool = True
    visibility_threshold: float = 20.0  # blindspot cutoff (0-100%)
    fat_finger_min_px: int = 44  # WCAG minimum touch-target dimension
    wcag_min_contrast: float = 4.5  # minimum text/bg contrast ratio
    visual_overload_clutter_pct: float = 35.0  # % high-intensity saliency to trigger overload
    visual_overload_frustration_spike: float = 4.0

    # Phase 2: Sleep Cycle — consolidation LLM (task: consolidation)
    consolidation_model: str = "local-gpt-oss"

    # Phase 4: Memory Decay — Ebbinghaus forgetting curve thresholds
    memory_perfect_recall_threshold: float = 0.7
    memory_fuzzy_recall_threshold: float = 0.4

    # Decay rates (k) per persona usage frequency.
    # Lower k → slower forgetting; higher k → faster forgetting.
    decay_rate_daily: float = 0.05
    decay_rate_weekly: float = 0.15
    decay_rate_monthly: float = 0.3
    decay_rate_quarterly: float = 0.5

    # Motor Errors
    motor_errors_enabled: bool = True
    motor_offset_scale_desktop: float = 0.008  # fraction of viewport for offset radius
    motor_offset_scale_mobile: float = 0.025   # fraction of viewport for offset radius (mobile)
    proximity_min_margin_desktop: int = 8      # pixels minimum spacing between critical buttons
    proximity_min_margin_mobile: int = 16      # pixels minimum spacing for mobile

    # Risk Aversion / Hesitation
    risk_aversion_enabled: bool = True
    hesitation_llm_enabled: bool = True  # Use LLM for dynamic high-stakes detection (falls back to regex if False/unavailable)
    model_hesitation: Optional[str] = None  # Override model for hesitation analysis

    # Contextual Distraction
    distraction_enabled: bool = True
    distraction_llm_enabled: bool = True
    model_distraction: Optional[str] = None

    # F-Pattern Geographic Weighting
    geographic_weighting_enabled: bool = True

    # Skimming
    skimming_enabled: bool = True
    skimming_max_list_items: int = 4  # max items shown to low-patience persona

    output_dir: str = f"/opt/data/throngs/workspace/{run_id}"
    screenshots_dir: str = f"/opt/data/throngs/workspace/{run_id}/screenshots"
    heatmaps_dir: str = f"/opt/data/throngs/workspace/{run_id}/heatmaps"
    reports_dir: str = f"/opt/data/throngs/workspace/{run_id}/reports"

    rate_limit_rpm: int = 60
    rate_limit_backoff_base: float = 2.0
    rate_limit_max_retries: int = 5

    # Simulation time scale
    sim_time_scale_factor: float = 10.0   # SWARM_SIM_TIME_SCALE_FACTOR — real secs per sim minute
    sim_start_time: Optional[str] = None  # SWARM_SIM_START_TIME (ISO datetime, e.g. 2026-01-15T09:00:00)

    # Diary-based goal inspiration
    diary_entries_dir: str = "diary_entries"  # SWARM_DIARY_ENTRIES_DIR — path to persona diary folders

    # Street simulation
    street_simulation_enabled: bool = False  # SWARM_STREET_SIMULATION_ENABLED
    street_initial_bank_balance: float = 5000.0  # SWARM_STREET_INITIAL_BANK_BALANCE
    street_bank_db: str = "data/street_bank.db"  # SQLite path for persisting bank balances

    # Software stack — path to JSON defining available apps (accounting, email, etc.)
    software_stack_path: Optional[str] = None  # SWARM_SOFTWARE_STACK_PATH

    # Personas directory — switch to "persona-single" for single-persona debug runs.
    # All persona-related file defaults (default_personas.json, credentials.json, etc.)
    # are resolved relative to this directory.
    # Example: SWARM_PERSONAS_DIR=persona-single poetry run throngs ...
    personas_dir: str = "persona"  # SWARM_PERSONAS_DIR


settings = Settings()


def _parse_sim_start(iso_str: Optional[str]) -> Optional[datetime.datetime]:
    if not iso_str:
        return None
    return datetime.datetime.fromisoformat(iso_str)
