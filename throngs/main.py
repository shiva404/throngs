from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from throngs.config import settings
from throngs.logging_config import setup_logging
from throngs.persona import PersonaEngine
from throngs.relations import load_throng_graph
from throngs.runner import run_single_agent, run_swarm
from throngs.schemas import PersonaDNA
from throngs.workspace import SoftwareRegistry

# ---------------------------------------------------------------------------
# Resolve paths relative to the configured personas directory.
# SWARM_PERSONAS_DIR controls which profile set is used:
#   personas/         — full 6-persona swarm (default)
#   persona-single/   — 1-persona debug rig (set SWARM_PERSONAS_DIR=persona-single)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PERSONAS_DIR = (
    Path(settings.personas_dir)
    if Path(settings.personas_dir).is_absolute()
    else _PROJECT_ROOT / settings.personas_dir
)
_DEFAULT_PERSONAS_PATH = str(_PERSONAS_DIR / "default_personas.json")
_DEFAULT_CREDENTIALS_PATH = str(_PERSONAS_DIR / "credentials.json")

logger = logging.getLogger(__name__)


def cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="throngs",
        description="Synthetic Swarm — AI-Driven UX Simulation Engine",
    )
    subparsers = parser.add_subparsers(dest="cmd", help="Command")

    parser.add_argument("--url", help="Starting URL to test (required for run)")
    parser.add_argument(
        "--goal",
        default=None,
        help="Goal for the agent(s) to achieve. If omitted, a goal is synthesized on-demand from the persona's inner voice (Autonomous Executive Function spec).",
    )
    parser.add_argument(
        "--personas",
        default=_DEFAULT_PERSONAS_PATH,
        help=(
            "Path to personas JSON file "
            f"(default: {_DEFAULT_PERSONAS_PATH}, override via SWARM_PERSONAS_DIR)"
        ),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Maximum steps per agent (default: 50)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=2,
        help="Max concurrent agents (default from config)",
    )
    parser.add_argument(
        "--single",
        type=str,
        default=None,
        help="Run a single persona by name instead of the full swarm",
    )
    parser.add_argument(
        "--credentials",
        type=str,
        default=_DEFAULT_CREDENTIALS_PATH,
        help=(
            "Path to credentials JSON file mapping persona names to login details "
            f"(default: {_DEFAULT_CREDENTIALS_PATH}, override via SWARM_PERSONAS_DIR)"
        ),
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Company name to select from the credentials file (lists available companies when set to '?')",
    )
    parser.add_argument(
        "--dashboard-url",
        type=str,
        default=None,
        help="Push real-time agent state to this dashboard (e.g. http://localhost:8765). Start with: throngs dashboard --port 8765",
    )
    parser.add_argument(
        "--relations",
        type=str,
        default=None,
        help="Path to throng relationship graph (JSON or YAML). Defines who depends on whom (accountant, supplier, delivery, etc.); persona_id in graph links personas to throngs.",
    )
    parser.add_argument(
        "--software-stack",
        type=str,
        default=None,
        help="Path to a software stack JSON file defining available apps (accounting, email, etc.). If omitted, --url is used as a single-app registry.",
    )
    parser.add_argument(
        "--business-type",
        type=str,
        default=None,
        choices=["plumber", "event_organizer", "cpa"],
        help="Shortcut: auto-loads a built-in software stack for this business type. Overrides --software-stack.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=True, help="Enable debug logging (default: on)"
    )
    parser.add_argument(
        "--no-verbose", action="store_false", dest="verbose", help="Use INFO log level only"
    )

    dashboard_parser = subparsers.add_parser("dashboard", help="Start real-time dashboard server (SSE)")
    dashboard_parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    dashboard_parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1)")

    args = parser.parse_args()
    setup_logging(getattr(args, "verbose", False))

    if getattr(args, "cmd", None) == "dashboard":
        import uvicorn
        from throngs.dashboard import server as dashboard_server
        host = args.host
        port = args.port
        logger.info("Starting dashboard on http://%s:%s", host, port)
        print(f"Dashboard at http://{host}:{port} — open in browser; run agents with --dashboard-url http://{host}:{port}")
        uvicorn.run(dashboard_server.app, host=host, port=port)
        return

    has_url = bool(getattr(args, "url", None))
    has_stack = bool(getattr(args, "software_stack", None) or getattr(args, "business_type", None))
    if not has_url and not has_stack:
        parser.error("--url or --software-stack/--business-type is required for run. Use 'throngs dashboard' to start the dashboard server only.")

    if args.company == "?":
        companies = PersonaEngine.list_companies(args.credentials)
        if companies:
            print("Available companies in credentials file:")
            for c in companies:
                print(f"  - {c}")
        else:
            print("Credentials file uses flat format (no company grouping).")
        sys.exit(0)

    # Build SoftwareRegistry from CLI args
    sw_registry = None
    if getattr(args, "business_type", None):
        stack_dir = _PERSONAS_DIR / "software_stacks"
        stack_path = stack_dir / f"{args.business_type}_stack.json"
        if stack_path.exists():
            sw_registry = SoftwareRegistry.from_file(stack_path)
            logger.info("Loaded software stack for %s from %s", args.business_type, stack_path)
        else:
            print(f"Built-in stack not found: {stack_path}")
            sys.exit(1)
    elif getattr(args, "software_stack", None):
        sw_registry = SoftwareRegistry.from_file(args.software_stack)
        logger.info("Loaded software stack from %s", args.software_stack)

    engine = PersonaEngine()
    personas = engine.load_from_file(args.personas)

    if not personas:
        print("No personas found in the provided file.")
        sys.exit(1)

    if args.single:
        match = [p for p in personas if p.name.lower() == args.single.lower()]
        if not match:
            print(f"Persona '{args.single}' not found. Available: {[p.name for p in personas]}")
            sys.exit(1)
        persona = match[0]
        logger.info(
            "Starting single agent: persona=%s url=%s goal=%s max_steps=%s dashboard=%s",
            persona.name, args.url, args.goal or "(auto)", args.max_steps, args.dashboard_url or "none",
        )
        throng_graph = load_throng_graph(args.relations) if getattr(args, "relations", None) else None
        result = asyncio.run(
            run_single_agent(
                persona=persona,
                goal=args.goal if args.goal else None,
                start_url=args.url or "",
                software_registry=sw_registry,
                max_steps=args.max_steps,
                credentials_file=args.credentials,
                company=args.company,
                dashboard_url=args.dashboard_url,
                throng_graph=throng_graph,
            )
        )
        print(f"\n{'='*60}")
        print(f"Persona: {result.persona.name}")
        print(f"Outcome: {result.outcome}")
        print(f"Steps:   {result.total_steps}")
        print(f"Frustration: {result.total_frustration:.1f}")
        print(f"Duration: {result.duration_seconds:.1f}s")
        print(f"{'='*60}")
        logger.info("Single agent finished: persona=%s outcome=%s steps=%s", result.persona.name, result.outcome, result.total_steps)
    else:
        logger.info(
            "Starting swarm: url=%s goal=%s max_concurrent=%s max_steps=%s personas=%d dashboard=%s",
            args.url, args.goal or "(auto)", args.max_concurrent, args.max_steps, len(personas), args.dashboard_url or "none",
        )
        throng_graph = load_throng_graph(args.relations) if getattr(args, "relations", None) else None
        report = asyncio.run(
            run_swarm(
                personas=personas,
                goal=args.goal if args.goal else None,
                start_url=args.url or "",
                software_registry=sw_registry,
                max_concurrent=args.max_concurrent,
                max_steps=args.max_steps,
                credentials_file=args.credentials,
                company=args.company,
                dashboard_url=args.dashboard_url,
                throng_graph=throng_graph,
            )
        )
        print(f"\n{'='*60}")
        print(report.report_markdown)
        print(f"{'='*60}")
        completed = sum(1 for r in report.results if r.outcome == "success")
        logger.info("Swarm finished: completed=%d failed=%d total_agents=%d", completed, len(report.results) - completed, report.total_agents)


if __name__ == "__main__":
    cli()
