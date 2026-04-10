# BOB Roadmap

A public roadmap is a contract with the community. This document is *not* a guarantee — it's a statement of current priorities. Things shift. When they do, this file gets updated.

The roadmap is organized into three tiers based on the competitive analysis in `BOB-content/11_research_comparison.md`. Tier 1 is "ship before the open source launch." Tier 2 is "earn legitimacy in the first 60 days." Tier 3 is "differentiation in the next 60-90 days."

---

## Where BOB Is Today

**Deployed and working** on a home Ubuntu server (the prototype):

- BOB Orchestrator (LangGraph + Claude Opus 4.6, 35 native tools)
- BOB Voice (multi-user via Cloudflare Zero Trust, Deepgram + ElevenLabs)
- Debate Arena (4 specialist agents: PM, RA, CE, QA)
- Message Bus (FastAPI + SQLite)
- ChromaDB shared memory with proposal/review workflow
- Production layer: firewall, circuit breakers, retry, offline queue, recovery monitor, rate limiting, audit log, structured JSON logging
- Multi-user authentication with per-user memory silos
- Public website chat widget
- ntfy push notifications
- Uptime Kuma monitoring
- ElevenLabs usage tracking
- Daily briefings

**Built but not yet pushed to the server** (ready when network is back):

- MCP native support — both client (consume external MCP tools) and server (expose BOB to other MCP clients like Claude Desktop, Cursor, goose)
- 10-minute quickstart with two example specialist agents

**Total: 35 native tools, ~3,500 lines of Python across 19 modules.**

---

## Tier 1 — Ship Before the Open Source Launch

These are the existential items. If they're not done before going public, BOB will be dismissed as "an Anthropic wrapper" or worse.

### Model-agnostic adapter — DONE (locally), pending deploy

BOB now ships with a model-agnostic adapter (`app/llm.py`) supporting three providers:

- **Anthropic Claude** — `claude-opus-4-6` default. Best tool-calling reliability. Reference implementation.
- **OpenAI GPT** — `gpt-4o` default. Also supports any OpenAI-compatible endpoint (vLLM, LiteLLM proxy, LM Studio, OpenRouter) via `BOB_LLM_BASE_URL`.
- **Ollama (local models)** — `qwen2.5:14b` default. Supports any Ollama-compatible model with tool calling (Qwen, Llama, DeepSeek, Mistral). Free after hardware, total privacy, air-gapped friendly.

Provider switching is a single env var change (`BOB_LLM_PROVIDER=anthropic|openai|ollama`) with no code changes. The `/llm/status` endpoint reports which provider is active and which adapters are installed. Full documentation in `LLM_PROVIDERS.md`.

**Effort:** ~1 day actual (smaller than estimated because LangChain's `BaseChatModel` interface and `bind_tools()` standard handles most of the heavy lifting). **Status:** Code complete. Awaiting deploy.

### MCP native support — DONE (locally), pending deploy

BOB speaks MCP both as a client (consumes tools from external MCP servers) and as a server (exposes his capabilities to other AI clients). All code is written, syntax-checked, and ready to push when the network is back. See `MCP_INTEGRATION.md` and `MCP_DEPLOYMENT_NOTES.md`.

**Effort:** ~3 days actual. **Status:** Code complete. Awaiting deploy.

### 10-minute quickstart — IN PROGRESS

A `docker compose up` experience that brings up BOB plus two example specialist agents (researcher + coder) so first-time users see the orchestration pattern in 10 minutes. See `quickstart/` once it's complete.

**Effort:** ~1 day. **Status:** Building now.

### Public roadmap, LICENSE, CONTRIBUTING, SECURITY — DONE

You're reading the roadmap. The other three live alongside this file.

**Effort:** ~half a day. **Status:** Complete.

### Repo cleanup and README — NOT STARTED

The current `README.md` (if there is one in the orchestrator dir) is internal. The launch needs a proper README with the narrative, the quickstart link, the architecture diagram, and the credits.

**Effort:** ~1 day. **Status:** Not started.

---

## Tier 2 — Earn Legitimacy (Days 30-60 After Launch)

These bring BOB to feature parity with the leaders.

### MCP server expansion — DONE (locally), pending deploy

BOB's MCP server now exposes 12 tools (was 6) and 2 resources, covering:

- Delegation to the debate arena
- Memory recall + proposal workflow
- Memory export
- System health + server resources
- Daily briefing generation
- Paused task inspection
- Scheduler operations (list, add, trigger)
- Email triage (read-only) + Gmail status
- ElevenLabs voice usage telemetry

**Effort:** ~30 minutes actual. **Status:** Code complete. Awaiting deploy.

### A2A protocol support

The Agent-to-Agent protocol (Google's) is becoming a standard alongside MCP. BOB should speak A2A for orchestrator-to-orchestrator calls, especially for the federation case where two BOB instances share work.

**Effort:** ~3-4 days.

### Eval harness — DONE (locally), pending deploy

10-task benchmark protocol from `BOB-content/10_why_and_how_to_measure.md` Part 5 is built as `eval/runner.py`. Run with `python -m eval.runner --url http://localhost:8100`. Produces a 100-point scorecard with per-task notes, latency, and pass/fail. Honest scoring — designed to compare BOB to other frameworks on the same protocol, not to make BOB look good.

**Effort:** ~1 hour actual. **Status:** Code complete. Awaiting deploy + first public benchmark run.

### Loop detection module — DONE (locally), pending deploy

Three deterministic detectors in `app/loop_detector.py`, wired into the firewall gate as a new `DENY_LOOP` decision:

1. **Repeated tool call** — same tool + same args N times in a window
2. **Tool sequence cycle** — A→B→A→B repeating subsequence detector
3. **Token burn budget** — cumulative tokens per run hard cap

When a loop trips, BOB returns a structured error to the LLM telling it to stop and either change approach or escalate to Rob. Per Cogent's "you cannot ask an agent if it is in a loop, you must prove it mathematically."

**Effort:** ~30 minutes actual. **Status:** Code complete. Awaiting deploy.

### Cost tracker and budget guards — DONE (locally), pending deploy

`app/cost_tracker.py` records every LLM call to a SQLite DB with provider, model, user, tool, input/output tokens, and estimated USD cost (using an approximate per-million-tokens pricing table for Anthropic, OpenAI, and Ollama). The `/chat` endpoint now passes through a budget guard that aborts the request with HTTP 429 if any of three thresholds are exceeded:

- `DAILY_BUDGET_USD_TOTAL` (default $10/day for the whole instance)
- `DAILY_BUDGET_USD_PER_USER` (default $2/day per user, Rob bypasses)
- `MONTHLY_BUDGET_USD_TOTAL` (default $200/month)

Endpoints: `/cost/status` (summary + 7-day breakdown), `/cost/check/{user}` (per-user check). Cost summary now appears in `/health`. Directly addresses the SECURITY.md known limitation about cost-based DoS.

**Effort:** ~1 hour actual. **Status:** Code complete. Awaiting deploy.

### Read-only web dashboard

BOB has lots of API endpoints (`/health`, `/status`, `/threads`, `/firewall/audit`, `/proposals/pending`, `/recovery/paused`, `/mcp/status`, `/llm/status`, `/cost/status`, etc.). A simple web UI that displays them as a single dashboard would be a huge usability win. Read-only is fine for v1.

**Effort:** ~5-7 days. **Status:** Not started.

### Memory export and import — DONE (locally), pending deploy

`memory.py` now ships `export_all()` / `export_to_file()` / `import_all()` / `import_from_file()`. Output format is portable (text + metadata, no embeddings) so it works across vector DB implementations. Two import modes: `merge` (upsert) and `replace` (wipe-then-import).

Endpoints: `GET /memory/export` (returns the full dump as JSON), `POST /memory/import` (accepts a previous export with `merge` or `replace` mode). Also exposed as the `export_bob_memory` MCP tool so federated BOBs can pull each other's memory.

**Effort:** ~30 minutes actual. **Status:** Code complete. Awaiting deploy.

---

## Tier 3 — Differentiation (Days 60-90)

These put BOB ahead of the leaders, not just at parity.

### K8s helm chart — DONE (alpha), pending real cluster test

Alpha helm chart in `helm/` deploys BOB orchestrator + ChromaDB with a PVC for persistent SQLite data, MCP config ConfigMap, optional Ingress, ServiceAccount. Templates render cleanly via `helm lint`. Documented caveats (single-replica only due to APScheduler SQLite jobstore, runs as root, no HPA/PDB/NetworkPolicy yet) in `helm/README.md`. Future maintainer can run it through a real cluster.

**Effort:** ~1 hour actual. **Status:** Alpha. Awaiting real cluster validation.

### Voice SDK extracted — DONE (skeleton), pending PyPI publish

`bob_voice_sdk/` package extracted from `bob-voice/` with three reusable modules:
- `STTClient` — speech-to-text (Deepgram backend, provider-agnostic interface)
- `TTSClient` — text-to-speech with LRU caching (ElevenLabs backend)
- `SentenceChunker` — streaming sentence-boundary chunker for low-latency TTS

Lazy imports so the SDK doesn't require Deepgram or ElevenLabs unless you use them. Documented in `bob_voice_sdk/README.md` with full usage example. Lives inside `bob-voice/` for now — PyPI publish is mechanical from here.

**Effort:** ~45 minutes actual. **Status:** Code complete. Awaiting PyPI publish + version stabilization.

### Personality config layer — DONE (deployed)

`app/personality.py` loads one of N personality variants from `bob_context/personalities/` based on the `BOB_PERSONALITY` env var. Three default variants ship: `sardonic` (canonical BOB), `neutral` (no personality, just facts), `terse` (sardonic but minimal length). Operators can drop in custom variants. `/personality/status` endpoint reports active + available variants.

**Effort:** ~30 minutes actual. **Status:** Deployed and live on don-quixote.

### Auth abstraction layer — DONE (deployed)

`bob-voice/auth.py` refactored into a backend-agnostic interface with four backends:
- `cloudflare` (default, current behavior — CF Access JWT)
- `oidc` (generic OIDC bearer token via JWKS — Auth0, Okta, Keycloak, Google, etc.)
- `shared_secret` (simple bearer token from env var, with optional multi-user JSON map)
- `none` (everyone is GUEST — dev / public deployments)

Same `identify_user(headers)` interface so `app.py` doesn't change. Backend chosen by `BOB_AUTH_BACKEND` env var. New `/auth/status` endpoint reports active backend and which backends are configured.

**Effort:** ~1 hour actual. **Status:** Deployed and live on the voice service.

### Replay tool — DONE (deployed)

`app/replay.py` reads the audit log and re-runs past tool calls deterministically. The audit log was extended to capture sanitized params (secrets redacted, long values truncated) so replays have the inputs they need. Three modes:

- **Find by audit ID** — look up a single entry and replay it
- **Replay recent** — replay the last N entries, optionally filtered by tool
- **Dry run** — show what WOULD replay without executing

Write tools (`create_task`, `send_message`, `notify_rob`, etc.) are skipped by default to avoid duplicate side effects — pass `include_writes=true` to override. Verified end-to-end: BOB called `check_system_health`, the audit log captured it with params, the replay tool found it by ID, re-ran it, and returned the new result in 1.6 seconds.

**Effort:** ~1 hour actual. **Status:** Deployed and verified live on don-quixote.

### A2A protocol adapter — DONE (deployed)

`app/a2a.py` adds Google's Agent-to-Agent protocol support. BOB exposes himself at `/a2a/.well-known/agent.json` (discovery), `/a2a/message` (incoming task), `/a2a/task/{id}` (status check). Supports four skills: `delegate`, `query_memory`, `system_health`, `generate_briefing`. Also has client-side functions to call peer A2A agents at configured URLs (`A2A_PEERS` env var). Minimal subset of the spec — enough for federation, not a full conformant implementation. The roadmap explicitly noted "minimal subset" was the right scope.

**Effort:** ~1 hour actual. **Status:** Deployed and live. Agent card serving from BOB on don-quixote.

### Engineering team (cloud)

Bring the planned 12-agent Engineering team online. This requires the K8s helm chart (Tier 3 above, now alpha) and is the first real test of the AWS migration. Specs for all 28 planned agents (Engineering 12 + Marketing 8 + Research 8) are designed by the debate arena per `AGENT_BUILDOUT_PLAN.md`.

**Effort:** ~10-15 days. **Status:** Not started — depends on AWS account setup and the helm chart graduating from alpha.

---

## Beyond 90 Days — The Big Vision

These are the items in the parking lot. Not committed, but on the horizon.

### Marketing team (cloud)

8 specialized agents handling brand, social, content strategy, ASO, community, influencer outreach, performance marketing.

### Research team (cloud)

8 specialized agents handling market analysis, competitor intelligence, player behavior, tech trends, patent/IP, academic literature, survey design.

### Smartphone photo intake

Snap a photo of a whiteboard, BOB extracts action items and creates tasks. Multimodal Claude already supports this — needs the upload pipeline.

### Customer chatbot (full version)

The current website chat widget is a basic guest mode. A richer version with history, login persistence, image uploads, and product-specific knowledge would turn it into a real customer support tool.

### Google Play Console integration

Pull download counts, revenue, ratings, crash reports, and review sentiment automatically. Required for the Bear Creek Trail launch and any future game shipments.

### iOS App Store version (Bear Creek Trail)

Not BOB scope, but BOB would manage the deployment pipeline.

### Hosted multi-tenant BOB-as-a-service

Currently BOB is single-user self-hosted. A hosted multi-tenant version would lower the barrier to entry. This is the most controversial item on the roadmap because it conflicts with the self-hosted-first philosophy. Probably last.

---

## Things Explicitly NOT on the Roadmap

These have been considered and rejected. If you want them, fork the repo.

- **Removing the personality.** It's load-bearing. See `CONTRIBUTING.md`.
- **Visual workflow builder.** Dify, n8n, Sim, Flowise have eaten that segment. BOB stays code-first.
- **Replacing LangGraph.** The state graph model is intentional and works.
- **Telemetry that phones home.** Self-hosted means self-hosted.
- **Switching to a more permissive license.** MIT is the right license for this kind of project.
- **Switching to a more restrictive license.** Same answer.
- **Fully autonomous mode.** BOB recommends, Rob decides. The architecture is human-in-the-loop on purpose. Autonomy increases blast radius and the cost of bad calls is too high.
- **Multi-tenant SaaS as the default deployment mode.** See above re: self-hosted philosophy.
- **Claude Code or Cursor integration as a *replacement* for BOB.** They're complementary tools. BOB might call them via MCP. They are not BOB's replacement.

---

## How This Roadmap Gets Updated

When a roadmap item ships, its status changes from "Not started" or "In progress" to "Done" with a date and a brief note. Items that get reprioritized or cut entirely are moved to a `CHANGELOG.md` so the history is preserved.

If you want to lobby for something to move up or down the priority list, open a discussion (not an issue) and make the case. The maintainer (Rob) will listen but the decision is his.

---

## Honest Caveat

This roadmap is one person's plan. That person has a day job (running a one-person game studio shipping Bear Creek Trail) and BOB is a side project. Timelines will slip. Priorities will shift. Some Tier 2 items may end up in Tier 3 because something more urgent showed up.

The constants are:
- Production-grade for one person
- Self-hosted by default
- MIT license
- Personality stays load-bearing
- Honest about limits

Everything else is negotiable.

---

*Last updated: shipped with the open source launch.*
