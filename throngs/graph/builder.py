"""Composable GraphBuilder — configurable node pipeline.

Instead of the hardcoded 8-node graph in ``build_agent_graph()``, the
``GraphBuilder`` lets callers pick which nodes to include and wire custom
conditional edges.

Usage::

    builder = GraphBuilder()

    # Required core loop
    builder.add_node("initialize", make_initialize_node(memory_store, persona_engine))
    builder.add_node("perceive", make_perceive_node(browser_manager))
    builder.add_node("calculate_load", make_calculate_load_node(frustration_engine))
    builder.add_node("reason", make_reason_node(vision_llm, persona_engine))
    builder.add_node("execute_action", make_execute_action_node(...))
    builder.add_node("evaluate", make_evaluate_node(frustration_engine, memory_store))

    # Optional — skip if the app has no login
    builder.add_node("handle_login", make_handle_login_node(...))
    builder.add_node("handle_profile_setup", make_handle_profile_setup_node(...))

    graph = builder.compile()
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from throngs.graph.state import AgentState

logger = logging.getLogger(__name__)


# The standard node ordering.  Nodes are wired in this order; missing nodes
# are skipped and their edges are bridged automatically.
_DEFAULT_ORDER = [
    "initialize",
    "perceive",
    "handle_login",
    "handle_profile_setup",
    "calculate_load",
    "reason",
    "execute_action",
    "evaluate",
]


class GraphBuilder:
    """Incrementally builds a LangGraph StateGraph from named node functions.

    Nodes are wired in ``_DEFAULT_ORDER``.  If a node name is not added,
    it is skipped and the edge bridges across to the next present node.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Callable] = {}
        self._conditional_edges: dict[str, tuple[Callable, dict[str, str]]] = {}

    def add_node(self, name: str, fn: Callable) -> GraphBuilder:
        """Register a node function."""
        self._nodes[name] = fn
        return self

    def add_conditional_edge(
        self, source: str, router: Callable, route_map: dict[str, str]
    ) -> GraphBuilder:
        """Register a conditional edge from *source* with *router* → route_map."""
        self._conditional_edges[source] = (router, route_map)
        return self

    def compile(self) -> Any:
        """Build and compile the StateGraph.

        Returns a LangGraph ``CompiledGraph`` ready for ``astream()`` / ``ainvoke()``.
        """
        ordered = [n for n in _DEFAULT_ORDER if n in self._nodes]
        if not ordered:
            raise ValueError("GraphBuilder has no nodes added")

        graph = StateGraph(AgentState)

        for name in ordered:
            graph.add_node(name, self._nodes[name])

        graph.set_entry_point(ordered[0])

        for i, name in enumerate(ordered):
            if name in self._conditional_edges:
                router, route_map = self._conditional_edges[name]
                # Rewrite route targets: if a target node was not added, bridge
                # to the next present node in order.
                resolved_map = {}
                for key, target in route_map.items():
                    resolved_map[key] = self._resolve_target(target, ordered, i)
                graph.add_conditional_edges(name, router, resolved_map)
            elif i < len(ordered) - 1:
                graph.add_edge(name, ordered[i + 1])

        # Last node → evaluate loop
        if "evaluate" in self._nodes:
            if "evaluate" not in self._conditional_edges:
                # Default evaluate routing: continue → perceive, done → END
                perceive_target = "perceive" if "perceive" in self._nodes else ordered[1] if len(ordered) > 1 else END

                def _should_continue(state: AgentState) -> str:
                    if state.outcome in ("success", "failure"):
                        return "done"
                    if state.error:
                        return "done"
                    return "continue"

                graph.add_conditional_edges(
                    "evaluate",
                    _should_continue,
                    {"continue": perceive_target, "done": END},
                )

        compiled = graph.compile()
        logger.debug(
            "GraphBuilder compiled: %d nodes [%s]",
            len(ordered),
            " → ".join(ordered),
        )
        return compiled

    def _resolve_target(self, target: str, ordered: list[str], current_idx: int) -> str:
        """Resolve a target node name, bridging to the next present node if needed."""
        if target in self._nodes:
            return target
        if target == END:
            return END
        # Target was not added — find the next present node after current
        for j in range(current_idx + 1, len(ordered)):
            return ordered[j]
        return END
