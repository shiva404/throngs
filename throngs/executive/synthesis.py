"""
Phase 3 Level 1: Hierarchical Goal Synthesis (Executive Decision).

Synthesizes Internal State + World State into macro-goal and actionable software goal.
Spec: 2_Throngs - Autonomous Executive Function.md Section 3.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from throngs.persona import PersonaEngine
from throngs.schemas import PersonaDNA

from throngs.executive.state import GoalSynthesisResult

logger = logging.getLogger(__name__)


GOAL_SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "inner_voice_thought": {
            "type": "string",
            "description": (
                "In-character stream of consciousness: what is on this persona's mind "
                "right now given their internal state and world context."
            ),
        },
        "macro_goal": {"type": "string"},
        "actionable_software_goal": {"type": "string"},
    },
    "required": ["inner_voice_thought", "macro_goal", "actionable_software_goal"],
}

GOAL_SYNTHESIS_WITH_CONTEXT = """\
You are generating the "Executive Decision" (Level 1) for a simulated user in an autonomous UX simulation.

{persona_fragment}
{diary_block}
The application they will use: {start_url}

CONTEXT (use this to decide what they want to do):
{context_narrative}

Based on this persona and context, answer in character:
1. What is your macro-goal for the next period? (Include both life context and what you want to do in the app — e.g. "Feed the kids quickly, then spend 15 minutes checking the app to see if the Smith invoice was paid so I can buy supplies for the 10AM job.")
2. What is the concrete software-only goal? (One clear task in the app — e.g. "Check if the Smith invoice was paid in the last 30 days.")

Respond with ONLY valid JSON with keys: inner_voice_thought (1–2 sentences in-character), macro_goal, actionable_software_goal.
"""

GOAL_SYNTHESIS_MINIMAL = """\
You are generating the initial "inner voice" and software goal for a simulated user (persona) in an autonomous UX simulation.

{persona_fragment}
{diary_block}
The application URL they will start on: {start_url}

Based on this persona, produce:
1. inner_voice_thought: What is on their mind right now? One or two sentences, in character.
2. macro_goal: Same as actionable_software_goal when no life context is given.
3. actionable_software_goal: One clear, concrete task they want to accomplish in the app (e.g. "Create a new customer named Acme Corp", "Find and open the Smith invoice").

Respond with ONLY valid JSON: inner_voice_thought, macro_goal, actionable_software_goal.
"""

# Goal chain: realistic business workflow — ordered list of 3–8 tasks (e.g. check cashflow → raise PO → pay invoice)
GOAL_CHAIN_PROMPT = """\
You are generating a realistic business workflow for a simulated user (persona) in an autonomous UX simulation.

{persona_fragment}
{diary_block}
{software_block}
{context_block}

Think like a small business owner or operator. They don't do "one goal and stop" — they do a natural sequence of tasks.

{workflow_examples}

Generate an ordered list of 3 to 8 concrete software tasks that form one realistic business use case. Each task should be one clear action in a specific software application. Order matters: do the logical first step first.

For each task, specify which software_type the persona would use. Use ONLY the software types listed above.
- Use "accounting" for: creating estimates, sending invoices, recording payments, checking P&L, bank feeds, purchase orders
- Use "email" for: reading inquiries, replying to clients, sending estimates/quotes as attachments
- Do NOT use accounting software for tasks that should happen in email, and vice versa.

Respond with ONLY valid JSON in this exact form:
{{ "goal_chain": [ {{ "description": "First task", "software_type": "accounting" }}, {{ "description": "Second task", "software_type": "email" }}, ... ] }}
"""

# Fallback prompt when no software registry is provided (backward compat)
GOAL_CHAIN_PROMPT_LEGACY = """\
You are generating a realistic business workflow for a simulated user (persona) in an autonomous UX simulation.

{persona_fragment}
{diary_block}
The application they will use: {start_url}
{context_block}

Think like a small business owner or operator. They don't do "one goal and stop" — they do a natural sequence of tasks. Example: a stationary shop owner arrives, sees pens are running low. They would: 1) Check bank balance and cashflow in the app, 2) Create a purchase order for pens, 3) Pay the invoice when it arrives (or record the payment). Each step is one concrete task in the app.

Generate an ordered list of 3 to 8 concrete software tasks that form one realistic business use case. Each task should be one clear action or short flow (e.g. "Check bank balance and recent cashflow", "Create purchase order for [item]", "Pay or record payment for invoice X"). Order matters: do the logical first step first.

Respond with ONLY valid JSON in this exact form:
{{ "goal_chain": [ "First task in the app", "Second task", "Third task", ... ] }}
"""

_SERVICE_WORKFLOW_EXAMPLES = """\
Examples for a plumber:
- "Check email for new job inquiries" (email)
- "Create estimate for Alice Smith's drain repair" (accounting)
- "Send invoice for completed water heater install at Johnson residence" (accounting)
- "Check this week's profit and loss" (accounting)
- "Reply to Brian Johnson's email about scheduling" (email)

Examples for a CPA:
- "Check email for new client inquiries" (email)
- "Create invoice for Smith LLC tax preparation" (accounting)
- "Record payment received from Johnson family tax return" (accounting)
- "Check profit and loss statement for the month" (accounting)
- "Email Alice Brown about missing W-2 forms" (email)"""

_RETAIL_WORKFLOW_EXAMPLES = """\
Example: a stationary shop owner arrives, sees pens are running low. They would: 1) Check bank balance and cashflow in the app, 2) Create a purchase order for pens, 3) Pay the invoice when it arrives (or record the payment). Each step is one concrete task in the app."""

_DIARY_INSPIRATION_BLOCK = """\
DIARY INSPIRATION — a real day in this persona's work life. Use it to understand what they care \
about, what tasks feel natural to them, and what frustrates them. Do NOT follow this as a literal \
task list — treat it as flavour and context that informs what a realistic goal would look like for \
this person:
---
{diary_context}
---
"""


def _build_diary_block(diary_context: str | None) -> str:
    if not diary_context:
        return ""
    return "\n" + _DIARY_INSPIRATION_BLOCK.format(diary_context=diary_context) + "\n"


def _build_context_narrative(
    internal_state_dict: dict[str, float] | None,
    world_state_dict: dict[str, Any] | None,
    relation_context: str | None = None,
) -> str:
    """Build spec-style narrative for the LLM (Phase 1 + 2 + throng relations)."""
    parts = []
    if relation_context:
        parts.append(relation_context)
    if world_state_dict:
        ts = world_state_dict.get("timestamp_simulated", "")
        if ts:
            parts.append(f"It is {ts}.")
        cal = world_state_dict.get("calendar", "")
        if cal:
            parts.append(f"Calendar: {cal}")
        env = world_state_dict.get("environment", "")
        if env:
            parts.append(f"Environment: {env}")
        dev = world_state_dict.get("device", "")
        if dev:
            parts.append(f"Device: {dev}")
    if internal_state_dict:
        fin = internal_state_dict.get("financial_security", 0.5)
        energy = internal_state_dict.get("physical_energy", 0.8)
        stress = internal_state_dict.get("stress_level", 0.3)
        family = internal_state_dict.get("family_obligation", 0.2)
        parts.append(
            f"Your internal state: Financial_Security={fin:.2f}, Physical_Energy={energy:.2f}, "
            f"Stress_Level={stress:.2f}, Family_Obligation={family:.2f}."
        )
        if fin < 0.3:
            parts.append(
                "Financial_Security is critically low — revenue-generating or payment-checking tasks are a priority."
            )
    if world_state_dict:
        biz_model = world_state_dict.get("business_model", "retail")

        if biz_model == "service":
            # --- Service business context ---
            svc_parts = []
            bank_bal = world_state_dict.get("bank_balance")
            if bank_bal is not None:
                svc_parts.append(f"Recorded bank balance: ${bank_bal:.2f}")
            unrecorded = world_state_dict.get("unrecorded_payments") or world_state_dict.get("unrecorded_cash")
            if unrecorded:
                svc_parts.append(f"${unrecorded:.2f} received but NOT yet recorded in accounting software")
            phone = world_state_dict.get("pending_phone_calls")
            if phone:
                svc_parts.append(f"{phone} unanswered phone call(s) — URGENT, handle first")
            emails = world_state_dict.get("unread_email_inquiries")
            if emails:
                svc_parts.append(f"{emails} unread email inquiry/inquiries")
            est = world_state_dict.get("estimates_to_send")
            if est:
                svc_parts.append(f"{est} client(s) waiting for an estimate")
            inv = world_state_dict.get("invoices_to_send")
            if inv:
                svc_parts.append(f"{inv} completed job(s) needing an invoice")
            outstanding = world_state_dict.get("outstanding_invoices")
            outstanding_amt = world_state_dict.get("outstanding_amount")
            if outstanding:
                svc_parts.append(f"{outstanding} outstanding invoice(s) (${outstanding_amt:.2f} total)")
            if svc_parts:
                parts.append("Business status: " + "; ".join(svc_parts) + ".")
        else:
            # --- Retail walk-in business context ---
            served = world_state_dict.get("customers_served_today")
            waiting = world_state_dict.get("customers_waiting_to_pay")
            sales = world_state_dict.get("todays_sales")
            bank_bal = world_state_dict.get("bank_balance")
            unrecorded = world_state_dict.get("unrecorded_cash")
            pending_deposits = world_state_dict.get("pending_deposit_count")

            if served is not None or bank_bal is not None:
                street_parts = []
                if served is not None:
                    street_parts.append(f"Customers served today: {served}")
                if waiting:
                    street_parts.append(f"{waiting} customer(s) still waiting to be billed")
                if sales is not None:
                    street_parts.append(f"Today's takings: ${sales:.2f}")
                if bank_bal is not None:
                    street_parts.append(f"Recorded bank balance: ${bank_bal:.2f}")
                if unrecorded:
                    street_parts.append(
                        f"${unrecorded:.2f} cash/card received but NOT yet entered in the app"
                        f" ({pending_deposits} transaction(s) to record)"
                    )
                if street_parts:
                    parts.append("Shop status: " + "; ".join(street_parts) + ".")

    if not parts:
        return "No additional context (simulated time/calendar/internal state not provided)."
    return "\n".join(parts)


def synthesize_goal(
    persona: PersonaDNA,
    start_url: str,
    llm: Any,
    *,
    persona_engine: PersonaEngine | None = None,
    internal_state_dict: dict[str, float] | None = None,
    world_state_dict: dict[str, Any] | None = None,
    relation_context: str | None = None,
    diary_context: str | None = None,
    return_result: bool = False,
) -> str | GoalSynthesisResult:
    """
    Phase 3 Level 1: Synthesize an actionable software goal from Internal State and World State.

    When internal_state_dict and/or world_state_dict are provided, the prompt follows
    the spec example: "It is 7:30 AM. Your Financial_Security is critically low (0.2)..."

    relation_context: optional narrative from ThrongGraph.context_for_throng (e.g. "You are
    throng X; you act as accountant for A; you depend on Y for delivery.") to ground the
    agent in inter-throng relationships.

    Returns the actionable_software_goal string, or GoalSynthesisResult if return_result=True.
    """
    persona_engine = persona_engine or PersonaEngine()
    persona_engine.load_persona(persona)
    persona_fragment = persona_engine.build_system_prompt_fragment(persona)
    diary_block = _build_diary_block(diary_context)

    has_context = internal_state_dict or world_state_dict or relation_context
    if has_context:
        context_narrative = _build_context_narrative(
            internal_state_dict, world_state_dict, relation_context
        )
        prompt = GOAL_SYNTHESIS_WITH_CONTEXT.format(
            persona_fragment=persona_fragment,
            diary_block=diary_block,
            start_url=start_url,
            context_narrative=context_narrative,
        )
    else:
        prompt = GOAL_SYNTHESIS_MINIMAL.format(
            persona_fragment=persona_fragment,
            diary_block=diary_block,
            start_url=start_url,
        )

    from langchain_core.messages import HumanMessage

    response = llm.invoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", "") or (response if isinstance(response, str) else "")
    if not isinstance(content, str):
        content = str(content)

    inner = ""
    macro = ""
    goal = ""
    try:
        raw = json.loads(content.strip())
        if isinstance(raw, dict):
            inner = raw.get("inner_voice_thought", "")
            macro = raw.get("macro_goal", "")
            goal = raw.get("actionable_software_goal", "")
            if not goal and macro:
                goal = macro
    except json.JSONDecodeError:
        logger.warning("Goal synthesis response was not valid JSON; using fallback goal.")

    if inner:
        logger.info(
            "Goal synthesis [%s] inner voice: %s",
            persona.name,
            (inner[:200] + "..." if len(inner) > 200 else inner),
        )
    if not goal or not goal.strip():
        goal = "Complete a realistic task in the application that fits your persona."
        macro = macro or goal
        logger.warning("Goal synthesis returned empty goal; using fallback.")

    goal = goal.strip()
    macro = (macro or goal).strip()
    if return_result:
        return GoalSynthesisResult(
            inner_voice_thought=inner,
            macro_goal=macro,
            actionable_software_goal=goal,
        )
    return goal


def synthesize_goal_chain(
    persona: PersonaDNA,
    start_url: str,
    llm: Any,
    *,
    persona_engine: PersonaEngine | None = None,
    relation_context: str | None = None,
    diary_context: str | None = None,
    world_state_dict: dict[str, Any] | None = None,
    software_registry: Any | None = None,
) -> list[str]:
    """
    Synthesize an ordered list of goals (business workflow) for a realistic use case.

    When ``software_registry`` is provided, each goal is a dict with
    ``description`` and ``software_type`` keys.  Otherwise, returns plain
    strings (backward compat).

    Returns 3–8 concrete tasks; the agent will work through them in order.
    """
    from throngs.workspace import BusinessTask, SoftwareRegistry as SR

    persona_engine = persona_engine or PersonaEngine()
    persona_engine.load_persona(persona)
    persona_fragment = persona_engine.build_system_prompt_fragment(persona)
    diary_block = _build_diary_block(diary_context)
    context_block = ""
    if relation_context:
        context_block = "Relationship context: " + relation_context
    if world_state_dict:
        street_narrative = _build_context_narrative(None, world_state_dict)
        if street_narrative and "No additional context" not in street_narrative:
            context_block = (context_block + "\n" + street_narrative).strip()

    use_software_aware = software_registry is not None and isinstance(software_registry, SR) and len(software_registry.entries) > 1

    if use_software_aware:
        # Multi-app prompt
        is_service = world_state_dict and world_state_dict.get("business_model") == "service"
        examples = _SERVICE_WORKFLOW_EXAMPLES if is_service else _RETAIL_WORKFLOW_EXAMPLES
        prompt = GOAL_CHAIN_PROMPT.format(
            persona_fragment=persona_fragment,
            diary_block=diary_block,
            software_block="SOFTWARE AVAILABLE TO THIS PERSONA:\n" + software_registry.to_prompt_fragment(),
            context_block=context_block,
            workflow_examples=examples,
        )
    else:
        # Legacy single-app prompt
        prompt = GOAL_CHAIN_PROMPT_LEGACY.format(
            persona_fragment=persona_fragment,
            diary_block=diary_block,
            start_url=start_url,
            context_block=context_block,
        )

    from langchain_core.messages import HumanMessage

    response = llm.invoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", "") or (response if isinstance(response, str) else "")
    if not isinstance(content, str):
        content = str(content)

    chain: list[str] = []
    try:
        raw = json.loads(content.strip())
        if isinstance(raw, dict) and "goal_chain" in raw:
            raw_chain = raw["goal_chain"]
            if isinstance(raw_chain, list):
                for item in raw_chain:
                    if isinstance(item, dict):
                        # Software-aware format: {"description": ..., "software_type": ...}
                        desc = str(item.get("description", "")).strip()
                        sw_type = str(item.get("software_type", "")).strip()
                        if desc:
                            if use_software_aware and sw_type:
                                # Resolve URL from registry
                                entry = software_registry.get(sw_type)
                                url = entry.url if entry else ""
                                task = BusinessTask(description=desc, software_type=sw_type, url=url)
                                chain.append(task.to_goal_chain_dict())
                            else:
                                chain.append(desc)
                    elif isinstance(item, str) and item.strip():
                        chain.append(item.strip())
    except (json.JSONDecodeError, TypeError):
        logger.warning("Goal chain response was not valid JSON; using single fallback goal.")

    if not chain:
        chain = ["Complete a realistic business task in the application that fits your persona."]
        logger.warning("Goal chain empty; using single fallback goal.")

    # Log summary
    def _task_label(item):
        if isinstance(item, dict):
            return f"{item.get('description', '')} [{item.get('software_type', '')}]"
        return str(item)

    logger.info(
        "Goal chain [%s] (%d steps): %s",
        persona.name,
        len(chain),
        " → ".join(_task_label(t) for t in chain[:3]) + (" ..." if len(chain) > 3 else ""),
    )
    return chain
