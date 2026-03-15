

# **Motor Errors & Input Clumsiness**

**Module:** The "Oops" Engine (Physical Error Simulator) **Objective:** Simulate physical human imperfections during UI interaction. The system must degrade the mathematical precision of Playwright's click and type actions based on the Persona's environment and device. It will actively test if touch targets are too close together, if forms can handle bad data formatting, and if the product's error-recovery UX is helpful or punishing.

## **1\. Phase 1: The "Fat Finger" Click Scatter (Targeting Errors)**

Playwright naturally clicks the exact `(x, y)` dead-center of a bounding box. This module intercepts that action and applies a randomized spatial offset to simulate clumsy clicking.

* **The Persona Variable:** Add a `motor_precision` float (0.0 to 1.0) to the Persona DNA Card.  
  * *Desktop Pro (High Precision):* `0.98`  
  * *Mobile Contractor in a Truck (Low Precision):* `0.65`  
* **The Scatter Algorithm:**  
  * When the LLM outputs `target_element_id`, Python calculates the element's exact center `(Cx, Cy)`.  
  * Python applies a Gaussian noise function to generate an offset `(dx, dy)`. The radius of this noise is inversely proportional to the `motor_precision` score and proportional to the simulated viewport size.  
  * Playwright is commanded to click the new coordinate: `(Cx + dx, Cy + dy)`.  
* **The Mis-Click Event:** \* If the offset coordinate falls outside the intended button's bounding box and lands on an adjacent element (e.g., hitting "Cancel" instead of "Save"), Playwright executes the click on the unintended element.  
  * **UX Evaluation:** The LLM receives the next screenshot. If the UI abruptly deleted all the user's work without an "Are you sure?" prompt, the agent logs a catastrophic `Irreversible_Destruction_Error` and spikes the Frustration Score.

## **2\. Phase 2: The Typo Generator (Data Entry Errors)**

Users rarely type perfectly formatted data on the first try, especially on mobile keyboards. The system must test how gracefully the UI handles bad inputs.

* **The Mechanism:** When the LLM's chosen action is `type` (e.g., entering an invoice amount or date), the Python orchestrator intercepts the `input_text` string.  
* **The Mutation Types:** Based on a configurable `typo_rate` (e.g., 10%), apply one of the following mutations:  
  * *Character Swap:* Change "100.00" to "100..00" or "100.0p" (adjacent keyboard keys).  
  * *Formatting Error:* Change standard date "12/25/2026" to "25-12-26" or "12252026".  
  * *Omission:* Drop a required digit from a routing number.  
* **UX Evaluation:** When the agent clicks "Submit" with the bad data, the LLM evaluates the resulting Error State.  
  * *Good UX:* The UI highlights the specific field in red with a plain-English tooltip: "Please use MM/DD/YYYY format." Agent fixes it and proceeds.  
  * *Bad UX:* The UI throws a generic "Error 500" or clears the entire form. Agent logs an `Unhelpful_Error_State` and abandons the task.

## **3\. Phase 3: Fitts's Law Enforcement (Proximity Penalties)**

The engine must proactively penalize UI designs that place destructive actions too close to primary actions, regardless of whether a mis-click actually occurs during that specific run.

* **The Logic:** During the A11y Tree extraction, the Python script calculates the margin (pixel distance) between critical buttons.  
* **The Penalty:** If the margin between a "Submit" button and a "Clear Form" button is less than `8px` (desktop) or `16px` (mobile), the system immediately applies a `Proximity_Anxiety_Spike` to the agent's Frustration Score before it even attempts to click.

---

## **4\. Data Schema Definition**

To track error recovery metrics, engineers must append an `error_recovery_metrics` object to the JSON logs:

JSON

```
{
  "event_type": "MOTOR_ERROR_SIMULATION",
  "error_variant": "FAT_FINGER_MISCLICK",
  "intended_action": {
    "element_id": "btn-save-invoice",
    "coordinates": [450, 800]
  },
  "actual_execution": {
    "clicked_element_id": "btn-cancel-invoice",
    "coordinates": [410, 800],
    "motor_precision_applied": 0.75
  },
  "system_recovery_ux": {
    "destructive_warning_present": false,
    "undo_option_available": false
  },
  "resulting_behavior": "FRUSTRATION_QUIT",
  "system_feedback_log": "I tried to tap Save, but the buttons are too close together and I accidentally hit Cancel. The app deleted my 15-line invoice without asking for confirmation. I am furious."
}
```

## **5\. Engineering Constraints & Recommendations**

* **Viewport Emulation:** The pixel offset radius for the scatter algorithm *must* be scaled based on the Playwright viewport. A 10-pixel offset on a 4K desktop monitor is negligible; a 10-pixel offset on an iPhone SE emulator is the difference between two entirely different menus.  
* **Typo Dictionary:** Utilize a standard "adjacent key" mapping array (QWERTY layout) in Python so that the typos generated are physically realistic (e.g., swapping 'm' for 'n', not 'm' for 'q').

