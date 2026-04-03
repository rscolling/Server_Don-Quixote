# ATG — Make/Buy Analysis Framework
### *Applied by BOB to every significant build or procurement decision*
### *Rob makes all final calls.*

---

## Purpose

Every project reaches decision points where ATG must choose between building something internally using the agent teams, buying or licensing an existing solution, or using a hybrid of both. This framework is BOB's standing instruction for how to structure that analysis — consistently, across all projects, at any scale.

BOB initiates a Make/Buy analysis when:
- A new tool, component, service, or capability is being considered
- Engineering estimates a task will take more than 3 days to build
- A third-party solution exists that overlaps with planned work
- Rob asks "should we just buy this?"
- A Research team finding surfaces a relevant existing solution

---

## The Seven Factors

BOB scores every Make/Buy decision across seven factors. Each factor is scored 1–5 for both the Make option and the Buy option. Higher score = stronger case for that option on that factor.

---

### Factor 1 — Strategic Control
*How important is it that ATG owns and controls this capability long-term?*

| Score | Make | Buy |
|---|---|---|
| 5 | Core to ATG's competitive advantage. Must own it. | Commodity — no strategic value in owning it. |
| 3 | Useful to own but not critical. | Acceptable dependency if vendor is stable. |
| 1 | No strategic reason to build this. | Risky dependency — vendor lock-in concern. |

---

### Factor 2 — Cost (Total Cost of Ownership, 12 months)
*What does each option actually cost when fully accounted for?*

**Make cost includes:**
- Agent team time (estimate debate rounds × tier × Opus/Sonnet cost)
- Maintenance burden ongoing
- Infrastructure additions (RAM, disk, new containers)
- Rob's review and decision time

**Buy cost includes:**
- License or subscription fee
- Integration development time
- Ongoing per-seat or per-use fees
- Vendor dependency risk (what if they raise prices or shut down?)

| Score | Make | Buy |
|---|---|---|
| 5 | Build cost is clearly lower over 12 months | Buy cost is clearly lower over 12 months |
| 3 | Roughly comparable | Roughly comparable |
| 1 | Build cost is significantly higher | Buy cost is significantly higher |

---

### Factor 3 — Time to Value
*How quickly does each option deliver a working result?*

| Score | Make | Buy |
|---|---|---|
| 5 | Can be built and deployed in < 1 week | Available and deployable today |
| 3 | 2–4 weeks to working state | 1–2 weeks to integrate and configure |
| 1 | Months of development required | Long procurement/setup process |

---

### Factor 4 — Quality & Fit
*How well does each option actually solve the problem?*

| Score | Make | Buy |
|---|---|---|
| 5 | Can be built precisely to ATG's needs | Existing solution is an exact fit |
| 3 | Good fit with some compromises | Requires workarounds or missing features |
| 1 | Poor fit — significant gaps or over-engineering | Poor fit — bloated, missing key features, or wrong use case |

---

### Factor 5 — Maintenance Burden
*What does ongoing ownership look like?*

| Score | Make | Buy |
|---|---|---|
| 5 | Low maintenance — stable once built | Vendor handles all maintenance |
| 3 | Moderate — periodic updates needed | Some integration maintenance required |
| 1 | High ongoing maintenance — frequent changes, debugging | High maintenance — fragile integration, poor vendor support |

---

### Factor 6 — Brand & Independence
*Does this decision align with ATG's values and reduce external dependencies?*

ATG's brand is handcrafted and independent. Over-reliance on third-party services creates fragility and cost exposure. This factor rewards decisions that keep ATG self-sufficient.

| Score | Make | Buy |
|---|---|---|
| 5 | Builds ATG capability — fully self-hosted, no ongoing cost | Open source, self-hostable — aligns with independence |
| 3 | Neutral — doesn't affect brand or independence meaningfully | Reputable vendor, reasonable terms |
| 1 | Not applicable (internal tooling) | Proprietary lock-in, data leaves ATG's control, ongoing cost exposure |

---

### Factor 7 — Risk
*What can go wrong with each option, and how bad is it?*

**Make risks:** Agent builds the wrong thing, cost overrun, maintenance debt, Rob's time consumed in review cycles.

**Buy risks:** Vendor discontinues product, price increase, data privacy, integration breaks on update, service outage.

| Score | Make | Buy |
|---|---|---|
| 5 | Low risk — well-understood problem, clear spec | Low risk — proven product, stable vendor, easy to replace |
| 3 | Moderate risk — some unknowns | Moderate risk — some vendor dependency |
| 1 | High risk — complex build, many unknowns | High risk — critical dependency, no good alternative |

---

## Scoring Sheet

BOB produces this table for every Make/Buy analysis:

```
Decision: [What is being evaluated]
Project: [Which project this applies to]
Date: YYYY-MM-DD

Factor                  | Make Score (1-5) | Buy Score (1-5) | Notes
------------------------|-----------------|-----------------|-------
Strategic Control       |                 |                 |
Cost (12-month TCO)     |                 |                 |
Time to Value           |                 |                 |
Quality & Fit           |                 |                 |
Maintenance Burden      |                 |                 |
Brand & Independence    |                 |                 |
Risk                    |                 |                 |
------------------------|-----------------|-----------------|-------
TOTAL                   |       /35       |       /35       |

RECOMMENDATION: [Make / Buy / Hybrid]
CONFIDENCE: [High / Medium / Low]

BOB's reasoning:
[2-3 sentences on the deciding factors]

Open questions before deciding:
[What Rob needs to know that the analysis couldn't resolve]

If Buy — recommended option:
[Specific product/vendor, cost, link]

If Make — recommended approach:
[Which team, estimated debate tier, rough timeline]
```

---

## Hybrid Option

When neither Make nor Buy scores clearly higher, BOB evaluates a Hybrid approach:
- Buy a foundation (existing tool, library, or service) and build ATG-specific layers on top
- Use a Buy solution short-term while Make is in progress, then migrate
- Buy for non-core functionality, Make for anything that touches ATG's competitive differentiation

Hybrid gets its own row in the scoring sheet when BOB identifies it as viable.

---

## Standing ATG Preferences

These are Rob's standing biases — BOB applies them as tiebreakers and notes when a decision runs against them:

| Preference | Reasoning |
|---|---|
| Self-hosted over cloud SaaS where practical | Data stays on the server, no ongoing subscription creep |
| Open source over proprietary when quality is comparable | No vendor lock-in, can fork if needed |
| Build when it's core to how ATG works | Bought tools shape your workflow; built tools serve it |
| Buy when it's commodity infrastructure | No strategic value in reinventing solved problems |
| Prototype before committing to either | A 2-hour spike often resolves what a 2-day analysis can't |

---

## Log of Past Make/Buy Decisions

*BOB appends completed analyses here for reference.*

| Date | Decision | Project | Verdict | Outcome |
|---|---|---|---|---|
| 2026-03-18 | Observability stack | BOB infrastructure | Buy (Langfuse — open source, self-hosted) | Deployed Phase 1–12 |
| 2026-03-18 | Voice interface | BOB voice layer | Buy (ElevenLabs) | Planned — pending deployment |
| 2026-03-18 | Agent orchestration | BOB infrastructure | Buy (LangGraph) | Architecture defined |
| 2026-03-18 | AI music generation | Mobile game + Marketing | Buy (Suno — Rob has active account) | Available for agent use |

---

*This file lives at `/opt/atg-agents/bob-context/MAKE_BUY_FRAMEWORK.md`*
*BOB reads this before producing any Make/Buy analysis.*
*Rob approves all final Make/Buy decisions.*
*Last updated: 2026-03-18 (Suno added)*
