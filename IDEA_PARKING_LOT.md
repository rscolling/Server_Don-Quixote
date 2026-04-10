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

### IDEA — BOB multilingual support (starting with Mexican Spanish)
**Added:** 2026-04-07
**Source:** Rob
**Status:** Parked

**The idea:**
Give BOB the ability to converse, write, and understand in multiple languages. First target: **Mexican Spanish**. BOB detects the user's language, responds in that language while preserving his sardonic personality, and translates work as needed across the agent teams. Personality preservation matters — Spanish BOB should still push back, still be encyclopedic and dry. Same BOB, different language.

**Why it might be worth doing:**
Opens BOB and ATG products to Spanish-speaking customers. Bear Creek Trail's Appalachian theme has natural cross-cultural appeal — Latin American players love nature/mountain themes. Demonstrates BOB's personality and orchestration aren't English-only. Future-proofs the customer chatbot widget for non-English visitors. Mexican Spanish first because it's the largest Spanish-speaking market in the Americas and matches ATG's regional, place-rooted sensibility.

**What it would need:**
Language detection on inbound (LLMs handle natively). Per-user language preference stored in BOB's memory silo. Personality file translation that preserves voice and idioms (the hard part — needs native-speaker workshop). Voice service updates: ElevenLabs Spanish voices, Deepgram Spanish STT. Brand voice translation so the debate arena CE agent produces Spanish copy that matches the English brand voice. App store listings in Spanish for Bear Creek Trail.

**Open questions:**
Should language preference be per-user or per-conversation? How does BOB handle code-switching ("BOB, ¿cuál es mi system status?")? Does the personality file need a parallel `00_personality.es.md`, or can the LLM translate at runtime? Which Mexican Spanish voice persona fits BOB best (dry, slightly older, intellectual — not customer service tone)? What's the next language after Spanish?

**BOB notes:**
Personality preservation across languages is the load-bearing challenge. Literal translation will lose the bite — "Yes Boss" → "Sí jefe" is grammatically correct but flat. Needs at least one native Mexican Spanish speaker to review the personality file and sample dialogues before shipping. Pilot as chat-only first (text in, text out) to validate personality survives translation. Voice comes after text proves the concept.

---

### IDEA — Payment System for BOB-as-a-Service
**Added:** 2026-04-10
**Source:** Rob
**Status:** Parked

**The idea:**
Research and implement a payment system that allows external customers to pay to use BOB and his agent team as a service. This turns the BOB infrastructure — orchestrator, debate arena, agent teams, voice interface — into a revenue-generating product. Customers would subscribe or pay per-use to access BOB's capabilities (AI assistant, multi-agent research, voice interaction, etc.) through a managed offering. Requires billing infrastructure, usage metering, access tiers, and a customer-facing onboarding flow.

**Why it might be worth doing:**
BOB is already a working multi-agent orchestrator with voice, memory, tool use, and team coordination. Monetizing it turns ongoing infrastructure costs into a business. Pairs naturally with the open-source documentation idea (free tier / self-host vs. managed paid tier). Recurring SaaS revenue is the highest-leverage business model for what's already built. Also validates whether the market values what BOB does enough to pay for it.

**What it would need:**
Payment processor integration (Stripe is the default choice — handles subscriptions, metering, invoicing, and has solid APIs). Usage metering system to track tokens consumed, API calls, voice minutes, agent invocations per customer. Access tier design (free trial, basic, pro, enterprise). Customer account management (ties into the existing multi-user/CF Zero Trust auth). Billing dashboard for customers. Legal: terms of service, privacy policy, refund policy. Cost modeling to ensure per-customer margins are positive after LLM API costs.

**Open questions:**
What's the pricing model — flat monthly subscription, usage-based (per token/per request), or hybrid? What access tiers make sense (e.g., text-only vs. text+voice vs. full agent team)? How do we isolate customer data/memory from each other and from ATG internal data? What's the minimum viable billing flow (Stripe Checkout + webhook, or full embedded billing portal)? Do we need SOC 2 or other compliance for enterprise customers? Should customers get their own BOB personality, or use a neutral default? What's the LLM cost ceiling per customer before we lose money?

**BOB notes:**
*(none yet)*

---

### IDEA — ATG Website Overhaul to Sell BOB Services
**Added:** 2026-04-10
**Source:** Rob
**Status:** Parked

**The idea:**
Redesign and expand appalachiantoysgames.com to serve as the commercial storefront for BOB and his agent team services. The current site showcases ATG products and games — the update would add dedicated pages for BOB-as-a-Service: what BOB does, live demo or interactive preview, pricing tiers, customer signup/onboarding flow, and a dashboard login for paying customers. The site becomes the sales funnel that converts visitors into BOB subscribers, while still maintaining the existing ATG brand and product pages.

**Why it might be worth doing:**
A product needs a storefront. The website already exists, is hosted on don-quixote, and has a working chat widget — it's the natural place to sell BOB. A well-designed services page with clear pricing and a live demo (the chat widget itself) is the lowest-friction way to convert interest into revenue. Pairs directly with the Payment System idea — Stripe handles the backend billing, the website handles the frontend sales experience.

**What it would need:**
New pages: services overview, pricing/tiers, customer signup, dashboard login. Integration with Stripe Checkout or embedded pricing table. Landing page copywriting that explains BOB's value to non-technical buyers. Live demo widget (already partially built — the existing chat widget). Testimonials or case studies once early customers exist. Mobile-responsive design. SEO basics for "AI assistant service" and related terms. Possibly a blog or content section for inbound marketing.

**Open questions:**
Should the BOB services section be a subdomain (bob.appalachiantoysgames.com) or integrated into the main site? How do we position BOB to non-technical customers — "AI assistant" vs "agent team" vs something simpler? Do we need a separate brand identity for BOB-as-a-product vs BOB-as-ATG's-internal-tool? What's the MVP landing page — could we ship a single page with pricing + Stripe link before building a full portal? How does the existing static site architecture handle dynamic elements like login and dashboards?

**BOB notes:**
*(none yet)*

---

### IDEA — Agent Skills & Tools Marketplace
**Added:** 2026-04-10
**Source:** Rob
**Status:** Parked

**The idea:**
Research and build a marketplace where AI agents can discover and purchase skills, tools, or MCP server integrations. Think of it as an app store for agents — ATG creates and sells packaged capabilities (e.g., a "financial analysis" skill, a "web scraping" tool, a "Google Workspace" MCP server bundle) that other people's agents can plug into. Buyers could be developers running their own agent frameworks, companies building on LangGraph/CrewAI/AutoGen, or individual Claude Code users looking for MCP servers. ATG becomes a vendor in the emerging agent tooling ecosystem, monetizing the skills and integrations already built for BOB.

**Why it might be worth doing:**
The agent ecosystem is exploding but tooling is fragmented — everyone is building their own integrations from scratch. A curated marketplace for production-tested agent capabilities fills a real gap. ATG has already built dozens of tools for BOB (web search, Gmail, calendar, ChromaDB, cost tracking, etc.) — packaging and selling these is incremental effort on top of existing work. MCP is becoming a standard protocol, which means interoperability is improving and the addressable market of compatible agents is growing. This could become a platform business with recurring revenue from tool subscriptions and transaction fees.

**What it would need:**
Market research on existing agent tool marketplaces and MCP registries (what exists, what's missing, who's buying). Packaging format for skills/tools — likely MCP server bundles with documentation, install scripts, and configuration templates. Storefront (could be a section of the ATG website or a standalone platform). Licensing model (one-time purchase, subscription, usage-based). Distribution mechanism (Docker images, npm/pip packages, or hosted MCP endpoints). Quality assurance and versioning for sold tools. Payment integration (Stripe, ties into the Payment System idea).

**Open questions:**
What's the competitive landscape — are there already agent tool marketplaces (Composio, LangChain Hub, MCP registries)? Is the market ready to pay for agent tools, or is everything still open-source and free? Should we sell self-hosted packages (customer runs the MCP server) or hosted endpoints (we run it, they connect)? What's the IP situation — can we sell MCP servers that wrap third-party APIs (Google, Slack, etc.)? What's the right unit of sale — individual tools, skill bundles, or full agent templates? How do we handle support and updates for sold tools?

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
