from __future__ import annotations

import json
import logging
from pathlib import Path

from throngs.config import settings
from throngs.schemas import SimulationResult, SwarmReport

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates UX Report Cards from simulation results."""

    def __init__(self, llm=None) -> None:
        self._llm = llm

    def compile_report(
        self, goal: str, start_url: str, results: list[SimulationResult]
    ) -> SwarmReport:
        """Aggregate simulation results into a SwarmReport with basic statistics."""
        total = len(results)
        successes = [r for r in results if r.outcome == "success"]
        disc_rate = len(successes) / total * 100 if total else 0.0
        avg_steps = (
            sum(r.total_steps for r in successes) / len(successes)
            if successes
            else 0.0
        )
        avg_frust = (
            sum(r.total_frustration for r in results) / total if total else 0.0
        )

        friction_points = _identify_friction_points(results)

        report = SwarmReport(
            goal=goal,
            start_url=start_url,
            total_agents=total,
            results=results,
            discoverability_rate=round(disc_rate, 1),
            avg_steps_to_discovery=round(avg_steps, 1),
            avg_frustration=round(avg_frust, 2),
            primary_friction_points=friction_points,
        )
        return report

    async def generate_markdown_report(self, report: SwarmReport) -> str:
        """Use the LLM to synthesize a human-readable markdown report."""
        stats = {
            "goal": report.goal,
            "start_url": report.start_url,
            "total_agents": report.total_agents,
            "discoverability_rate": f"{report.discoverability_rate}%",
            "avg_steps_to_discovery": report.avg_steps_to_discovery,
            "avg_frustration": report.avg_frustration,
            "primary_friction_points": report.primary_friction_points,
            "per_persona_summary": [
                {
                    "persona": r.persona.name,
                    "outcome": r.outcome,
                    "steps": r.total_steps,
                    "frustration": r.total_frustration,
                }
                for r in report.results
            ],
        }

        if self._llm:
            from langchain_core.messages import HumanMessage

            prompt = (
                "You are a UX research analyst. Given the following JSON simulation data, "
                "write a concise markdown UX Report Card. Include sections: "
                "Executive Summary, Discoverability Rate, Average Path Length, "
                "Primary Friction Points, Persona Breakdown, Recommendations.\n\n"
                f"```json\n{json.dumps(stats, indent=2)}\n```"
            )
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            report.report_markdown = response.content
        else:
            report.report_markdown = _fallback_report(report, stats)

        return report.report_markdown

    def save_report(self, report: SwarmReport, output_dir: str | None = None) -> str:
        out = Path(output_dir or settings.reports_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "ux_report.md"
        path.write_text(report.report_markdown)
        logger.info("Report saved: %s", path)

        json_path = out / "ux_report.json"
        json_path.write_text(report.model_dump_json(indent=2))
        return str(path)


def _identify_friction_points(results: list[SimulationResult]) -> list[str]:
    """Extract common friction points from action logs across all agents."""
    high_frust_actions: dict[str, int] = {}
    for r in results:
        for log in r.action_log:
            if log.frustration_score > 10:
                key = f"{log.emotional_state} at {log.url}"
                high_frust_actions[key] = high_frust_actions.get(key, 0) + 1

    sorted_points = sorted(high_frust_actions.items(), key=lambda x: -x[1])
    return [point for point, _ in sorted_points[:5]]


def _fallback_report(report: SwarmReport, stats: dict) -> str:
    lines = [
        f"# UX Report Card: {report.goal}",
        "",
        "## Executive Summary",
        f"Tested with **{report.total_agents}** synthetic personas.",
        "",
        "## Key Metrics",
        f"- **Discoverability Rate:** {report.discoverability_rate}%",
        f"- **Avg Steps to Discovery:** {report.avg_steps_to_discovery}",
        f"- **Avg Frustration Score:** {report.avg_frustration}",
        "",
        "## Primary Friction Points",
    ]
    for fp in report.primary_friction_points:
        lines.append(f"- {fp}")
    if not report.primary_friction_points:
        lines.append("- No major friction points detected.")

    lines.extend(["", "## Persona Breakdown", ""])
    for r in report.results:
        status = "Succeeded" if r.outcome == "success" else "Failed"
        lines.append(
            f"- **{r.persona.name}**: {status} in {r.total_steps} steps "
            f"(frustration: {r.total_frustration})"
        )

    return "\n".join(lines)
