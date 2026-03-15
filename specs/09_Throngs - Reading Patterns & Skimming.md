# **Reading Patterns & Skimming**

**Module:** The "F-Pattern" Engine (Geographic Attention Weighting) **Objective:** Simulate natural human skimming and reading behaviors. The engine must mathematically bias the AI agent's attention toward the top and left sides of the viewport (the standard Western "F-Pattern" and "Z-Pattern"), heavily penalizing the discoverability of UI elements placed in visual "dead zones" (like the bottom-right corner).

## **1\. Phase 1: Geographic Zoning & The Spatial Grid**

The engine cannot treat every pixel on the screen equally. It must divide the Playwright viewport into weighted geographic zones before evaluating the UI.

* **Grid Generation:** The Python orchestrator divides the current viewport dimensions (width and height) into a 3x3 grid (9 sectors total).  
* **The Weighting Matrix:** Assign a `geographic_multiplier` to each sector based on standard eye-tracking studies:  
  * **Top-Left (Primary Anchor):** `1.5x` (Maximum attention)  
  * **Top-Middle & Middle-Left (Scanning Path):** `1.2x`  
  * **Center (Focus Zone):** `1.0x` (Neutral)  
  * **Top-Right (Secondary Anchor/Utility):** `0.9x` (Often reserved for profiles/settings, usually scanned last)  
  * **Bottom-Left & Bottom-Middle:** `0.7x` (Fatigue zone)  
  * **Middle-Right & Bottom-Right (The "Dead Zone"):** `0.4x` (Requires extremely high visual contrast to be noticed)

## **2\. Phase 2: Modifying the True Visibility Score**

This module directly hooks into the **Hybrid Visual Perception Layer (The Retina)** we built previously.

* **The Integration:** After calculating the `Base Saliency Score` (from the computer vision heatmap) and subtracting the size/contrast penalties, the engine applies the `geographic_multiplier`.  
* **The Formula:** `Final Visibility Score = (Base Saliency Score - Penalties) * Geographic_Multiplier`  
* **The Outcome:** If your designers place a standard grey "Advanced Settings" button in the bottom-right corner, the `0.4x` multiplier will crush its visibility score below the `Visibility_Threshold` (e.g., 20%). The Python engine will literally hide this element from the LLM, simulating that the user's eyes simply never made it that far down the page.

## **3\. Phase 3: Time-Bounded Skimming (The Impatience Factor)**

When humans are in a rush, their F-Pattern scanning becomes even more severe. They only read the first two words of a sentence or the first item in a list.

* **The Persona Variable:** Utilize the existing `patience_budget` metric from the Persona DNA Card.  
* **The "Skim" Penalty:** If a persona has a low patience budget (e.g., "The On-the-Go Contractor"), the engine enforces a strict "Skim Rule" on text-heavy elements (like tables or long drop-down menus).  
* **The Execution:** Playwright truncates the A11y text of long lists or paragraphs before sending them to the LLM.  
  * *Example:* If a dropdown has 15 items, the engine only passes the first 4 items to the LLM, plus a note: `[11 more items hidden. User stopped scanning.]`  
  * If the target action is item \#12, the agent fails to find it, accurately simulating a user who gives up scanning a poorly alphabetized or overly long list.

---

## **4\. Data Schema Definition**

To track how placement affects discoverability, append this `spatial_attention_metrics` object to the JSON logs:

JSON

```
{
  "event_type": "GEOGRAPHIC_SCAN_EVALUATION",
  "target_element": {
    "id": "link-export-csv",
    "screen_sector": "BOTTOM_RIGHT",
    "geographic_multiplier_applied": 0.4
  },
  "visibility_calculation": {
    "base_saliency": 45,
    "adjusted_visibility_score": 18,
    "blindspot_threshold": 20
  },
  "passed_blindspot_threshold": false,
  "resulting_behavior": "ELEMENT_IGNORED",
  "system_feedback_log": "Agent completely missed the 'Export CSV' link because it was placed in the bottom-right dead zone and did not possess enough visual contrast to break the F-pattern scanning habit."
}
```

## **5\. Engineering Constraints & Recommendations**

* **Responsive Design (Mobile vs. Desktop):** The F-Pattern is highly prevalent on Desktop (wide screens), but Mobile users tend to scan straight down the center (the "I-Pattern") due to narrow viewports. Engineers *must* dynamically swap the Weighting Matrix based on the active Playwright device emulator.  
* **RTL (Right-to-Left) Localization:** If QuickBooks supports languages like Arabic or Hebrew, the engine must invert the Weighting Matrix (Top-Right becomes the `1.5x` Primary Anchor). The engine should check the `dir` attribute of the `<html>` tag to determine the correct matrix automatically.

