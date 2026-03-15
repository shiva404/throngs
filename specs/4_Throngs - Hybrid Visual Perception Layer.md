# **Hybrid Visual Perception Layer**

**Module:** The "Retina" (Visual-Structural Evaluation Engine) 

**Objective:** Upgrade the agent's perception from purely code-based (Accessibility Tree) to true human visual simulation. The engine must programmatically calculate element size, contrast, and color semantics, and intersect that data with a computer vision saliency model to determine the "True Visibility Score" of UI elements. Elements that fall below the visibility threshold will be hidden from the LLM's context, realistically simulating human oversight.

## **1\. Phase 1: Enhanced Programmatic DOM Scraper (The "Physical" Profile)**

Playwright must be extended to capture the physical and stylistic attributes of every interactive element in the Accessibility (A11y) Tree, not just its label.

* **Size & Positioning (`getBoundingClientRect`):** \* Extract `width`, `height`, `x`, and `y` coordinates for every interactable node.  
  * **Fitts's Law / "Fat Finger" Check:** Calculate the click target area. If area \< `44px by 44px` (standard mobile minimum), flag the element with a `size_penalty`.  
* **Computed Style Extraction:**  
  * Extract `background-color`, `color` (text color), `opacity`, and `z-index`.  
  * **WCAG Contrast Check:** Calculate the contrast ratio between text and background. If ratio \< `4.5:1`, apply a `contrast_penalty`.  
* **Semantic Color Mapping:**  
  * Compare the element's color against a predefined UX dictionary injected by the Persona Card (e.g., `Positive_Actions = ["#00FF00", "green", "blue"]`, `Destructive_Actions = ["#FF0000", "red", "grey"]`).  
  * **Deceptive Pattern Flag:** If the action label is "Delete" but the color maps to "Positive", flag a `semantic_mismatch_penalty`.

## **2\. Phase 2: Computer Vision Saliency Layer (The "Eye-Tracking" Profile)**

We cannot rely on CSS alone, as it doesn't account for complex layouts. The engine must predict where the human eye is naturally drawn based on pixel data.

* **Infrastructure:** A lightweight, fast, pre-trained Saliency Prediction Model running locally (e.g., using OpenCV, PyTorch, or an open-source model like DeepGaze/SalGAN).  
* **Execution:** Upon page load, the engine feeds the raw viewport screenshot into the Saliency Model.  
* **Output:** A grayscale heatmap image (same dimensions as the viewport) where pixel intensity (0 to 255\) represents the predicted human visual attention.  
  * `White/High Intensity (200-255)` \= Visually loud; immediate eye fixation.  
  * `Black/Low Intensity (0-50)` \= Visually quiet; completely ignored on first scan.

## **3\. Phase 3: The Hybrid Intersection (The "True Visibility Score")**

This is the core logic engine. We must overlay the programmatic bounding boxes (Phase 1\) onto the Saliency heatmap (Phase 2\) to calculate a final score for every element.

* **The Intersection Logic:**  
  * Take the bounding box `[x, y, width, height]` of a specific button.  
  * Crop that exact region out of the grayscale Saliency Heatmap.  
  * Calculate the **Average Pixel Intensity** of that cropped region. This represents the element's `Base Saliency Score` (0-100%).  
* **The Final Formula:** `True Visibility Score = (Base Saliency Score) - (Size Penalty) - (Contrast Penalty)`  
* **The "Blindspot" Threshold:** Engineers must define a `Visibility_Threshold` (e.g., 20%).  
  * If an element's `True Visibility Score` is \> 20%, it is passed to the LLM's context.  
  * **CRITICAL MECHANIC:** If the score is \< 20%, the Python engine **removes this element from the A11y tree JSON** before sending it to the LLM. The AI will literally not know the button exists, perfectly mimicking a user missing it\!

## **4\. Phase 4: Visual Cognitive Overload Detection**

The engine must detect when a screen is so visually noisy that the user panics or gets distracted.

* **Global Saliency Clutter:** Calculate the total percentage of the Saliency Heatmap that is "High Intensity" (\> 200). If more than 35% of the screen is screaming for attention, trigger a global `Visual_Overload_Spike` to the agent's Frustration Score.  
* **Distraction Mechanics:** If the Persona's Goal is to "Create an Invoice," but the element with the highest True Visibility Score on the page is a massive promotional banner, the engine forces the LLM to acknowledge the distraction in its internal monologue prompt.

---

## **5\. Data Schema Definition**

Every element extracted from the DOM must now match this expanded JSON structure before being evaluated:

JSON

```
{
  "element_id": "btn-save-draft",
  "a11y_role": "button",
  "a11y_name": "Save Draft",
  "physical_properties": {
    "width_px": 80,
    "height_px": 24,
    "contrast_ratio": 3.1, 
    "semantic_color": "grey"
  },
  "saliency_metrics": {
    "average_heatmap_intensity": 45, 
    "true_visibility_score_percentage": 12 
  },
  "flags": ["FAILED_WCAG_CONTRAST", "BELOW_FAT_FINGER_MINIMUM", "SEMANTIC_COLOR_MISMATCH"],
  "passed_blindspot_threshold": false 
}
```

*(In this example, because `passed_blindspot_threshold` is false, this JSON block is scrubbed before the LLM sees the page state).*

## **6\. Engineering Recommendations & Constraints**

* **Performance:** Running a deep-learning saliency model on every single click will introduce latency. Engineers should use highly optimized, quantized ONNX models for the Saliency network to keep inference times under 200ms per frame.  
* **Viewport Dependency:** Saliency models are highly sensitive to screen size. Ensure Playwright viewports are strictly defined to match the Persona (e.g., explicitly emulate an iPhone 14 Pro for Mobile personas, or a 1080p monitor for Desktop personas).

