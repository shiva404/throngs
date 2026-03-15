"""Shared logging configuration for CLI and local server."""

from __future__ import annotations

import logging
import sys


def setup_logging(verbose: bool = True) -> None:
    """Configure logging: DEBUG by default so all logs are captured to console."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    root = logging.getLogger()
    root.setLevel(level)
    # Ensure all throngs loggers emit to console at DEBUG
    logging.getLogger("throngs").setLevel(logging.DEBUG)
