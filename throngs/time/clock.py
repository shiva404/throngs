"""Global Simulation Clock — 1 real second = 1 simulated minute (60× default).

All agents in a throngs run share a single SimulationClock singleton so that
ActionLog timestamps, memory decay, and distraction durations reflect simulated
time rather than real wall-clock time.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

_clock: Optional["SimulationClock"] = None


class SimulationClock:
    def __init__(
        self,
        scale_factor: float = 60.0,
        sim_start: Optional[datetime] = None,
    ) -> None:
        self.scale_factor = scale_factor
        self.start_real: float = time.monotonic()
        if sim_start is None:
            today = datetime.now().date()
            sim_start = datetime(today.year, today.month, today.day, 9, 0, 0)
        self.sim_start = sim_start

    def now(self) -> datetime:
        elapsed = time.monotonic() - self.start_real
        return self.sim_start + timedelta(seconds=elapsed * self.scale_factor)

    def elapsed_sim_minutes(self) -> float:
        return (time.monotonic() - self.start_real) * self.scale_factor / 60.0


def start_clock(
    scale_factor: float = 60.0,
    sim_start: Optional[datetime] = None,
) -> SimulationClock:
    global _clock
    _clock = SimulationClock(scale_factor=scale_factor, sim_start=sim_start)
    return _clock


def get_clock() -> SimulationClock:
    if _clock is None:
        raise RuntimeError(
            "Simulation clock not started. Call start_clock() first."
        )
    return _clock
