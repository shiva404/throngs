"""
Autonomous Executive Function (Life Simulation / Goal-Free Autonomy).

Implements specs/2_Throngs - Autonomous Executive Function.md:
- Phase 1: Internal State (Needs & Drives) — state.internal_state()
- Phase 2: World State (Environmental Observer) — state.world_state()
- Phase 3 Level 1: Goal synthesis from inner voice — synthesis.synthesize_goal()
- Phase 3 Level 2: Task decomposition — decomposition.decompose_goal()
"""

from throngs.executive.decomposition import decompose_goal
from throngs.executive.state import GoalSynthesisResult, internal_state, world_state
from throngs.executive.synthesis import synthesize_goal, synthesize_goal_chain

__all__ = [
    "decompose_goal",
    "GoalSynthesisResult",
    "internal_state",
    "synthesize_goal",
    "synthesize_goal_chain",
    "world_state",
]
