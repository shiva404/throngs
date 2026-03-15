# Human Flaws & Environmental Constraints Module

**Module:** The "Chaos & Psychology" Engine 

**Objective:** Introduce realistic human behavioral constraints into the Synthetic Swarm. Agents must no longer execute tasks with robotic perfection. The system must simulate financial anxiety (Risk Aversion), working memory loss (Distractions), physical clumsiness (Motor Errors), and lazy reading habits (F-Pattern Scanning) to stress-test error recovery and UI reassurance.

## **1\. Phase 1: Risk Aversion & The Hesitation Engine**

Financial software induces anxiety. The engine must intercept actions that involve money or data destruction and force the agent to verify the UI before proceeding.

* **High-Stakes Dictionary:** Maintain a localized array of regex triggers (e.g., `["pay", "submit", "delete", "file tax", "transfer"]`).  
* **The Intercept Trigger:** Before Playwright executes a `click` on an element containing a High-Stakes keyword, the Python orchestrator halts execution.  
* **The Verification Loop:**  
  * The engine checks the Persona's `risk_tolerance` score (1-10).  
  * **If Risk Tolerance \< 5:** The engine sends the current screenshot back to the LLM with an overridden prompt: *"HESITATION TRIGGERED: You are about to execute a high-stakes action. Scan the current screen. Can you explicitly see the total dollar amount and recipient? If not, you must PANIC and output an 'abandon\_flow' action."*  
* **UX Success/Failure:** If the UI provides clear contextual reassurance near the button, the agent proceeds. If the UI hides the totals on a previous screen, the agent abandons the flow, logging a "Psychological Drop-off."

## **2\. Phase 2: Contextual Distraction (The "Chaos Monkey")**

Real users multitask. The system must test if the SaaS UI provides enough context (breadcrumbs, clear headers) for a user to resume a task after being interrupted.

* **The Distraction Probability:** Introduce a `distraction_rate` (e.g., 5% chance per step) into the Python orchestrator.  
* **The Interruption Event:** When triggered, the script pauses Playwright for a simulated duration.  
* **Working Memory Wipe:** The engine forcefully deletes the last 3 actions from the agent's Short-Term Memory buffer (Redis).  
* **The "Resume" Prompt:** The LLM is re-engaged with the prompt: *"You stepped away for a 20-minute phone call. You have forgotten your last 3 clicks. Look at the current screen. Based ONLY on the visual breadcrumbs and headers, determine what you were doing and decide your next action."*  
* **UX Success/Failure:** Tests whether the UI successfully orientates lost users or if it relies too heavily on the user remembering how they got there.

## **3\. Phase 3: Motor Errors & The "Fat Finger" Simulator**

Agents must simulate physical mistakes, particularly for mobile personas or users rushing through data entry, to test the product's Error State UX.

* **The Precision Metric:** Assign a `motor_precision` float to the Persona (e.g., 0.95 for Desktop Pro, 0.70 for Mobile Contractor in a truck).  
* **Coordinate Offsets:** When the LLM targets an `element_id`, Playwright retrieves the exact `(x, y)` center. The Python script then applies a randomized scatter algorithm based on the `motor_precision`.  
* **The Mis-Click Result:** If the scatter pushes the click outside the target's bounding box and onto an adjacent "Cancel" button, Playwright clicks the wrong button.  
* **Error Recovery Evaluation:** The LLM evaluates the resulting screen. Does the UI offer a forgiving "Undo" toast notification, or does the user lose all their work and spike their Frustration Score?

## **4\. Phase 4: F-Pattern Geographical Weighting**

Agents must scan the screen like humans do—prioritizing the top-left and largely ignoring the right margins.

* **Spatial Grid Calculation:** The Python engine divides the Playwright viewport into a 3x3 geographic grid.  
* **Saliency Modification:** \* Elements located in the Top-Left and Middle-Left sectors receive a `1.5x` multiplier to their True Visibility Score.  
  * Elements in the Far-Right or Bottom-Right "dead zones" receive a `0.6x` penalty.  
* **Outcome:** If a Product Manager places the critical "Save" button in the bottom right corner without enough contrasting color, the F-Pattern penalty pushes its Visibility Score below the threshold, and the LLM literally cannot "see" it.

---

## **5\. Expanded Data Schema Definition**

The agent's state JSON must be expanded to log these human flaws for the final UX Report Card:

JSON

```
{
  "event_type": "HUMAN_FLAW_SIMULATION",
  "flaw_triggered": "HESITATION_PHASE",
  "persona_metrics": {
    "risk_tolerance": 3,
    "motor_precision": 0.90
  },
  "environmental_factors": {
    "interruption_occurred": false,
    "memory_wiped": false
  },
  "action_intercepted": true,
  "verification_successful": false,
  "resulting_behavior": "ABANDON_TASK",
  "system_feedback_log": "Agent attempted to process payroll. Hesitation triggered due to high-stakes action. Agent failed to find 'Total Amount' on the active screen. Agent abandoned task."
}
```

## **6\. Engineering Recommendations**

* **Random Seed Control:** Because the "Chaos Monkey" and Motor Errors introduce randomness, engineers must implement fixed random seeds during specific test runs. This ensures that if a bot fails due to a mis-click, a developer can replay the *exact* same simulation to debug the UI error state.  
* **Mobile Viewports:** The Motor Error offset radius should dynamically increase when Playwright is emulating a mobile device (touch target constraint) versus a desktop environment (cursor constraint).

