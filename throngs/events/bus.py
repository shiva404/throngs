"""Async priority queue event bus.

Events are enqueued with a priority level and drained in priority order.
CRITICAL events (e.g. CUSTOMER_ARRIVAL) preempt lower-priority work —
callers check ``has_critical()`` before executing browser actions.

Priority levels (lower number = higher priority):
    CRITICAL (0)  — CUSTOMER_ARRIVAL: preempts the current browser action
    HIGH     (10) — POPUP_SQUIRREL: captures attention after action
    NORMAL   (50) — COFFEE_BREAK, TAB_SWITCH: post-action interruptions
    LOW      (100)— Motor errors, hesitation: applied during/before action
"""
from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class EventPriority(IntEnum):
    """Lower number = higher priority = processed first."""

    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100


@dataclass(order=True)
class PrioritizedEvent:
    """Wrapper that makes events comparable for the heap."""

    priority: int
    sequence: int = field(compare=True)
    event: Any = field(compare=False)
    event_type: str = field(compare=False)


class EventBus:
    """Async priority queue for simulation events.

    Usage::

        bus = EventBus()
        bus.subscribe("CUSTOMER_ARRIVAL", handle_customer)
        bus.emit("CUSTOMER_ARRIVAL", evt, EventPriority.CRITICAL)

        if bus.has_critical():
            # skip browser action — persona is preempted
            ...

        results = await bus.drain()
    """

    def __init__(self) -> None:
        self._heap: list[PrioritizedEvent] = []
        self._seq: int = 0
        self._handlers: dict[str, list[Callable[..., Awaitable]]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: Callable[..., Awaitable]) -> None:
        """Register *handler* for *event_type*.  Called during ``drain()``."""
        self._handlers.setdefault(event_type, []).append(handler)

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        event: Any,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        """Enqueue an event at the given priority."""
        heapq.heappush(
            self._heap,
            PrioritizedEvent(
                priority=int(priority),
                sequence=self._seq,
                event=event,
                event_type=event_type,
            ),
        )
        self._seq += 1
        logger.debug(
            "EventBus: enqueued %s (priority=%s, seq=%d)",
            event_type,
            priority.name,
            self._seq - 1,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def has_critical(self) -> bool:
        """Return True if any CRITICAL-priority event is pending."""
        return any(e.priority == EventPriority.CRITICAL for e in self._heap)

    def pending_count(self) -> int:
        return len(self._heap)

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(self) -> list[Any]:
        """Pop and process all queued events in priority order.

        Returns a list of handler results (one per handler invocation).
        """
        results: list[Any] = []
        while self._heap:
            item = heapq.heappop(self._heap)
            handlers = self._handlers.get(item.event_type, [])
            if not handlers:
                logger.debug(
                    "EventBus: no handler for %s, discarding", item.event_type,
                )
                continue
            for handler in handlers:
                result = await handler(item.event)
                results.append(result)
        return results

    def clear(self) -> None:
        """Discard all pending events without processing."""
        self._heap.clear()
