"""
Phase 1 (Internal State) and Phase 2 (World State) for Autonomous Executive Function.

Spec: 2_Throngs - Autonomous Executive Function.md Sections 1–2.
"""

from __future__ import annotations

from dataclasses import dataclass


def internal_state(
    financial_security: float = 0.5,
    physical_energy: float = 0.8,
    stress_level: float = 0.3,
    family_obligation: float = 0.2,
) -> dict[str, float]:
    """
    Build internal state dict per spec Phase 1 (Needs & Drives).

    All values normalized 0.0–1.0. Decay/regen is handled elsewhere;
    pass the result into synthesize_goal() as internal_state_dict.
    """
    return {
        "financial_security": max(0.0, min(1.0, financial_security)),
        "physical_energy": max(0.0, min(1.0, physical_energy)),
        "stress_level": max(0.0, min(1.0, stress_level)),
        "family_obligation": max(0.0, min(1.0, family_obligation)),
    }


def world_state(
    timestamp_simulated: str = "",
    calendar: str = "",
    environment: str = "",
    device: str = "",
) -> dict[str, str]:
    """
    Build world state dict per spec Phase 2 (Environmental Observer).

    E.g. timestamp_simulated='Tuesday 7:30 AM', calendar entry, location, device.
    """
    return {
        "timestamp_simulated": timestamp_simulated,
        "calendar": calendar,
        "environment": environment,
        "device": device,
    }


@dataclass
class GoalSynthesisResult:
    """
    Result of Level 1 synthesis; for spec Section 5 state tree logging.

    Log as active_macro_goal, inner_voice_thought, etc.
    """

    inner_voice_thought: str
    macro_goal: str
    actionable_software_goal: str
