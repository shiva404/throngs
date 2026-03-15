"""In-memory broadcaster for SSE: one-to-many push to all connected clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SSEBroadcaster:
    """Hold a set of asyncio queues; broadcast pushes to all."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Add a new subscriber; returns a queue that will receive all events."""
        async with self._lock:
            q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._subscribers.append(q)
            logger.debug("SSE subscriber connected; total=%d", len(self._subscribers))
            return q

    async def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber."""
        async with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
            logger.debug("SSE subscriber disconnected; total=%d", len(self._subscribers))

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Push event to all subscribers (non-blocking put)."""
        async with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def subscriber_count(self) -> int:
        return len(self._subscribers)
