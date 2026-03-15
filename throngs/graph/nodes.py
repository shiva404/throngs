from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from throngs.config import settings
from throngs.distraction.engine import DistractionEngine
from throngs.graph.state import AgentState
from throngs.hesitation.engine import HesitationEngine
from throngs.motor.engine import MotorErrorEngine
from throngs.perception.a11y import extract_a11y_tree, get_visible_text
from throngs.schemas import ActionLog, ActionType, LLMResponse, LoginCredentials

logger = logging.getLogger(__name__)


def _parse_json_robust(raw: str) -> dict:
    """Parse JSON with repair for common LLM truncation issues.

    When max_tokens cuts the response mid-string, the JSON is syntactically
    broken.  This tries increasingly aggressive repairs before giving up.
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strip trailing comma then close any open strings / objects / arrays
    repaired = raw.rstrip().rstrip(",")
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    open_quotes = repaired.count('"') % 2 == 1

    if open_quotes:
        repaired += '"'
    repaired += "]" * open_brackets
    repaired += "}" * open_braces

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Last resort: find the last complete key-value pair boundary
    last_good = repaired.rfind('",')
    if last_good == -1:
        last_good = repaired.rfind('",\n')
    if last_good > 0:
        truncated = repaired[: last_good + 1]
        truncated += "}" * (truncated.count("{") - truncated.count("}"))
        try:
            return json.loads(truncated)
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("Could not repair truncated JSON", raw, 0)


LLM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "internal_monologue": {
            "type": "string",
            "description": (
                "Your in-character stream of consciousness. Reference what you "
                "did on previous steps, what worked/failed, and WHY you are "
                "choosing this specific next action. Do NOT repeat generic "
                "statements like 'I need to create a customer' — instead say "
                "things like 'I already typed the first name on step 6, now I "
                "need to fill in the last name field.'"
            ),
        },
        "perceived_clutter_rating": {"type": "integer", "minimum": 1, "maximum": 10},
        "emotional_state": {
            "type": "string",
            "description": (
                "Your current emotional state, which should EVOLVE based on "
                "what happened. If your previous actions failed, show growing "
                "frustration. If you just made progress, show relief."
            ),
        },
        "action_type": {"type": "string", "enum": ["click", "type", "scroll", "give_up"]},
        "target_element_id": {"type": "string"},
        "input_text": {"type": "string"},
        "task_completed": {"type": "boolean"},
        "session_notes": {
            "type": "string",
            "description": (
                "Running log of what you have accomplished and learned so far "
                "in this session. Update this each step — carry forward what "
                "you already noted, add what you just did, and note what you "
                "still need to do. Example: 'Navigated to Customers page. "
                "Opened new customer form. Typed first name Alice. Still need: "
                "last name, display name, then Save.'"
            ),
        },
    },
    "required": [
        "internal_monologue",
        "perceived_clutter_rating",
        "emotional_state",
        "action_type",
        "target_element_id",
        "task_completed",
        "session_notes",
    ],
}

ACTION_HISTORY_WINDOW = 8

SYSTEM_PROMPT_TEMPLATE = """\
You are a simulated user testing a web application. Your task is to navigate \
the UI and accomplish a specific goal.

{persona_fragment}

{memory_fragment}

GOAL: {goal}

RULES:
- You can ONLY interact with elements listed in the Accessibility Tree below.
- Choose an element by its element_id (e.g., "e1", "e2").
- Think step-by-step in your internal_monologue, staying in character.
- Your perceived_clutter_rating should reflect how overwhelming the current page feels (1=clean, 10=chaotic).
- Your emotional_state should EVOLVE naturally — if things are going well show confidence, \
if you keep failing show frustration, confusion, or anxiety appropriate to your persona.
- CRITICAL: You have an ACTION HISTORY below showing what you already did. READ IT \
CAREFULLY before deciding your next action. Do NOT repeat actions that already \
succeeded (e.g., don't re-type a field you already filled). Do NOT ignore what \
you just did. If you typed "Alice" into the first name field last step, the first \
name is already filled — move on to the next field.
- If a previous action didn't seem to work (e.g., you clicked something but the page \
didn't change), try a DIFFERENT approach. Don't blindly repeat the same action.
- PAY CLOSE ATTENTION to PAGE SIGNALS below — these are alerts, error messages, \
validation errors, and warnings currently visible on screen. If you see an error \
like "required field missing" or a validation warning, you MUST address it \
(e.g., fill the required field) before proceeding. React to these signals the way \
a real human would — read the message and adjust your action accordingly.
- Also look at the SCREENSHOT for any visual feedback the structured data might miss — \
red borders on fields, banner messages, toast notifications, highlighted errors.
- Your session_notes field is your working memory. Use it to track what you've \
accomplished, what fields are filled, what you still need to do.
- BE PERSISTENT: Try different approaches before giving up. Scroll around, look for \
menus, try navigation links, use the back button. Real users explore and try \
multiple paths before quitting. You should too.
- ONLY use action_type "give_up" as an absolute last resort after you have genuinely \
tried several different approaches and none of them work. A few confusing screens \
are NOT a reason to give up — keep trying.
- Set "task_completed" to true when you believe you have successfully achieved the GOAL. \
For example, if the goal is to find a specific page and you are now on it, set it to true.
- IMPORTANT: These are TEST ACCOUNTS. If the page asks you to add a phone number, \
set up a passkey, enable two-factor authentication, add recovery info, or complete \
any profile/security setup, ALWAYS click "Skip", "Not now", "Remind me later", \
"Cancel", or any similar dismiss/skip button. Do NOT fill in phone numbers, \
passkeys, or other personal profile information.

Respond with ONLY valid JSON matching this schema:
{schema}
"""


def make_initialize_node(memory_store, persona_engine):
    """Create the initialization node that loads persona context and memory."""

    async def initialize(state: AgentState) -> dict:
        run_id = state.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = str(
            Path(settings.screenshots_dir) / run_id / state.persona.name
        )
        Path(session_dir).mkdir(parents=True, exist_ok=True)

        memory_prompt = memory_store.build_memory_prompt(
            state.persona.id, state.goal, state.persona.usage_frequency
        )
        recalled = memory_store.recall(
            state.persona.id, state.goal, state.persona.usage_frequency
        )
        memories = [mem for mem, _strength, _state in recalled]

        logger.info(
            "Initialized agent: persona=%s goal='%s' url=%s",
            state.persona.name,
            state.goal,
            state.start_url,
        )

        return {
            "session_dir": session_dir,
            "memory_prompt": memory_prompt,
            "past_memories": memories,
            "current_url": state.start_url,
            "step": 0,
            "cumulative_frustration": 0.0,
            "outcome": "",
            "action_log": [],
        }

    return initialize


def make_perceive_node(browser_manager):
    """Create the perception node that captures page state.

    After raw capture, the Retina layer (VisualPerceptionEngine) runs
    the enabled perception phases — DOM enrichment, saliency mapping,
    visibility scoring, and cognitive-overload detection.
    """

    async def perceive(state: AgentState) -> dict:
        page = _get_page(browser_manager, state)
        if page is None:
            return {"error": "No browser page available"}

        if state.current_url and page.url != state.current_url and state.step == 0:
            await page.goto(state.current_url, wait_until="domcontentloaded", timeout=60_000)

        ctx = await browser_manager.capture_page(
            page, state.step, state.session_dir
        )

        from throngs.perception.visibility import VisualPerceptionEngine

        # Determine RTL and mobile flags from persona device preference
        is_mobile = getattr(state.persona, "usage_device", "desktop") == "mobile"
        # RTL detection: could be extended via persona locale field; default False
        is_rtl = False

        engine = VisualPerceptionEngine()
        elements, overload = engine.process(
            elements=ctx.a11y_elements,
            screenshot_bytes=ctx.screenshot_bytes,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
            goal=state.goal,
            rtl=is_rtl,
        )

        return {
            "screenshot_b64": ctx.screenshot_b64,
            "screenshot_path": ctx.screenshot_path,
            "a11y_elements": elements,
            "visible_text": ctx.visible_text,
            "current_url": ctx.url,
            "page_title": ctx.title,
            "visual_overload": overload,
            "visual_signals": ctx.visual_signals,
        }

    return perceive


LOGIN_INDICATORS = {
    "url_patterns": [
        "/login", "/signin", "/sign-in", "/auth", "/sso",
        "accounts.intuit.com", "oauth", "/authorize",
    ],
    "a11y_roles_names": [
        ("textbox", "email"), ("textbox", "username"), ("textbox", "user id"),
        ("textbox", "e-mail"), ("textbox", "user name"),
    ],
    "password_roles": [
        ("textbox", "password"), ("textbox", "passwd"),
    ],
    "submit_names": [
        "sign in", "log in", "login", "signin", "submit", "continue", "next",
    ],
}


def _detect_login_page(url: str, a11y_elements: list, visible_text: str) -> bool:
    """Heuristic check: does the current page look like a login / sign-in form?"""
    url_lower = url.lower()
    for pat in LOGIN_INDICATORS["url_patterns"]:
        if pat in url_lower:
            return True

    roles_names = {(e.role.lower(), e.name.lower()) for e in a11y_elements}
    element_names = {e.name.lower() for e in a11y_elements}

    has_email_field = any(
        (role, name) in roles_names or name in element_names
        for role, name in LOGIN_INDICATORS["a11y_roles_names"]
    )
    has_password_field = any(
        (role, name) in roles_names or name in element_names
        for role, name in LOGIN_INDICATORS["password_roles"]
    )

    if has_email_field and has_password_field:
        return True

    text_lower = visible_text.lower()
    login_phrases = ["sign in to", "log in to", "enter your email", "enter your password"]
    if any(phrase in text_lower for phrase in login_phrases):
        return True

    return False


def make_handle_login_node(browser_manager, persona_engine):
    """Create the login-handling node.

    After perception, this node checks whether the page is a login form.
    If credentials are available for the persona it fills them in automatically,
    keeping the login process outside the agent's step/frustration budget.
    """

    async def handle_login(state: AgentState) -> dict:
        if state.login_completed:
            return {"login_redirect": False}

        if not state.credentials:
            creds = persona_engine.get_credentials(state.persona.name)
            if creds is None:
                return {}
        else:
            creds = state.credentials

        is_login = _detect_login_page(
            state.current_url, state.a11y_elements, state.visible_text
        )

        if not is_login:
            return {}

        page = _get_page(browser_manager, state)
        if page is None:
            return {"error": "No browser page available for login"}

        logger.info(
            "Login page detected for %s at %s — filling credentials",
            state.persona.name,
            state.current_url,
        )

        # Try multiple common strategies to fill the login form
        login_success = False

        # Strategy 1: Use semantic locators (aria-label, role, placeholder)
        email_selectors = [
            'input[type="email"]',
            'input[name="Email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[name="userid"]',
            'input[aria-label*="mail" i]',
            'input[aria-label*="user" i]',
            'input[placeholder*="mail" i]',
            'input[placeholder*="user" i]',
            '#Email', '#email', '#username', '#userId',
        ]

        password_selectors = [
            'input[type="password"]',
            'input[name="Password"]',
            'input[name="password"]',
            'input[aria-label*="assword" i]',
            '#Password', '#password',
        ]

        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Sign In")',
            'button:has-text("Log In")',
            'button:has-text("Login")',
            'button:has-text("Continue")',
            'button:has-text("Next")',
            'button:has-text("Submit")',
        ]

        # Fill email / username
        for selector in email_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=1000):
                    await locator.fill(creds.email)
                    logger.debug("Filled email via selector: %s", selector)
                    break
            except Exception:
                continue

        # Some login flows split email and password across pages (e.g. Intuit SSO).
        # Check if there's a "Next" / "Continue" button before the password field.
        for selector in submit_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=500):
                    pwd_visible = False
                    for ps in password_selectors:
                        try:
                            pwd_visible = await page.locator(ps).first.is_visible(timeout=500)
                            if pwd_visible:
                                break
                        except Exception:
                            continue

                    if not pwd_visible:
                        await locator.click()
                        logger.debug("Clicked next/continue to advance to password page")
                        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                        await asyncio.sleep(2.0)
                        break
            except Exception:
                continue

        await asyncio.sleep(0.5)

        # Fill password
        for selector in password_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=2000):
                    await locator.fill(creds.password)
                    logger.debug("Filled password via selector: %s", selector)
                    break
            except Exception:
                continue

        # Submit
        for selector in submit_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=1000):
                    await locator.click()
                    logger.debug("Clicked submit via selector: %s", selector)
                    login_success = True
                    break
            except Exception:
                continue

        if login_success:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            await asyncio.sleep(3.0)
            logger.info("Login submitted for %s — now at %s", state.persona.name, page.url)

            return {
                "login_completed": True,
                "login_redirect": True,
                "credentials": creds,
                "current_url": page.url,
            }

        logger.warning(
            "Login page detected but automated login could not complete for %s",
            state.persona.name,
        )
        return {"credentials": creds}

    return handle_login


PROFILE_SETUP_INDICATORS = {
    "url_patterns": [
        "/profile", "/account/setup", "/account/security",
        "/passkey", "/passkeys", "/mfa", "/2fa", "/two-factor",
        "/phone", "/verify-phone", "/recovery", "/security-check",
        "/onboarding", "/welcome/setup",
    ],
    "skip_keywords_in_text": [
        "add phone number", "enter phone number", "verify your phone",
        "set up passkey", "create a passkey", "create passkey",
        "add a passkey", "use passkey", "passkeys",
        "two-factor authentication", "two-step verification",
        "enable 2fa", "set up 2fa",
        "recovery phone", "recovery email", "backup phone",
        "secure your account", "protect your account",
        "additional security", "extra security",
        "verify your identity", "confirm your identity",
        "add recovery", "add a recovery",
        "save your progress", "complete your profile",
        "keep your account secure",
    ],
    "skip_button_labels": [
        "skip", "skip for now", "not now", "no thanks", "no, thanks",
        "remind me later", "do this later", "maybe later",
        "i'll do this later", "set up later", "skip this step",
        "skip setup", "skip this", "dismiss", "close", "cancel",
        "not interested", "don't add", "don't enable",
    ],
}


def _detect_profile_setup_page(url: str, a11y_elements: list, visible_text: str) -> bool:
    """Heuristic check: does the page look like a profile / security setup prompt?"""
    url_lower = url.lower()
    for pat in PROFILE_SETUP_INDICATORS["url_patterns"]:
        if pat in url_lower:
            text_lower = visible_text.lower()
            if any(kw in text_lower for kw in PROFILE_SETUP_INDICATORS["skip_keywords_in_text"]):
                return True

    text_lower = visible_text.lower()
    if any(kw in text_lower for kw in PROFILE_SETUP_INDICATORS["skip_keywords_in_text"]):
        element_names = {e.name.lower().strip() for e in a11y_elements}
        if any(
            label in element_names or any(label in n for n in element_names)
            for label in PROFILE_SETUP_INDICATORS["skip_button_labels"]
        ):
            return True

    return False


def make_handle_profile_setup_node(browser_manager):
    """Create the profile-setup skip node.

    After login, many services prompt users to add phone numbers, passkeys,
    or other profile info. For test accounts these should be skipped.
    This node detects such pages and clicks the skip/dismiss button.
    """

    async def handle_profile_setup(state: AgentState) -> dict:
        if not _detect_profile_setup_page(
            state.current_url, state.a11y_elements, state.visible_text
        ):
            return {"profile_setup_redirect": False}

        page = _get_page(browser_manager, state)
        if page is None:
            return {"profile_setup_redirect": False}

        logger.info(
            "Profile setup page detected for %s at %s — attempting to skip",
            state.persona.name,
            state.current_url,
        )

        skip_selectors = [
            'button:has-text("Skip")',
            'button:has-text("Not now")',
            'button:has-text("No thanks")',
            'button:has-text("Remind me later")',
            'button:has-text("Do this later")',
            'button:has-text("Maybe later")',
            'button:has-text("Skip for now")',
            'button:has-text("Skip this step")',
            'button:has-text("Skip setup")',
            'a:has-text("Skip")',
            'a:has-text("Not now")',
            'a:has-text("No thanks")',
            'a:has-text("Do this later")',
            'a:has-text("Remind me later")',
            'a:has-text("Skip for now")',
            '[aria-label*="skip" i]',
            '[aria-label*="dismiss" i]',
            '[aria-label*="close" i]',
            'button:has-text("Cancel")',
            'button:has-text("Dismiss")',
            'button:has-text("Close")',
            'a:has-text("Cancel")',
        ]

        skipped = False
        for selector in skip_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=1000):
                    await locator.click()
                    logger.info("Clicked skip/dismiss via selector: %s", selector)
                    skipped = True
                    break
            except Exception:
                continue

        if not skipped:
            for el in state.a11y_elements:
                name_lower = el.name.lower().strip()
                if any(
                    label in name_lower
                    for label in PROFILE_SETUP_INDICATORS["skip_button_labels"]
                ):
                    try:
                        locator = page.locator(f'[data-element-id="{el.element_id}"]')
                        if await locator.count() == 0:
                            locator = page.get_by_role(
                                el.role.lower(), name=el.name
                            ).first
                        if await locator.is_visible(timeout=1000):
                            await locator.click()
                            logger.info(
                                "Clicked skip via a11y element: role=%s name='%s'",
                                el.role,
                                el.name,
                            )
                            skipped = True
                            break
                    except Exception:
                        continue

        if skipped:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            logger.info(
                "Profile setup skipped for %s — now at %s",
                state.persona.name,
                page.url,
            )
            return {
                "profile_setup_skipped": True,
                "profile_setup_redirect": True,
                "current_url": page.url,
            }

        logger.warning(
            "Profile setup page detected but could not find skip button for %s",
            state.persona.name,
        )
        return {"profile_setup_redirect": False}

    return handle_profile_setup


def make_calculate_load_node(frustration_engine):
    """Create the cognitive load calculation node."""

    async def calculate_load(state: AgentState) -> dict:
        last_action = ""
        last_element = ""
        if state.action_log:
            prev = state.action_log[-1]
            last_action = prev.action_type.value
            last_element = prev.target_element_id

        metrics = frustration_engine.calculate(
            persona=state.persona,
            a11y_elements=state.a11y_elements,
            visible_text=state.visible_text,
            current_url=state.current_url,
            base_frustration=state.cumulative_frustration,
            visual_overload=state.visual_overload,
            last_action_type=last_action,
            last_element_id=last_element,
        )
        return {
            "frustration_metrics": metrics,
            "cumulative_frustration": metrics.total_frustration,
        }

    return calculate_load


def _build_action_history(action_log: list[ActionLog], window: int = ACTION_HISTORY_WINDOW) -> str:
    """Format recent action history so the LLM sees what it already did."""
    if not action_log:
        return ""

    recent = action_log[-window:]
    lines = ["=== YOUR ACTION HISTORY (what you already did) ==="]
    for log in recent:
        target_desc = ""
        if log.target_element_id:
            name = f" '{log.target_element_name}'" if hasattr(log, "target_element_name") and log.target_element_name else ""
            role = f" ({log.target_element_role})" if hasattr(log, "target_element_role") and log.target_element_role else ""
            target_desc = f" → {log.target_element_id}{name}{role}"

        input_desc = f' with text "{log.input_text}"' if log.input_text else ""
        lines.append(
            f"  Step {log.step}: {log.action_type.value}{target_desc}{input_desc} "
            f"| on {log.url} "
            f"| emotion: {log.emotional_state} "
            f"| thought: {log.internal_monologue[:150]}"
        )
    lines.append("=== END ACTION HISTORY ===")
    return "\n".join(lines)


def _build_frustration_hint(state: AgentState) -> str:
    """Build a situational hint about frustration / looping for the LLM."""
    hints: list[str] = []
    fm = state.frustration_metrics
    budget = state.persona.patience_budget

    pct = (state.cumulative_frustration / budget * 100) if budget else 0
    if pct > 70:
        hints.append(
            f"⚠ Your frustration is at {state.cumulative_frustration:.0f}/{budget} "
            f"({pct:.0f}%) — you are close to giving up. Consider a different strategy."
        )
    elif pct > 40:
        hints.append(
            f"Your frustration is building ({state.cumulative_frustration:.0f}/{budget}). "
            "Stay focused but think about what approaches have NOT worked."
        )

    if fm and fm.loop_penalty > 0:
        hints.append(
            "⚠ LOOP DETECTED: You are repeating the same action on the same element. "
            "This is NOT productive. Try a DIFFERENT element or approach."
        )

    return "\n".join(hints)


def _build_signals_block(state: AgentState) -> str:
    """Format detected visual signals (alerts, errors, toasts) for the LLM."""
    if not state.visual_signals:
        return ""

    severity_icon = {"error": "🔴", "warning": "🟡", "info": "🔵", "success": "🟢"}
    lines = ["=== PAGE SIGNALS (alerts, errors, warnings visible on screen) ==="]
    for sig in state.visual_signals:
        icon = severity_icon.get(sig.severity.value, "•")
        lines.append(f"  {icon} [{sig.severity.value.upper()}] {sig.message}")
    lines.append("=== END PAGE SIGNALS ===")
    return "\n".join(lines)


def make_reason_node(llm, persona_engine):
    """Create the LLM reasoning node."""

    async def reason(state: AgentState) -> dict:
        persona_fragment = persona_engine.build_system_prompt_fragment(state.persona)
        a11y_text = extract_a11y_tree(
            state.a11y_elements,
            patience_budget=state.persona.patience_budget - int(state.cumulative_frustration),
            skimming_enabled=settings.skimming_enabled,
        )
        vis_text = get_visible_text(state.visible_text, max_chars=2000)

        goal_display = state.goal
        if state.goal_chain:
            n, total = state.current_goal_index + 1, len(state.goal_chain)
            goal_display = f"{state.goal} [Step {n} of {total} in workflow]"
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            persona_fragment=persona_fragment,
            memory_fragment=state.memory_prompt,
            goal=goal_display,
            schema=json.dumps(LLM_OUTPUT_SCHEMA, indent=2),
        )

        action_history = _build_action_history(state.action_log)
        frustration_hint = _build_frustration_hint(state)
        signals_block = _build_signals_block(state)

        distraction = ""
        if state.visual_overload.distraction_note:
            distraction = f"\n⚠ DISTRACTION: {state.visual_overload.distraction_note}\n"

        session_notes_block = ""
        if state.session_notes:
            session_notes_block = (
                f"\n=== YOUR SESSION NOTES (your working memory) ===\n"
                f"{state.session_notes}\n"
                f"=== END SESSION NOTES ===\n"
            )

        # Distraction / coffee-break: inject re-orientation prompt and clear flag
        distraction_context = ""
        distraction_state_updates: dict = {}
        if state.distraction_memory_wipe_pending and state.distraction_context_prompt:
            distraction_context = (
                f"\n{'='*60}\n"
                f"{state.distraction_context_prompt}\n"
                f"{'='*60}\n"
            )
            distraction_state_updates = {
                "distraction_memory_wipe_pending": False,
                "distraction_context_prompt": "",
            }
            logger.info(
                "[%s] Distraction re-orientation prompt injected at step %d",
                state.persona.name,
                state.step,
            )

        user_text = (
            f"Current URL: {state.current_url}\n"
            f"Page Title: {state.page_title}\n"
            f"Current Frustration: {state.cumulative_frustration:.1f} / {state.persona.patience_budget}\n"
            f"Step: {state.step}\n"
        )

        if distraction_context:
            user_text += distraction_context
        if signals_block:
            user_text += f"\n{signals_block}\n"
        if frustration_hint:
            user_text += f"\n{frustration_hint}\n"
        if distraction:
            user_text += distraction
        if session_notes_block:
            user_text += session_notes_block
        if action_history:
            user_text += f"\n{action_history}\n"

        user_text += (
            f"\n{a11y_text}\n\n"
            f"Visible Text (excerpt):\n{vis_text}"
        )

        user_content = [{"type": "text", "text": user_text}]

        if state.screenshot_b64:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{state.screenshot_b64}",
                    },
                }
            )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        for attempt in range(settings.rate_limit_max_retries):
            try:
                response = await llm.ainvoke(messages)
                break
            except Exception as e:
                wait = settings.rate_limit_backoff_base ** attempt
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1,
                    settings.rate_limit_max_retries,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)
        else:
            return {"error": "LLM call failed after all retries"}

        try:
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = _parse_json_robust(raw)
            llm_response = LLMResponse.model_validate(parsed)
        except Exception as e:
            logger.error("Failed to parse LLM response: %s\nRaw: %s", e, response.content)
            llm_response = LLMResponse(
                internal_monologue="I'm confused by the interface.",
                perceived_clutter_rating=7,
                emotional_state="Confused",
                action_type=ActionType.SCROLL,
                target_element_id="",
                session_notes=state.session_notes,
            )

        target_name = ""
        if llm_response.target_element_id:
            t = next(
                (e for e in state.a11y_elements if e.element_id == llm_response.target_element_id),
                None,
            )
            target_name = f" '{t.name[:60]}'" if t else ""

        logger.info(
            "[%s] Step %d | Thinking: %s",
            state.persona.name,
            state.step,
            llm_response.internal_monologue,
        )
        logger.info(
            "[%s] Step %d | Action: %s %s%s | Emotion: %s | Clutter: %d/10%s",
            state.persona.name,
            state.step,
            llm_response.action_type.value,
            llm_response.target_element_id,
            target_name,
            llm_response.emotional_state,
            llm_response.perceived_clutter_rating,
            " | TASK COMPLETED" if llm_response.task_completed else "",
        )

        result: dict = {
            "llm_response": llm_response,
            "session_notes": llm_response.session_notes or state.session_notes,
        }
        result.update(distraction_state_updates)
        return result

    return reason


def make_execute_action_node(browser_manager, hesitation_llm=None, distraction_llm=None, street_simulation=None, event_bus=None):
    """Create the action execution node.

    Wires in:
    - HesitationEngine  — intercepts high-stakes clicks when risk_aversion_enabled
    - MotorErrorEngine  — scatter clicks and inject typos when motor_errors_enabled
    - DistractionEngine — LLM-driven persona/environment-aware interruptions
    - EventBus          — priority queue; CUSTOMER_ARRIVAL at CRITICAL preempts action
    """
    _motor_engine = MotorErrorEngine()
    _hesitation_engine = HesitationEngine(llm=hesitation_llm)
    _distraction_engine = DistractionEngine(llm=distraction_llm)

    # Lazy import to avoid circular dependency at module level
    from throngs.events.bus import EventBus, EventPriority
    _event_bus = event_bus or EventBus()

    async def execute_action(state: AgentState) -> dict:
        if state.llm_response is None:
            return {"error": "No LLM response to execute"}

        llm_resp = state.llm_response
        page = _get_page(browser_manager, state)

        persona = state.persona
        device = getattr(persona, "usage_device", "desktop")

        # Accumulated event records for this step
        motor_event = None
        hesitation_event = None
        distraction_event = None
        new_motor_log = list(state.motor_error_log)
        new_hesitation_log = list(state.hesitation_log)
        new_distraction_log = list(state.distraction_log)

        # Coordinates override from motor scatter (None = use element centre)
        scatter_coords: tuple[float, float] | None = None

        target_el = next(
            (e for e in state.a11y_elements if e.element_id == llm_resp.target_element_id),
            None,
        )

        # ----------------------------------------------------------
        # 0. Street simulation tick — check for CUSTOMER_ARRIVAL
        #    BEFORE the browser action so it can preempt.
        # ----------------------------------------------------------
        _event_bus.clear()  # fresh per step
        distraction_memory_wipe_pending = state.distraction_memory_wipe_pending
        distraction_context_prompt = state.distraction_context_prompt

        if street_simulation is not None:
            try:
                from throngs.time.clock import get_clock
                sim_now = get_clock().now()
            except RuntimeError:
                from datetime import datetime as _dt
                sim_now = _dt.utcnow()

            street_simulation.tick(sim_now)

            # Check for retail walk-in customers (CUSTOMER_ARRIVAL)
            pending_customer_events = street_simulation.pop_pending_customer_events(persona.name)
            for customer_evt in pending_customer_events:
                _event_bus.emit("CUSTOMER_ARRIVAL", customer_evt, EventPriority.CRITICAL)

            # Check for service business phone calls (PHONE_CALL) and email inquiries (EMAIL_INQUIRY)
            pending_phone_calls = street_simulation.pop_pending_phone_calls(persona.name)
            for phone_evt in pending_phone_calls:
                _event_bus.emit("PHONE_CALL", phone_evt, EventPriority.CRITICAL)
            pending_emails = street_simulation.pop_pending_emails(persona.name)
            for email_evt in pending_emails:
                _event_bus.emit("EMAIL_INQUIRY", email_evt, EventPriority.CRITICAL)

        if _event_bus.has_critical():
            # ----- PREEMPTION: customer at counter OR phone ringing OR email inquiry -----
            critical_evt = _event_bus._heap[0].event  # peek first critical
            event_type = _event_bus._heap[0].event_type
            is_phone_call = event_type == "PHONE_CALL"
            is_email_inquiry = event_type == "EMAIL_INQUIRY"

            if is_phone_call or is_email_inquiry:
                # Service business: phone or email interrupts — then interact with QB (estimate, invoice)
                svc_request = critical_evt.service_request
                handling_mins = svc_request.handling_minutes() if svc_request else 5.0
                variant = "PHONE_CALL" if is_phone_call else "EMAIL_INQUIRY"
                narrative = critical_evt.narrative
                client_name = svc_request.client_name if svc_request else "the client"

                distraction_result = _distraction_engine._generate_fallback(
                    persona, state.goal, variant=variant,
                )
                distraction_result["narrative"] = narrative
                if is_phone_call:
                    distraction_result["reorientation_prompt"] = (
                        f"📞 PHONE CALL: {narrative} "
                        f"You spent about {handling_mins:.0f} minutes on the call discussing "
                        f"the job details. "
                        f"You now need to create an estimate for this client in QuickBooks and send it. "
                        f"Get back to your computer and continue working."
                    )
                else:
                    distraction_result["reorientation_prompt"] = (
                        f"📧 EMAIL INQUIRY: {narrative} "
                        f"You read the email and noted the request. "
                        f"You now need to create an estimate in QuickBooks for {client_name} and send it. "
                        f"Get back to your computer and continue working."
                    )
                distraction_result["estimated_away_minutes"] = handling_mins
                billing_mins = handling_mins
            else:
                # Retail: customer at counter
                customer = critical_evt.customer
                billing_mins = customer.billing_minutes() if customer else 8.0
                variant = "CUSTOMER_ARRIVAL"

                distraction_result = _distraction_engine._generate_fallback(
                    persona, state.goal, variant="CUSTOMER_ARRIVAL",
                )
                distraction_result["narrative"] = critical_evt.narrative
                distraction_result["reorientation_prompt"] = (
                    f"🛒 CUSTOMER AT THE COUNTER: {critical_evt.narrative} "
                    f"You stepped away from the computer to serve them — "
                    f"it took about {billing_mins:.0f} minutes to ring them up "
                    f"and process their payment. "
                    f"You're back at the screen — re-orient and continue your task."
                )
                distraction_result["estimated_away_minutes"] = billing_mins

            wipe_count = distraction_result["memory_wipe_lines"]
            notes_lines = (llm_resp.session_notes or "").split("\n")
            wipe_count = min(wipe_count, len(notes_lines))
            wiped_notes = (
                "\n".join(notes_lines[:-wipe_count])
                if wipe_count and wipe_count < len(notes_lines)
                else (llm_resp.session_notes or "")
            )

            # Log the INTERRUPTED action — the intended action was never executed
            total_area = sum(e.width * e.height for e in state.a11y_elements)
            viewport_area = settings.viewport_width * settings.viewport_height
            coverage_pct = round(min(total_area / viewport_area, 1.0) * 100, 1) if viewport_area else 0.0

            distraction_event = _distraction_engine.create_distraction_event(
                variant=variant,
                pre_url=state.current_url,
                memory_wiped=wipe_count,
                narrative=distraction_result["narrative"],
                feedback=f"{variant} preempted action at step {state.step}: {critical_evt.narrative}",
                sim_time_away_minutes=float(billing_mins),
            )

            interrupt_msg = (
                f"\n\n⚠️ [INTERRUPTED — phone rang, had to take a call]"
                if is_phone_call
                else (
                    f"\n\n⚠️ [INTERRUPTED — new email inquiry, had to read it]"
                    if is_email_inquiry
                    else f"\n\n⚠️ [INTERRUPTED — a customer arrived at the counter before I could act]"
                )
            )

            log_entry = ActionLog(
                step=state.step,
                url=state.current_url,
                page_title=state.page_title,
                action_type=ActionType.INTERRUPTED,
                target_element_id=llm_resp.target_element_id,
                target_element_name=target_el.name[:120] if target_el else "",
                target_element_role=target_el.role if target_el else "",
                input_text=llm_resp.input_text,
                x=target_el.x + target_el.width / 2 if target_el else 0,
                y=target_el.y + target_el.height / 2 if target_el else 0,
                frustration_score=state.cumulative_frustration,
                emotional_state=llm_resp.emotional_state,
                internal_monologue=llm_resp.internal_monologue + interrupt_msg,
                perceived_clutter_rating=llm_resp.perceived_clutter_rating,
                task_completed=False,
                screenshot_path=state.screenshot_path,
                frustration_breakdown=state.frustration_metrics,
                frustration_reasoning=state.frustration_metrics.reasoning if state.frustration_metrics else [],
                visual_overload=state.visual_overload,
                interactable_element_count=len(state.a11y_elements),
                viewport_coverage_pct=coverage_pct,
                session_notes=wiped_notes,
                visual_signals=state.visual_signals,
                distraction=distraction_event,
            )

            new_log = list(state.action_log) + [log_entry]
            new_distraction_log.append(distraction_event)

            logger.info(
                "[%s] Step %d %s PREEMPTED action '%s' on '%s' — %s (%.0f sim-min)",
                persona.name, state.step, variant, llm_resp.action_type.value,
                llm_resp.target_element_id, critical_evt.narrative[:100], billing_mins,
            )

            # Dynamic goal: after accepting phone/email, next action is QB (estimate or invoice)
            next_goal = state.goal
            if (is_phone_call or is_email_inquiry) and critical_evt.service_request:
                req = critical_evt.service_request
                if req.state == "inquiry":
                    next_goal = (
                        f"Create an estimate in QuickBooks for {req.client_name} and send it to them."
                    )
                elif req.state in ("accepted", "in_progress"):
                    next_goal = (
                        f"Send an invoice in QuickBooks for {req.client_name} for the completed work."
                    )
                elif req.state == "invoice_sent":
                    next_goal = (
                        f"Record any payment from {req.client_name} in QuickBooks when it arrives."
                    )

            _event_bus.clear()
            return {
                "action_log": new_log,
                "step": state.step + 1,
                "motor_error_log": new_motor_log,
                "hesitation_log": new_hesitation_log,
                "distraction_log": new_distraction_log,
                "distraction_memory_wipe_pending": True,
                "distraction_context_prompt": distraction_result["reorientation_prompt"],
                "goal": next_goal,
            }

        # ----------------------------------------------------------
        # 1. Hesitation check (before executing the action)
        # ----------------------------------------------------------
        if (
            settings.risk_aversion_enabled
            and llm_resp.action_type == ActionType.CLICK
            and target_el is not None
        ):
            nearby_names = [
                e.name[:60] for e in state.a11y_elements
                if e.element_id != target_el.element_id and e.name
            ][:8]

            if await _hesitation_engine.should_hesitate(
                element_name=target_el.name,
                action_type="click",
                risk_tolerance=getattr(persona, "risk_tolerance", 5),
                element_role=target_el.role,
                page_url=state.current_url,
                goal=state.goal,
                nearby_elements=nearby_names,
            ):
                risk_analysis = await _hesitation_engine.analyze_risk(
                    element_name=target_el.name,
                    element_role=target_el.role,
                    page_url=state.current_url,
                    goal=state.goal,
                    nearby_elements=nearby_names,
                )
                hesitation_prompt = _hesitation_engine.build_hesitation_prompt(
                    element_name=target_el.name,
                    risk_tolerance=getattr(persona, "risk_tolerance", 5),
                    risk_analysis=risk_analysis,
                )
                llm_resp = llm_resp.model_copy(
                    update={
                        "internal_monologue": (
                            llm_resp.internal_monologue
                            + f"\n\n{hesitation_prompt}"
                        )
                    }
                )
                hesitation_event = _hesitation_engine.create_hesitation_event(
                    element_name=target_el.name,
                    risk_tolerance=getattr(persona, "risk_tolerance", 5),
                    verification_prompt_injected=True,
                    resulting_behavior="PROCEEDED",
                )
                new_hesitation_log.append(hesitation_event)
                logger.info(
                    "[%s] Step %d HESITATION on '%s' (source=%s, risk=%d, category=%s)",
                    persona.name,
                    state.step,
                    target_el.name,
                    risk_analysis.get("source", "unknown"),
                    risk_analysis.get("risk_level", 0),
                    risk_analysis.get("risk_category", ""),
                )

        # ----------------------------------------------------------
        # 2. Motor errors — click scatter
        # ----------------------------------------------------------
        if (
            settings.motor_errors_enabled
            and llm_resp.action_type == ActionType.CLICK
            and target_el is not None
        ):
            motor_precision = getattr(persona, "motor_precision", 0.95)
            actual_x, actual_y, actual_el_id, is_misclick = (
                _motor_engine.apply_click_scatter(
                    target_el=target_el,
                    all_elements=state.a11y_elements,
                    motor_precision=motor_precision,
                    viewport_width=settings.viewport_width,
                    viewport_height=settings.viewport_height,
                    device=device,
                )
            )

            if is_misclick:
                scatter_coords = (actual_x, actual_y)
                motor_event = _motor_engine.create_motor_event(
                    error_variant="FAT_FINGER_MISCLICK",
                    intended_element_id=target_el.element_id,
                    intended_coords=(
                        target_el.x + target_el.width / 2,
                        target_el.y + target_el.height / 2,
                    ),
                    actual_coords=(actual_x, actual_y),
                    actual_element_id=actual_el_id,
                    motor_precision_applied=motor_precision,
                    resulting_behavior="PROCEEDED",
                )
                new_motor_log.append(motor_event)
                logger.info(
                    "[%s] Step %d FAT_FINGER_MISCLICK: intended=%s, hit=%s",
                    persona.name,
                    state.step,
                    target_el.element_id,
                    actual_el_id,
                )

            # Proximity anxiety check
            if _motor_engine.check_proximity_anxiety(
                target_el=target_el,
                all_elements=state.a11y_elements,
                device=device,
            ):
                prox_event = _motor_engine.create_motor_event(
                    error_variant="PROXIMITY_ANXIETY",
                    intended_element_id=target_el.element_id,
                    intended_coords=(
                        target_el.x + target_el.width / 2,
                        target_el.y + target_el.height / 2,
                    ),
                    actual_coords=(actual_x, actual_y),
                    actual_element_id=actual_el_id,
                    motor_precision_applied=motor_precision,
                    resulting_behavior="PROCEEDED",
                )
                new_motor_log.append(prox_event)
                logger.debug(
                    "[%s] Step %d PROXIMITY_ANXIETY on element %s",
                    persona.name,
                    state.step,
                    target_el.element_id,
                )

        # ----------------------------------------------------------
        # 3. Motor errors — typo injection
        # ----------------------------------------------------------
        if (
            settings.motor_errors_enabled
            and llm_resp.action_type == ActionType.TYPE
            and llm_resp.input_text
            and getattr(persona, "typo_rate", 0.0) > 0.0
        ):
            original_text = llm_resp.input_text
            mutated_text, did_inject = _motor_engine.inject_typos(
                text=original_text,
                typo_rate=getattr(persona, "typo_rate", 0.05),
            )
            if did_inject:
                llm_resp = llm_resp.model_copy(update={"input_text": mutated_text})
                typo_event = _motor_engine.create_motor_event(
                    error_variant="TYPO_INJECTION",
                    intended_element_id=llm_resp.target_element_id,
                    intended_coords=(0.0, 0.0),
                    actual_coords=(0.0, 0.0),
                    actual_element_id=llm_resp.target_element_id,
                    motor_precision_applied=getattr(persona, "motor_precision", 0.95),
                    original_text=original_text,
                    mutated_text=mutated_text,
                    resulting_behavior="PROCEEDED",
                )
                if motor_event is None:
                    motor_event = typo_event
                new_motor_log.append(typo_event)
                logger.info(
                    "[%s] Step %d TYPO_INJECTION: '%s' → '%s'",
                    persona.name,
                    state.step,
                    original_text,
                    mutated_text,
                )

        # ----------------------------------------------------------
        # Execute the (possibly modified) action in the browser
        # ----------------------------------------------------------
        if page is not None and llm_resp.action_type != ActionType.GIVE_UP:
            await browser_manager.execute_action(
                page=page,
                action_type=llm_resp.action_type,
                element_id=llm_resp.target_element_id,
                a11y_elements=state.a11y_elements,
                input_text=llm_resp.input_text,
                override_coords=scatter_coords,
            )

        total_area = sum(e.width * e.height for e in state.a11y_elements)
        viewport_area = settings.viewport_width * settings.viewport_height
        coverage_pct = round(min(total_area / viewport_area, 1.0) * 100, 1) if viewport_area else 0.0

        log_entry = ActionLog(
            step=state.step,
            url=state.current_url,
            page_title=state.page_title,
            action_type=llm_resp.action_type,
            target_element_id=llm_resp.target_element_id,
            target_element_name=target_el.name[:120] if target_el else "",
            target_element_role=target_el.role if target_el else "",
            input_text=llm_resp.input_text,
            x=target_el.x + target_el.width / 2 if target_el else 0,
            y=target_el.y + target_el.height / 2 if target_el else 0,
            frustration_score=state.cumulative_frustration,
            emotional_state=llm_resp.emotional_state,
            internal_monologue=llm_resp.internal_monologue,
            perceived_clutter_rating=llm_resp.perceived_clutter_rating,
            task_completed=llm_resp.task_completed,
            screenshot_path=state.screenshot_path,
            frustration_breakdown=state.frustration_metrics,
            frustration_reasoning=state.frustration_metrics.reasoning if state.frustration_metrics else [],
            visual_overload=state.visual_overload,
            interactable_element_count=len(state.a11y_elements),
            viewport_coverage_pct=coverage_pct,
            session_notes=llm_resp.session_notes,
            visual_signals=state.visual_signals,
            motor_error=motor_event,
            hesitation=hesitation_event,
        )

        new_log = list(state.action_log) + [log_entry]

        # ----------------------------------------------------------
        # 4. Distraction check — LLM-driven persona-aware chaos monkey
        # ----------------------------------------------------------
        distraction_memory_wipe_pending = state.distraction_memory_wipe_pending
        distraction_context_prompt = state.distraction_context_prompt

        # (Street simulation tick + CUSTOMER_ARRIVAL preemption handled in step 0 above)

        if settings.distraction_enabled:
            interruption_prob = getattr(persona, "interruption_probability", 0.05)

            squirrel_signal = _distraction_engine.detect_squirrel(
                state.visual_signals, state.goal,
            )
            should_fire = squirrel_signal is not None or (
                _distraction_engine.should_trigger_interruption(
                    action_count=state.step,
                    interruption_probability=interruption_prob,
                )
            )

            if should_fire:
                last_action_summary = (
                    f"{llm_resp.action_type.value} on '{llm_resp.target_element_id}'"
                    if llm_resp.target_element_id
                    else llm_resp.action_type.value
                )

                distraction_result = await _distraction_engine.generate_distraction(
                    persona=persona,
                    goal=state.goal,
                    current_url=state.current_url,
                    page_title=getattr(state, "page_title", ""),
                    step=state.step,
                    last_action_summary=last_action_summary,
                    visual_signals=state.visual_signals,
                    squirrel_signal=squirrel_signal,
                )

                variant = distraction_result["variant"]
                wipe_count = distraction_result["memory_wipe_lines"]

                notes_lines = (llm_resp.session_notes or "").split("\n")
                wipe_count = min(wipe_count, len(notes_lines))
                wiped_notes = (
                    "\n".join(notes_lines[:-wipe_count])
                    if wipe_count and wipe_count < len(notes_lines)
                    else (llm_resp.session_notes or "")
                )

                log_entry_updated = log_entry.model_copy(
                    update={"session_notes": wiped_notes},
                )
                new_log[-1] = log_entry_updated

                distraction_memory_wipe_pending = True
                distraction_context_prompt = distraction_result["reorientation_prompt"]

                distraction_event = _distraction_engine.create_distraction_event(
                    variant=variant,
                    pre_url=state.current_url,
                    memory_wiped=wipe_count,
                    narrative=distraction_result.get("narrative", ""),
                    feedback=(
                        f"{variant} triggered at step {state.step}. "
                        f"Wiped {wipe_count} session note lines. "
                        f"{distraction_result.get('narrative', '')}"
                    ),
                    sim_time_away_minutes=float(distraction_result.get("estimated_away_minutes", 0)),
                )
                log_entry_with_distraction = new_log[-1].model_copy(
                    update={"distraction": distraction_event},
                )
                new_log[-1] = log_entry_with_distraction
                new_distraction_log.append(distraction_event)
                logger.info(
                    "[%s] Step %d %s distraction — %s (wiped %d note lines)",
                    persona.name,
                    state.step,
                    variant,
                    distraction_result.get("narrative", "")[:120],
                    wipe_count,
                )

        logger.info(
            "[%s] Step %d executed: %s on '%s' | frustration=%.1f/%d | url=%s",
            persona.name,
            state.step,
            llm_resp.action_type.value,
            llm_resp.target_element_id,
            state.cumulative_frustration,
            persona.patience_budget,
            state.current_url,
        )

        return {
            "action_log": new_log,
            "step": state.step + 1,
            "motor_error_log": new_motor_log,
            "hesitation_log": new_hesitation_log,
            "distraction_log": new_distraction_log,
            "distraction_memory_wipe_pending": distraction_memory_wipe_pending,
            "distraction_context_prompt": distraction_context_prompt,
        }

    return execute_action


def make_evaluate_node(frustration_engine, memory_store):
    """Create the evaluation node that decides whether to continue or stop."""

    async def evaluate(state: AgentState) -> dict:
        if state.error:
            return {"outcome": "failure"}

        if state.llm_response and state.llm_response.task_completed:
            chain = state.goal_chain or []
            idx = state.current_goal_index
            next_idx = idx + 1
            if chain and next_idx < len(chain):
                next_item = chain[next_idx]
                # Support both dict-based BusinessTask and plain string goals
                if isinstance(next_item, dict):
                    next_goal = next_item.get("description", str(next_item))
                    next_sw = next_item.get("software_type", "")
                else:
                    next_goal = str(next_item)
                    next_sw = ""
                sw_label = f" (app: {next_sw})" if next_sw else ""
                logger.info(
                    "[%s] Sub-goal %d/%d done at step %d; advancing to: %s%s",
                    state.persona.name,
                    next_idx,
                    len(chain),
                    state.step,
                    next_goal[:60] + ("..." if len(next_goal) > 60 else ""),
                    sw_label,
                )
                return {
                    "current_goal_index": next_idx,
                    "goal": next_goal,
                    "outcome": "",
                }
            logger.info(
                "[%s] All goals completed at step %d! frustration=%.1f",
                state.persona.name,
                state.step,
                state.cumulative_frustration,
            )
            await _consolidate_session(memory_store, state, "success")
            return {"outcome": "success"}

        if state.llm_response and state.llm_response.action_type == ActionType.GIVE_UP:
            logger.info(
                "[%s] Gave up at step %d | frustration=%.1f",
                state.persona.name,
                state.step,
                state.cumulative_frustration,
            )
            await _consolidate_session(memory_store, state, "failure")
            return {"outcome": "failure"}

        if frustration_engine.should_rage_quit(
            state.cumulative_frustration, state.persona
        ):
            logger.info(
                "[%s] Rage quit! frustration=%.1f > budget=%d at step %d",
                state.persona.name,
                state.cumulative_frustration,
                state.persona.patience_budget,
                state.step,
            )
            await _consolidate_session(memory_store, state, "failure")
            return {"outcome": "failure"}

        if state.step >= state.max_steps:
            logger.info(
                "[%s] Max steps reached (%d)",
                state.persona.name,
                state.max_steps,
            )
            await _consolidate_session(memory_store, state, "failure")
            return {"outcome": "failure"}

        return {"outcome": ""}

    return evaluate


async def _consolidate_session(
    memory_store, state: AgentState, outcome: str
) -> None:
    """Run the Sleep Cycle: consolidate raw session events into long-term memory."""
    await memory_store.run_sleep_cycle(
        persona_id=state.persona.id,
        goal=state.goal,
        action_log=state.action_log,
        outcome=outcome,
        persona_description=state.persona.description,
    )


def _get_page(browser_manager, state: AgentState):
    """Retrieve the Playwright page handle registered on the browser manager."""
    return browser_manager.get_page(state.persona.name)


def make_switch_app_node(browser_manager):
    """Create the app-switching node.

    Inserted between ``evaluate`` and ``perceive`` in the graph.  When the
    next goal in the chain targets a different software_type than what is
    currently active, navigates the browser to the new app URL.
    """

    async def switch_app(state: AgentState) -> dict:
        chain = state.goal_chain or []
        idx = state.current_goal_index
        if idx >= len(chain):
            return {}

        current_task = chain[idx]
        if not isinstance(current_task, dict):
            return {}  # legacy plain-string goal — no switching

        target_type = current_task.get("software_type", "")
        target_url = current_task.get("url", "")

        if not target_type or not target_url:
            return {}

        if target_type == state.active_software_type:
            return {}  # already on the right app

        # Navigate browser to new app
        page = _get_page(browser_manager, state)
        logger.info(
            "[%s] Switching from %s → %s (%s)",
            state.persona.name,
            state.active_software_type or "(none)",
            target_type,
            target_url,
        )

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            logger.warning(
                "[%s] Failed to navigate to %s: %s",
                state.persona.name, target_url, e,
            )
            return {"error": f"App switch failed: {e}"}

        return {
            "active_software_type": target_type,
            "active_software_url": target_url,
            "current_url": target_url,
            "login_completed": False,   # may need to re-login for new app
            "login_redirect": False,
        }

    return switch_app
