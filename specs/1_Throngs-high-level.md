# **Synthetic Swarm**

**Version:** 1.0 

**Product:** Internal AI-Driven UX Simulation Engine (Tailored for QuickBooks Ecosystem) 

**Objective:** Build an automated testing pipeline that simulates human behavior, cognitive load, and emotional frustration to evaluate the discoverability and UX of new features prior to launch.

## **1\. Product Vision & Scope**

We are moving beyond functional testing (e.g., Selenium checking if a button works) to **Cognitive Testing**. The "Synthetic Swarm" will deploy multiple LLM-driven autonomous agents ("Personas") into staging environments. These agents will use vision and structural DOM analysis to attempt specific goals, experiencing human-like frustration, cognitive overload, and learning curves, ultimately generating actionable UX feedback and heatmaps.

---

## **2\. Core System Architecture**

The system relies on a Python-based orchestration layer connecting a headless browser grid, a multimodal Large Language Model (LLM), and a localized memory database.

* **Execution Environment:** Python 3.12+  
* **Browser Automation:** Playwright (Async) for handling dynamic JavaScript, pop-ups, and extracting the Accessibility (A11y) Tree.  
* **Cognitive Brain:** Multimodal LLM (Gemini 1.5 Pro or GPT-4o) capable of structured JSON output and image \+ text processing.  
* **Memory Store:** Vector Database (e.g., ChromaDB, Pinecone) or structured JSON document store for Agent Episodic Memory.  
* **Concurrency:** Asyncio or Celery workers to run 10-50 headless browser sessions simultaneously.

---

## **3\. Component Requirements**

### **Component 1: The Perception Layer (Eyes & Hands)**

The engine must "see" the interface as a human would, not just as raw code.

* **Visual Ingestion:** Playwright must capture a full viewport screenshot at every step.  
* **Structural Ingestion:** Playwright must extract the Accessibility (A11y) Tree. This tree maps interactive elements (buttons, links, inputs) to specific `element_ids` and `(X,Y)` coordinates.  
* **Execution:** The system must parse the LLM's chosen `element_id` and execute a physical Playwright action (`click`, `type`, `scroll`, `hover`).

### **Component 2: The Persona Engine (The DNA Cards)**

Engineers must build a configuration system to inject user archetypes into the LLM context. Personas are defined by a JSON structure.

* **Required Persona Parameters:**  
  * `domain_literacy` (1-10): Determines understanding of accounting jargon.  
  * `tech_literacy` (1-10): Determines navigation speed and usage of UI patterns (e.g., hidden menus).  
  * `patience_budget` (Integer): The maximum number of actions/clicks allowed before the agent "rage quits."  
  * `trigger_words` (Array): Jargon that induces anxiety (e.g., `["reconcile", "general ledger"]`).  
  * `friendly_words` (Array): Words the persona actively searches for (e.g., `["money in", "unpaid bills"]`).

### **Component 3: The Frustration & Cognitive Overload Engine**

The system must calculate a dynamic "Frustration Score" locally before asking the LLM for its next move.

* **Visual Clutter Calculation:** Python script counts interactable nodes in the current viewport via the A11y tree. If `nodes > 50`, apply a `cognitive_load_multiplier`.  
* **Jargon Density Calculation:** Python script scrapes visible text. If text intersects with the Persona's `trigger_words` array, apply a `jargon_penalty`.  
* **Dead-End Loop Detection:** The engine tracks the last 5 URLs/States. If the agent visits the same state 3 times without achieving the goal, apply a `loop_penalty`.  
* **The Flight Response:** If the `Frustration Score` exceeds the Persona's `patience_budget`, the agent must forcibly end the task or click a "Home/Escape" button, logging a Task Failure.

### **Component 4: Agent Memory System (The Learning Curve)**

To simulate returning users and "moved cheese" friction, agents must possess episodic memory.

* **State Saving:** Upon task success or failure, the system writes a memory object to the database containing the `Goal`, the `Final State/URL`, and the `Successful Path`.  
* **State Retrieval:** At the start of a new simulation, the engine queries the DB for past attempts at the same `Goal` and injects this into the LLM's system prompt (e.g., *"You remember finding 'Invoices' under the 'Sales' tab yesterday."*).

### **Component 5: Analytics & Output (The Translator)**

Raw logs are useless to product managers. The system must synthesize the data automatically.

* **Coordinate Logging:** Every action must log the `(X, Y)` coordinates, the timestamp, and the `frustration_multiplier` at the moment of the click.  
* **Heatmap Generation:** Use Python (OpenCV/Pillow) to overlay click data onto the staging screenshots. Green dots \= low frustration; Red clusters \= high frustration/rage clicks.  
* **UX Report Card:** A secondary LLM call triggers after a swarm completes. It ingests all JSON logs and outputs a markdown summary detailing:  
  * *Discoverability Rate (%)*  
  * *Average Time/Clicks to Discovery*  
  * *Primary Friction Points (e.g., "70% of Low-Tech users experienced Cognitive Overload on the Dashboard").*

---

## **4\. The Execution Loop (Step-by-Step Flow)**

For every single action an agent takes, the system must execute this exact loop:

1. **Initialize:** Load Persona DNA, load Goal, load Past Memory.  
2. **Perceive:** Playwright navigates to URL, waits for network idle, takes Screenshot, extracts A11y Tree.  
3. **Calculate Load:** Python evaluates Visual Clutter and Jargon Density \-\> Updates `current_frustration`.  
4. **Prompt LLM:** Send Screenshot \+ A11y Tree JSON \+ Persona DNA \+ `current_frustration` to LLM.  
5. **LLM Reasoning:** LLM outputs strictly formatted JSON containing its internal thought process and chosen `element_id`.  
6. **Action:** Playwright executes interaction on `element_id`.  
7. **Evaluate:** Did action achieve goal? If yes \-\> Log Success & Save Memory. If no \-\> Loop back to Step 2\. (If `current_frustration` \> `patience_budget` \-\> Log Failure & Save Memory).

---

## **5\. Data Schemas**

**LLM Required Output Format (Enforced via JSON Schema):**

JSON

```
{
  "internal_monologue": "String. The persona's thoughts based on their tech/domain literacy.",
  "perceived_clutter_rating": "Integer 1-10",
  "emotional_state": "String. e.g., 'Anxious', 'Confident', 'Confused'.",
  "action_type": "Enum: ['click', 'type', 'scroll', 'give_up']",
  "target_element_id": "String. Must match an ID from the A11y tree.",
  "input_text": "String. Optional, only if action_type is 'type'."
}
```

---

## **6\. Technical Considerations & Constraints**

* **LLM Rate Limits:** Running 50 concurrent agents sending screenshots will hit token/rate limits rapidly. Implement exponential backoff and request queuing for API calls.  
* **Dynamic Selectors:** Do *not* rely on CSS class names (e.g., `.bg-blue-500`). The engine must rely *only* on semantic HTML/A11y labels (e.g., `aria-label="Create Invoice"`) to prevent the bot from breaking when styling changes.  
* **Authentication:** The system needs a dedicated set of test user accounts in the staging environment to bypass captchas and 2FA.

