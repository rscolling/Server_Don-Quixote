# GA / WD Reactivation Decision

**Created:** 2026-04-08
**Status:** awaiting Rob's decision
**Owner:** Rob

This doc captures the current state of the two **dormant agents** in the
debate arena and the decisions Rob needs to make before either is reactivated.
Both have been on the audit board as LOW priority since the initial agent
inventory; this doc is the "park here until Rob decides" landing point.

---

## Current state

| Agent | Status | Code location | Active in `docker-compose.yml`? |
|---|---|---|---|
| **GA** (Graphic Artist) | dormant | `~/debate-arena/agents/graphic-artist/` | NO |
| **WD** (Web Designer) | dormant | `~/debate-arena/agents/web-designer/` | NO |

Both have a directory tree with `agent.py`, `main.py`, `Dockerfile`, and
`requirements.txt`, but neither is wired into the running stack. PM's keyword
classifier will still route `visual` tasks to GA — which then sit in
`ASSIGNED` state forever because no consumer exists. (As of the PM keyword
priority fix in this session, the primary-agent existence filter catches
this and falls back to RA, so the bug is contained — but the *decision*
about whether to actually reactivate GA is still open.)

---

## GA — Graphic Artist

### What it would do
Generate or guide the creation of visual assets: thumbnails, banners, social
graphics, sprites, icons, mood boards. Currently routed via the `visual`
task type in PM's classifier (keywords: `thumbnail`, `image`, `graphic`,
`design`, `visual`, `sprite`, `background`, `banner`).

### What it needs to be useful
- **An image generation backend.** Three options, each with different cost
  and quality tradeoffs:
  1. **OpenAI gpt-image-1 / DALL-E 3** via API. Pay-per-image, ~$0.04–0.12
     each depending on resolution. Fast, well-supported, no infra to run.
  2. **Stable Diffusion** running locally on don-quixote. Free per image but
     don-quixote has **no GPU** — CPU-only inference is ~30s per image at 512px.
     Workable for 1–2 images per task, painful for batches.
  3. **Midjourney** via the Discord bot. No official API; would need a
     bot-bridging hack. Best quality but the integration cost is high.
- **Local image processing**: `pillow` or `imagemagick` for resizing,
  cropping, format conversion, alpha-channel work.
- **A graphics workspace** in agent-share (`~/agent-share/workspace/graphics/`)
  with `proposals/` and `deliverables/` subdirs, same pattern as FE/BE.
- **Brand asset library**: read-only access to existing logos, color palettes,
  fonts. ChromaDB `brand_voice` collection (which has palette info) plus a
  bind-mount of an `~/atg-brand-assets/` dir if Rob wants to maintain one.
- **A deliverable JSON schema** that includes `image_files: [{path, prompt,
  generation_seed, model}]` so other agents can reference what GA produced.

### Decisions Rob needs to make
1. **Which generation backend?** This is the load-bearing question. It
   determines cost structure, latency, and how much infrastructure work is
   needed before GA is useful.
2. **Where do generated images live?** Same agent-share `proposals/` pattern
   as FE/BE? Or a separate `assets/` tree? The promotion gate would need a
   new target root entry either way.
3. **What's the first real task?** GA only matters when there's a graphics
   need in the queue. Bear Creek Trail needs app store icons, screenshots,
   marketing visuals — that's the natural first job.
4. **How does GA hand off to FE?** When FE builds a landing page, who
   commissions the hero image? PM routes the page task to FE; does FE
   delegate the image to GA, or does Rob create both tasks separately?

### Recommendation
**Park GA until Bear Creek Trail launch needs visual assets.** Don't activate
on speculation. When the first real visual task lands, the cheapest path is
gpt-image-1 (option 1) — no GPU, no infra, pay only for what you use. Add
fallback to Stable Diffusion later if cost becomes a real concern.

---

## WD — Web Designer

### What it would do
Pre-implementation design: wireframes, mockups, design systems, layout
exploration, accessibility audits. The "design before code" half of website
work.

### The role overlap problem
Since FE Engineer was deployed (2026-04-08), there's a real question about
whether WD is still a separate role. FE already:
- Reads `brand_voice` from ChromaDB
- Sees the actual page brief and product specs
- Generates HTML + CSS in one step
- Runs static analysis via the code-sandbox before submitting

A separate "design first, then implement" agent would add:
- A wireframe / mockup step before the implementation step
- An accessibility/usability review distinct from the code-sandbox lint
- A design system perspective — is the page consistent with other pages?

But WD without GA is awkward — design without visual generation is mostly
text mockups, which is hard to evaluate.

### Decisions Rob needs to make
1. **Keep WD as a separate agent, or fold its role into FE?**
   - **Option A: Separate WD.** Pre-step before FE. Produces a design spec
     (sections, layout, components, accessibility notes) that FE then
     implements. Two-step pipeline. Better separation of concerns. More agents
     to maintain.
   - **Option B: Fold into FE.** FE's prompt grows a "design first, then
     implement" section. Single agent. Simpler. Loses the explicit design
     review step.
   - **Option C: Activate WD only when GA is also active.** Bundle them as
     "the visual team."
2. **What does a WD deliverable look like?** Markdown spec? JSON with
   structured component/layout fields? Annotated wireframe images (which
   needs GA)?
3. **Does WD review FE's output?** I.e., is WD a critic in the debate arena
   for `frontend_dev` tasks? Right now FE's critics are `BE` and `RE`.

### Recommendation
**Fold into FE for now (Option B).** Add a `## Design considerations` section
to FE's system prompt that requires a design rationale paragraph at the top
of every deliverable. Reactivate WD as a separate agent only if this proves
inadequate — likely the signal would be "FE keeps shipping pages that look
generic" or "FE doesn't catch obvious accessibility problems even with the
sandbox lint."

---

## Audit doc status after this decision

When Rob signs off on the recommendations above (or picks different ones),
the audit doc's GA/WD line moves from "open LOW" to:
- GA: "parked, awaiting Bear Creek Trail visual asset need"
- WD: "rolled into FE per 2026-04-08 decision, separate reactivation only if FE design quality degrades"

---

## What this doc is NOT

This doc does NOT activate either agent. It does NOT modify any code. It
captures the current state, the open questions, and a recommendation. The
implementation work — which is real (image gen API integration, container
build, brand asset library, FE prompt update) — only happens after Rob
signs off on the direction.
