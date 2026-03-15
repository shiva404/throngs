from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from throngs.graph.nodes import (
    make_calculate_load_node,
    make_evaluate_node,
    make_execute_action_node,
    make_handle_login_node,
    make_handle_profile_setup_node,
    make_initialize_node,
    make_perceive_node,
    make_reason_node,
    make_switch_app_node,
)
from throngs.graph.state import AgentState

logger = logging.getLogger(__name__)


def build_agent_graph(
    llm,
    vision_llm,
    browser_manager,
    persona_engine,
    frustration_engine,
    memory_store,
    street_simulation=None,
):
    """Construct the LangGraph state machine for a single agent simulation.

    The graph implements the PRD execution loop with automatic login handling
    and profile-setup skipping:

      initialize → perceive → handle_login ─(just_logged_in)─→ perceive
                    ↑              |                                 │
                    │              └──(no_login)──→ handle_profile_setup
                    │                                    │
                    │                     (skipped)──→ perceive
                    │                        │
                    │                   (proceed)──→ calculate_load
                    │                                    │
                    │                                 reason
                    │                                    │
                    │                              execute_action
                    │                                    │
                    └──────── (continue) ── evaluate ────┘
                                              │
                                           (done) → END
    """
    from throngs.config import settings
    from throngs.llm import create_llm_for_task

    logger.debug("Building agent graph (login, profile_setup, perceive→reason→execute→evaluate)")
    hesitation_llm = None
    if settings.risk_aversion_enabled and settings.hesitation_llm_enabled:
        try:
            hesitation_llm = create_llm_for_task("hesitation", max_tokens=512)
        except Exception as exc:
            logger.warning("Could not create hesitation LLM, falling back to regex: %s", exc)

    distraction_llm = None
    if settings.distraction_enabled and settings.distraction_llm_enabled:
        try:
            distraction_llm = create_llm_for_task("distraction", max_tokens=1024)
        except Exception as exc:
            logger.warning("Could not create distraction LLM, falling back to templates: %s", exc)

    initialize = make_initialize_node(memory_store, persona_engine)
    perceive = make_perceive_node(browser_manager)
    handle_login = make_handle_login_node(browser_manager, persona_engine)
    handle_profile_setup = make_handle_profile_setup_node(browser_manager)
    calculate_load = make_calculate_load_node(frustration_engine)
    reason = make_reason_node(vision_llm, persona_engine)
    from throngs.events.bus import EventBus
    event_bus = EventBus()

    execute_action = make_execute_action_node(
        browser_manager,
        hesitation_llm=hesitation_llm,
        distraction_llm=distraction_llm,
        street_simulation=street_simulation,
        event_bus=event_bus,
    )
    evaluate = make_evaluate_node(frustration_engine, memory_store)
    switch_app = make_switch_app_node(browser_manager)

    graph = StateGraph(AgentState)

    graph.add_node("initialize", initialize)
    graph.add_node("perceive", perceive)
    graph.add_node("handle_login", handle_login)
    graph.add_node("handle_profile_setup", handle_profile_setup)
    graph.add_node("calculate_load", calculate_load)
    graph.add_node("reason", reason)
    graph.add_node("execute_action", execute_action)
    graph.add_node("evaluate", evaluate)
    graph.add_node("switch_app", switch_app)

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "perceive")
    graph.add_edge("perceive", "handle_login")

    graph.add_conditional_edges(
        "handle_login",
        _after_login_check,
        {
            "re_perceive": "perceive",
            "proceed": "handle_profile_setup",
        },
    )

    graph.add_conditional_edges(
        "handle_profile_setup",
        _after_profile_setup_check,
        {
            "re_perceive": "perceive",
            "proceed": "calculate_load",
        },
    )

    graph.add_edge("calculate_load", "reason")
    graph.add_edge("reason", "execute_action")
    graph.add_edge("execute_action", "evaluate")

    # evaluate → switch_app → perceive (app switch before re-perception)
    graph.add_conditional_edges(
        "evaluate",
        _should_continue,
        {
            "continue": "switch_app",
            "done": END,
        },
    )
    graph.add_edge("switch_app", "perceive")

    return graph.compile()


def _after_login_check(state: AgentState) -> str:
    """Route after handle_login: if we just logged in, re-perceive the new page."""
    if state.login_redirect:
        return "re_perceive"
    return "proceed"


def _after_profile_setup_check(state: AgentState) -> str:
    """Route after handle_profile_setup: if we skipped a prompt, re-perceive."""
    if state.profile_setup_redirect:
        return "re_perceive"
    return "proceed"


def _should_continue(state: AgentState) -> str:
    if state.outcome in ("success", "failure"):
        return "done"
    if state.error:
        return "done"
    return "continue"
