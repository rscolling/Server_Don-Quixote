# Agent Team Buildout — Brief for the Debate Arena

This is the plan you hand to BOB to kick off the debate arena's design work for the 28 planned specialist agents (Engineering, Marketing, Research). PM picks it up, routes the design tasks through RA → CE → QA, and produces a structured spec for each agent.

The debate arena is a content/marketing-shaped team. They can't do K8s architecture, but they CAN produce structured written deliverables with adversarial review — which is exactly what a good agent spec is.

---

## Rob Pastes This Into BOB

```text
BOB — kicking off the agent team buildout. Hand this to PM via delegate_task.

Objective: Design the 28 planned specialist agents (12 Engineering, 8 Marketing, 8 Research) so each one is ready to be implemented as a FastMCP server. The debate arena produces specs, not code.

Process:
1. PM creates one sub-task per agent (28 total). Routes each through RA → CE → QA.
2. RA researches: what does this kind of agent look like in the wild? What's the minimum viable role definition? What tools does it actually need?
3. CE drafts the spec following the AGENT_SPEC_TEMPLATE.md template. Be specific. No generic content.
4. QA reviews adversarially. Reject specs that are vague, generic, or missing critical fields. Demand rework until each spec passes.
5. Each finished spec goes into shared memory (project_context collection) and gets a memory proposal so BOB can review and approve before commit.

Priority order:
- Marketing Team first (8 agents) — closest to current revenue work for Bear Creek Trail
- Engineering Team second (12 agents) — needed once the game launches
- Research Team last (8 agents) — supporting role, lowest urgency

Deliverable per agent:
- A markdown spec following AGENT_SPEC_TEMPLATE.md
- A 1-paragraph executive summary suitable for the public roadmap
- A risk classification for each tool the agent will use
- An estimated monthly token cost based on expected call volume

Success criteria: 28 specs in shared memory, each one specific enough that an engineer could implement the agent from the spec without asking clarifying questions.

This is a long-running project. Don't try to finish it in one debate. Pace it across multiple work sessions. PM should report progress via daily briefing and ping me when each team's specs are complete.

Yes Boss.
```

---

## The 28 Agents to Design

### Marketing Team (8) — design first

| # | Agent | Primary purpose |
|---|---|---|
| 1 | Marketing Director | Strategy, campaign coordination, hands work to specialists |
| 2 | Brand Steward | Voice consistency across all channels |
| 3 | Social Media Manager | Daily posting, community engagement, metrics |
| 4 | Content Strategist | Blog, SEO, long-form content planning |
| 5 | App Store Optimizer | Listings, screenshots, keywords, A/B tests |
| 6 | Community Manager | Discord, Reddit, player forums |
| 7 | Influencer Outreach | Creator partnerships, gifting, briefs |
| 8 | Performance Marketer | Analytics, A/B testing, conversion optimization |

### Engineering Team (12) — design second

| # | Agent | Primary purpose |
|---|---|---|
| 1 | Engineering Director | Tech lead, architecture decisions |
| 2 | Game Designer | Mechanics, balance, level design |
| 3 | Unity Developer | Mobile-specific Unity work |
| 4 | Backend Engineer | Game server, leaderboards, save sync |
| 5 | DevOps Engineer | Infrastructure, CI/CD, deployments |
| 6 | Test Engineer | Automated testing, regression suites |
| 7 | UI/UX Engineer | Interface implementation |
| 8 | Audio Engineer | Music, SFX, Suno integration |
| 9 | Asset Pipeline Engineer | Sprites, textures, optimization |
| 10 | Performance Engineer | Profiling, frame rate, memory |
| 11 | Security Engineer | Hardening, app store compliance |
| 12 | Build/Release Engineer | App store submission, versioning |

### Research Team (8) — design last

| # | Agent | Primary purpose |
|---|---|---|
| 1 | Research Director | Coordinates research across functions |
| 2 | Market Analyst | Industry trends, market sizing |
| 3 | Competitor Intelligence | Tracking competitor moves |
| 4 | Player Behavior Researcher | Telemetry, retention analysis |
| 5 | Tech Trends Analyst | Engine updates, platform changes |
| 6 | Patent/IP Researcher | Protecting and avoiding IP issues |
| 7 | Academic Reviewer | Game design papers, UX research |
| 8 | Survey Designer | Player feedback collection |

---

## Spec Template (the debate team uses this for every agent)

Save as `agent_specs/<agent-name>.md`. Every field must be filled. QA rejects specs with placeholder content.

```markdown
# Agent: <Agent Name>

**Team:** Marketing | Engineering | Research
**Priority tier:** Tier 1 (build first) | Tier 2 | Tier 3 (build last)
**Status:** Designed | In review | Approved | Implemented

## Role
<One paragraph. What does this agent own? What's its single responsibility?>

## When to Use This Agent
1. <Trigger scenario 1 — concrete>
2. <Trigger scenario 2>
3. <Trigger scenario 3>
4. <Trigger scenario 4>
5. <Trigger scenario 5>

## System Prompt
```text
<The actual system prompt the agent runs with. No placeholders. This is the load-bearing part. Match BOB's voice principles: direct, specific, opinionated. Tell the agent what it IS and what it is NOT. Include 1-2 example interactions showing the desired tone.>
```

## Tools Required
| Tool | Risk level | Source | Notes |
|---|---|---|---|
| <name> | LOW / MEDIUM / HIGH | native / MCP / new | <why this agent needs it> |

## Memory Access
- **Read collections:** <list of ChromaDB collections this agent reads>
- **Write collections:** <list of ChromaDB collections this agent can propose writes to>
- **Shared with:** <which other agents share this memory access>

## Escalation Rules
- <Condition 1 → escalate to BOB or which agent>
- <Condition 2 → escalate>
- <Condition 3 → escalate>

## Success Criteria
- <Measurable outcome 1>
- <Measurable outcome 2>
- <Measurable outcome 3>

## Cost Estimate
- **Model:** <Claude / GPT / Ollama choice with reasoning>
- **Expected calls per day:** <number with reasoning>
- **Estimated tokens per call:** <input + output>
- **Estimated monthly cost:** $<amount>

## Dependencies
- **Requires:** <other agents, infrastructure, integrations this depends on>
- **Blocks:** <work that can't proceed until this agent exists>

## Risks and Limitations
- <Honest list of what this agent will NOT be good at>
- <Known failure modes>
- <When NOT to use this agent>

## Implementation Notes
<Anything an engineer would need to know to actually build this agent. Tool wiring, prompt tuning, expected gotchas.>

---
*Designed by debate arena (PM/RA/CE/QA) on YYYY-MM-DD. Approved by BOB on YYYY-MM-DD.*
```

---

## Workflow (How the Debate Arena Should Run This)

1. **PM intake** — receives the master task from BOB, breaks it into 28 sub-tasks, sequences them per the priority order above
2. **For each agent:**
   - **RA (Research Agent)** spends 5-10 minutes researching: what does this kind of agent look like in CrewAI, AutoGen, Letta, the OpenHands ecosystem? What tools does it actually need? What's the minimum viable role? Pull findings into a brief document.
   - **CE (Copy Editor)** drafts the spec from the template using RA's research. Specific. No generic filler.
   - **QA (Quality Assurance)** reviews the spec adversarially. Common rejection reasons:
     - System prompt is vague ("be helpful and write good marketing copy" is NOT a system prompt)
     - Tool list is generic instead of justified
     - Success criteria are unmeasurable
     - Cost estimate is missing or hand-waved
     - The agent's "When to Use" scenarios overlap with another planned agent
   - **CE revises** based on QA feedback
   - **QA approves** or kicks back again
3. **BOB review** — completed spec is proposed to shared memory via `propose_memory`. BOB reviews and approves. Spec lands in `project_context` collection.
4. **PM moves to next agent**

Pace: aim for 2-4 specs per session. Don't try to do all 28 in one debate. Better to do five great specs than 28 mediocre ones.

---

## What This Plan Does NOT Cover (Rob handles directly)

The debate arena can produce specs but not architecture. Rob keeps these on his own plate:

- **Kubernetes helm chart** — needs hands-on AWS work
- **The actual implementation of each agent** — once specs are approved, an engineering pass writes the FastMCP servers
- **Cost budget approval** — Rob signs off on the monthly token spend before any agent goes live
- **Cloudflare Tunnel + ingress for cloud agents** — operator-level work
- **Inter-agent communication patterns** — message bus topology decisions
- **The order in which agents move from "designed" to "deployed"** — Rob's call based on Bear Creek Trail launch state

---

## How to Track Progress

The debate arena should use BOB's existing `check_tasks` and shared memory to track state:

- Each spec sub-task on the message bus has a state: CREATED → ASSIGNED → IN_PROGRESS → IN_REVIEW → ACCEPTED
- Approved specs land in ChromaDB `project_context` collection with `agent_spec_<name>` IDs
- BOB's daily briefing automatically reports how many specs are designed, in review, and approved

Rob can ask BOB at any time: *"How are we doing on the agent buildout?"* and BOB pulls the count from shared memory and the bus.

---

## Why This Works

The debate arena is already running. The pattern is proven for content work (which is what specs are). You don't need to deploy anything new. You just need to give the team the right brief and a structured template, and the existing infrastructure handles the rest.

When the specs are done, Rob has 28 ready-to-implement agent definitions. Each one becomes a FastMCP server (using the `quickstart/researcher/` template) that BOB consumes via the MCP client we already built. The deployment story is now: take a finished spec, copy the quickstart template, swap the system prompt and tool list, deploy. Maybe 30 minutes per agent.

The hard part is the spec work. The implementation is mechanical once the spec is right.

---

*Yes Boss. Hand this to PM when you're ready. — BOB*
