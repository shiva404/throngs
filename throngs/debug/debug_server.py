"""
Component Debug Server — test individual Throngs subsystems in isolation.

Run with:
    python -m throngs.debug.server
    # or
    uvicorn throngs.debug.server:app --host 0.0.0.0 --port 8766 --reload

Provides a visual UI to exercise each engine independently:
  - Saliency heatmap (eye-tracking prediction)
  - Visual Perception Engine (4-phase pipeline)
  - Frustration Engine
  - Motor Error Engine (click scatter, typos, proximity)
  - Hesitation Engine
  - Distraction Engine
  - A11y tree formatting
  - F-Pattern geographic weighting visualizer
  - Live URL capture via Playwright
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image

from throngs.config import settings
from throngs.perception.saliency import (
    compute_saliency_map,
    high_intensity_percentage,
)
from throngs.perception.visibility import VisualPerceptionEngine
from throngs.perception.a11y import extract_a11y_tree
from throngs.schemas import (
    A11yElement,
    PersonaDNA,
    VisualOverloadInfo,
    VisualSignal,
)
from throngs.frustration.engine import FrustrationEngine
from throngs.motor.engine import MotorErrorEngine
from throngs.hesitation.engine import HesitationEngine
from throngs.distraction.engine import DistractionEngine

logger = logging.getLogger(__name__)

app = FastAPI(title="Throngs Component Debugger", version="0.1.0")

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Shared engine instances for stateful testing
_frustration_engine = FrustrationEngine()
_motor_engine = MotorErrorEngine()
_perception_engine = VisualPerceptionEngine()

# Hesitation engine — try to attach LLM if available
_hesitation_llm = None
try:
    if settings.hesitation_llm_enabled:
        from throngs.llm import create_llm_for_task
        _hesitation_llm = create_llm_for_task("hesitation", max_tokens=512)
except Exception:
    pass
_hesitation_engine = HesitationEngine(llm=_hesitation_llm)

# Distraction engine — try to attach LLM if available
_distraction_llm = None
try:
    if settings.distraction_enabled and settings.distraction_llm_enabled:
        from throngs.llm import create_llm_for_task as _create_llm
        _distraction_llm = _create_llm("distraction", max_tokens=1024)
except Exception:
    pass
_distraction_engine = DistractionEngine(llm=_distraction_llm)

# Cached capture data from last live capture
_last_capture: dict = {}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = _STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<p>Debug UI not found.</p>", status_code=404)


# ── Saliency Heatmap ─────────────────────────────────────────────────────────

@app.post("/api/saliency")
async def compute_saliency(
    screenshot: UploadFile = File(...),
    viewport_width: int = Form(1280),
    viewport_height: int = Form(720),
):
    """Compute saliency heatmap from uploaded screenshot. Returns overlay PNG."""
    img_bytes = await screenshot.read()
    heatmap = compute_saliency_map(img_bytes, viewport_width, viewport_height)

    hi_pct = high_intensity_percentage(heatmap)

    overlay_b64 = _heatmap_to_overlay_b64(heatmap, img_bytes)

    return JSONResponse({
        "heatmap_overlay_b64": overlay_b64,
        "high_intensity_pct": round(hi_pct, 2),
        "shape": list(heatmap.shape),
        "max_intensity": int(np.max(heatmap)),
        "mean_intensity": round(float(np.mean(heatmap)), 1),
    })


# ── Visual Perception Engine (full pipeline) ─────────────────────────────────

@app.post("/api/perception")
async def run_perception(request: Request):
    """Run the full 4-phase visual perception pipeline.

    Expects JSON: {screenshot_b64, elements, viewport_width, viewport_height,
                   perception_level, goal, rtl}
    """
    body = await request.json()
    screenshot_b64 = body.get("screenshot_b64", "")
    raw_elements = body.get("elements", [])
    vw = body.get("viewport_width", 1280)
    vh = body.get("viewport_height", 720)
    goal = body.get("goal", "")
    rtl = body.get("rtl", False)
    level = body.get("perception_level", settings.perception_level)

    if not screenshot_b64 and _last_capture.get("screenshot_b64"):
        screenshot_b64 = _last_capture["screenshot_b64"]
    if not raw_elements and _last_capture.get("elements"):
        raw_elements = _last_capture["elements"]

    screenshot_bytes = base64.b64decode(screenshot_b64) if screenshot_b64 else b""

    elements = [A11yElement.model_validate(e) for e in raw_elements]

    original_level = settings.perception_level
    settings.perception_level = level
    try:
        enriched, overload = _perception_engine.process(
            elements, screenshot_bytes, vw, vh, goal=goal, rtl=rtl
        )
    finally:
        settings.perception_level = original_level

    heatmap_overlay_b64 = ""
    if screenshot_bytes:
        heatmap = compute_saliency_map(screenshot_bytes, vw, vh)
        heatmap_overlay_b64 = _heatmap_to_overlay_b64(heatmap, screenshot_bytes)

    return JSONResponse({
        "elements": [e.model_dump() for e in enriched],
        "overload": overload.model_dump(),
        "heatmap_overlay_b64": heatmap_overlay_b64,
        "perception_level": level,
    })


# ── Frustration Engine ────────────────────────────────────────────────────────

@app.post("/api/frustration")
async def calculate_frustration(request: Request):
    """Calculate frustration metrics.

    Expects JSON: {persona, elements, visible_text, current_url,
                   base_frustration, last_action_type, last_element_id}
    """
    body = await request.json()
    persona = PersonaDNA.model_validate(body.get("persona", {
        "name": "Debug User", "domain_literacy": 5,
        "tech_literacy": 5, "patience_budget": 50,
    }))
    raw_elements = body.get("elements", _last_capture.get("elements", []))
    elements = [A11yElement.model_validate(e) for e in raw_elements]
    visible_text = body.get("visible_text", _last_capture.get("visible_text", ""))
    current_url = body.get("current_url", _last_capture.get("url", "http://example.com"))
    base_frustration = body.get("base_frustration", 0.0)
    last_action_type = body.get("last_action_type", "")
    last_element_id = body.get("last_element_id", "")

    overload_data = body.get("visual_overload")
    overload = VisualOverloadInfo.model_validate(overload_data) if overload_data else None

    if body.get("reset", False):
        _frustration_engine.reset()

    metrics = _frustration_engine.calculate(
        persona=persona,
        a11y_elements=elements,
        visible_text=visible_text,
        current_url=current_url,
        base_frustration=base_frustration,
        visual_overload=overload,
        last_action_type=last_action_type,
        last_element_id=last_element_id,
    )
    rage_quit = _frustration_engine.should_rage_quit(
        metrics.total_frustration, persona
    )
    result = metrics.model_dump()
    result["rage_quit"] = rage_quit
    result["patience_budget"] = persona.patience_budget
    return JSONResponse(result)


@app.post("/api/frustration/reset")
async def reset_frustration():
    _frustration_engine.reset()
    return JSONResponse({"status": "reset"})


# ── Motor Error Engine ────────────────────────────────────────────────────────

@app.post("/api/motor/scatter")
async def motor_scatter(request: Request):
    """Test click scatter.

    Expects JSON: {target_element, all_elements, motor_precision, viewport_width,
                   viewport_height, device}
    """
    body = await request.json()
    target = A11yElement.model_validate(body["target_element"])
    all_els = [A11yElement.model_validate(e) for e in body.get("all_elements", [target.model_dump()])]
    precision = body.get("motor_precision", 0.95)
    vw = body.get("viewport_width", 1280)
    vh = body.get("viewport_height", 720)
    device = body.get("device", "desktop")

    trials = body.get("trials", 50)
    results = []
    misclick_count = 0
    for _ in range(trials):
        ax, ay, hit_id, is_miss = _motor_engine.apply_click_scatter(
            target, all_els, precision, vw, vh, device
        )
        results.append({"x": round(ax, 1), "y": round(ay, 1),
                        "hit_element": hit_id, "misclick": is_miss})
        if is_miss:
            misclick_count += 1

    return JSONResponse({
        "target": {"x": target.x, "y": target.y, "w": target.width, "h": target.height},
        "trials": trials,
        "misclick_count": misclick_count,
        "misclick_rate": round(misclick_count / trials * 100, 1),
        "scatter_points": results,
    })


@app.post("/api/motor/typos")
async def motor_typos(request: Request):
    """Test typo injection.

    Expects JSON: {text, typo_rate, trials}
    """
    body = await request.json()
    text = body.get("text", "Hello World")
    typo_rate = body.get("typo_rate", 0.05)
    trials = body.get("trials", 20)

    results = []
    inject_count = 0
    for _ in range(trials):
        mutated, did_inject = _motor_engine.inject_typos(text, typo_rate)
        results.append({"mutated": mutated, "had_typo": did_inject})
        if did_inject:
            inject_count += 1

    return JSONResponse({
        "original": text,
        "typo_rate": typo_rate,
        "trials": trials,
        "injection_count": inject_count,
        "injection_rate": round(inject_count / trials * 100, 1),
        "samples": results[:20],
    })


@app.post("/api/motor/proximity")
async def motor_proximity(request: Request):
    """Test proximity anxiety detection.

    Expects JSON: {target_element, all_elements, device}
    """
    body = await request.json()
    target = A11yElement.model_validate(body["target_element"])
    all_els = [A11yElement.model_validate(e) for e in body.get("all_elements", [])]
    device = body.get("device", "desktop")

    is_anxious = _motor_engine.check_proximity_anxiety(target, all_els, device)

    return JSONResponse({
        "target_element_id": target.element_id,
        "proximity_anxiety": is_anxious,
        "device": device,
        "min_margin_px": (
            settings.proximity_min_margin_mobile if device == "mobile"
            else settings.proximity_min_margin_desktop
        ),
    })


# ── Hesitation Engine ─────────────────────────────────────────────────────────

@app.post("/api/hesitation")
async def test_hesitation(request: Request):
    """Test hesitation triggers with LLM-driven risk analysis.

    Expects JSON: {element_name, action_type, risk_tolerance, element_role,
                   page_url, goal, nearby_elements, trials}
    """
    from throngs.hesitation.engine import HIGH_STAKES_PATTERNS

    body = await request.json()
    element_name = body.get("element_name", "Submit Payment")
    action_type = body.get("action_type", "click")
    risk_tolerance = body.get("risk_tolerance", 5)
    element_role = body.get("element_role", "button")
    page_url = body.get("page_url", _last_capture.get("url", ""))
    goal = body.get("goal", "")
    nearby_elements = body.get("nearby_elements", [])
    trials = body.get("trials", 50)

    if not nearby_elements and _last_capture.get("elements"):
        nearby_elements = [
            e.get("name", "")[:60]
            for e in _last_capture["elements"][:8]
            if e.get("name")
        ]

    action_is_click = action_type.lower() == "click"
    regex_matched = bool(HIGH_STAKES_PATTERNS.search(element_name))

    risk_analysis = await _hesitation_engine.analyze_risk(
        element_name=element_name,
        element_role=element_role,
        page_url=page_url,
        goal=goal,
        nearby_elements=nearby_elements,
    )

    trigger_count = 0
    for _ in range(trials):
        if await _hesitation_engine.should_hesitate(
            element_name=element_name,
            action_type=action_type,
            risk_tolerance=risk_tolerance,
            element_role=element_role,
            page_url=page_url,
            goal=goal,
            nearby_elements=nearby_elements,
        ):
            trigger_count += 1

    prompt = ""
    if trigger_count > 0:
        prompt = _hesitation_engine.build_hesitation_prompt(
            element_name, risk_tolerance, risk_analysis=risk_analysis,
        )

    gate_reason = ""
    if not action_is_click:
        gate_reason = f"Action '{action_type}' is not 'click' — hesitation only fires on clicks"
    elif not risk_analysis.get("is_high_stakes") and risk_analysis.get("risk_level", 0) < 5:
        gate_reason = (
            f"Risk analysis determined '{element_name}' is not high-stakes "
            f"(risk_level={risk_analysis.get('risk_level', 0)}, "
            f"category={risk_analysis.get('risk_category', 'safe')}). "
            f"Reasoning: {risk_analysis.get('reasoning', 'N/A')}"
        )

    return JSONResponse({
        "element_name": element_name,
        "action_type": action_type,
        "risk_tolerance": risk_tolerance,
        "trials": trials,
        "regex_matched": regex_matched,
        "action_is_click": action_is_click,
        "risk_analysis": risk_analysis,
        "gate_reason": gate_reason,
        "trigger_count": trigger_count,
        "trigger_rate": round(trigger_count / trials * 100, 1),
        "hesitation_prompt": prompt,
        "llm_available": _hesitation_llm is not None,
    })


# ── Distraction Engine ────────────────────────────────────────────────────────

@app.post("/api/distraction")
async def test_distraction(request: Request):
    """Test LLM-driven distraction generation with persona and environment context.

    Expects JSON: {
        persona?, goal?, current_url?, page_title?, step?,
        last_action?, visual_signals?, interruption_probability?, trials?
    }
    """
    body = await request.json()
    prob = body.get("interruption_probability", 0.05)
    trials = body.get("trials", 100)

    raw_persona = body.get("persona", {
        "name": "Debug User",
        "description": "A generic test user.",
        "domain_literacy": 5,
        "tech_literacy": 5,
        "patience_budget": 50,
    })
    persona = PersonaDNA.model_validate(raw_persona)
    goal = body.get("goal", _last_capture.get("title", ""))
    current_url = body.get("current_url", _last_capture.get("url", "http://example.com"))
    page_title = body.get("page_title", _last_capture.get("title", ""))
    step = body.get("step", 5)
    last_action = body.get("last_action", "navigating the interface")

    raw_signals = body.get("visual_signals", _last_capture.get("visual_signals", []))
    visual_signals: list[VisualSignal] = []
    for sig in raw_signals:
        try:
            visual_signals.append(VisualSignal.model_validate(sig) if isinstance(sig, dict) else sig)
        except Exception:
            pass

    trigger_count = 0
    for i in range(trials):
        if _distraction_engine.should_trigger_interruption(i, prob):
            trigger_count += 1

    squirrel_signal = _distraction_engine.detect_squirrel(visual_signals, goal)

    distraction_result = await _distraction_engine.generate_distraction(
        persona=persona,
        goal=goal,
        current_url=current_url,
        page_title=page_title,
        step=step,
        last_action_summary=last_action,
        visual_signals=visual_signals,
        squirrel_signal=squirrel_signal,
    )

    return JSONResponse({
        "interruption_probability": prob,
        "trials": trials,
        "trigger_count": trigger_count,
        "trigger_rate": round(trigger_count / trials * 100, 1),
        "variant": distraction_result["variant"],
        "narrative": distraction_result["narrative"],
        "reorientation_prompt": distraction_result["reorientation_prompt"],
        "memory_wipe_lines": distraction_result["memory_wipe_lines"],
        "estimated_away_minutes": distraction_result.get("estimated_away_minutes", 0),
        "squirrel_detected": squirrel_signal is not None,
        "squirrel_message": squirrel_signal.message[:200] if squirrel_signal else "",
        "visual_signals_count": len(visual_signals),
        "llm_available": _distraction_llm is not None,
        "persona_name": persona.name,
    })


# ── A11y Tree ─────────────────────────────────────────────────────────────────

@app.post("/api/a11y-tree")
async def format_a11y_tree(request: Request):
    """Format elements as a11y tree text.

    Expects JSON: {elements, patience_budget, skimming_enabled}
    """
    body = await request.json()
    raw_elements = body.get("elements", _last_capture.get("elements", []))
    elements = [A11yElement.model_validate(e) for e in raw_elements]
    patience = body.get("patience_budget", 100)
    skimming = body.get("skimming_enabled", False)

    tree_text = extract_a11y_tree(elements, patience, skimming)
    total = len(elements)
    visible = len([e for e in elements if e.passed_blindspot])
    hidden = total - visible

    return JSONResponse({
        "tree_text": tree_text,
        "total_elements": total,
        "visible_elements": visible,
        "hidden_by_blindspot": hidden,
    })


# ── F-Pattern Geographic Weighting ────────────────────────────────────────────

@app.post("/api/geographic")
async def geographic_weighting(request: Request):
    """Visualize F-Pattern / I-Pattern geographic weighting.

    Expects JSON: {viewport_width, viewport_height, rtl, elements?}
    """
    body = await request.json()
    vw = body.get("viewport_width", 1280)
    vh = body.get("viewport_height", 720)
    rtl = body.get("rtl", False)

    F_PATTERN = [[1.5, 1.2, 0.9], [1.2, 1.0, 0.6], [0.7, 0.7, 0.4]]
    F_PATTERN_RTL = [[0.9, 1.2, 1.5], [0.6, 1.0, 1.2], [0.4, 0.7, 0.7]]
    I_PATTERN = [[1.0, 1.5, 1.0], [0.8, 1.3, 0.8], [0.5, 0.8, 0.5]]

    if vw < 768:
        matrix = I_PATTERN
        pattern_name = "I-Pattern (Mobile)"
    elif rtl:
        matrix = F_PATTERN_RTL
        pattern_name = "F-Pattern RTL"
    else:
        matrix = F_PATTERN
        pattern_name = "F-Pattern LTR"

    raw_elements = body.get("elements", _last_capture.get("elements", []))
    element_sectors = []
    for el_data in raw_elements:
        el = A11yElement.model_validate(el_data) if isinstance(el_data, dict) else el_data
        col = min(2, max(0, int(el.x / (vw / 3.0)))) if vw > 0 else 0
        row = min(2, max(0, int(el.y / (vh / 3.0)))) if vh > 0 else 0
        element_sectors.append({
            "element_id": el.element_id,
            "name": el.name[:60],
            "row": row, "col": col,
            "multiplier": matrix[row][col],
        })

    return JSONResponse({
        "pattern_name": pattern_name,
        "viewport_width": vw,
        "viewport_height": vh,
        "rtl": rtl,
        "matrix": matrix,
        "element_sectors": element_sectors,
    })


# ── Live URL Capture ──────────────────────────────────────────────────────────

@app.post("/api/capture")
async def capture_url(request: Request):
    """Capture a live URL using Playwright and cache the result.

    Expects JSON: {url, viewport_width?, viewport_height?}
    """
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "url is required"}, status_code=400)

    vw = body.get("viewport_width", settings.viewport_width)
    vh = body.get("viewport_height", settings.viewport_height)

    from playwright.async_api import async_playwright
    from throngs.perception.browser import _DOM_PHYSICAL_JS, _VISUAL_SIGNALS_JS

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": vw, "height": vh}
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2.0)

            screenshot_bytes = await page.screenshot(full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

            dom_data = await page.evaluate(_DOM_PHYSICAL_JS) or []
            visible_text = await page.evaluate("() => document.body.innerText") or ""
            title = await page.title()

            raw_signals = []
            try:
                raw_signals = await page.evaluate(_VISUAL_SIGNALS_JS) or []
            except Exception:
                pass

            await browser.close()
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    elements = []
    for i, dom in enumerate(dom_data, start=1):
        elements.append({
            "element_id": f"e{i}",
            "role": dom.get("role", ""),
            "name": dom.get("name", ""),
            "x": dom.get("x", 0),
            "y": dom.get("y", 0),
            "width": dom.get("width", 0),
            "height": dom.get("height", 0),
            "text_color": dom.get("color", ""),
            "bg_color": dom.get("backgroundColor", ""),
            "opacity": dom.get("opacity", 1.0),
        })

    global _last_capture
    _last_capture = {
        "url": url,
        "title": title,
        "screenshot_b64": screenshot_b64,
        "elements": elements,
        "visible_text": visible_text[:5000],
        "visual_signals": raw_signals,
        "viewport_width": vw,
        "viewport_height": vh,
    }

    return JSONResponse({
        "url": url,
        "title": title,
        "screenshot_b64": screenshot_b64,
        "element_count": len(elements),
        "elements": elements,
        "visible_text": visible_text[:2000],
        "visual_signals": raw_signals[:10],
        "viewport_width": vw,
        "viewport_height": vh,
    })


@app.get("/api/last-capture")
async def get_last_capture():
    """Return the cached data from the most recent URL capture."""
    if not _last_capture:
        return JSONResponse({"error": "No capture yet. Use /api/capture first."}, status_code=404)
    return JSONResponse({
        "url": _last_capture.get("url", ""),
        "title": _last_capture.get("title", ""),
        "element_count": len(_last_capture.get("elements", [])),
        "has_screenshot": bool(_last_capture.get("screenshot_b64")),
        "viewport_width": _last_capture.get("viewport_width", 1280),
        "viewport_height": _last_capture.get("viewport_height", 720),
    })


# ── Config Inspector ──────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Return current Throngs settings relevant to debug."""
    return JSONResponse({
        "perception_level": settings.perception_level,
        "visibility_threshold": settings.visibility_threshold,
        "fat_finger_min_px": settings.fat_finger_min_px,
        "wcag_min_contrast": settings.wcag_min_contrast,
        "visual_overload_clutter_pct": settings.visual_overload_clutter_pct,
        "visual_signals_enabled": settings.visual_signals_enabled,
        "geographic_weighting_enabled": settings.geographic_weighting_enabled,
        "motor_errors_enabled": settings.motor_errors_enabled,
        "risk_aversion_enabled": settings.risk_aversion_enabled,
        "distraction_enabled": settings.distraction_enabled,
        "distraction_llm_enabled": settings.distraction_llm_enabled,
        "hesitation_llm_enabled": settings.hesitation_llm_enabled,
        "skimming_enabled": settings.skimming_enabled,
        "skimming_max_list_items": settings.skimming_max_list_items,
        "viewport_width": settings.viewport_width,
        "viewport_height": settings.viewport_height,
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _heatmap_to_overlay_b64(heatmap: np.ndarray, original_bytes: bytes) -> str:
    """Colorize a grayscale saliency heatmap and composite over the original screenshot."""
    original = Image.open(io.BytesIO(original_bytes)).convert("RGBA")
    h, w = heatmap.shape[:2]

    hm = heatmap.astype(np.float32)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    # Vectorized blue→green→yellow→red gradient
    mask1 = hm < 64
    mask2 = (hm >= 64) & (hm < 128)
    mask3 = (hm >= 128) & (hm < 200)
    mask4 = hm >= 200

    t1 = hm / 64.0
    rgba[mask1, 0] = 0
    rgba[mask1, 1] = 0
    rgba[mask1, 2] = (128 + 127 * t1[mask1]).astype(np.uint8)

    t2 = (hm - 64) / 64.0
    rgba[mask2, 0] = 0
    rgba[mask2, 1] = (255 * t2[mask2]).astype(np.uint8)
    rgba[mask2, 2] = (255 * (1 - t2[mask2])).astype(np.uint8)

    t3 = (hm - 128) / 72.0
    rgba[mask3, 0] = (255 * t3[mask3]).astype(np.uint8)
    rgba[mask3, 1] = 255
    rgba[mask3, 2] = 0

    t4 = (hm - 200) / 55.0
    rgba[mask4, 0] = 255
    rgba[mask4, 1] = (255 * (1 - np.clip(t4[mask4], 0, 1))).astype(np.uint8)
    rgba[mask4, 2] = 0

    alpha = np.clip((hm * 0.6).astype(np.int32), 0, 180).astype(np.uint8)
    alpha[hm < 10] = 0
    rgba[:, :, 3] = alpha

    overlay = Image.fromarray(rgba, "RGBA")
    if overlay.size != original.size:
        overlay = overlay.resize(original.size, Image.BILINEAR)

    composited = Image.alpha_composite(original, overlay)
    buf = io.BytesIO()
    composited.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(
        "throngs.debug.server:app",
        host="0.0.0.0",
        port=8766,
        reload=True,
    )


if __name__ == "__main__":
    main()
