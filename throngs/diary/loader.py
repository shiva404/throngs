"""Diary entry loader — maps persona names to diary directories and extracts
a concise context snippet (header + reflection) for use as goal-synthesis
inspiration.

The snippet is intentionally *short* — it captures the persona's character,
typical workload, and tomorrow's priorities without exposing a full 50 KB log
to the LLM.  Goal synthesis uses it for flavour, not as a task list to follow.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lines taken from the start and end of a diary file.
# Start captures: decorative header, persona name, opening quote, DAY SUMMARY.
# End captures: end-of-day reflection, frustrations, and the TO-DO list.
_HEAD_LINES = 30
_TAIL_LINES = 60


def _persona_slug(persona_name: str) -> str:
    """Return the first word of a persona name, lowercased.

    Examples:
      'Martha_Bookkeeper'    → 'martha'
      'Jake_Startup_Founder' → 'jake'
      'Priya_New_Hire'       → 'priya'
    """
    return persona_name.split("_")[0].lower()


def find_diary_dir(persona_name: str, base_dir: str | Path) -> Optional[Path]:
    """Return the diary directory for a persona, or None if it doesn't exist."""
    slug = _persona_slug(persona_name)
    d = Path(base_dir) / slug
    return d if d.is_dir() else None


def load_diary_snippet(
    persona_name: str,
    base_dir: str | Path,
    *,
    day: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> Optional[str]:
    """Load a diary entry and return a condensed snippet for goal inspiration.

    Picks a random day file unless ``day`` is specified.  Extracts the first
    ``_HEAD_LINES`` and last ``_TAIL_LINES`` lines (joined with an ellipsis)
    so the LLM sees the persona's character, daily stats, and priorities
    without receiving the full chronological log.

    Returns None if no diary directory exists for this persona.
    """
    diary_dir = find_diary_dir(persona_name, base_dir)
    if not diary_dir:
        logger.debug("No diary directory for persona %r at %s", persona_name, base_dir)
        return None

    day_files = sorted(diary_dir.glob("day-*.txt"))
    if not day_files:
        logger.debug("Diary dir %s has no day-*.txt files", diary_dir)
        return None

    if day is not None:
        target = diary_dir / f"day-{day}.txt"
        selected = target if target.exists() else day_files[0]
    else:
        _rng = rng or random.Random()
        selected = _rng.choice(day_files)

    try:
        lines = selected.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning("Could not read diary file %s: %s", selected, e)
        return None

    if len(lines) <= _HEAD_LINES + _TAIL_LINES:
        return "\n".join(lines)

    head = lines[:_HEAD_LINES]
    tail = lines[-_TAIL_LINES:]
    return "\n".join(head) + "\n\n[... mid-day log omitted ...]\n\n" + "\n".join(tail)
