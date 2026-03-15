from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from throngs.config import settings
from throngs.schemas import A11yElement, ActionType, PerceptionLevel, VisualSignal

logger = logging.getLogger(__name__)

# JavaScript that extracts physical + style data for every interactive element.
_DOM_PHYSICAL_JS = """
() => {
    const tagToRole = {
        BUTTON: 'button', A: 'link',
        INPUT: 'textbox', SELECT: 'combobox', TEXTAREA: 'textbox'
    };
    const inputTypeRoles = {
        checkbox: 'checkbox', radio: 'radio', submit: 'button',
        reset: 'button', image: 'button'
    };
    const results = [];
    const seen = new Set();
    const selectors = [
        'button', 'a', 'input', 'select', 'textarea',
        '[role="button"]', '[role="link"]', '[role="tab"]',
        '[role="menuitem"]', '[role="checkbox"]', '[role="radio"]',
        '[role="switch"]', '[role="combobox"]', '[role="slider"]',
        '[role="searchbox"]', '[role="spinbutton"]', '[role="option"]',
        '[role="menuitemcheckbox"]', '[role="menuitemradio"]'
    ];
    for (const el of document.querySelectorAll(selectors.join(','))) {
        if (seen.has(el)) continue;
        seen.add(el);
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const style = window.getComputedStyle(el);
        let role = el.getAttribute('role') || '';
        if (!role) {
            const tag = el.tagName;
            const type = (el.getAttribute('type') || '').toLowerCase();
            role = (tag === 'INPUT' && inputTypeRoles[type])
                || tagToRole[tag] || tag.toLowerCase();
        }
        let name = el.getAttribute('aria-label') || '';
        if (!name) {
            const lblId = el.getAttribute('aria-labelledby');
            if (lblId) {
                const lbl = document.getElementById(lblId);
                if (lbl) name = lbl.textContent.trim();
            }
        }
        if (!name) name = (el.textContent || '').trim().substring(0, 200);
        if (!name) name = el.getAttribute('title') || el.getAttribute('placeholder') || '';
        if (!name) continue;
        results.push({
            name, role,
            x: rect.x, y: rect.y, width: rect.width, height: rect.height,
            color: style.color,
            backgroundColor: style.backgroundColor,
            opacity: parseFloat(style.opacity) || 1.0,
            zIndex: parseInt(style.zIndex) || 0,
        });
    }
    return results;
}
"""


_VISUAL_SIGNALS_JS = """
() => {
    const signals = [];
    const seen = new Set();

    function addSignal(type, severity, message, el) {
        const text = (message || '').trim();
        if (!text || seen.has(text)) return;
        seen.add(text);
        let box = {};
        if (el) {
            const r = el.getBoundingClientRect();
            box = {x: r.x, y: r.y, width: r.width, height: r.height};
        }
        const tag = el ? (el.getAttribute('aria-label') || el.tagName.toLowerCase()) : '';
        signals.push({signal_type: type, severity, message: text.substring(0, 500), source_element: tag, bounding_box: box});
    }

    // 1. ARIA role-based alerts and status messages
    for (const el of document.querySelectorAll('[role="alert"], [role="alertdialog"], [role="status"]')) {
        const text = el.textContent;
        if (!text || !text.trim()) continue;
        const role = el.getAttribute('role');
        const sev = role === 'alert' || role === 'alertdialog' ? 'error' : 'info';
        addSignal('aria_' + role, sev, text, el);
    }

    // 2. aria-live regions with content
    for (const el of document.querySelectorAll('[aria-live="assertive"], [aria-live="polite"]')) {
        if (el.getAttribute('role')) continue; // already caught above
        const text = el.textContent;
        if (!text || !text.trim()) continue;
        const sev = el.getAttribute('aria-live') === 'assertive' ? 'warning' : 'info';
        addSignal('aria_live', sev, text, el);
    }

    // 3. Form validation: aria-invalid fields + their error messages
    for (const el of document.querySelectorAll('[aria-invalid="true"]')) {
        const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || '';
        let errMsg = '';
        const errId = el.getAttribute('aria-errormessage') || el.getAttribute('aria-describedby');
        if (errId) {
            for (const id of errId.split(/\\s+/)) {
                const errEl = document.getElementById(id);
                if (errEl && errEl.textContent.trim()) {
                    errMsg = errEl.textContent.trim();
                    break;
                }
            }
        }
        const msg = errMsg ? name + ': ' + errMsg : 'Field "' + name + '" has a validation error';
        addSignal('validation_error', 'error', msg, el);
    }

    // 4. Native HTML5 validation messages on visible inputs
    for (const el of document.querySelectorAll('input:invalid, select:invalid, textarea:invalid')) {
        if (el.validity && !el.validity.valid && el.validationMessage) {
            const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || '';
            addSignal('html5_validation', 'error', name + ': ' + el.validationMessage, el);
        }
    }

    // 5. Class-based error/warning/success/info messages
    const classPatterns = [
        {re: /\\b(error|danger|invalid|err-msg|form-error|field-error|has-error|is-invalid)\\b/i, sev: 'error', type: 'css_error'},
        {re: /\\b(warning|warn|caution)\\b/i, sev: 'warning', type: 'css_warning'},
        {re: /\\b(success|valid|is-valid|confirmed)\\b/i, sev: 'success', type: 'css_success'},
        {re: /\\b(info|notice|hint)\\b/i, sev: 'info', type: 'css_info'},
    ];
    const classSelectors = [
        '.error', '.danger', '.invalid', '.err-msg', '.form-error', '.field-error',
        '.has-error', '.is-invalid', '.alert-danger', '.alert-error',
        '.warning', '.warn', '.caution', '.alert-warning',
        '.success', '.valid', '.is-valid', '.alert-success',
        '.info', '.notice', '.hint', '.alert-info',
        '.toast', '.snackbar', '.notification',
        '[class*="error"]', '[class*="warning"]', '[class*="alert"]',
        '[class*="toast"]', '[class*="snackbar"]', '[class*="notification"]',
        '[class*="banner"]', '[class*="message"]'
    ];
    for (const el of document.querySelectorAll(classSelectors.join(','))) {
        const text = el.textContent;
        if (!text || !text.trim() || text.trim().length < 3 || text.trim().length > 500) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) < 0.1) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const cls = el.className || '';
        let matched = false;
        for (const p of classPatterns) {
            if (p.re.test(cls)) {
                addSignal(p.type, p.sev, text.trim(), el);
                matched = true;
                break;
            }
        }
        if (!matched) {
            const tag = el.tagName.toLowerCase();
            const isToast = /toast|snackbar|notification/i.test(cls);
            const isBanner = /banner|alert/i.test(cls);
            if (isToast || isBanner) {
                addSignal(isToast ? 'toast' : 'banner', 'info', text.trim(), el);
            }
        }
    }

    // 6. Color-based signal detection: red-bordered inputs (validation feedback)
    for (const el of document.querySelectorAll('input, select, textarea')) {
        const style = window.getComputedStyle(el);
        const bc = style.borderColor || '';
        const isRed = /rgb\\(\\s*(2[0-2]\\d|1[6-9]\\d)\\s*,\\s*([0-6]?\\d)\\s*,\\s*([0-6]?\\d)\\s*\\)/.test(bc)
                    || /^#(f|e|d|c)[0-5a-f]{1}[0-3a-f]{4}$/i.test(bc);
        if (isRed) {
            const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || 'unknown field';
            addSignal('red_border', 'error', 'Field "' + name + '" has a red border (likely validation error)', el);
        }
    }

    // 7. Dialog/modal detection
    for (const el of document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')) {
        const text = el.textContent;
        if (!text || !text.trim() || text.trim().length > 500) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none') continue;
        addSignal('dialog', 'info', text.trim().substring(0, 300), el);
    }

    return signals;
}
"""


@dataclass
class PageContext:
    """Snapshot of a page at a single point in time."""

    url: str
    screenshot_b64: str
    screenshot_path: str
    screenshot_bytes: bytes = b""
    a11y_elements: list[A11yElement] = field(default_factory=list)
    visible_text: str = ""
    title: str = ""
    visual_signals: list[VisualSignal] = field(default_factory=list)


class BrowserManager:
    """Manages Playwright browser lifecycle and page interactions."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._pages: dict[str, Page] = {}

    def register_page(self, key: str, page: Page) -> None:
        self._pages[key] = page

    def get_page(self, key: str) -> Optional[Page]:
        return self._pages.get(key)

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.browser_headless,
        )
        logger.info("Browser started (headless=%s)", settings.browser_headless)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser stopped")

    async def new_context(self) -> BrowserContext:
        assert self._browser is not None, "Browser not started"
        return await self._browser.new_context(
            viewport={
                "width": settings.viewport_width,
                "height": settings.viewport_height,
            },
        )

    async def capture_page(
        self, page: Page, step: int, session_dir: str
    ) -> PageContext:
        """Take a full snapshot: screenshot + a11y tree + visible text.

        When perception_level >= DOM, the a11y elements are enriched with
        bounding-box coordinates and computed CSS styles extracted via JS.
        """
        await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        # try:
        #     await page.wait_for_load_state("networkidle", timeout=8_000)
        # except Exception:
        #     pass
        await asyncio.sleep(settings.page_settle_seconds)

        screenshots_path = Path(session_dir) / f"step_{step:04d}.png"
        screenshots_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_bytes = await page.screenshot(full_page=False)
        screenshots_path.write_bytes(screenshot_bytes)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

        dom_data = await page.evaluate(_DOM_PHYSICAL_JS) or []
        elements = _build_elements_from_dom(dom_data)

        visible_text = await page.evaluate("() => document.body.innerText")

        signals: list[VisualSignal] = []
        if settings.visual_signals_enabled:
            try:
                raw_signals = await page.evaluate(_VISUAL_SIGNALS_JS) or []
                signals = _build_signals(raw_signals)
                if signals:
                    logger.info(
                        "Detected %d visual signal(s) at step %d: %s",
                        len(signals),
                        step,
                        "; ".join(f"[{s.severity.value}] {s.message[:80]}" for s in signals[:5]),
                    )
            except Exception as e:
                logger.debug("Visual signal extraction failed: %s", e)

        return PageContext(
            url=page.url,
            screenshot_b64=screenshot_b64,
            screenshot_path=str(screenshots_path),
            screenshot_bytes=screenshot_bytes,
            a11y_elements=elements,
            visible_text=visible_text or "",
            title=await page.title(),
            visual_signals=signals,
        )

    async def execute_action(
        self,
        page: Page,
        action_type: ActionType,
        element_id: str,
        a11y_elements: list[A11yElement],
        input_text: str = "",
        override_coords: tuple[float, float] | None = None,
    ) -> None:
        """Execute a Playwright action based on the LLM's decision.

        Parameters
        ----------
        page:
            Active Playwright :class:`Page` handle.
        action_type:
            The action to perform (click, type, scroll, hover, give_up).
        element_id:
            The ``element_id`` of the target ``A11yElement``.
        a11y_elements:
            All elements on the current page.
        input_text:
            Text to type (only used for ``ActionType.TYPE``).
        override_coords:
            Optional ``(x, y)`` tuple.  When provided, these coordinates are
            used directly for the click instead of the element's centre.
            This enables motor-error scatter simulation from
            :class:`~throngs.motor.engine.MotorErrorEngine`.
        """
        if action_type == ActionType.GIVE_UP:
            logger.info("Agent chose to give up")
            return

        target = next((e for e in a11y_elements if e.element_id == element_id), None)

        if action_type == ActionType.SCROLL:
            await page.mouse.wheel(0, 300)
            await asyncio.sleep(settings.post_action_wait_seconds)
            return

        if target is None:
            logger.warning("Element %s not found, attempting aria selector", element_id)
            try:
                locator = page.get_by_role(
                    "button", name=element_id
                ).or_(
                    page.get_by_role("link", name=element_id)
                ).or_(
                    page.get_by_label(element_id)
                ).first
                if action_type == ActionType.CLICK:
                    if override_coords is not None:
                        await page.mouse.click(override_coords[0], override_coords[1])
                    else:
                        await locator.click(timeout=5000)
                elif action_type == ActionType.TYPE:
                    await locator.fill(input_text, timeout=5000)
                elif action_type == ActionType.HOVER:
                    await locator.hover(timeout=5000)
            except Exception:
                logger.error("Could not locate element: %s", element_id)
            return

        # Determine click coordinates — use override if motor scatter was applied
        if override_coords is not None:
            cx, cy = override_coords
            logger.debug(
                "Motor scatter override: element=%s original_centre=(%.1f, %.1f) "
                "scattered=(%.1f, %.1f)",
                element_id,
                target.x + target.width / 2,
                target.y + target.height / 2,
                cx,
                cy,
            )
        else:
            cx = target.x + target.width / 2
            cy = target.y + target.height / 2

        if action_type == ActionType.CLICK:
            await page.mouse.click(cx, cy)
        elif action_type == ActionType.TYPE:
            await page.mouse.click(cx, cy)
            await page.keyboard.type(input_text, delay=50)
        elif action_type == ActionType.HOVER:
            await page.mouse.move(cx, cy)

        await asyncio.sleep(settings.post_action_wait_seconds)


# ------------------------------------------------------------------
# Build A11yElements directly from DOM extraction
# ------------------------------------------------------------------

def _build_elements_from_dom(dom_data: list[dict]) -> list[A11yElement]:
    """Convert raw DOM physical data into A11yElement objects."""
    elements: list[A11yElement] = []
    for i, dom in enumerate(dom_data, start=1):
        elements.append(
            A11yElement(
                element_id=f"e{i}",
                role=dom.get("role", ""),
                name=dom.get("name", ""),
                x=dom.get("x", 0),
                y=dom.get("y", 0),
                width=dom.get("width", 0),
                height=dom.get("height", 0),
                text_color=dom.get("color", ""),
                bg_color=dom.get("backgroundColor", ""),
                opacity=dom.get("opacity", 1.0),
            )
        )
    return elements


def _build_signals(raw_signals: list[dict]) -> list[VisualSignal]:
    """Convert raw JS signal data into VisualSignal objects."""
    from throngs.schemas import SignalSeverity

    severity_map = {
        "error": SignalSeverity.ERROR,
        "warning": SignalSeverity.WARNING,
        "info": SignalSeverity.INFO,
        "success": SignalSeverity.SUCCESS,
    }
    signals: list[VisualSignal] = []
    for raw in raw_signals:
        sev = severity_map.get(raw.get("severity", "info"), SignalSeverity.INFO)
        signals.append(
            VisualSignal(
                signal_type=raw.get("signal_type", ""),
                severity=sev,
                message=raw.get("message", ""),
                source_element=raw.get("source_element", ""),
                bounding_box=raw.get("bounding_box", {}),
            )
        )
    return signals
