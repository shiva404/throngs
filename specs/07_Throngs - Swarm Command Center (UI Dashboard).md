# Swarm Command Center (UI Dashboard)

**Module:** The Output & Analytics Interface 

**Objective:** Provide a centralized web dashboard for Product Managers and UX Researchers to configure swarm tests, monitor real-time AI agents, and extract highly synthesized, visual, and actionable UX insights without needing to read raw code logs.

## **1\. Phase 1: The Executive Overview (The "At-a-Glance" View)**

This page is for leadership. It answers the fundamental question: *"Is the new feature ready to launch, or is it too confusing?"*

* **The KPI Banner:**  
  * **Global Discoverability Score (%):** Aggregate probability that users will find the feature within their `patience_budget`.  
  * **Average Frustration Index:** A dial (1-10) showing the average cognitive load and annoyance across all successful runs.  
  * **Average Time/Clicks to Discovery:** e.g., "4.2 clicks / 18 seconds."  
* **Persona Performance Matrix:** A table breaking down success rates by Persona.  
  * *Example:* The "DIY CFO" found the Cash Flow tool 95% of the time, but the "Cautious Baker" found it 12% of the time. This immediately highlights segment-specific UX flaws.

## **2\. Phase 2: The Heatmap Studio (The "Visual Evidence" View)**

This is for the UI/UX Designers. It visualizes the Saliency Maps, Geographic F-Patterns, and Motor Errors we engineered in the backend.

* **Interactive Screen Viewer:** Loads the staging environment screenshots.  
* **Data Overlay Toggles:** Users can toggle different data layers on and off over the screenshot:  
  * **Attention Heatmap:** Shows the computer vision saliency map (Where did the bots "look"?).  
  * **Click Scatter Plot:** Shows exactly where the Playwright clicks landed, visually highlighting "Fat Finger" mis-clicks around small buttons.  
  * **Frustration Hotspots:** Red pulsing circles over UI elements that caused the highest spikes in the `cognitive_load_multiplier` (e.g., jargon-heavy text or confusing menus).

## **3\. Phase 3: The Session Replay Trace (The "Deep Dive" View)**

When a bot fails catastrophically, engineers and researchers need to know *why*. This view acts like a DVR for the AI agent.

* **Timeline Scrubbing:** A step-by-step timeline of a single bot's session.  
* **The "Mind-Reader" Panel:** For each step, the dashboard displays:  
  1. **The Screenshot:** What the bot saw at that exact millisecond.  
  2. **The Internal Monologue:** The LLM's raw thought process (e.g., *"I am looking for 'Money In', but I only see 'General Ledger'. I am confused."*).  
  3. **The Action:** What it decided to click.  
  4. **The Metrics:** Current Frustration Score, Memory Strength applied, and any Chaos Monkey events (e.g., *"Interruption Triggered: Forgot last 3 clicks"*).

## **4\. Phase 4: The Automated UX Report Card (The "Actionable" View)**

Nobody wants to manually synthesize 500 test runs. The dashboard must use a secondary LLM to generate a plain-English summary.

* **Friction Point Ranking:** The LLM analyzes all the "Emotional Scars" and outputs the Top 3 UX blockers. (e.g., *"Blocker \#1: The 'Save' button contrast is too low, causing 40% of agents to miss it entirely."*)  
* **Recommended Fixes:** The LLM suggests actionable design changes based on the data. (e.g., *"Move the 'Export' button from the bottom-right dead zone to the top-left scanning path."*)

---

## **5\. Engineering Integration Constraints**

* **Tech Stack:** The dashboard should be built using a modern reactive framework (React, Vue, or Next.js) to handle the complex overlaying of images and coordinate data smoothly.  
* **Database Connections:** \* Connect to PostgreSQL (or similar) for the aggregate KPI data and UX Report Cards.  
  * Connect to cloud storage (AWS S3 or GCP Cloud Storage) to retrieve the raw Playwright screenshots and Heatmap image files for the Session Replays.

