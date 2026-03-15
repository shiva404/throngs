"""
SSE dashboard server for real-time agent state visualization.

Run with: uvicorn throngs.dashboard.server:app --host 0.0.0.0 --port 8765
Or: throngs dashboard --port 8765

Agents push state via POST /event when run with --dashboard-url http://localhost:8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from throngs.config import settings
from throngs.dashboard.bank_store import get_balances, record_sale as bank_record_sale
from throngs.dashboard.broadcaster import SSEBroadcaster
from throngs.persona import PersonaEngine
from throngs.relations import load_throng_graph
from throngs.runner import run_single_agent, run_swarm

logger = logging.getLogger(__name__)

app = FastAPI(title="Throngs Agent Dashboard", version="0.1.0")
broadcaster = SSEBroadcaster()

# Active runs: in-process asyncio tasks (same process, same logs, easy teardown)
_active_runs: dict[str, dict] = {}

# Mount static files (dashboard UI) from this package's static dir
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Resolve personas directory from config (same logic as main.py).
# SWARM_PERSONAS_DIR: e.g. "personas" or "persona-single".
# We try configured dir first, then fallback "personas" so dashboard always finds files.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PERSONAS_DIR = (
    Path(settings.personas_dir)
    if Path(settings.personas_dir).is_absolute()
    else _PROJECT_ROOT / settings.personas_dir
)
_PERSONAS_FALLBACK_DIR = _PROJECT_ROOT / "personas"


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the Sims-style dashboard UI."""
    logger.debug("GET / (dashboard index)")
    html_path = _STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    logger.warning("Dashboard static index.html not found at %s", html_path)
    return HTMLResponse(
        content="<p>Dashboard static files not found. Install the package.</p>",
        status_code=404,
    )


@app.get("/personas")
async def get_personas() -> JSONResponse:
    """Return personas JSON for the street simulation UI (from configured SWARM_PERSONAS_DIR)."""
    path = _personas_path()
    if path and path.exists():
        return JSONResponse(content=json.loads(path.read_text()))
    return JSONResponse(content=[])


@app.get("/street", response_class=HTMLResponse)
async def street() -> HTMLResponse:
    """Serve the 3D street simulation rendering (Three.js WebGL)."""
    logger.debug("GET /street")
    html_path = _STATIC_DIR / "street.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    logger.warning("Street simulation not found at %s", html_path)
    return HTMLResponse(
        content="<p>Street simulation not found.</p>",
        status_code=404,
    )


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE endpoint: stream agent_state events to the browser."""
    logger.info("SSE client connecting; subscribers will be %d", broadcaster.subscriber_count() + 1)
    async def event_generator():
        queue = await broadcaster.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/event")
async def post_event(request: Request) -> dict[str, str]:
    """Accept agent state snapshot from runner; broadcast to all SSE clients."""
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Invalid /event body: %s", e)
        return {"status": "error", "message": "Invalid JSON"}
    n = broadcaster.subscriber_count()
    persona = body.get("persona_name") or body.get("persona") or "?"
    event = body.get("event", "agent_state")
    logger.debug("POST /event %s persona=%s → %d subscribers", event, persona, n)
    await broadcaster.broadcast(body)
    return {"status": "ok", "subscribers": str(n)}


# ─── Simulation launcher ──────────────────────────────────────────────────────

def _find_file(*candidates: Path) -> Path | None:
    for p in candidates:
        if p.exists():
            return p
    return None


def _personas_path() -> Path | None:
    """Path to default_personas.json: configured dir first, then fallback 'personas'."""
    return _find_file(
        Path(os.getcwd()) / settings.personas_dir / "default_personas.json",
        _PERSONAS_DIR / "default_personas.json",
        Path(os.getcwd()) / "personas" / "default_personas.json",
        _PERSONAS_FALLBACK_DIR / "default_personas.json",
    )


def _credentials_path() -> Path | None:
    return _find_file(
        Path(os.getcwd()) / settings.personas_dir / "credentials.json",
        _PERSONAS_DIR / "credentials.json",
        Path(os.getcwd()) / "personas" / "credentials.json",
        _PERSONAS_FALLBACK_DIR / "credentials.json",
    )


def _relations_path() -> Path | None:
    return _find_file(
        Path(os.getcwd()) / settings.personas_dir / "relations_example.json",
        _PERSONAS_DIR / "relations_example.json",
        Path(os.getcwd()) / "personas" / "relations_example.json",
        _PERSONAS_FALLBACK_DIR / "relations_example.json",
    )


def _street_config_path() -> Path | None:
    return _find_file(
        Path(os.getcwd()) / settings.personas_dir / "street_config.json",
        _PERSONAS_DIR / "street_config.json",
        Path(os.getcwd()) / "personas" / "street_config.json",
        _PERSONAS_FALLBACK_DIR / "street_config.json",
    )


# Fallback places only when no street_config.json exists in persona folder(s).
_DEFAULT_SHOPS = [
    {"id": "shop", "name": "Shop", "emoji": "🏪", "color": 0xF39C12, "hex": "#f39c12", "floor": 0xFFF8EE, "pos": [-6, 0, -6]},
    {"id": "office", "name": "Office", "emoji": "🏢", "color": 0x3F88E2, "hex": "#3f88e2", "floor": 0xE8EEFF, "pos": [6, 0, -6]},
]
_DEFAULT_ROOMS: list[dict] = []
_DEFAULT_COLORS = [0x4A8FE2, 0xE2B04A, 0xE24A4A, 0xE24AAD, 0x4AB08A, 0x9B59B6]


@app.get("/street-config")
async def get_street_config() -> JSONResponse:
    """Return persona_config (place/role/emoji for credentialed personas), places (shops/rooms), and colors.
    Street uses this plus GET /runs to show only running throngs; placement comes from here."""
    logger.debug("GET /street-config")
    persona_config: dict[str, dict] = {}
    credentials_map: dict[str, list[str]] = {}
    cred = _credentials_path()
    if cred:
        try:
            data = json.loads(cred.read_text())
            if isinstance(data, dict):
                for company, personas in data.items():
                    if isinstance(personas, dict):
                        credentials_map[company] = list(personas.keys())
        except Exception:
            pass

    street_cfg: dict = {}
    scp = _street_config_path()
    if scp:
        try:
            street_cfg = json.loads(scp.read_text())
        except Exception:
            pass

    company_places: dict[str, str] = (street_cfg.get("company_places") or {})
    persona_display: dict[str, dict] = (street_cfg.get("persona_display") or {})
    cfg_places = street_cfg.get("places")

    first_place_id = (_DEFAULT_SHOPS[0]["id"] if _DEFAULT_SHOPS else "shop")
    if cfg_places and isinstance(cfg_places.get("shops"), list):
        shops = cfg_places["shops"]
        rooms = cfg_places.get("rooms") if isinstance(cfg_places.get("rooms"), list) else _DEFAULT_ROOMS
    else:
        shops = _DEFAULT_SHOPS
        rooms = _DEFAULT_ROOMS

    all_place_ids = [p["id"] for p in shops] + [p["id"] for p in rooms]
    default_place = all_place_ids[0] if all_place_ids else first_place_id

    for company, persona_names in credentials_map.items():
        place_id = company_places.get(company) or default_place
        if place_id not in all_place_ids:
            place_id = default_place
        for i, pname in enumerate(persona_names):
            override = persona_display.get(pname) or {}
            persona_config[pname] = {
                "place": override.get("place") or place_id,
                "role": override.get("role") or ("owner" if i == 0 else "staff"),
                "emoji": override.get("emoji") or "👤",
            }

    return JSONResponse(content={
        "persona_config": persona_config,
        "places": {"shops": shops, "rooms": rooms},
        "colors": street_cfg.get("colors") if isinstance(street_cfg.get("colors"), list) else _DEFAULT_COLORS,
        "sim_time_scale_factor": settings.sim_time_scale_factor,
    })


@app.post("/street/record-sale")
async def street_record_sale(request: Request) -> JSONResponse:
    """Record a sale for a place; updates persisted bank balance (SQLite)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"status": "error", "message": "Invalid JSON"},
            status_code=400,
        )
    place_id = (body.get("place_id") or "").strip()
    amount = body.get("amount")
    account_name = (body.get("account_name") or place_id or "Account").strip()
    if not place_id:
        return JSONResponse(
            content={"status": "error", "message": "place_id is required"},
            status_code=400,
        )
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JSONResponse(
            content={"status": "error", "message": "amount must be a number"},
            status_code=400,
        )
    if amount <= 0:
        return JSONResponse(
            content={"status": "error", "message": "amount must be positive"},
            status_code=400,
        )
    try:
        balance = bank_record_sale(place_id, amount, account_name, description="Customer sale")
        return JSONResponse(content={"status": "ok", "place_id": place_id, "balance": balance})
    except Exception as e:
        logger.exception("Failed to record sale: %s", e)
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500,
        )


@app.get("/street/bank-balances")
async def street_bank_balances() -> JSONResponse:
    """Return persisted bank balances per account (place) for the street UI."""
    try:
        accounts = get_balances()
        return JSONResponse(content={"accounts": accounts})
    except Exception as e:
        logger.exception("Failed to get bank balances: %s", e)
        return JSONResponse(content={"accounts": []})


@app.get("/companies")
async def list_companies() -> JSONResponse:
    """Return available company names from credentials.json."""
    cred = _credentials_path()
    if cred:
        try:
            data = json.loads(cred.read_text())
            if isinstance(data, dict):
                return JSONResponse(content=list(data.keys()))
        except Exception:
            pass
    return JSONResponse(content=[])


@app.get("/credentials-map")
async def credentials_map() -> JSONResponse:
    """Return company→persona mapping without sensitive fields."""
    cred = _credentials_path()
    if cred:
        try:
            data = json.loads(cred.read_text())
            if isinstance(data, dict):
                result = {}
                for company, personas in data.items():
                    if isinstance(personas, dict):
                        result[company] = list(personas.keys())
                return JSONResponse(content=result)
        except Exception:
            pass
    return JSONResponse(content={})


@app.get("/relations")
async def get_relations() -> JSONResponse:
    """Return the throng relations graph JSON."""
    rp = _relations_path()
    if rp:
        try:
            return JSONResponse(content=json.loads(rp.read_text()))
        except Exception:
            pass
    return JSONResponse(content={})


def _dashboard_base_url(request: Request) -> str:
    """Base URL for dashboard (runner will POST /event here)."""
    host = request.headers.get("host", "127.0.0.1:8765")
    return f"http://{host}"


def _load_personas(body: dict) -> list:
    """Load personas list from body override or default path."""
    pf = (body.get("personas_file") or "").strip()
    path = Path(pf) if pf else _personas_path()
    if not path or not path.exists():
        return []
    engine = PersonaEngine()
    return engine.load_from_file(path)


def _credentials_path_from_body(body: dict) -> str | None:
    cf = (body.get("credentials") or "").strip()
    path = Path(cf) if cf else _credentials_path()
    return str(path) if path and path.exists() else None


def _throng_graph_from_body(body: dict):
    relations = (body.get("relations") or "").strip()
    path = Path(relations) if relations else _relations_path()
    if path and path.exists():
        return load_throng_graph(str(path))
    return None


def _run_done_callback(run_id: str, task: asyncio.Task) -> None:
    """Called when a run task completes; store exit_code / error for list_runs."""
    info = _active_runs.get(run_id)
    if not info:
        return
    try:
        task.result()
        info["exit_code"] = 0
        info["error"] = None
    except asyncio.CancelledError:
        info["exit_code"] = -1
        info["error"] = "cancelled"
        logger.info("Run cancelled: run_id=%s", run_id)
    except Exception as e:
        info["exit_code"] = 1
        info["error"] = str(e)
        logger.exception("Run failed: run_id=%s", run_id)


@app.post("/run")
async def start_run(request: Request) -> JSONResponse:
    """Start a single-persona simulation in-process (same process, same logs).

    Expects JSON body: {persona, url, company?, goal?, max_steps?, relations?,
    credentials?, personas_file?}
    """
    body = await request.json()
    persona_name = (body.get("persona") or "").strip()
    url = (body.get("url") or "").strip()
    logger.info("POST /run persona=%s url=%s", persona_name or "(empty)", url or "(empty)")

    if not persona_name or not url:
        return JSONResponse(
            content={"status": "error", "message": "persona and url are required"},
            status_code=400,
        )

    personas = _load_personas(body)
    if not personas:
        return JSONResponse(
            content={"status": "error", "message": "No personas file or empty personas"},
            status_code=400,
        )
    match = [p for p in personas if p.name.lower() == persona_name.lower()]
    if not match:
        return JSONResponse(
            content={"status": "error", "message": f"Persona '{persona_name}' not found"},
            status_code=400,
        )

    run_id = f"{persona_name}_{int(_time.time())}"
    dashboard_url = _dashboard_base_url(request)
    max_steps = int(body.get("max_steps", 50))
    company = (body.get("company") or "").strip() or None
    goal = (body.get("goal") or "").strip() or None
    credentials_file = _credentials_path_from_body(body)
    throng_graph = _throng_graph_from_body(body)

    async def _run() -> None:
        await run_single_agent(
            persona=match[0],
            goal=goal,
            start_url=url,
            max_steps=max_steps,
            credentials_file=credentials_file,
            company=company,
            dashboard_url=dashboard_url,
            throng_graph=throng_graph,
        )

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: _run_done_callback(run_id, t))
    _active_runs[run_id] = {
        "run_id": run_id,
        "task": task,
        "started": _time.time(),
        "mode": "single",
        "persona": persona_name,
        "url": url,
        "company": (body.get("company") or "").strip(),
        "goal": (body.get("goal") or "").strip(),
        "exit_code": None,
        "error": None,
    }
    logger.info("Simulation started in-process: run_id=%s", run_id)
    return JSONResponse(content={"status": "started", "run_id": run_id})


@app.post("/run/swarm")
async def start_swarm(request: Request) -> JSONResponse:
    """Start a full swarm simulation in-process (same process, same logs).

    Expects JSON body: {url, goal?, company?, max_steps?, max_concurrent?,
    relations?, credentials?, personas_file?}
    """
    body = await request.json()
    url = (body.get("url") or "").strip()
    logger.info("POST /run/swarm url=%s", url or "(empty)")

    if not url:
        return JSONResponse(
            content={"status": "error", "message": "url is required"},
            status_code=400,
        )

    personas = _load_personas(body)
    if not personas:
        return JSONResponse(
            content={"status": "error", "message": "No personas file or empty personas"},
            status_code=400,
        )

    run_id = f"swarm_{int(_time.time())}"
    dashboard_url = _dashboard_base_url(request)
    max_steps = int(body.get("max_steps", 50))
    max_concurrent = int(body.get("max_concurrent", 0)) or settings.max_concurrent_agents
    company = (body.get("company") or "").strip() or None
    goal = (body.get("goal") or "").strip() or None
    credentials_file = _credentials_path_from_body(body)
    throng_graph = _throng_graph_from_body(body)

    async def _run() -> None:
        await run_swarm(
            personas=personas,
            goal=goal,
            start_url=url,
            max_steps=max_steps,
            max_concurrent=max_concurrent,
            credentials_file=credentials_file,
            company=company,
            dashboard_url=dashboard_url,
            throng_graph=throng_graph,
        )

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: _run_done_callback(run_id, t))
    _active_runs[run_id] = {
        "run_id": run_id,
        "task": task,
        "started": _time.time(),
        "mode": "swarm",
        "persona": "all",
        "url": url,
        "company": (body.get("company") or "").strip(),
        "goal": (body.get("goal") or "").strip(),
        "exit_code": None,
        "error": None,
    }
    logger.info("Swarm started in-process: run_id=%s personas=%d", run_id, len(personas))
    return JSONResponse(content={"status": "started", "run_id": run_id})


@app.get("/runs")
async def list_runs() -> JSONResponse:
    """Return active and recently-finished simulation runs (in-process tasks)."""
    result = []
    for rid, info in list(_active_runs.items()):
        task = info["task"]
        running = not task.done()
        exit_code = info.get("exit_code")
        if running and exit_code is None:
            exit_code = None
        result.append({
            "run_id": rid,
            "mode": info.get("mode", "single"),
            "persona": info["persona"],
            "url": info["url"],
            "company": info.get("company", ""),
            "goal": info.get("goal", ""),
            "pid": None,
            "running": running,
            "exit_code": exit_code,
            "error": info.get("error"),
            "elapsed": round(_time.time() - info["started"], 1),
        })
    return JSONResponse(content=result)


@app.post("/run/stop")
async def stop_run(request: Request) -> JSONResponse:
    """Cancel a running simulation task (in-process teardown)."""
    body = await request.json()
    run_id = body.get("run_id", "")
    info = _active_runs.get(run_id)

    if not info:
        return JSONResponse(
            content={"status": "error", "message": f"run '{run_id}' not found"},
            status_code=404,
        )

    task = info["task"]
    if not task.done():
        task.cancel()
        logger.info("Cancelled simulation: run_id=%s", run_id)

    return JSONResponse(content={"status": "stopped", "run_id": run_id})
