# Contextual Distraction & State Management

**Module:** The "Chaos Monkey" (Real-World Interruption Engine) 

**Objective:** Simulate the chaotic environment of real-world SaaS usage. The engine must actively interrupt agents mid-workflow to test the UI's ability to preserve uncommitted data (auto-save), provide visual orientation (breadcrumbs/headers), and recover gracefully from cross-tab navigation and in-app popups.

## **1\. Phase 1: The "Coffee Break" (Temporal Interruption & Memory Wipe)**

The system must simulate a user stepping away from their desk and forgetting their immediate train of thought. This tests the efficacy of UI breadcrumbs, progress bars, and clear page headers.

* **The Trigger Mechanism:** Introduce a configurable `interruption_probability` variable into the Python orchestrator (e.g., 5% chance per action).  
* **The Interruption Event:** 1\. The Python script pauses the Playwright execution thread for a configurable duration (e.g., 5 seconds in real-time to simulate 30 minutes). 2\. **Crucial Step:** The script forcefully flushes the last 3-5 actions from the agent's Short-Term Memory buffer (Redis). The agent officially "forgets" how it got to the current screen.  
* **The Recovery Prompt:** The LLM is re-engaged with a modified System Prompt: *"HESITATION TRIGGERED: You stepped away for a long phone call. You have forgotten your last few clicks. Look at the current screen. Based ONLY on the visual headers, breadcrumbs, and active form fields, determine what you were doing and decide your next action."*  
* **Success/Failure Metric:** If the LLM successfully parses its location and proceeds, log a `Context_Recovery_Success`. If the LLM is confused by generic labeling (e.g., a screen that just says "Form" instead of "Step 2: Contractor Details") and clicks "Home" to start over, log a `Context_Recovery_Failure` and apply a massive Frustration penalty.

## **2\. Phase 2: The "Tab Hoarder" (Concurrent State Testing)**

Power users frequently open multiple tabs to cross-reference data. The engine must test if navigating away and returning causes session timeouts or data loss.

* **The Trigger Mechanism:** When the agent needs a specific piece of data to complete a form (e.g., "Find Contractor ID"), trigger the Tab Hoarder routine.  
* **The Execution Flow:**  
  * Playwright opens a *new* headless browser tab (`Tab B`) while leaving the primary form open and unsubmitted in `Tab A`.  
  * The agent navigates `Tab B` to a different section of the app (e.g., the "Vendor Directory") and extracts the required data.  
  * Playwright closes `Tab B` and switches focus back to `Tab A`.  
* **The State Check:** The LLM evaluates `Tab A`.  
  * Did the uncommitted text disappear?  
  * Did the session time out?  
  * If data was lost, the agent logs a `State_Destruction_Error`, spikes the Frustration Score, and abandons the task.

## **3\. Phase 3: The "Squirrel\!" (In-App Distraction & Recovery)**

Marketing banners, tooltips, and chat bubbles often hijack the user's attention. The system must test how disruptive these are to the primary workflow.

* **Saliency Hijacking:** Utilizing the Hybrid Visual-Structural Layer (the "Retina" built previously), the engine continuously monitors the screen for newly rendered pop-ups or banners.  
* **The Distraction Event:** If a non-critical pop-up (e.g., "Try our new Premium feature\!") achieves a True Visibility Score higher than the agent's primary task element, the agent is *forced* to interact with the distraction (either reading it or clicking its "Close/X" button).  
* **Recovery Time Measurement:** After dismissing the popup, the engine measures how many clicks or seconds it takes for the agent to re-orient and find the primary task element again. If the pop-up forced a page reload or wiped the form, log a `Distraction_Abandonment`.

---

## **4\. Data Schema Definition**

To track the impact of the Chaos Monkey, engineers must append an `interruption_metrics` object to the final JSON output log for each simulation run:

JSON

```
{
  "event_type": "CONTEXTUAL_DISTRACTION",
  "distraction_variant": "COFFEE_BREAK_MEMORY_WIPE",
  "pre_interruption_state": {
    "url": "/app/payroll/run/step-2",
    "uncommitted_inputs": 4
  },
  "post_interruption_behavior": {
    "state_preserved_by_app": true,
    "context_recovered_by_agent": false,
    "recovery_time_ms": null
  },
  "resulting_action": "ABANDON_TASK",
  "system_feedback_log": "I returned to the screen but the header only said 'Details'. I didn't know if I was paying a vendor or an employee, so I clicked the Home button to start over to be safe."
}
```

## **5\. Engineering Constraints & Recommendations**

* **Deterministic Chaos (Random Seeds):** Because this module introduces randomness (e.g., a 5% chance to interrupt), engineers *must* implement configurable random seeds. If an agent fails due to an interruption, a developer needs to be able to pass that exact seed into their local environment to replay the exact same interruption and debug the UI.  
* **Session Persistence:** For the "Tab Hoarder" tests, ensure Playwright is configured to share the browser context (cookies, localStorage, sessionStorage) across tabs exactly as a real Chrome instance would.

