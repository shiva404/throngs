"""
Real-time agent state dashboard (SSE).

Run the server: throngs dashboard --port 8765
Run agents with: throngs --dashboard-url http://localhost:8765 --url ... --personas ...
"""

from throngs.dashboard.broadcaster import SSEBroadcaster
from throngs.dashboard.snapshot import build_snapshot

__all__ = ["SSEBroadcaster", "build_snapshot"]
