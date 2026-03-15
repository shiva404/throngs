from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

from throngs.config import settings
from throngs.schemas import ActionLog

logger = logging.getLogger(__name__)

LOW_FRUSTRATION = 5.0
HIGH_FRUSTRATION = 15.0
DOT_RADIUS = 12
DOT_OPACITY = 160


class HeatmapGenerator:
    """Overlays click/action data onto screenshots with frustration-coloured dots."""

    def generate(
        self,
        action_logs: list[ActionLog],
        output_dir: str | None = None,
    ) -> list[str]:
        """Generate heatmap overlays, one per unique screenshot.

        Returns list of generated heatmap file paths.
        """
        out = Path(output_dir or settings.heatmaps_dir)
        out.mkdir(parents=True, exist_ok=True)

        by_screenshot: dict[str, list[ActionLog]] = {}
        for log in action_logs:
            if log.screenshot_path and log.x > 0 and log.y > 0:
                by_screenshot.setdefault(log.screenshot_path, []).append(log)

        generated = []
        for screenshot_path, logs in by_screenshot.items():
            src = Path(screenshot_path)
            if not src.exists():
                logger.warning("Screenshot not found: %s", src)
                continue

            base = Image.open(src).convert("RGBA")
            overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            for log in logs:
                colour = _frustration_colour(log.frustration_score)
                x, y = int(log.x), int(log.y)
                draw.ellipse(
                    [x - DOT_RADIUS, y - DOT_RADIUS, x + DOT_RADIUS, y + DOT_RADIUS],
                    fill=colour,
                )

            composited = Image.alpha_composite(base, overlay)
            dest = out / f"heatmap_{src.stem}.png"
            composited.save(str(dest))
            generated.append(str(dest))
            logger.info("Heatmap saved: %s", dest)

        return generated


def _frustration_colour(score: float) -> tuple[int, int, int, int]:
    """Map frustration score to green→yellow→red gradient."""
    if score <= LOW_FRUSTRATION:
        return (0, 200, 0, DOT_OPACITY)
    if score >= HIGH_FRUSTRATION:
        return (220, 0, 0, DOT_OPACITY)
    ratio = (score - LOW_FRUSTRATION) / (HIGH_FRUSTRATION - LOW_FRUSTRATION)
    r = int(220 * ratio)
    g = int(200 * (1 - ratio))
    return (r, g, 0, DOT_OPACITY)
