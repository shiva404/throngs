from __future__ import annotations

from collections import Counter

from throngs.config import settings
from throngs.schemas import A11yElement


def extract_a11y_tree(
    elements: list[A11yElement],
    patience_budget: int = 100,
    skimming_enabled: bool = False,
) -> str:
    """Format the A11y element list into a concise text for the LLM.

    Elements with ``passed_blindspot == False`` are silently excluded —
    the LLM literally does not know they exist, simulating human oversight.

    When ``skimming_enabled=True`` and ``patience_budget <= 30`` (low
    patience), long lists of homogeneous elements (e.g. menu items) are
    truncated to ``settings.skimming_max_list_items`` with a note
    appended so the LLM understands how many items were omitted.

    Parameters
    ----------
    elements:
        Full list of :class:`A11yElement` objects from the page capture.
    patience_budget:
        Remaining patience points for the persona; values <= 30 activate
        the skimming truncation when ``skimming_enabled`` is True.
    skimming_enabled:
        Whether to apply patience-based skimming truncation at all.
    """
    visible = [e for e in elements if e.passed_blindspot]

    if not visible:
        return "No interactive elements detected."

    # Patience-based skimming — truncate long homogeneous role groups
    if skimming_enabled and patience_budget <= 30:
        visible = _apply_skimming(visible)

    lines = ["Interactive Elements:"]
    for el in visible:
        if el.role == "__skimming_note__":
            lines.append(el.name)
            continue
        desc = f'  [{el.element_id}] {el.role}: "{el.name}"'
        if el.value:
            desc += f" (value: {el.value})"
        if el.visual_flags:
            warnings = ", ".join(_human_readable_flag(f) for f in el.visual_flags)
            desc += f"  ⚠ {warnings}"
        lines.append(desc)

    return "\n".join(lines)


def _apply_skimming(elements: list[A11yElement]) -> list[A11yElement]:
    """Truncate runs of repeated roles to ``skimming_max_list_items``.

    Roles subject to truncation: ``option``, ``listitem``, ``menuitem``.
    A synthetic note element is appended after each truncated group so the
    LLM receives a human-readable signal that items were skipped.
    """
    max_items = settings.skimming_max_list_items
    skimmable_roles = {"option", "listitem", "menuitem"}

    result: list[A11yElement] = []
    # Track per-role count as we encounter them
    role_counts: Counter[str] = Counter()

    for el in elements:
        role = el.role.lower()
        if role in skimmable_roles:
            role_counts[role] += 1
            if role_counts[role] <= max_items:
                result.append(el)
            # On exactly max_items+1, we'll add the note when we move past this role
        else:
            # Flush notes for any role groups that were truncated
            for skipped_role, count in list(role_counts.items()):
                if count > max_items:
                    remaining = count - max_items
                    # Create a synthetic placeholder element for the note
                    note = A11yElement(
                        element_id=f"__skim_{skipped_role}__",
                        role="__skimming_note__",
                        name=f"  [... {remaining} more items — user stopped scanning]",
                        x=0, y=0, width=0, height=0,
                    )
                    result.append(note)
            role_counts.clear()
            result.append(el)

    # Flush any remaining truncated groups
    for skipped_role, count in role_counts.items():
        if count > max_items:
            remaining = count - max_items
            note = A11yElement(
                element_id=f"__skim_{skipped_role}__",
                role="__skimming_note__",
                name=f"  [... {remaining} more items — user stopped scanning]",
                x=0, y=0, width=0, height=0,
            )
            result.append(note)

    return result


def get_visible_text(text: str, max_chars: int = 3000) -> str:
    """Truncate visible page text to fit within LLM context."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _human_readable_flag(flag: str) -> str:
    _MAP = {
        "BELOW_FAT_FINGER_MINIMUM": "tiny click target",
        "FAILED_WCAG_CONTRAST": "low contrast",
        "SEMANTIC_COLOR_MISMATCH": "misleading color for this action",
    }
    return _MAP.get(flag, flag.lower().replace("_", " "))
