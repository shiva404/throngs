"""Hybrid Visual Perception — the "Retina" engine.

Phase 1:  Programmatic DOM penalties  (size, contrast, semantic color)
Phase 3:  True Visibility Score = Base Saliency − penalties
Phase 4:  Global overload detection + distraction mechanics
"""

from __future__ import annotations

import logging
import math
import re

import numpy as np

from throngs.config import settings
from throngs.perception.saliency import (
    compute_saliency_map,
    high_intensity_percentage,
    region_mean_intensity,
)
from throngs.schemas import A11yElement, PerceptionLevel, VisualOverloadInfo

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Semantic colour dictionaries
# ------------------------------------------------------------------
POSITIVE_COLORS = {"green", "blue", "#00ff00", "#4caf50", "#28a745", "#0000ff", "#007bff", "#2196f3"}
DESTRUCTIVE_COLORS = {"red", "#ff0000", "#f44336", "#dc3545", "grey", "gray", "#808080", "#6c757d"}
WARNING_COLORS = {"orange", "#ff9800", "#ffc107", "yellow", "#ffff00"}

DESTRUCTIVE_LABELS = re.compile(
    r"\b(delete|remove|cancel|discard|clear|destroy|revoke|unsubscribe)\b", re.I
)
POSITIVE_LABELS = re.compile(
    r"\b(save|submit|confirm|create|add|ok|accept|approve|enable|publish)\b", re.I
)


class VisualPerceptionEngine:
    """Runs through the four visual-perception phases based on config level."""

    def process(
        self,
        elements: list[A11yElement],
        screenshot_bytes: bytes,
        viewport_width: int,
        viewport_height: int,
        goal: str = "",
        rtl: bool = False,
    ) -> tuple[list[A11yElement], VisualOverloadInfo]:
        """Run all enabled perception phases; return enriched elements + overload info."""
        level = PerceptionLevel(settings.perception_level)
        overload = VisualOverloadInfo()

        if level == PerceptionLevel.BASIC:
            return elements, overload

        # Phase 1 — DOM physical penalties
        self._apply_physical_penalties(elements)

        if level == PerceptionLevel.DOM:
            return elements, overload

        # Phase 2 — Saliency heatmap
        heatmap = compute_saliency_map(
            screenshot_bytes, viewport_width, viewport_height
        )

        # Phase 3 — True Visibility Score + blindspot filter
        if level in (PerceptionLevel.SALIENCY, PerceptionLevel.HYBRID, PerceptionLevel.FULL):
            self._score_visibility(
                elements,
                heatmap,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                rtl=rtl,
            )

        if level in (PerceptionLevel.HYBRID, PerceptionLevel.FULL):
            self._apply_blindspot(elements)

        # Phase 4 — Cognitive overload detection
        if level == PerceptionLevel.FULL:
            overload = self._detect_overload(elements, heatmap, goal)

        return elements, overload

    # ------------------------------------------------------------------
    # Phase 1 — Physical / style penalties
    # ------------------------------------------------------------------

    def _apply_physical_penalties(self, elements: list[A11yElement]) -> None:
        for el in elements:
            # Fitts's Law / fat-finger check
            min_px = settings.fat_finger_min_px
            if el.width > 0 and el.height > 0:
                if el.width < min_px or el.height < min_px:
                    el.size_penalty = _size_penalty(el.width, el.height, min_px)
                    el.visual_flags.append("BELOW_FAT_FINGER_MINIMUM")

            # WCAG contrast check
            if el.text_color and el.bg_color:
                ratio = _contrast_ratio(el.text_color, el.bg_color)
                el.contrast_ratio = round(ratio, 2)
                if ratio < settings.wcag_min_contrast:
                    el.contrast_penalty = _contrast_penalty(ratio)
                    el.visual_flags.append("FAILED_WCAG_CONTRAST")

            # Semantic colour mapping + deceptive-pattern flag
            if el.bg_color:
                el.semantic_color = _classify_color(el.bg_color)
                if _has_semantic_mismatch(el.name, el.semantic_color):
                    el.visual_flags.append("SEMANTIC_COLOR_MISMATCH")

    # ------------------------------------------------------------------
    # Phase 3 — True Visibility Score
    # ------------------------------------------------------------------

    def _score_visibility(
        self,
        elements: list[A11yElement],
        heatmap: np.ndarray,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        rtl: bool = False,
    ) -> None:
        for el in elements:
            if el.width <= 0 or el.height <= 0:
                el.saliency_intensity = 0.0
                el.true_visibility_score = 50.0
                continue

            raw_intensity = region_mean_intensity(
                heatmap, el.x, el.y, el.width, el.height
            )
            el.saliency_intensity = round(raw_intensity, 1)

            base = raw_intensity / 255.0 * 100.0
            score = base - el.size_penalty - el.contrast_penalty

            # Apply F-Pattern geographic multiplier when enabled
            if settings.geographic_weighting_enabled:
                geo_mult = self._get_geographic_multiplier(
                    el, viewport_width, viewport_height, rtl=rtl
                )
                score = score * geo_mult

            el.true_visibility_score = round(max(score, 0.0), 1)

    def _get_geographic_multiplier(
        self,
        el: A11yElement,
        viewport_width: int,
        viewport_height: int,
        rtl: bool = False,
    ) -> float:
        """Return the F-Pattern / I-Pattern geographic attention multiplier.

        Divides the viewport into a 3×3 grid and returns a weight that
        reflects how likely a human is to notice content in that sector,
        based on eye-tracking and F-pattern reading studies.

        Mobile viewports (width < 768) use a centre-column–weighted
        I-pattern instead of the desktop F-pattern.  RTL locales (Arabic,
        Hebrew) have the F-pattern matrix flipped horizontally.

        Parameters
        ----------
        el:
            The element whose top-left corner (x, y) determines the sector.
        viewport_width / viewport_height:
            Current browser viewport dimensions in pixels.
        rtl:
            True for right-to-left locales.

        Returns
        -------
        float
            Multiplier in the range [0.4, 1.5].
        """
        # 3×3 grid multipliers — F-pattern (LTR desktop)
        F_PATTERN: list[list[float]] = [
            [1.5, 1.2, 0.9],   # Top row    (left, middle, right)
            [1.2, 1.0, 0.6],   # Middle row
            [0.7, 0.7, 0.4],   # Bottom row
        ]

        # RTL mirror of F-pattern
        F_PATTERN_RTL: list[list[float]] = [
            [0.9, 1.2, 1.5],
            [0.6, 1.0, 1.2],
            [0.4, 0.7, 0.7],
        ]

        # I-pattern for mobile (centre-column weighted)
        I_PATTERN: list[list[float]] = [
            [1.0, 1.5, 1.0],
            [0.8, 1.3, 0.8],
            [0.5, 0.8, 0.5],
        ]

        # Select matrix
        if viewport_width < 768:
            matrix = I_PATTERN
        elif rtl:
            matrix = F_PATTERN_RTL
        else:
            matrix = F_PATTERN

        # Determine grid sector, clamped to [0, 2]
        col_width = viewport_width / 3.0
        row_height = viewport_height / 3.0

        col = int(el.x / col_width) if col_width > 0 else 0
        row = int(el.y / row_height) if row_height > 0 else 0
        col = max(0, min(2, col))
        row = max(0, min(2, row))

        return matrix[row][col]

    def _apply_blindspot(self, elements: list[A11yElement]) -> None:
        threshold = settings.visibility_threshold
        for el in elements:
            if el.true_visibility_score < threshold:
                el.passed_blindspot = False
            else:
                el.passed_blindspot = True

    # ------------------------------------------------------------------
    # Phase 4 — Cognitive overload + distraction
    # ------------------------------------------------------------------

    def _detect_overload(
        self,
        elements: list[A11yElement],
        heatmap: np.ndarray,
        goal: str,
    ) -> VisualOverloadInfo:
        pct = high_intensity_percentage(heatmap)
        overload_triggered = pct > settings.visual_overload_clutter_pct

        top_distractor = ""
        distraction_note = ""

        visible = [e for e in elements if e.passed_blindspot]
        if visible:
            loudest = max(visible, key=lambda e: e.true_visibility_score)
            goal_lower = goal.lower()
            name_lower = loudest.name.lower()
            goal_related = any(
                w in name_lower
                for w in goal_lower.split()
                if len(w) > 3
            )
            if not goal_related and loudest.true_visibility_score > 60:
                top_distractor = loudest.name
                distraction_note = (
                    f'The most visually dominant element on this page is '
                    f'"{loudest.name}" ({loudest.role}), which seems unrelated '
                    f'to your goal. This may pull your attention away.'
                )

        return VisualOverloadInfo(
            high_saliency_pct=round(pct, 1),
            overload_triggered=overload_triggered,
            top_distractor=top_distractor,
            distraction_note=distraction_note,
        )


# ------------------------------------------------------------------
# Colour / contrast helpers
# ------------------------------------------------------------------

_RGB_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)"
)
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3,8})$")


def _parse_rgb(css_color: str) -> tuple[int, int, int] | None:
    """Parse a CSS colour string into (R, G, B) ints."""
    if not css_color or css_color == "transparent":
        return None

    m = _RGB_RE.match(css_color.strip())
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    m = _HEX_RE.match(css_color.strip())
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return None


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG 2.x relative luminance (sRGB → linear)."""
    def _lin(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(fg_css: str, bg_css: str) -> float:
    fg = _parse_rgb(fg_css)
    bg = _parse_rgb(bg_css)
    if fg is None or bg is None:
        return 21.0  # assume perfect contrast if we can't parse
    l1 = _relative_luminance(*fg)
    l2 = _relative_luminance(*bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _contrast_penalty(ratio: float) -> float:
    """Higher penalty the further below the WCAG threshold."""
    gap = max(settings.wcag_min_contrast - ratio, 0.0)
    return min(gap * 5.0, 20.0)


def _size_penalty(w: float, h: float, min_px: int) -> float:
    """Penalty based on how far below the minimum touch-target the element is."""
    area = w * h
    min_area = min_px * min_px
    if area >= min_area:
        return 0.0
    ratio = area / min_area
    return round((1.0 - ratio) * 15.0, 1)


def _classify_color(css_color: str) -> str:
    rgb = _parse_rgb(css_color)
    if rgb is None:
        return "neutral"
    hex_lower = "#{:02x}{:02x}{:02x}".format(*rgb)
    if hex_lower in POSITIVE_COLORS or css_color.lower() in POSITIVE_COLORS:
        return "positive"
    if hex_lower in DESTRUCTIVE_COLORS or css_color.lower() in DESTRUCTIVE_COLORS:
        return "destructive"
    if hex_lower in WARNING_COLORS or css_color.lower() in WARNING_COLORS:
        return "warning"
    r, g, b = rgb
    if g > r * 1.3 and g > b * 1.3:
        return "positive"
    if r > g * 1.3 and r > b * 1.3:
        return "destructive"
    return "neutral"


def _has_semantic_mismatch(name: str, semantic_color: str) -> bool:
    if DESTRUCTIVE_LABELS.search(name) and semantic_color == "positive":
        return True
    if POSITIVE_LABELS.search(name) and semantic_color == "destructive":
        return True
    return False
