# Agent Tooling Audit — Business Operations Team

**Created:** 2026-04-08
**Owner:** Rob (with BOB as research/tracking partner)
**Status:** in progress — use this file as the master TODO for closing tooling gaps

The debate arena is now positioned as the **Business Operations team**, not a marketing-only crew. With FE and BE engineers added (2026-04-08), every agent should be re-examined for whether it has the *actual capability* to do real work in its domain — or whether it's still stuck producing JSON deliverables that a human has to translate into action.

This file is the audit. Each agent gets a section. The format is the same:
- **Current capability** — what the agent can actually do today
- **Gaps** — what's missing for it to do real work
- **Tools / plugins / libraries needed** — concrete additions
- **Blast radius / safety notes** — what could go wrong if we hand it the keys
- **Priority** — high / medium / low

---

## PM (Project Manager) — port 8101
**Container:** `atg-pm`  ·  **Code:** `~/debate-arena/agents/pm/`

**Current capability**
- Classifies incoming tasks via keyword matching (`debate.py:get_tier_for_task`)
- Routes tasks to primary agent + critics based on `PRIMARY_AGENT_MAP`
- Manages debate rounds, escalation, and final acceptance
- Talks to message bus only

**Gaps**
- ~~Classification is keyword-based and brittle.~~ ✅ **PARTIAL CLOSED 2026-04-08:** Added an LLM-fallback classifier. When the keyword matcher returns `simple` on a non-trivial task (>50 chars), PM calls Claude Haiku with the task text and the list of valid task types. If the LLM picks a real type, PM uses it. The classifier source is now in the log line: `type=research (llm_fallback)` vs `type=visual (keyword)`. Verified working: a keyword-free competitive-research task ("Tell me which of our toys get the most positive feedback...") was correctly upgraded from `simple` to `research`.
- ~~Routes silently to non-existent agents.~~ ✅ **CLOSED 2026-04-08:** PM now filters the *primary agent* against the live agent registry, not just the critics. If the chosen primary isn't running (e.g. GA), PM logs a WARNING and falls back to RA. Verified by re-running the previously-broken Task #18 case.
- ~~Keyword priority bug: `frontend_dev` and `backend_dev` were inserted before `infrastructure` in the dict, so words like `endpoint`/`service`/`api` won on tie matches even when the task was clearly infrastructure work.~~ ✅ **CLOSED 2026-04-08:** Reordered `_TASK_KEYWORDS` so `infrastructure` comes first. Also added new infra synonyms: `compose`, `cloudflared`, `ingress`, `socket`, `tunnel`, `audit`, `capacity check`. Regression-tested with three representative tasks: a FastAPI-endpoint task still routes to BE, an HTML-landing-page task still routes to FE, and a "deploy a new agent container with docker compose" task now routes to SE (it would have gone to BE before).
- No memory of prior task outcomes — can't learn that certain task shapes go better through specific routes.
- No human-in-the-loop confirmation for routing decisions.

**Needed (remaining)**
- ~~LLM-based fallback classification~~ ✅ done — Claude Haiku via `_classify_with_llm()` in `pm/orchestrator.py`. Triggers only when keyword match is `simple` and task text is non-trivial.
- ~~Filter primary agent against live registry~~ ✅ done — same patch.
- Optional: small ChromaDB collection of `task_routing_history` so PM can search "tasks similar to this one were routed to X and went well/poorly."
- A `--dry-run` mode in the bus API so a human can preview routing without executing.
- Cost monitoring on the LLM classifier — Haiku is cheap but not free; should report tokens used per classification in PM logs.

**Blast radius:** medium. PM is the central nervous system; bad routing wastes time and cost but doesn't break anything.

**Priority:** medium

---

## RA (Research Agent) — port 8102
**Container:** `atg-researcher`  ·  **Code:** `~/debate-arena/agents/researcher/`

**Current capability**
- Produces written research analyses via Claude
- Writes JSON deliverables to `/agent-share/workspace/research/`
- No actual web access — research is from Claude's training data

**Gaps**
- ~~**Cannot actually research the live web.**~~ ✅ **CLOSED 2026-04-08:** RA now has `search_web` via DuckDuckGo (`ddgs` library, same as BOB). Iterative tool-use loop, up to 6 rounds, multiple searches per round. Verified working: 22 calls / 205 results in a competitor pricing smoke test that returned 6 real US wooden toy makers with current prices and source URLs.
- ~~No image / PDF parsing — can't read the uploaded materials Rob shares.~~ ✅ **CLOSED 2026-04-08:** RA now reads `task.file_paths` and loads images (jpg/png/gif/webp), PDFs, and text/CSV/JSON/YAML files as Claude content blocks. Images via vision, PDFs via Claude native document support, text inlined fenced. Path-safety: only files under `/agent-share/`, max 30 MB per file, 60 MB total. Verified working on a 327 KB game screenshot — RA correctly identified the game type, read the HUD numbers, spotted the AzRecorder watermark, and inferred the business model.
- ~~No access to ChromaDB to look up prior research before duplicating it.~~ ✅ **CLOSED 2026-04-08:** RA now has a `query_memory(collection, query, n_results)` Claude tool wired into its tool-use loop alongside `search_web` and `fetch_url`. Backed by a new `buslib/memory.py` `ReadOnlyMemory` class with per-agent collection allowlists. RA's allowlist: `research`, `decisions`, `project_context`. System prompt was updated to tell RA to call `query_memory` FIRST on non-trivial tasks before burning a web search. Verified: a 'Bear Creek Trail launch' research task triggered 4 `query_memory` calls across `project_context`, `decisions`, and `research` collections; allowlist enforcement also verified by attempting to query `brand_voice` and getting back the expected error envelope.
- ~~No URL fetcher for full article reading~~ ✅ **CLOSED 2026-04-08:** Added `fetch_url(url)` tool to RA using `trafilatura` for clean main-content extraction (strips nav/ads/boilerplate). Wired into the same Claude tool-use loop as `search_web` so RA can iterate: search → spot a high-signal result → fetch the full article → quote specifics. 50 KB cap per fetch, 20 s HTTP timeout, follows redirects, custom User-Agent. Verified end-to-end with an Anthropic-pricing research task: RA searched, fetched two URLs (`https://platform.claude.com/docs/en/about-claude/pricing` and `https://claude.com/pricing`), and reported real per-token pricing with both URLs as cited sources.

**Needed (remaining)**
- ~~Web search tool~~ ✅ done — `ddgs` (DuckDuckGo), not Tavily. Free, no key.
- ~~Image / PDF parsing~~ ✅ done — native Claude vision + document blocks.
- **ChromaDB read access** to the `research` collection so RA can find prior work and not duplicate it.
- ~~URL fetcher~~ ✅ done via `fetch_url` tool + `trafilatura`. See Gaps above.
- Optional: **Google Scholar / arXiv** wrapper for academic research tasks.

**Blast radius:** low. Read-only tools.

**Priority:** **HIGH** — RA is the most-asked-for agent and currently the least functional.

---

## CE (Content Editor) — port 8103
**Container:** `atg-copy-editor`  ·  **Code:** `~/debate-arena/agents/copy-editor/`

**Current capability**
- Writes content drafts via Claude
- Already produces solid long-form work (see Task #12 — 2184-word tech consulting page draft)
- JSON deliverables to `/agent-share/workspace/content/`

**Gaps**
- Output is JSON, not publishable HTML/Markdown. Every CE deliverable currently needs a human or FE to render it.
- ~~No access to ChromaDB `brand_voice` collection — has to be fed brand guidelines via the briefing each time.~~ ✅ **CLOSED 2026-04-08:** CE now auto-prepends a `[memory snapshot]` block from `brand_voice` + `decisions` + `project_context` to every `execute_writing` and `critique_output` call. Previous flow (BOB injecting brand guidelines into the task brief) still works — the new flow is additive and lets CE pull current versions even when the brief is stale.
- No spelling / grammar tooling — Claude is good at grammar but not perfect, and a `languagetool` pass would catch what slips through.
- No image generation handoff — when CE wants "a hero image showing X" it has no way to actually request one from a graphic agent.

**Needed**
- Output mode flag in the brief: `output_format: json | markdown | html`. CE should be able to render directly to publishable formats.
- ChromaDB read access to `brand_voice` (and write access for proposed updates as a `brand_voice_proposal/` collection).
- Optional: `languagetool` server in a sidecar container.
- Handoff capability to GA (graphic-artist) once GA is operational.

**Blast radius:** low. Content goes to proposals dirs anyway.

**Priority:** medium — works fine today, just inefficient.

---

## QA (Quality / Adversarial Critic) — port 8104
**Container:** `atg-qa`  ·  **Code:** `~/debate-arena/agents/qa/`

**Current capability**
- Critiques other agents' deliverables via Claude
- Returns approve/revise/reject verdicts
- Pure LLM — no code execution, no testing

**Gaps**
- ~~**For code deliverables (FE/BE work):** QA can read the code but can't run it.~~ ✅ **REASSIGNED 2026-04-08:** Code review moved to **RE** (Reliability Engineer), which is the engineering-side critic. QA stays purely brand-side per its existing DOMAIN GUARD. The new  service handles the static analysis — see RE section below.
- For content: can't verify links resolve, images exist, or facts are accurate.
- No access to a content-side sandboxed runtime (link checker, image existence checker, fact verifier).

**Needed (revised)**
- ~~Sandboxed code execution for QA~~ ✅ **MOVED TO RE 2026-04-08** — see code-sandbox service. QA's domain stays brand/content-only.
- ~~Direct ChromaDB read access to brand_voice~~ ✅ **CLOSED 2026-04-08:** QA now auto-prepends a `[memory snapshot]` block with `brand_voice` + `decisions` to every `adversarial_review` call. Verified pulling `brand_identity`, `brand_tone`, plus the Bear Creek Trail mobile game decision.
- For QA's actual brand-side gaps that remain:
  - **Link checker** for URLs in marketing copy
  - **Image existence checker** for any deliverable referencing image paths
  - Optional: live web search for fact-checking marketing claims

**Blast radius:** medium-high. Sandboxed execution is the right answer; never give QA host shell access.

**Priority:** **HIGH** — without runtime verification, FE/BE deliverables will ship broken code.

---

## SE (Systems Engineer) — port 8105
**Container:** `atg-sys-engineer`  ·  **Code:** `~/debate-arena/agents/sys-engineer/`

**Current capability**
- Produces infrastructure analyses, resource models, deployment plans
- Already has solid system prompt and JSON output schema
- No actual access to the systems it analyzes

**Gaps**
- ~~Cannot read current system metrics~~ ✅ **CLOSED 2026-04-08:** SE now calls `host-metrics:8111/summary` before every analysis and critique. Returns real CPU%, memory used/total/available, swap, load avg, uptime, and disk usage per host mountpoint. Numbers are injected into the Claude prompt as a `[host-metrics — don-quixote ground truth]` block with explicit instructions to never invent values.
- ~~Cannot read existing docker-compose.yml, container configs, or running container state~~ ✅ **FULLY CLOSED 2026-04-08:** Two layers now: (a) runtime state via host-metrics + docker-socket-proxy, (b) source-of-truth config files via read-only mounts. SE has `~/debate-arena/`, `~/bob-orchestrator/` mounted read-only at `/configs/debate-arena/` and `/configs/bob-orchestrator/`, plus a single-file mount of `~/.cloudflared/config.yml` at `/configs/cloudflared/config.yml` (avoids exposing the cert.pem and credential JSON in the same dir). A new `_load_config_snapshot()` helper reads all four files at execute time and prepends them to every Claude prompt as a `[config snapshot — source-of-truth files on don-quixote]` block. Verified end-to-end: SE quoted the actual cloudflared `ingress:` YAML in a smoke-test answer, no hallucination.
- ~~Cannot run docker stats, df -h, free -m, or any observability commands~~ ✅ **CLOSED 2026-04-08:** Same `/summary` endpoint covers all of these.
- No access to ChromaDB `decisions` collection to see prior infra decisions.

**Needed (remaining)**
- ~~Read-only host metrics tool~~ ✅ done — `atg-host-metrics` sidecar (port 8111).
- ~~Read-only Docker socket~~ ✅ done — `atg-docker-proxy` (tecnativa/docker-socket-proxy) with strict allowlist (CONTAINERS=1, IMAGES=1, INFO=1, NETWORKS=1, VERSION=1; everything else 0).
- ~~Read-only mount of `~/debate-arena/`, `~/bob-orchestrator/`, `~/cloudflared/`~~ ✅ done — see Gaps above. Cloudflared mount tightened to a single-file bind of `config.yml` only, so SE never sees the credential JSON or cert.pem that live in the same directory.
- **ChromaDB read access** to `decisions` collection so SE can see prior infrastructure decisions before re-litigating them.
- Optional: `docker compose config` proxying (would need a small wrapper since compose is host-side, not docker-API).

**Blast radius:** medium. Read-only is essential. Never give SE write access to compose files or live containers.

**Priority:** high — SE was just used for the Engineering team buildout decision (Task #5/6) and was mostly hand-waving for lack of real data.

---

## RE (Reliability Engineer) — port 8106
**Container:** `atg-reliability-engineer`  ·  **Code:** `~/debate-arena/agents/reliability-engineer/`

**Current capability**
- Acts as final critic on infrastructure work AND on FE/BE code deliverables (as of 2026-04-08)
- ✅ ** integration (2026-04-08):** RE automatically calls the new
   service before forming its critique. The sandbox runs static
  analysis on every file the deliverable wrote (Python via ruff + py_compile, HTML
  via html5lib, CSS via tinycss2, JSON via json.loads) and returns ground-truth
  findings. RE incorporates these into its critique with sandbox errors treated
  as critical and warnings as major/minor.
- LLM-only for everything else

**Gaps**
- Same as SE — no actual access to the systems it's reviewing for reliability. *(SE-shared mounts could be reused; deferred.)*
- ~~No access to container logs~~ ✅ **CLOSED 2026-04-08:** RE has `_search_container_logs(container, grep, since_seconds, tail)` helper that calls a new `host-metrics:8111/logs` endpoint, which proxies docker-socket-proxy `/containers/{name}/logs`. Strips docker stream framing, supports grep filter + tail cap. Verified end-to-end against `atg-bob` and `atg-pm`.
- No access to uptime-kuma data — **deferred:** uptime-kuma's API requires a public status page slug Rob has created, OR Prometheus metrics auth, OR socket.io. None of those work out of the box without operator config. Documented in audit doc; reactivate when Rob picks an option.
- No access to incident history or runbooks (because none exist yet).

**Needed (remaining)**
- ~~Log search tool~~ ✅ done — `host-metrics /logs` endpoint + RE `_search_container_logs` helper.
- Uptime-Kuma API access — **deferred** until operator config (status page slug or Prometheus auth).
- **ntfy history** — read-only access to recent notifications so RE can spot flapping alerts.
- A `runbooks/` directory in agent-share that RE can read and propose updates to.
- Same read-only host tools as SE (sharing is fine — could enable in v2 with a single compose change).

**Blast radius:** low (read-only).

**Priority:** medium.

---

## FE (Front-End Engineer) — port 8107  ⭐ NEW
**Container:** `atg-fe-engineer`  ·  **Code:** `~/debate-arena/agents/fe-engineer/`

**Current capability** (as deployed 2026-04-08)
- Writes HTML/CSS/JS file_writes to `/agent-share/workspace/frontend/proposals/` and `/deliverables/`
- Read-only mount of `~/portfolio-site/` at `/website-src/` for context
- JSON deliverables with full file content per file
- Path-safety: rejects writes outside the workspace, rejects `..` and absolute paths

**Gaps**
- Cannot preview its own work — no headless browser, no rendering
- Cannot run a build step (npm, vite, parcel) for projects that need one
- ~~Cannot lint its own output before declaring done~~ ✅ **CLOSED 2026-04-08:** FE got the same self-test loop as BE — runs `code-sandbox` (html5lib for HTML, tinycss2 for CSS, json.loads for JSON) after writing files, with one Claude repair round if errors are found. Final results in `_self_test_results` on the deliverable.
- Cannot fetch external assets (Google Fonts, CDN images) to verify they're reachable
- Cannot promote its own proposals to the live site — promotion is fully manual

**Needed**
- **Playwright** in the container (or a sidecar) for rendering preview screenshots of generated pages
- **`htmlhint` / `stylelint` / `eslint`** for self-linting before sending the deliverable
- **Promotion tool** — a controlled `promote_proposal(proposal_path, target_path)` HTTP endpoint that requires Rob's approval token. FE can request promotion; Rob clicks approve.
- Optional: **Node.js + npm** in the image for projects that need a build step (kept minimal — most ATG website work doesn't need it)
- **Image optimization** — `sharp` or `imagemagick` for any agent-generated visuals
- ChromaDB read access to `brand_voice`

**Blast radius:** medium. Currently low because all writes go to proposals. Once we add `promote_proposal`, blast radius rises to "live website."

**Priority:** medium — works as a v1 today; gaps to address before serious volume.

---

## BE (Back-End Engineer) — port 8109  ⭐ NEW
**Container:** `atg-be-engineer`  ·  **Code:** `~/debate-arena/agents/be-engineer/`

**Current capability** (as deployed 2026-04-08)
- Writes back-end code to `/agent-share/workspace/backend/proposals/` and `/deliverables/`
- Read-only mounts of `~/bob-orchestrator/` at `/bob-src/` and `~/debate-arena/` at `/debate-src/`
- JSON deliverables with full file content per file
- Same path-safety as FE

**Gaps**
- ~~Cannot run the code it writes — no Python, no Docker, no testing~~ ✅ **PARTIAL CLOSED 2026-04-08:** BE now runs an automatic **self-test loop** after writing files. Calls `code-sandbox` on every file it wrote (ruff + py_compile for Python, html5lib for HTML, tinycss2 for CSS, json.loads for JSON). If any file has an error-severity issue, BE does ONE repair round — sends the sandbox findings to Claude with the original task and asks for a corrected response in the same JSON schema. New file_writes are applied and re-tested. Final results land in `_self_test_results` on the deliverable. Verified working: a deliberately broken `def add(x): int` syntax error was repaired in one round to clean code on first try. Still NO arbitrary code execution / unit test running — that's a v2 sandbox item.
- Cannot run database migrations, even against a throwaway SQLite (still open)
- Cannot inspect the running BOB orchestrator state via its API (still open)
- Cannot promote proposals to live code (still open — pairs with the cross-cutting promotion gate item)
- Cannot run `docker compose config` to validate compose changes before submitting (still open)
- No access to existing test suites (still open — would need a real `tests/` dir under each repo)

**Needed (remaining)**
- ~~Sandboxed Python runtime for syntax checks~~ ✅ done — `code-sandbox` + `ruff` + `py_compile`. Wired through BE's self-test loop.
- ~~`ruff` for self-linting~~ ✅ done — same.
- **`mypy` / `pytest` for type checks and unit tests** — still open. Would need pytest in the sandbox image plus a way for BE to declare which test files belong to which proposal.
- **Read-only Docker socket via socket-proxy** ✅ done at the infra level (`atg-docker-proxy` is live for SE/host-metrics). Need to expose it to BE next — currently BE doesn't query it.
- **HTTP client to BOB's own API** for read-only introspection (`/health`, `/threads`, `/cost/status`) — still open. One small env var + httpx call away.
- **Promotion tool** with approval gate (same pattern as FE) — still open, cross-cutting item below.
- **A real `tests/` directory** in `~/debate-arena/` and `~/bob-orchestrator/` so BE has something to run against — still open. This is a longer-term effort; the current codebases largely lack tests.

**Blast radius:** high once promotion is added. BE's promoted proposals can edit BOB itself.

**Priority:** high — write self-test capability before BE is asked to do anything load-bearing.

---

## GA (Graphic Artist) — currently dormant
**Container:** none running  ·  **Code:** `~/debate-arena/agents/graphic-artist/`

**Status:** Container directory exists but agent is not in `docker-compose.yml`'s active service list. Needs to be brought online before tooling audit is meaningful.

**Likely needs (when activated):**
- Image generation API access (DALL-E, Stable Diffusion, or Midjourney via a wrapper)
- Local image processing (`sharp`, `pillow`, `imagemagick`)
- File access to a graphics workspace in agent-share
- Brand-asset library (logos, color palettes) read access

**Priority:** medium — only matters when we have an image-driven task in the queue.

---

## WD (Web Designer) — currently dormant
**Container:** none running  ·  **Code:** `~/debate-arena/agents/web-designer/`

**Status:** dormant. With FE Engineer live (and now reading `brand_voice` directly via the ChromaDB auto-prepend), the role overlap is real and the right call has been written up.

✅ **DECISION DOC CREATED 2026-04-08:** `~/bob-orchestrator/GA_WD_REACTIVATION_DECISION.md` (146 lines). Captures current state, what each agent would need to be useful, the open questions, and a recommendation. Recommendation summary:
- **GA:** park until Bear Creek Trail launch needs visual assets. Cheapest activation path is `gpt-image-1` API (no GPU, no infra, pay per image).
- **WD:** fold into FE for now (Option B). Add a "design considerations" section to FE's system prompt requiring a design rationale at the top of every deliverable. Reactivate WD as a separate agent only if FE design quality degrades.

Both items now wait on Rob's signoff. The audit doc treats this as **PARKED** rather than open.

---


---

## Code Sandbox (cross-cutting service) — port 8110  ⭐ NEW
**Container:** `atg-code-sandbox`  ·  **Code:** `~/debate-arena/services/code-sandbox/`

A read-only static-analysis sidecar shared by all critic agents. Created 2026-04-08
in response to the QA-sandbox audit item, but assigned to RE (engineering-side critic)
since QA's existing DOMAIN GUARD keeps it on brand work only.

**Current capability**
- HTTP API on `http://code-sandbox:8110` exposing `/check/python`, `/check/html`,
  `/check/css`, `/check/json`, `/check/file` (auto-dispatch by extension), `/check/batch`
- Read-only mount of `/agent-share` — can read any FE/BE proposal by path
- Path safety: rejects paths outside `/agent-share/`, files > 5 MB, unknown extensions
- Runs as non-root user inside its container (defense in depth)
- **Ruff** for Python lint, **py_compile** for syntax check
- **html5lib** for HTML parse + warnings
- **tinycss2** for CSS parse
- **json.loads** for JSON parse
- **NO code execution in v1** — static checks only. Code execution adds real security
  work and isn't needed to catch the bugs FE/BE actually produce.

**Gaps / known limitations**
- CSS check is permissive (tinycss2 doesn't catch missing semicolons or unclosed braces
  reliably). Stricter CSS would need `stylelint` (Node).
- No JavaScript checking. Would need `eslint` (Node).
- No HTML accessibility/a11y check. Would need `axe-core` (Node).
- No actual code execution / unit test running. v2 candidate (need to design sandboxing
  carefully — this is the load-bearing security boundary).
- No screenshot rendering. `playwright` would close this.
- No URL liveness check (could add a tiny endpoint for `httpx.head` checks).

**Needed**
- `stylelint`, `eslint`, `axe-core` (Node sidecar with a small npm install)
- `playwright` headless browser for rendering screenshots of generated HTML
- A safe code-execution mode using `seccomp` + cgroup limits for the v2 milestone
- Self-test endpoint (`POST /selftest`) that runs known-bad fixtures and asserts
  expected error counts — so we can verify the sandbox itself isn't broken

**Blast radius:** low (read-only, no host shell, runs as non-root). Will rise if/when
v2 adds code execution.

**Priority:** v1 is live; v2 (Node linters, Playwright, code execution) is medium
priority — pick up after the URL fetcher for RA and the ChromaDB read pattern.


---

## Host Metrics + Docker Proxy (cross-cutting service) — port 8111  ⭐ NEW
**Containers:** `atg-host-metrics` and `atg-docker-proxy`  ·  **Code:** `~/debate-arena/services/host-metrics/`

A read-only sidecar pair giving engineering-side agents (currently SE; RE eligible too)
real ground truth on don-quixote's actual capacity. Created 2026-04-08.

**Architecture**
- `atg-docker-proxy` — `tecnativa/docker-socket-proxy:latest`. Mounts the host
  Docker socket read-only and re-exposes ONLY safe READ endpoints (containers, images,
  info, networks, version). Blocks POST, EXEC, DELETE, BUILD, COMMIT, and every other
  write or shell endpoint. Runs `read_only: true` with `tmpfs: /run, /tmp`.
- `atg-host-metrics` — small FastAPI service using `psutil`. Mounts host `/proc`,
  `/sys`, and `/` read-only into `/host/`. Reads `/host/proc/1/mounts` (PID 1's
  namespace = host's mount table) so it sees real host mountpoints, not its own
  docker bind mounts. Talks to `docker-proxy` over the `agent-net` network.

**Current capability**
- `GET /system` — CPU% now, logical/physical cores, load avg 1m/5m/15m, memory
  used/total/available, swap, uptime, boot time
- `GET /disk` — every host mountpoint with used/total/free GB and percent. Filters
  out cgroup, tmpfs, devpts, proc, sysfs, overlay, fuse.snapfuse and other noise.
- `GET /containers` — list of all running containers with id, name, image, state,
  status (via docker-proxy)
- `GET /container_stats` — per-container CPU% and memory MB/percent (via N+1
  `docker stats` sampling — slow, ~10–20 s for 24 containers, not in /summary)
- `GET /summary` — fast rollup of `/system + /disk + /containers` for prompt injection

**Verified working 2026-04-08:** real host data flowing — 12.7% CPU, 3.74/31.21 GB
memory used, 24 containers running, root disk at 5.1% (45 GB used of 913 GB), and a
useful early warning: `/media` is at **97.7%** capacity (Jellyfin media volume).

**Gaps / known limitations**
- `/container_stats` is slow because Docker's stats endpoint is per-container and
  each call samples for ~1 s. Not in `/summary`. SE doesn't get per-container stats
  by default — would need either parallel calls or a Prometheus-style scrape.
- No CPU temperature, no GPU metrics (don-quixote has no GPU), no fan speeds.
- No historical metrics — every call is a point-in-time snapshot. For trend analysis
  (the kind SE actually needs for "is this growing?"), we'd want a small Prometheus
  + Grafana sidecar OR period samples written to SQLite.
- No reading of the actual compose YAML files. SE sees runtime state but not the
  source of truth. To close: bind-mount `~/debate-arena/`, `~/bob-orchestrator/`,
  `~/cloudflared/` read-only into SE.
- No network stats (bytes in/out per interface, connections per port).

**Needed**
- Read-only mount of compose / config dirs into SE for source-of-truth file reading
- Trend storage (SQLite or Prometheus) so SE can answer "is memory growing?"
- Per-process metrics (`ps aux` style) so SE can attribute CPU spikes to specific
  PIDs not just containers

**Blast radius:** very low. Both containers are read-only mounts, no shell, no host
network access for docker-proxy, non-root user inside host-metrics. The docker-proxy
allowlist is the load-bearing safety boundary — if its env is misconfigured to allow
POST/EXEC, an attacker on agent-net could spawn host-level containers. Audit this
periodically.

**Priority:** v1 is live; the trend-storage and compose-file reading are the next
sub-items (medium priority).


---

## Promotion Gate (cross-cutting service) — port 8112  ⭐ NEW
**Container:** `atg-promotion-gate`  ·  **Code:** `~/debate-arena/services/promotion-gate/`

A small FastAPI + SQLite service that turns "FE/BE wrote files into proposals/" into
"those files actually land in the live target tree" — but only after a human approves.
Created 2026-04-08 to close the cross-cutting promotion gap.

**Architecture**
- FastAPI app with SQLite backing (DB on a named docker volume `promotion-state`,
  survives container restarts)
- Mounts:
  - `~/agent-share` read-only (sources)
  - `~/portfolio-site` read-write (the only allowlisted target in v1)
  - `promotion-state` (named volume) for the SQLite DB
- Path safety: source must be under one of the configured source roots, target
  must be under one of the configured target roots, both resolved with `.resolve()`
  to catch symlinks and `..`
- Approval is single-shot: once `applied` or `rejected`, the record is frozen
- Every state change is timestamped in the DB; the API can list history filtered
  by state, agent, or task

**Endpoints**
- `GET /health`
- `POST /promotions` — create pending (body: source_path, target_path, agent, task_id, reason)
- `GET /promotions?state=pending&agent=BE&limit=50`
- `GET /promotions/{id}` — single record
- `GET /promotions/{id}/diff` — unified diff source vs current target, file by file,
  with summary (added / modified / unchanged / removed_from_source / binary_skipped)
- `POST /promotions/{id}/approve` — executes the copy, stores files_copied + bytes_copied
- `POST /promotions/{id}/reject` — marks rejected with note

**Verified working 2026-04-08:** Promoted `built-different/index.html` + `style.css`
from FE proposals into `~/portfolio-site/built-different/` end-to-end. Diff preview
correctly identified both as `added`. Approval copied 2 files / 15,681 bytes.
Audit trail persisted.

**Gaps / known limitations**
- v1 allowlist only includes `~/portfolio-site/`. Adding `~/bob-orchestrator/` or
  `~/debate-arena/` requires careful blast-radius thinking (it would let approved
  promotions edit BOB itself).
- No ntfy notification on new pending promotions. Rob has to poll or BOB needs a
  tool to surface them.
- Files are owned by root (container UID). Doesn't break Nginx but ownership
  hygiene says we should run as a non-root user with matching uid:gid.
- No automatic Nginx reload after promotion. For static sites this is fine; for
  any target that needs a service restart, a follow-up hook is required.
- Agents don't yet auto-create promotions — Rob (or BOB on his behalf) creates
  them via the API. The natural next step is a BOB tool: `request_promotion(...)`
  that BOB can call when an agent's deliverable looks ready, plus
  `list_pending_promotions()` and `approve_promotion(id, note)`.
- No rollback. If you approve and the new files are bad, you have to manually
  restore from git or from a backup.

**Needed**
- ntfy notification on new pending → tells Rob's phone something's waiting
- BOB tools for `request_promotion`, `list_pending_promotions`, `approve_promotion`
  so Rob can do this through chat
- Non-root container user with matching uid:gid for clean file ownership
- Optional: post-approval hooks (Nginx reload, docker compose restart, git commit)
- Optional: simple rollback by keeping the previous file version in the DB blob

**Blast radius:** medium — the v1 allowlist contains only `~/portfolio-site/`,
which is the public website. Worst case if an attacker on `agent-net` could
forge an "approve" call: they could overwrite the live ATG home page. That's
recoverable from git but visible. Adding bob-orchestrator/debate-arena to the
allowlist raises blast radius significantly — defer until access controls are
tighter.

**Priority:** v1 is live; v2 (ntfy + BOB tools + non-root + hooks) is medium
priority — this is what makes the gate usable from BOB chat instead of via raw
HTTP calls.

## Cross-Cutting Items (apply to multiple agents)

### 1. ChromaDB read access pattern
✅ **PARTIAL CLOSED 2026-04-08:** New `buslib/memory.py` ships with a
`ReadOnlyMemory` class plus `DEFAULT_ALLOWLISTS` covering all 9 agents
(RA, CE, QA, SE, RE, FE, BE, PM, GA). Reads only — no agent can mutate BOB's
shared memory. Lazy ChromaDB client init so missing chromadb never breaks an
agent's module load. Allowlist enforcement returns an error envelope on
unauthorized collection access.

**Wired into 6 agents now (2026-04-08):**
- **RA** — Claude tool-use integration: `query_memory(collection, query, n_results)`
  registered alongside `search_web` and `fetch_url`. RA picks targeted queries.
- **CE** — auto-prepend on `execute_writing` and `critique_output`. Allowlist:
  `brand_voice`, `decisions`, `project_context`. Verified.
- **SE** — auto-prepend in front of the existing config + metrics blocks.
  Allowlist: `decisions`, `project_context`. Verified.
- **RE** — auto-prepend in front of the existing code-sandbox findings in
  `adversarial_review`. Allowlist: `decisions`, `project_context`. Verified.
- **FE** — auto-prepend on `execute_writing`. Allowlist: `brand_voice`,
  `product_specs`, `project_context`. Verified: a "Bear Creek Trail landing page"
  snapshot returned the actual game spec (`bear_creek_trail_overview` —
  "3-row match game, Appalachian theme, black bears, banjos, mason jars").
  FE building marketing pages now sees the real product spec, not boilerplate.
- **BE** — auto-prepend on `execute_writing`. Allowlist: `decisions`,
  `product_specs`, `project_context`. Verified.

**Two integration patterns documented in the codebase:**
1. **Tool-use loop** (RA only) — agent decides when to query, queries are
   targeted by Claude based on conversation. Best for agents that already do
   iterative tool use.
2. **Auto-prepend** (CE/SE/RE) — runtime calls `mem.query_all(task_text)` once
   per execute call and prepends a `[memory snapshot]` block. Cheaper, simpler,
   but less targeted than path 1. Used for agents whose `agent.py` has a
   single Claude `messages.create()` call.

**Still on backlog:** QA and PM only. QA needs `brand_voice` (5-line addition).
PM is pure routing and doesn't really need it. Both can ship next session.

**Cache note:** ✅ **CLOSED 2026-04-08:** Shared `chroma-cache` named
volume mounted at `/root/.cache/chroma` on all 8 agent containers (RA, CE, SE,
RE, FE, BE, plus PM and QA which inherited the mount via the same compose
pattern — harmless mount, no chroma usage there yet). The first agent that
queries pays the ~80 MB embedding model download cost; every other container
on every future rebuild gets it for free from the volume. Verified: after the
initial FE download (~13s), RA's next query took 1.8s — pure cache hit, no
re-download.

### 2. Promotion / approval gate
✅ **CLOSED 2026-04-08 (v1):** New `atg-promotion-gate` service on port 8112.
FastAPI + SQLite. Endpoints: `POST /promotions` (create pending), `GET /promotions`
(list with state filter), `GET /promotions/{id}`, `GET /promotions/{id}/diff` (unified
diff preview, file by file), `POST /promotions/{id}/approve` (executes the actual
copy), `POST /promotions/{id}/reject`. State persisted in a SQLite DB on a named
volume (survives restarts). Audit trail captures who approved/rejected with timestamp
and note.

**Current allowlist:**
- Sources: `/agent-share/workspace/frontend/proposals/`, `/agent-share/workspace/backend/proposals/`
- Targets: `/promote-targets/portfolio-site/` (mapped to `~/portfolio-site/`)

**Verified working 2026-04-08:** Promoted the `built-different/` consulting page
end-to-end — created pending → diff preview (2 added, 0 modified) → approved →
2 files / 15,681 bytes copied to `~/portfolio-site/built-different/`. Audit row
persisted in the DB.

**Updated 2026-04-08 — BOB chat tools added:**
BOB now exposes 5 new tools that wrap the promotion gate so Rob can manage
promotions through chat instead of raw HTTP:
- `list_pending_promotions()` (LOW risk — read-only)
- `get_promotion_details(id)` (LOW)
- `get_promotion_diff(id)` (LOW — returns per-file added/modified/unchanged summary
  plus unified diff for the first 2 modified files)
- `approve_promotion(id, note)` (**HIGH risk** — gated through firewall confirmation)
- `reject_promotion(id, note)` (MEDIUM)

**Bonus fix:** the firewall HIGH-risk gate previously generated a fresh
confirmation ID on every retry, ignoring prior approvals. Patched
`firewall.py` with `find_approved_confirmation()` and `consume_confirmation()`
helpers — when a HIGH-risk tool is called and the same `(tool_name, params)` has
a prior approved-and-not-expired confirmation, the gate now consumes it and
returns ALLOW. Verified end-to-end: BOB asked to approve → blocked with id →
Rob `/firewall/confirm/<id>` → BOB asked to retry → tool executed → files
landed on disk → audit row updated. This benefits **every** HIGH-risk tool, not
just promotions.

**Still open (v2):**
- ~~ntfy notification on new pending promotion~~ ✅ **CLOSED 2026-04-08:** promotion-gate now POSTs to ntfy on three lifecycle events:
  - **new pending** → topic `bob-reviews`, priority `high` (Rob should act)
  - **applied** → topic `bob-status`, priority `default` (audit/info)
  - **rejected** → topic `bob-status`, priority `low` (audit/info)

  Configurable via `NTFY_URL`, `NTFY_REVIEW_TOPIC`, `NTFY_AUDIT_TOPIC`, `NTFY_TOKEN` env vars (token sourced from `~/debate-arena/.env`, copied from BOB's `.env` at deploy time without ever displaying the value). All ntfy calls are best-effort: if ntfy is unreachable, the underlying promotion API call still succeeds. Verified: promotions #3 and #4 both fired notifications, both received `HTTP/1.1 200 OK` from ntfy. Bug fix in the same commit: promotion-gate's requirements.txt was missing `httpx`; added.
- Adding more target roots: `~/bob-orchestrator/`, `~/debate-arena/` (higher blast
  radius — needs careful design before allowing agent-initiated changes to BOB
  itself or to other agents)
- Files copied are owned by root (the container's UID). Nginx serves them fine,
  but ownership hygiene says we should run promotion-gate as a non-root user
  with matching uid:gid to `blueridge` for clean file ownership.
- The promotion gate copies files to disk but does NOT reload Nginx. For static
  sites that re-read on every request, this is fine. For services that need
  reload, the promotion needs a follow-up hook — out of scope for v1.
- Tool naming overlap: `list_pending_promotions` vs the existing
  `review_pending_proposals` (memory-proposals) is confusing for the LLM. BOB
  picked the wrong tool on its first attempt at a vague prompt. Disambiguating
  the names or adding stronger docstring guidance is a small follow-up.

### 3. Self-test before deliverable
✅ **CLOSED 2026-04-08 for FE and BE:** both agents now run `code-sandbox` on
every file they write, with one Claude repair round if errors are found. Final
results are embedded in `_self_test_results` on the deliverable. Other agents
(CE, RA, SE) don't write code so this item doesn't apply to them.

### 4. Cost tracking per agent
BOB has cost tracking but the debate agents don't roll up their own Claude API costs anywhere visible. Each agent should report its own token usage in its deliverable, and the bus should aggregate per-agent cost into a `/cost/agents` endpoint.

### 5. Heredoc-in-prompt content injection
Several agents (notably PM and the debate agents) currently get task context via long string concatenation in Python. This is fragile. A small `Brief` pydantic model + `format_for_agent()` method would be cleaner and easier to test.

---

## Priority Summary

| Priority | Item |
|---|---|
| ~~**HIGH** | RA: web search + URL fetcher~~ | ✅ **FULLY CLOSED 2026-04-08** — web search via ddgs, image/PDF/text attachment reading via Claude vision, full-article reading via `fetch_url` + `trafilatura`. |
| ~~**HIGH** | QA: sandboxed code execution + linters~~ | ✅ **CLOSED 2026-04-08** as code-sandbox v1, routed through RE (not QA — QA stays brand-side). v2 (Node linters, Playwright, code execution) is medium priority. |
| ~~**HIGH** | BE: self-test runtime before any promotion authority~~ | ✅ **CLOSED 2026-04-08** as a self-test loop in BE's `execute_writing()`. Calls `code-sandbox` on every written file, does one Claude repair round on error, embeds final results in `_self_test_results`. Same loop also added to FE. Verified working with a broken syntax repair smoke test (1 round, broken→clean). |
| ~~**HIGH** | SE: read-only Docker socket + host metrics~~ | ✅ **CLOSED 2026-04-08** as `atg-host-metrics` sidecar + `atg-docker-proxy`. Real CPU/mem/disk/load + container listing flowing into SE prompts. Compose-file reading is the next sub-item (medium priority). |
| **MEDIUM** | FE: playwright preview + linters + promotion gate |
| ~~**MEDIUM** | PM: LLM fallback classifier~~ | ✅ **CLOSED 2026-04-08** as `_classify_with_llm()` (Haiku) + primary-agent existence filter. Both fixes verified end-to-end. |
| **MEDIUM** | Cross-cutting: promotion / approval gate |
| ~~**MEDIUM** | Cross-cutting: ChromaDB read helper~~ | ✅ **PARTIAL CLOSED 2026-04-08** as `buslib/memory.py` + `ReadOnlyMemory` + RA `query_memory` tool. Other agents on v2 backlog. |
| ~~**LOW** | CE: brand_voice direct access~~ | ✅ **CLOSED 2026-04-08** as part of the ChromaDB auto-prepend rollout. |
| **LOW** | RE: log search + uptime-kuma read |
| ~~**LOW** | GA / WD: reactivation decisions~~ | ✅ **DOCUMENTED 2026-04-08** in `GA_WD_REACTIVATION_DECISION.md`. Both parked awaiting Rob's signoff. |

---

## How to use this doc

1. Pick a row from the priority summary.
2. Open the relevant agent section, read the gaps and needed-tools list.
3. Pick the smallest concrete sub-item (one tool, one mount, one helper).
4. Implement it as a small PR in `~/debate-arena/agents/<agent>/` or `~/debate-arena/common/buslib/`.
5. Update the agent's Dockerfile / requirements.txt.
6. Rebuild the container, restart, smoke-test.
7. Update this doc: cross out the closed gap, add anything new you discovered.

This file lives at `~/bob-orchestrator/AGENT_TOOLING_AUDIT.md` and is meant to be edited in place as gaps close.
