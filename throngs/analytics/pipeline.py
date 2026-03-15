"""AnalyticsPipeline — post-simulation analytics extracted from runner.py.

Generates heatmaps, UX reports, and trace files from simulation results.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from throngs.config import settings
from throngs.schemas import SimulationResult, SwarmReport

logger = logging.getLogger(__name__)


class AnalyticsPipeline:
    """Produces heatmaps, reports, and traces from a set of simulation results."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    async def run(
        self,
        results: list[SimulationResult],
        goal: str | None = None,
        start_url: str = "",
    ) -> SwarmReport:
        """Generate heatmaps, report, and traces. Returns the SwarmReport."""
        from throngs.analytics.heatmap import HeatmapGenerator
        from throngs.analytics.report import ReportGenerator
        from throngs.llm import create_llm_for_task

        heatmap_dir = str(Path(settings.heatmaps_dir) / self.run_id)
        report_dir = str(Path(settings.reports_dir) / self.run_id)
        traces_dir = str(Path(settings.output_dir) / "traces" / self.run_id)

        # Heatmaps
        heatmap_gen = HeatmapGenerator()
        all_logs = [log for r in results for log in r.action_log]
        heatmap_gen.generate(all_logs, output_dir=heatmap_dir)

        # Report
        report_llm = create_llm_for_task("report")
        report_gen = ReportGenerator(llm=report_llm)
        report_goal = goal if goal else "Autonomous (goals synthesized per persona from inner voice)"
        report = report_gen.compile_report(report_goal, start_url, results)
        await report_gen.generate_markdown_report(report)
        report_gen.save_report(report, output_dir=report_dir)

        # Traces
        dump_traces(results, traces_dir, self.run_id)

        logger.info(
            "Analytics complete [%s]: heatmaps=%s  reports=%s  traces=%s",
            self.run_id, heatmap_dir, report_dir, traces_dir,
        )

        return report


def dump_traces(
    results: list[SimulationResult], traces_dir: str, run_id: str
) -> None:
    """Write per-persona trace files with step-level detail for analysis."""
    out = Path(traces_dir)
    out.mkdir(parents=True, exist_ok=True)

    for result in results:
        persona_traces = {
            "run_id": run_id,
            "persona": result.persona.name,
            "goal": result.goal,
            "start_url": result.start_url,
            "outcome": result.outcome,
            "total_steps": result.total_steps,
            "total_frustration": result.total_frustration,
            "final_url": result.final_url,
            "duration_seconds": result.duration_seconds,
            "steps": [],
        }

        for log in result.action_log:
            frust_bk = None
            if log.frustration_breakdown:
                frust_bk = {
                    "visual_clutter_score": log.frustration_breakdown.visual_clutter_score,
                    "interactable_node_count": log.frustration_breakdown.interactable_node_count,
                    "cognitive_load_multiplier": log.frustration_breakdown.cognitive_load_multiplier,
                    "jargon_density": log.frustration_breakdown.jargon_density,
                    "jargon_penalty": log.frustration_breakdown.jargon_penalty,
                    "friendly_relief": log.frustration_breakdown.friendly_relief,
                    "loop_penalty": log.frustration_breakdown.loop_penalty,
                    "visual_overload_spike": log.frustration_breakdown.visual_overload_spike,
                    "familiarity_discount": log.frustration_breakdown.familiarity_discount,
                    "page_visit_count": log.frustration_breakdown.page_visit_count,
                    "tech_scaling_factor": log.frustration_breakdown.tech_scaling_factor,
                    "progress_relief": log.frustration_breakdown.progress_relief,
                    "raw_delta": log.frustration_breakdown.raw_delta,
                    "capped_delta": log.frustration_breakdown.capped_delta,
                    "carried_frustration": log.frustration_breakdown.carried_frustration,
                    "total_frustration": log.frustration_breakdown.total_frustration,
                }

            visual_obs = None
            if log.visual_overload:
                visual_obs = {
                    "high_saliency_pct": log.visual_overload.high_saliency_pct,
                    "overload_triggered": log.visual_overload.overload_triggered,
                    "top_distractor": log.visual_overload.top_distractor,
                    "distraction_note": log.visual_overload.distraction_note,
                }

            step_trace = {
                "step": log.step,
                "timestamp": log.timestamp.isoformat(),
                "url": log.url,
                "page_title": log.page_title,
                "action": {
                    "type": log.action_type.value,
                    "target_element_id": log.target_element_id,
                    "target_element_name": log.target_element_name,
                    "target_element_role": log.target_element_role,
                    "input_text": log.input_text,
                    "x": log.x,
                    "y": log.y,
                },
                "llm_reasoning": {
                    "internal_monologue": log.internal_monologue,
                    "emotional_state": log.emotional_state,
                    "perceived_clutter_rating": log.perceived_clutter_rating,
                    "task_completed": log.task_completed,
                    "session_notes": log.session_notes,
                },
                "frustration": {
                    "cumulative_score": log.frustration_score,
                    "breakdown": frust_bk,
                    "reasoning": log.frustration_reasoning,
                },
                "visual_observations": {
                    "interactable_element_count": log.interactable_element_count,
                    "viewport_coverage_pct": log.viewport_coverage_pct,
                    "overload": visual_obs,
                    "page_signals": [
                        {
                            "signal_type": sig.signal_type,
                            "severity": sig.severity.value,
                            "message": sig.message,
                            "source_element": sig.source_element,
                        }
                        for sig in (log.visual_signals or [])
                    ],
                },
                "screenshot_path": log.screenshot_path,
            }

            if hasattr(log, "distraction") and log.distraction:
                step_trace["distraction_event"] = {
                    "variant": log.distraction.distraction_variant,
                    "narrative": log.distraction.narrative,
                    "pre_interruption_url": log.distraction.pre_interruption_url,
                    "memory_entries_wiped": log.distraction.memory_entries_wiped,
                    "state_preserved_by_app": log.distraction.state_preserved_by_app,
                    "context_recovered_by_agent": log.distraction.context_recovered_by_agent,
                    "resulting_action": log.distraction.resulting_action,
                    "system_feedback_log": log.distraction.system_feedback_log,
                    "sim_time_away_minutes": log.distraction.sim_time_away_minutes,
                }

            persona_traces["steps"].append(step_trace)

        trace_path = out / f"{result.persona.name}.json"
        trace_path.write_text(json.dumps(persona_traces, indent=2))
        logger.info("Trace saved: %s", trace_path)

    summary = {
        "run_id": run_id,
        "total_agents": len(results),
        "successes": sum(1 for r in results if r.outcome == "success"),
        "failures": sum(1 for r in results if r.outcome == "failure"),
        "agents": [
            {
                "persona": r.persona.name,
                "outcome": r.outcome,
                "steps": r.total_steps,
                "frustration": r.total_frustration,
                "duration": r.duration_seconds,
                "final_url": r.final_url,
            }
            for r in results
        ],
    }
    summary_path = out / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    logger.info("Trace summary saved: %s", summary_path)
