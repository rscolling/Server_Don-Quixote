# ATG — Idea Parking Lot
### *Future projects, half-formed thoughts, and things worth revisiting*
### *BOB monitors this file. Rob owns it.*

---

> **How this works:** Drop ideas here in any state — rough, half-baked, or fully formed.
> Nothing in this file is a commitment. It's a holding pen.
> BOB reviews it during project planning and flags anything worth activating.
> Rob makes all final calls on what moves from here to `MISSION.md`.

---

## Active Parking Lot

---

### IDEA — Google Play Console integration
**Added:** 2026-03-18
**Source:** Rob
**Status:** Parked — needs build plan

**The idea:**
Connect BOB and the agent teams to the Google Play Console API for Bear Creek Trail. Agents should be able to query download counts, revenue, ratings, crash reports, and review sentiment without Rob manually checking the dashboard. BOB surfaces key metrics in the daily briefing.

**Why it might be worth doing:**
Revenue is the primary success metric. Agents can't optimize what they can't see. Marketing team needs real-time install and revenue data to adjust campaigns. Engineering team needs crash data and ANR rates to prioritize fixes.

**What it would need:**
Google Play Developer API credentials (service account + OAuth). Research team to identify which metrics endpoints to call. Engineering agent to write the integration. BOB webhook tool `get_play_metrics` added to orchestrator.

**Open questions:**
Which Google Play API endpoints expose revenue vs. installs vs. crashes? What are the rate limits? Does the service account need specific IAM permissions?

**BOB notes:**
Build plan needed before Android launch. Priority: HIGH — agents are blind to game performance without this.

---

### IDEA — iOS Apple App Store version (Bear Creek Trail)
**Added:** 2026-03-18
**Source:** Rob
**Status:** Parked — execute after Android launch

**The idea:**
After the Android version of Bear Creek Trail launches and is stable, execute the iOS port and App Store submission. Requires Apple Developer account, Xcode build pipeline, App Store Connect setup, and TestFlight beta before release.

**Why it might be worth doing:**
iOS users typically have higher LTV and spend more on in-app purchases. Expanding to iOS after a successful Android launch roughly doubles the addressable market at incremental cost.

**What it would need:**
Apple Developer account ($99/year). iOS build from the Unity project (likely a separate build target). App Store Connect setup and metadata. TestFlight beta period. App Store review process (typically 1-3 days). App Store Connect API for BOB metrics integration.

**Open questions:**
Is the current Unity project already configured for iOS build target? What changes are needed for iOS-specific UI (safe areas, notch, etc.)? What is Apple's current review timeline for games?

**BOB notes:**
Do not start until Android version is live and revenue-generating. Android launch validates the concept; iOS is the scale play. Build plan will be written when Android is live.

---

### IDEA — Customer Chatbot on ATG Website
**Added:** 2026-04-03
**Source:** Rob
**Status:** Parked

**The idea:**
Deploy a BOB-powered chatbot widget on appalachiantoysgames.com that handles customer questions — product info, order status, game support, brand story. BOB answers in ATG's voice using shared memory (brand voice collection in ChromaDB). Escalates to Rob when it can't resolve.

**Why it might be worth doing:**
24/7 customer support without Rob being online. Reduces friction for buyers. Can upsell products and answer Bear Creek Trail questions. Builds brand trust with an interactive experience that matches the Appalachian heritage tone.

**What it would need:**
Lightweight JS chat widget embedded in the static site. Backend endpoint on BOB (or a dedicated customer-facing agent) with guardrails — no internal data exposure. Rate limiting. Conversation logging for Rob to review.

**Open questions:**
Should this be BOB directly or a separate customer-facing agent with limited tools? What's the token cost model for public-facing chat? Does it need authentication or is anonymous OK?

**BOB notes:**
*(none yet)*

---

### IDEA — BOB Recreation Documentation (Open Source / Replicable)
**Added:** 2026-04-03
**Source:** Rob
**Status:** Parked

**The idea:**
Write comprehensive documentation that allows other people to stand up their own version of BOB — the full orchestrator stack (LangGraph agent, message bus, ChromaDB, scheduler, firewall, Gmail monitor, push notifications). Goal is a reproducible guide from zero to running BOB on any Ubuntu server.

**Why it might be worth doing:**
Community value and brand building for ATG. Could become an open-source project that attracts contributors. Demonstrates Rob's infrastructure publicly. Potential revenue if packaged as a product or consulting offering.

**What it would need:**
Step-by-step setup guide. Architecture diagrams. Environment variable reference. Docker Compose walkthrough. Troubleshooting guide. Decision on what to open-source vs keep private (API keys, business logic, personality).

**Open questions:**
Open-source under what license? How much of BOB's personality and ATG-specific config should be included vs abstracted? Is this a blog series, a GitHub repo, or both?

**BOB notes:**
*(none yet)*

---

### IDEA — Don Quixote Project Documentation Hub
**Added:** 2026-04-03
**Source:** Rob
**Status:** Parked

**The idea:**
Build thorough documentation for every project and service running on the don-quixote server — BOB orchestrator, message bus, debate arena, Syncthing bridge, Nginx/website, ChromaDB, Langfuse, scheduled jobs, Docker network topology, and all agent teams. Single source of truth for the entire infrastructure.

**Why it might be worth doing:**
Rob is the only person who knows how everything fits together. If something breaks at 2 AM, good docs mean faster recovery. Also critical for onboarding any future collaborators or agents that need to understand the full system. Reduces bus factor from 1 to something survivable.

**What it would need:**
Service inventory with ports, dependencies, and health check URLs. Network diagram. Restart/recovery procedures per service. Data flow diagrams showing how agents communicate. Runbook for common failure scenarios.

**Open questions:**
Where should docs live — in the Server Don Quixote repo, a separate docs site, or both? Should BOB auto-generate parts of it from live infrastructure state?

**BOB notes:**
*(none yet)*

---

### IDEA — BOB Smartphone Photo Intake
**Added:** 2026-04-03
**Source:** Rob
**Status:** Parked

**The idea:**
Give BOB the ability to receive and process photos taken on Rob's smartphone. Use cases: snap a whiteboard sketch and BOB extracts action items, photograph a product prototype and BOB logs it to the project, capture a handwritten note and BOB OCRs it into a task. Photos sent via a simple mechanism (ntfy attachment, dedicated upload endpoint, or email attachment to ATG Gmail).

**Why it might be worth doing:**
Rob works away from his desk. Ideas and decisions happen on the shop floor, in the car, at the store. A photo-to-BOB pipeline means nothing gets lost. Multimodal input makes BOB dramatically more useful as a daily assistant.

**What it would need:**
Photo upload endpoint or intake channel (ntfy supports file attachments, Gmail already monitored). Vision model integration (Claude supports image input). OCR/extraction pipeline. Storage for original images (Syncthing bridge or server filesystem). Metadata tagging (timestamp, source, project association).

**Open questions:**
Best intake method — dedicated upload URL, ntfy attachment, or Gmail attachment? Should BOB auto-classify photos (whiteboard, product, receipt, document) or ask Rob? What vision model — Claude native or a dedicated OCR service?

**BOB notes:**
*(none yet)*

---

## Idea Template

Copy this block for each new idea:

```
### IDEA — [Short title]
**Added:** YYYY-MM-DD
**Source:** Rob / BOB suggestion / Research team / etc.
**Status:** Parked

**The idea:**
[One paragraph. What is it?]

**Why it might be worth doing:**
[Revenue potential, strategic fit, brand alignment, etc.]

**What it would need:**
[Rough sense of effort — team, time, dependencies]

**Open questions:**
[What do we not know yet that matters?]

**BOB notes:**
[BOB appends observations here when relevant research or signals emerge]
```

---

## Archive — Ideas That Were Activated

*When an idea moves to `MISSION.md` as an active project, move the entry here.*

| Idea | Activated | Became |
|---|---|---|
| Mobile phone video game (Bear Creek Trail) | 2026-03-18 | PROJECT-01 in MISSION.md |

---

*This file lives at `/opt/atg-agents/bob-context/IDEA_PARKING_LOT.md`*
*BOB reads this during project planning sessions.*
*Last updated: 2026-03-18*
