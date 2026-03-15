"""
Task-based LLM factory (local only).

Creates the right local model for each task. Reads from throngs.config.settings:
- goal_synthesis / task_decomposition / consolidation / report: use fast or
  task-override model (text-only).
- reason: use vision-capable model for screenshot reasoning.
"""

from __future__ import annotations

from typing import Any

from throngs.config import LLMTask, settings


def _model_for_task(task: LLMTask) -> str:
    """Return the local model name for this task."""
    if task == "consolidation":
        return settings.consolidation_model
    if task == "goal_synthesis":
        return settings.model_goal_synthesis or settings.local_model_fast
    if task == "task_decomposition":
        return settings.model_task_decomposition or settings.local_model_fast
    if task == "report":
        return settings.model_report or settings.local_model
    if task == "reason":
        return settings.model_reason or settings.local_vision_model
    if task == "hesitation":
        return settings.model_hesitation or settings.local_model_fast
    if task == "distraction":
        return settings.model_distraction or settings.local_model_fast
    return settings.local_model


def create_llm_for_task(
    task: LLMTask,
    *,
    max_tokens: int = 2048,
) -> Any:
    """
    Create the LangChain LLM for the given task (local endpoint only).

    Uses per-task override when set (e.g. model_goal_synthesis), otherwise
    the default for that task (fast for synthesis/decomposition, vision for reason).
    """
    from langchain_openai import ChatOpenAI

    model_name = _model_for_task(task)
    return ChatOpenAI(
        model=model_name,
        api_key=settings.local_api_key,
        base_url=settings.local_base_url,
        max_tokens=max_tokens,
        streaming=False,
    )
