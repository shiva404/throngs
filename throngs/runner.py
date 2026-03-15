from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from asyncio_throttle import Throttler

from throngs.analytics.pipeline import AnalyticsPipeline, dump_traces
from throngs.config import settings
from throngs.context import FeatureFlags, SimulationContext
from throngs.dashboard.snapshot import build_snapshot
from throngs.frustration import FrustrationEngine
from throngs.executive import synthesize_goal, synthesize_goal_chain
from throngs.graph.agent import build_agent_graph
from throngs.graph.state import AgentState
from throngs.llm import create_llm_for_task
from throngs.memory import CognitiveMemoryStore
from throngs.perception.browser import BrowserManager
from throngs.persona import PersonaEngine
from throngs.relations import ThrongGraph, load_throng_graph
from throngs.schemas import PersonaDNA, SimulationResult, SwarmReport
from throngs.workspace import SoftwareRegistry


logger = logging.getLogger(__name__)


def _make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


async def _emit_dashboard_snapshot(
    dashboard_url: str, state_dict: dict, node_name: str
) -> None:
    """POST agent state snapshot to dashboard SSE broadcaster (fire-and-forget)."""
    try:
        import httpx
        snapshot = build_snapshot(state_dict, node_name=node_name)
        base = dashboard_url.rstrip("/")
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{base}/event", json=snapshot)
    except Exception as e:
        logger.debug("Dashboard emit failed: %s", e)


async def run_single_agent(
    persona: PersonaDNA,
    goal: str | None,
    start_url: str = "",
    *,
    software_registry=None,
    llm=None,
    vision_llm=None,
    browser_manager: BrowserManager | None = None,
    persona_engine: PersonaEngine | None = None,
    frustration_engine: FrustrationEngine | None = None,
    memory_store: CognitiveMemoryStore | None = None,
    max_steps: int = 50,
    credentials_file: str | None = None,
    company: str | None = None,
    goal_check_callback=None,
    run_id: str | None = None,
    dashboard_url: str | None = None,
    throng_graph: ThrongGraph | None = None,
    throng_id: str | None = None,
    street_simulation=None,
) -> SimulationResult:
    """Run a single agent simulation through the LangGraph pipeline.

    If goal is None, an actionable goal is synthesized on-demand from the persona's
    inner voice (Autonomous Executive Function spec, Level 1 executive decision).

    throng_graph / throng_id: when set, relationship context (e.g. "you are accountant
    for X; you depend on Y for delivery") is injected into goal synthesis. If throng_id
    is None, it is resolved from the graph by persona.name matching a ThrongRef.persona_id.
    """
    run_id = run_id or _make_run_id()
    logger.info("Starting agent run_id=%s persona=%s url=%s", run_id, persona.name, start_url)

    # Build SoftwareRegistry if not provided (backward compat: single URL → one-entry registry)
    if software_registry is None and start_url:
        software_registry = SoftwareRegistry.from_single_url(start_url)
    elif software_registry is None:
        software_registry = SoftwareRegistry()

    from throngs.time.clock import start_clock
    from throngs.config import _parse_sim_start
    sim_start = None
    if settings.sim_start_time:
        try:
            sim_start = _parse_sim_start(settings.sim_start_time)
        except ValueError:
            logger.warning(
                "Invalid SWARM_SIM_START_TIME=%r, defaulting to today 09:00",
                settings.sim_start_time,
            )
    start_clock(scale_factor=settings.sim_time_scale_factor, sim_start=sim_start)
    logger.info(
        "Simulation clock: scale=%.1fx, sim_start=%s",
        settings.sim_time_scale_factor,
        sim_start,
    )

    # Street simulation (optional — enabled via SWARM_STREET_SIMULATION_ENABLED)
    if street_simulation is None and settings.street_simulation_enabled:
        from throngs.street.simulation import ShopConfig, StreetSimulation
        from throngs.time.clock import get_clock
        shop_cfg = ShopConfig(
            persona_name=persona.name,
            persona_description=persona.description,
            initial_bank_balance=settings.street_initial_bank_balance,
        )
        street_simulation = StreetSimulation([shop_cfg])
        street_simulation.tick(get_clock().now())  # initial tick to set baseline
        logger.info("Street simulation enabled for %s (shop_type=%s)", persona.name, shop_cfg.shop_type)

    llm = llm or create_llm_for_task("goal_synthesis")
    vision_llm = vision_llm or create_llm_for_task("reason")
    own_browser = browser_manager is None
    browser_manager = browser_manager or BrowserManager()
    persona_engine = persona_engine or PersonaEngine()
    frustration_engine = frustration_engine or FrustrationEngine()
    memory_store = memory_store or CognitiveMemoryStore()

    persona_engine.load_persona(persona)
    if credentials_file:
        persona_engine.load_credentials(credentials_file, company=company)
    frustration_engine.reset()

    goal_chain: list = []
    if goal is None or not goal.strip():
        relation_context = None
        if throng_graph:
            tid = throng_id or throng_graph.throng_id_for_persona(persona.name)
            if tid:
                relation_context = throng_graph.context_for_throng(tid)

        from throngs.diary.loader import load_diary_snippet
        diary_context = load_diary_snippet(persona.name, settings.diary_entries_dir)
        if diary_context:
            logger.info("Loaded diary inspiration for %s", persona.name)

        # Enrich world state from street simulation
        street_world_state = {}
        if street_simulation is not None:
            street_world_state = street_simulation.world_state_for_persona(persona.name)

        goal_chain = synthesize_goal_chain(
            persona=persona,
            start_url=start_url,
            llm=llm,
            persona_engine=persona_engine,
            relation_context=relation_context,
            diary_context=diary_context,
            world_state_dict=street_world_state if street_world_state else None,
            software_registry=software_registry,
        )
        # Resolve first goal — may be a dict (service business) or string (legacy)
        if goal_chain:
            first = goal_chain[0]
            goal = first.get("description", str(first)) if isinstance(first, dict) else str(first)
        else:
            goal = "Complete a realistic task in the application."
        logger.info("Synthesized goal chain for %s (%d steps), first: %s", persona.name, len(goal_chain), goal[:80])
    else:
        goal_chain = [goal]

    # Determine the initial URL to navigate to
    # For multi-app registries, use the first goal's software_type or fall back to primary
    initial_url = start_url
    initial_software_type = ""
    initial_software_url = ""
    if software_registry.entries:
        if goal_chain and isinstance(goal_chain[0], dict):
            sw_type = goal_chain[0].get("software_type", "")
            entry = software_registry.get(sw_type) if sw_type else None
            if entry:
                initial_url = entry.url
                initial_software_type = entry.software_type
                initial_software_url = entry.url
        if not initial_software_type:
            primary = software_registry.primary()
            initial_url = initial_url or primary.url
            initial_software_type = primary.software_type
            initial_software_url = primary.url

    if own_browser:
        await browser_manager.start()

    ctx = await browser_manager.new_context()
    page = await ctx.new_page()
    await page.goto(initial_url, wait_until="domcontentloaded", timeout=60_000)

    browser_manager.register_page(persona.name, page)

    graph = build_agent_graph(
        llm=llm,
        vision_llm=vision_llm,
        browser_manager=browser_manager,
        persona_engine=persona_engine,
        frustration_engine=frustration_engine,
        memory_store=memory_store,
        street_simulation=street_simulation,
    )

    creds = persona_engine.get_credentials(persona.name)
    initial_state = AgentState(
        persona=persona,
        goal=goal,
        start_url=initial_url,
        goal_chain=goal_chain,
        current_goal_index=0,
        max_steps=max_steps,
        credentials=creds,
        run_id=run_id,
        software_registry=software_registry.model_dump(),
        active_software_type=initial_software_type,
        active_software_url=initial_software_url,
    )

    t0 = time.monotonic()

    state_dict = initial_state.model_dump()
    final_state_dict = state_dict

    async for event in graph.astream(state_dict):
        for node_name, node_output in event.items():
            if isinstance(node_output, dict):
                final_state_dict.update(node_output)
            logger.debug("Node '%s' completed", node_name)

            if dashboard_url:
                await _emit_dashboard_snapshot(
                    dashboard_url, final_state_dict, node_name
                )

            if goal_check_callback and node_name == "execute_action":
                if await goal_check_callback(page, final_state_dict):
                    from throngs.graph.nodes import _consolidate_session
                    final_state = AgentState.model_validate(final_state_dict)
                    await _consolidate_session(memory_store, final_state, "success")
                    final_state_dict["outcome"] = "success"
                    logger.info(
                        "[%s] Goal achieved (callback) at step %d",
                        persona.name,
                        final_state_dict.get("step", 0),
                    )

        if final_state_dict.get("outcome") in ("success", "failure"):
            break

    elapsed = time.monotonic() - t0

    await ctx.close()
    if own_browser:
        await browser_manager.stop()

    final = AgentState.model_validate(final_state_dict)

    result = SimulationResult(
        persona=persona,
        goal=goal,
        start_url=start_url,
        outcome=final.outcome or "failure",
        total_steps=final.step,
        total_frustration=final.cumulative_frustration,
        action_log=final.action_log,
        final_url=final.current_url,
        duration_seconds=round(elapsed, 2),
    )

    traces_dir = str(Path(settings.output_dir) / "traces" / run_id)
    dump_traces([result], traces_dir, run_id)

    return result


async def run_swarm(
    personas: list[PersonaDNA],
    goal: str | None,
    start_url: str = "",
    *,
    software_registry: SoftwareRegistry | None = None,
    max_concurrent: int | None = None,
    max_steps: int = 50,
    credentials_file: str | None = None,
    company: str | None = None,
    goal_check_callback=None,
    dashboard_url: str | None = None,
    throng_graph: ThrongGraph | None = None,
) -> SwarmReport:
    """Run multiple agent simulations concurrently and produce a full report.

    If goal is None, each agent gets a goal synthesized from their persona's inner
    voice (Autonomous Executive Function spec). If goal is provided, all agents
    share that goal. When throng_graph is set, each agent's throng_id is resolved
    from the graph (by persona_id) and relationship context is used in goal synthesis.
    """
    run_id = _make_run_id()

    from throngs.time.clock import start_clock
    from throngs.config import _parse_sim_start
    sim_start = None
    if settings.sim_start_time:
        try:
            sim_start = _parse_sim_start(settings.sim_start_time)
        except ValueError:
            logger.warning(
                "Invalid SWARM_SIM_START_TIME=%r, defaulting to today 09:00",
                settings.sim_start_time,
            )
    start_clock(scale_factor=settings.sim_time_scale_factor, sim_start=sim_start)
    logger.info(
        "Simulation clock: scale=%.1fx, sim_start=%s",
        settings.sim_time_scale_factor,
        sim_start,
    )

    # Street simulation for swarm — one shared street, all personas as shops
    swarm_street_simulation = None
    if settings.street_simulation_enabled:
        from throngs.street.simulation import ShopConfig, StreetSimulation
        from throngs.time.clock import get_clock
        shop_configs = [
            ShopConfig(
                persona_name=p.name,
                persona_description=p.description,
                initial_bank_balance=settings.street_initial_bank_balance,
            )
            for p in personas
        ]
        swarm_street_simulation = StreetSimulation(shop_configs)
        swarm_street_simulation.tick(get_clock().now())
        logger.info(
            "Street simulation enabled: %d shops on the street",
            len(shop_configs),
        )

    max_conc = max_concurrent or settings.max_concurrent_agents
    llm = create_llm_for_task("goal_synthesis")
    vision_llm = create_llm_for_task("reason")
    browser_manager = BrowserManager()
    persona_engine = PersonaEngine()
    memory_store = CognitiveMemoryStore()

    for p in personas:
        persona_engine.load_persona(p)

    if credentials_file:
        persona_engine.load_credentials(credentials_file, company=company)

    await browser_manager.start()

    semaphore = asyncio.Semaphore(max_conc)
    throttler = Throttler(rate_limit=settings.rate_limit_rpm, period=60)

    async def _run_one(persona: PersonaDNA) -> SimulationResult:
        async with semaphore:
            frust = FrustrationEngine()
            return await run_single_agent(
                persona=persona,
                goal=goal,
                start_url=start_url,
                software_registry=software_registry,
                llm=llm,
                vision_llm=vision_llm,
                browser_manager=browser_manager,
                persona_engine=persona_engine,
                frustration_engine=frust,
                memory_store=memory_store,
                max_steps=max_steps,
                goal_check_callback=goal_check_callback,
                run_id=run_id,
                dashboard_url=dashboard_url,
                throng_graph=throng_graph,
                street_simulation=swarm_street_simulation,
            )

    goal_label = goal[:60] + "..." if goal and len(goal) > 60 else (goal or "(synthesized per persona)")
    logger.info(
        "Starting swarm [%s]: %d personas, goal=%s, max_concurrent=%d",
        run_id,
        len(personas),
        goal_label,
        max_conc,
    )

    results = await asyncio.gather(
        *[_run_one(p) for p in personas],
        return_exceptions=True,
    )

    valid_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Agent %s failed: %s", personas[i].name, r)
        else:
            valid_results.append(r)

    await browser_manager.stop()

    # Generate analytics via pipeline
    pipeline = AnalyticsPipeline(run_id)
    report = await pipeline.run(valid_results, goal=goal, start_url=start_url)

    logger.info(
        "Swarm complete [%s]: %d/%d succeeded, discoverability=%.1f%%",
        run_id,
        sum(1 for r in valid_results if r.outcome == "success"),
        len(valid_results),
        report.discoverability_rate,
    )

    return report


