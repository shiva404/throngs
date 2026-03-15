# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install
poetry run playwright install chromium

# Run a single persona against a URL
poetry run throngs --url "https://example.com" --goal "Find the invoice page" --personas personas/default_personas.json --single "Martha_Bookkeeper" --verbose

# Run full swarm
poetry run throngs --url "https://example.com" --personas personas/default_personas.json

# Autonomous goal synthesis (no --goal flag)
poetry run throngs --url "https://example.com" --personas personas/default_personas.json

# Start real-time dashboard (separate terminal)
poetry run throngs dashboard --port 8765

# Run with dashboard streaming
poetry run throngs --url "https://example.com" --personas personas/default_personas.json --single "Martha_Bookkeeper" --dashboard-url http://127.0.0.1:8765
```

No test suite exists — testing is done via CLI integration runs.

## Architecture

**Throngs** is a cognitive UX simulation framework. It deploys LLM-powered autonomous agents ("personas") into web apps via Playwright to detect usability issues before production. Each persona has a "DNA" profile (age, domain literacy, tech literacy, motor precision, emotional traits) that drives how they interact.

### Execution Flow (LangGraph State Machine)

Each agent runs through these graph nodes (`throngs/graph/nodes.py`):
```
initialize → perceive → handle_login → handle_profile_setup → calculate_load
  → reason → execute_action → evaluate → (loop back to perceive or END)
```

`build_agent_graph()` in `throngs/graph/agent.py` wires these nodes with conditional edges. `AgentState` (in `throngs/schemas.py`) is the shared state threaded through all nodes.

### Key Modules

| Module | Role |
|--------|------|
| `throngs/main.py` | CLI entry point (click) |
| `throngs/runner.py` | `run_single_agent()` / `run_swarm()` orchestration, goal synthesis dispatch |
| `throngs/graph/` | LangGraph state machine — node factories and graph builder |
| `throngs/executive/` | Goal synthesis: `synthesize_goal()` and `synthesize_goal_chain()` for autonomous task decomposition |
| `throngs/perception/` | BrowserManager (Playwright), A11y tree extraction, saliency maps, visibility scoring, overload detection |
| `throngs/persona/` | PersonaEngine — loads persona DNA, generates system prompts, manages credentials |
| `throngs/frustration/` | FrustrationEngine — 12+ sub-metrics (jargon density, visual clutter, repeated loops, overload) |
| `throngs/memory/` | CognitiveMemoryStore — 4-phase sleep cycle consolidation into ChromaDB; Ebbinghaus decay |
| `throngs/motor/` | MotorErrorEngine — misclicks and typos driven by persona `motor_precision` / `typo_rate` |
| `throngs/hesitation/` | HesitationEngine — risk-aversion checks (regex fast-path + optional LLM analysis) before high-stakes actions |
| `throngs/distraction/` | DistractionEngine — COFFEE_BREAK, TAB_SWITCH, POPUP_SQUIRREL interruptions with memory wipe |
| `throngs/analytics/` | HeatmapGenerator, ReportGenerator (LLM-driven UX report card) |
| `throngs/dashboard/` | FastAPI + SSE real-time dashboard server |
| `throngs/llm.py` | Task-based LLM factory — selects model by task (goal_synthesis, reason, report, etc.) |
| `throngs/config.py` | All config via `SWARM_*` env vars |
| `throngs/schemas.py` | Pydantic models for PersonaDNA, ActionLog, AgentState, memory types |

### LLM Configuration

All LLM calls go through `throngs/llm.py` which selects model by task. Configured via `SWARM_*` env vars:

```
SWARM_LOCAL_BASE_URL=http://localhost:4000   # LLM API endpoint (OpenAI-compatible)
SWARM_LOCAL_MODEL=local-gpt-oss              # Default text model
SWARM_LOCAL_VISION_MODEL=local-gpt-oss      # Vision model (used for reason node)
SWARM_MODEL_GOAL_SYNTHESIS=...              # Per-task model overrides
SWARM_MODEL_REASON=...
SWARM_MODEL_REPORT=...
```

### Perception Levels

Controlled by `SWARM_PERCEPTION_LEVEL`: `basic` | `dom` | `saliency` | `hybrid` | `full`

Higher levels add saliency maps (ONNX computer vision) and deeper visual analysis at the cost of latency.

### Memory System

Four-phase sleep cycle: short-term action buffer → LLM compression into `muscle_memory_rule` / `emotional_scar` entries → ChromaDB semantic vault → Ebbinghaus forgetting curve decay.

### Output Structure

```
output/
├── screenshots/<run_id>/<persona>/
├── heatmaps/<run_id>/
├── reports/<run_id>/
└── traces/<run_id>/
```
