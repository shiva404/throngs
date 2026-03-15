"""Motor Errors & Input Clumsiness Engine — the "Oops" Engine.

Spec: 06_Throngs - Motor Errors & Input Clumsiness.md

Phase 1 — Fat Finger Click Scatter (Targeting Errors)
Phase 2 — Typo Generator (Data Entry Errors)
Phase 3 — Fitts's Law Proximity Penalties
"""
from __future__ import annotations

import logging
import random

from throngs.config import settings
from throngs.schemas import A11yElement, MotorErrorEvent

logger = logging.getLogger(__name__)

# QWERTY adjacency map for character swaps during typo injection
QWERTY_ADJACENCY: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wsdr", "r": "edft", "t": "rfgy",
    "y": "tghu", "u": "yhji", "i": "ujko", "o": "iklp", "p": "ol",
    "a": "qwsz", "s": "awedxz", "d": "serfcx", "f": "drtgvc",
    "g": "ftyhbv", "h": "gyujnb", "j": "huikmn", "k": "jiolm",
    "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb",
    "b": "vghn", "n": "bhjm", "m": "njk",
}

DIGIT_ADJACENCY: dict[str, str] = {
    "0": "9", "1": "2", "2": "13", "3": "24", "4": "35",
    "5": "46", "6": "57", "7": "68", "8": "79", "9": "80",
}


class MotorErrorEngine:
    """Simulates motor errors: fat-finger misclicks, typos, and proximity anxiety.

    All three phases can be enabled independently via config.
    The engine is stateless between calls — pass a random seed for reproducibility.
    """

    def __init__(self, random_seed: int | None = None) -> None:
        self._rng = random.Random(random_seed)

    # ------------------------------------------------------------------
    # Phase 1 — Fat Finger Click Scatter
    # ------------------------------------------------------------------

    def apply_click_scatter(
        self,
        target_el: A11yElement,
        all_elements: list[A11yElement],
        motor_precision: float,
        viewport_width: int,
        viewport_height: int,
        device: str,
    ) -> tuple[float, float, str, bool]:
        """Apply Gaussian scatter to a click target.

        Parameters
        ----------
        target_el:
            The element the agent intends to click.
        all_elements:
            All elements on the page (used to detect which element was
            accidentally clicked when a misclick occurs).
        motor_precision:
            Persona's motor precision (0.0–1.0). Higher = more accurate.
        viewport_width / viewport_height:
            Current browser viewport dimensions in pixels.
        device:
            ``"desktop"`` or ``"mobile"``; controls the scatter radius scale.

        Returns
        -------
        (actual_x, actual_y, actual_element_id, is_misclick)
            ``is_misclick`` is True when the scattered coords land outside
            the intended element's bounding box.  ``actual_element_id`` is
            the element that was hit instead (empty string if none).
        """
        # Calculate intended click centre
        cx = target_el.x + target_el.width / 2
        cy = target_el.y + target_el.height / 2

        # Determine scatter radius
        scale_factor = (
            settings.motor_offset_scale_mobile
            if device == "mobile"
            else settings.motor_offset_scale_desktop
        )
        precision = max(motor_precision, 0.01)  # avoid division by zero
        radius = viewport_width * scale_factor / precision

        # Apply Gaussian noise
        dx = self._rng.gauss(0, radius)
        dy = self._rng.gauss(0, radius)
        actual_x = cx + dx
        actual_y = cy + dy

        # Check if the new point still lands inside the intended element
        in_target = _point_in_element(actual_x, actual_y, target_el)
        if in_target:
            return actual_x, actual_y, target_el.element_id, False

        # Misclick — find which other element was hit
        for el in all_elements:
            if el.element_id == target_el.element_id:
                continue
            if _point_in_element(actual_x, actual_y, el):
                logger.debug(
                    "Motor scatter misclick: intended=%s, hit=%s at (%.1f, %.1f)",
                    target_el.element_id,
                    el.element_id,
                    actual_x,
                    actual_y,
                )
                return actual_x, actual_y, el.element_id, True

        # Scattered coords are outside all elements — fall back to original centre
        logger.debug(
            "Motor scatter landed outside all elements for %s — using original centre",
            target_el.element_id,
        )
        return cx, cy, target_el.element_id, False

    # ------------------------------------------------------------------
    # Phase 2 — Typo Generator
    # ------------------------------------------------------------------

    def inject_typos(
        self,
        text: str,
        typo_rate: float,
    ) -> tuple[str, bool]:
        """Apply probabilistic typos to a text string.

        Each character has a ``typo_rate`` probability of being mutated via
        one of: adjacent-key swap, duplication, or omission.  Digit and
        date-like sequences also receive format-error treatment at 10% of
        the base typo rate.

        Parameters
        ----------
        text:
            The original text the agent wants to type.
        typo_rate:
            Per-character probability of mutation (0.0–1.0).

        Returns
        -------
        (mutated_text, did_inject)
            ``did_inject`` is True when at least one mutation was applied.
        """
        if not text or typo_rate <= 0.0:
            return text, False

        result: list[str] = []
        did_inject = False

        for char in text:
            if self._rng.random() < typo_rate:
                mutated = self._mutate_char(char)
                result.append(mutated)
                did_inject = True
            else:
                result.append(char)

        mutated_text = "".join(result)

        # Format errors for digits / dates (10% of typo_rate)
        if self._rng.random() < typo_rate * 0.1:
            mutated_text, fmt_inject = self._apply_format_error(mutated_text)
            if fmt_inject:
                did_inject = True

        if did_inject:
            logger.debug("Typo injection: '%s' → '%s'", text, mutated_text)

        return mutated_text, did_inject

    def _mutate_char(self, char: str) -> str:
        """Apply one mutation to a single character."""
        choice = self._rng.random()

        if choice < 0.5:
            # Adjacent-key swap
            lower = char.lower()
            adjacents = QWERTY_ADJACENCY.get(lower) or DIGIT_ADJACENCY.get(lower)
            if adjacents:
                replacement = self._rng.choice(adjacents)
                # Preserve original case
                return replacement.upper() if char.isupper() else replacement
            return char

        elif choice < 0.75:
            # Duplication — return the character twice
            return char + char

        else:
            # Omission — return empty string (character is dropped)
            return ""

    def _apply_format_error(self, text: str) -> tuple[str, bool]:
        """Introduce formatting errors in date or number-like strings."""
        import re

        # Date format: swap separator style  MM/DD/YYYY → MM-DD-YYYY
        date_pat = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b")
        m = date_pat.search(text)
        if m:
            sep = "-" if "/" in m.group(0) else "/"
            replacement = f"{m.group(1)}{sep}{m.group(2)}{sep}{m.group(3)}"
            return text[: m.start()] + replacement + text[m.end():], True

        # Number format: drop thousands separator or add erroneous one
        num_pat = re.compile(r"\b(\d{1,3}),(\d{3})\b")
        m = num_pat.search(text)
        if m:
            # Remove the comma separator
            replacement = m.group(1) + m.group(2)
            return text[: m.start()] + replacement + text[m.end():], True

        return text, False

    # ------------------------------------------------------------------
    # Phase 3 — Fitts's Law Proximity Penalties
    # ------------------------------------------------------------------

    def check_proximity_anxiety(
        self,
        target_el: A11yElement,
        all_elements: list[A11yElement],
        device: str,
    ) -> bool:
        """Return True if target is dangerously close to another interactive element.

        Uses the minimum pixel margin from config based on device type.

        Parameters
        ----------
        target_el:
            The element the agent wants to interact with.
        all_elements:
            All interactive elements on the page.
        device:
            ``"desktop"`` or ``"mobile"``; controls the margin threshold.
        """
        min_margin = (
            settings.proximity_min_margin_mobile
            if device == "mobile"
            else settings.proximity_min_margin_desktop
        )

        for el in all_elements:
            if el.element_id == target_el.element_id:
                continue
            if el.width <= 0 or el.height <= 0:
                continue
            gap = _bbox_gap(target_el, el)
            if gap < min_margin:
                logger.debug(
                    "Proximity anxiety: %s is only %.1fpx from %s (threshold=%dpx)",
                    target_el.element_id,
                    gap,
                    el.element_id,
                    min_margin,
                )
                return True

        return False

    # ------------------------------------------------------------------
    # Event factory
    # ------------------------------------------------------------------

    def create_motor_event(
        self,
        error_variant: str,
        intended_element_id: str,
        intended_coords: tuple[float, float],
        actual_coords: tuple[float, float],
        actual_element_id: str,
        motor_precision_applied: float,
        original_text: str = "",
        mutated_text: str = "",
        recovery_ux_present: bool = False,
        resulting_behavior: str = "PROCEEDED",
    ) -> MotorErrorEvent:
        """Construct a :class:`MotorErrorEvent` from scatter/typo results."""
        return MotorErrorEvent(
            error_variant=error_variant,
            intended_element_id=intended_element_id,
            intended_coords=intended_coords,
            actual_coords=actual_coords,
            actual_element_id=actual_element_id,
            motor_precision_applied=motor_precision_applied,
            original_text=original_text,
            mutated_text=mutated_text,
            recovery_ux_present=recovery_ux_present,
            resulting_behavior=resulting_behavior,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _point_in_element(x: float, y: float, el: A11yElement) -> bool:
    """Return True if (x, y) is within the element's bounding box."""
    return (
        el.x <= x <= el.x + el.width
        and el.y <= y <= el.y + el.height
    )


def _bbox_gap(a: A11yElement, b: A11yElement) -> float:
    """Return the minimum pixel gap between two element bounding boxes.

    Returns 0.0 if they overlap.
    """
    # Horizontal gap
    h_gap = max(0.0, max(a.x, b.x) - min(a.x + a.width, b.x + b.width))
    # Vertical gap
    v_gap = max(0.0, max(a.y, b.y) - min(a.y + a.height, b.y + b.height))
    # Euclidean minimum distance (for diagonal neighbours)
    if h_gap == 0.0 and v_gap == 0.0:
        return 0.0
    if h_gap == 0.0:
        return v_gap
    if v_gap == 0.0:
        return h_gap
    return (h_gap ** 2 + v_gap ** 2) ** 0.5
