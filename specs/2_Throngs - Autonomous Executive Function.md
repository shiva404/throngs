# **Autonomous Executive Function**

**Module:** The "Life Simulation" Engine (Goal-Free Autonomy) **Objective:** Transition the Synthetic Swarm from rigid, human-assigned tasks to fully autonomous, open-ended simulation. Agents must dynamically generate their own goals based on internal psychological drives, simulated environmental contexts (time of day, calendar events), and spontaneous life interruptions.

**Implementation:** Goal synthesis (Phase 3 Level 1 & 2) and the *consumption* of Internal State and World State are in `throngs.executive` package (`state`, `synthesis`, `decomposition`). It accepts optional `internal_state_dict` (Phase 1) and `world_state_dict` (Phase 2); when provided, the LLM prompt follows the spec’s narrative style. Phase 1 decay/regen tick, Phase 2 simulated clock and polling, and Phase 4 life-event injection are separate (or future) work; their outputs can be passed into `synthesize_goal()` and into the graph as needed.

---

## **1\. Phase 1: The "Needs & Drives" Engine (Internal State)**

Agents must possess a continuously updating internal state that dictates their motivations, similar to a character in *The Sims*.

* **Internal Variables:** Maintain a JSON object for each active agent containing normalized floats (0.0 to 1.0) for core drives:  
  * `Financial_Security` (Decays when bills are due or invoices are unpaid).  
  * `Physical_Energy` (Decays over time, restores after simulated "sleep" or "meals").  
  * `Stress_Level` (Increases with complex tasks or looming deadlines).  
  * `Family_Obligation` (Spikes at specific times, e.g., morning school run).  
* **The Decay/Regen Tick:** A background cron job must update these variables every simulated "hour." If `Financial_Security` drops below `0.3`, the agent's primary motivation shifts to revenue-generating tasks.

## **2\. Phase 2: The Environmental Observer (The "World State")**

The agent needs context outside of the QuickBooks application to make realistic decisions about when and how to use the software.

* **The Simulated Clock:** The engine must run on a simulated timeline (e.g., Tuesday, 7:30 AM).  
* **The Context Payload:** Before the agent wakes up or shifts tasks, the system generates a "World State" JSON:  
  * *Calendar:* "10:00 AM \- Plumbing Job at 123 Main St."  
  * *Environment:* "You are currently at the kitchen table. The kids are waking up."  
  * *Device:* "You are using your mobile phone."  
* **The Polling Mechanism:** The agent polls this World State continuously to determine if its current activity is still contextually appropriate.

## **3\. Phase 3: Hierarchical Goal Synthesis (The Planner)**

The agent must use an LLM to synthesize its Internal State and World State into actionable software goals.

* **Level 1: The Executive Decision (What to do)**  
  * **Prompting the LLM:** *"It is 7:30 AM. Your 'Financial\_Security' is critically low (0.2). You have a job at 10:00 AM, but your kids need breakfast right now. What is your macro-goal for the next hour?"*  
  * **Output:** The LLM might output: *"Feed the kids quickly, then spend 15 minutes checking QuickBooks on my phone to see if the Smith invoice was paid so I can buy supplies for the 10:00 AM job."*  
* **Level 2: Task Decomposition (How to do it)**  
  * The engine takes the QuickBooks portion of the macro-goal and breaks it down into sub-tasks: `[1. Open App, 2. Navigate to Invoices, 3. Check status of 'Smith', 4. Send reminder if unpaid]`.  
* **Level 3: Execution Handoff:**  
  * These sub-tasks are then passed down to the **Perception Layer** (Playwright \+ Hybrid Retina) we built in previous PRDs to actually execute the clicks.

## **4\. Phase 4: Life Event Interruptions (Context Switching)**

Real life doesn't respect software workflows. The engine must dynamically force the agent to abandon tasks based on external priorities.

* **Event Injector:** The Python orchestrator randomly injects high-priority Life Events based on the agent's Persona (e.g., *"Client calls with an emergency,"* or *"Baby starts crying"*).  
* **The Cognitive Interrupt:** When an event fires, the agent's current Playwright execution pauses. The LLM evaluates the event against its active goal.  
* **UX Evaluation:**  
  * If the agent abandons a half-written invoice in QuickBooks to deal with a simulated emergency, the system waits 2 simulated hours, then prompts the agent to return.  
  * *The Ultimate Test:* Does QuickBooks auto-save the draft? When the agent logs back in, does the dashboard remind them they have an unfinished invoice? If not, the agent's `Stress_Level` spikes and a massive UX failure is logged.

---

## **5\. Data Schema Definition**

To track this autonomous behavior, the engine must log the agent's evolving state tree:

JSON

```
{
  "timestamp_simulated": "Tuesday 08:15 AM",
  "internal_state": {
    "financial_security": 0.25,
    "physical_energy": 0.80,
    "stress_level": 0.60
  },
  "active_macro_goal": "Secure funds for 10AM job by checking recent payments.",
  "current_micro_action": "Scanning Dashboard for 'Recent Transactions' widget.",
  "interruption_event": {
    "event_type": "KIDS_NEED_TO_LEAVE_FOR_SCHOOL",
    "agent_decision": "ABANDON_SOFTWARE_TASK",
    "expected_ux_outcome": "Draft state must be preserved for mobile resumption."
  }
}
```

## **6\. Engineering Constraints & Recommendations**

* **Token Cost Management:** Running a continuous "stream of consciousness" for an autonomous agent can consume LLM tokens rapidly. Use a smaller, faster model (like Gemini 1.5 Flash) for the Level 1 Executive Decisions and Goal Synthesis, and only invoke the heavier multimodal models (like Gemini 1.5 Pro) when the agent is actively looking at complex UI screenshots.  
* **Sandbox Boundaries:** Ensure the agent's Playwright environment is strictly isolated. An autonomous agent instructed to "find money" might attempt to navigate to simulated banking portals or external email clients. Whitelist allowed domains strictly to your staging environment to prevent the agent from wandering the actual internet.

