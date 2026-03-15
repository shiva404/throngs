"""SimulationContext — bundles shared resources for a simulation run.

Instead of passing 8+ individual objects through Runner → build_agent_graph →
node factories, a single ``SimulationContext`` carries everything that is
shared across one run (single agent or swarm).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from throngs.config import settings
from throngs.schemas import PersonaDNA

logger = logging.getLogger(__name__)


@dataclass
class SimulationContext:
    """All shared resources for one simulation run.

    Created once per ``run_single_agent()`` or ``run_swarm()`` call, then
    threaded through the graph builder and node factories.
    """

    # --- Identity ---
    run_id: str = ""

    # --- LLMs ---
    llm: Any = None              # goal_synthesis / general
    vision_llm: Any = None       # reason node (screenshot)

    # --- Browser ---
    browser_manager: Any = None  # BrowserManager
    owns_browser: bool = False   # True if we should start/stop

    # --- Engines (satisfy Protocol interfaces in protocols.py) ---
    persona_engine: Any = None   # PersonaEngine
    frustration_engine: Any = None  # FrustrationStrategy
    memory_store: Any = None     # MemoryBackend

    # --- World simulation (optional) ---
    street_simulation: Any = None
    throng_graph: Any = None
    throng_id: Optional[str] = None

    # --- Dashboard ---
    dashboard_url: Optional[str] = None

    # --- Feature flags (populated from config) ---
    flags: FeatureFlags = field(default_factory=lambda: FeatureFlags())

    # --- Credentials ---
    credentials_file: Optional[str] = None
    company: Optional[str] = None

    async def start_browser(self) -> None:
        if self.browser_manager and self.owns_browser:
            await self.browser_manager.start()

    async def stop_browser(self) -> None:
        if self.browser_manager and self.owns_browser:
            await self.browser_manager.stop()


@dataclass
class FeatureFlags:
    """Centralised feature toggles — one place to check instead of scattered
    ``settings.xyz_enabled`` checks across nodes and engines.

    Populated from ``throngs.config.settings`` by default, or overridden
    in tests / custom runners.
    """

    motor_errors: bool = True
    risk_aversion: bool = True
    hesitation_llm: bool = True
    distraction: bool = True
    distraction_llm: bool = True
    street_simulation: bool = False
    visual_signals: bool = True
    geographic_weighting: bool = True
    skimming: bool = True

    @classmethod
    def from_settings(cls) -> FeatureFlags:
        """Build flags from the global ``settings`` singleton."""
        return cls(
            motor_errors=settings.motor_errors_enabled,
            risk_aversion=settings.risk_aversion_enabled,
            hesitation_llm=settings.hesitation_llm_enabled,
            distraction=settings.distraction_enabled,
            distraction_llm=settings.distraction_llm_enabled,
            street_simulation=settings.street_simulation_enabled,
            visual_signals=settings.visual_signals_enabled,
            geographic_weighting=settings.geographic_weighting_enabled,
            skimming=settings.skimming_enabled,
        )

    @classmethod
    def all_disabled(cls) -> FeatureFlags:
        """All features off — useful for focused testing."""
        return cls(
            motor_errors=False,
            risk_aversion=False,
            hesitation_llm=False,
            distraction=False,
            distraction_llm=False,
            street_simulation=False,
            visual_signals=False,
            geographic_weighting=False,
            skimming=False,
        )
