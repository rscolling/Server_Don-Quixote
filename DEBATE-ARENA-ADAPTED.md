# ATG Debate Arena — Adapted for Existing Infrastructure

Adapted from the original debate arena plan. Uses the existing message bus, Syncthing, and website containers instead of rebuilding.

**Status as of 2026-03-18:** Phases 1-3 DEPLOYED. PM, RA, CE, QA agents running and polling the message bus. Phase 4 (GA) and Phase 5 (WD) not yet built.

## Key Differences from Original Plan

| Original Plan | Adapted |
|---------------|---------|
| `docker exec` to call agents | Agents poll message bus via HTTP |
| LangGraph StateGraph | Task state machine + message threads on existing bus |
| Passive containers invoked by subprocess | Long-running FastAPI services with poll loops |
| Separate ChromaDB | Deferred — bus + Syncthing handle state |
| Separate dashboard | Extend existing dashboard at :8585 |
| Uptime Kuma monitoring | PM agent healthchecks |
| Native Syncthing install | Already running as Docker |
| rsync staging workflow | Git branches + Docker rebuild |

## Architecture

```text
Human (dashboard / curl)
  |
  v
Message Bus (port 8585) <--- all agents poll here
  |
  +-- PM/Orchestrator: classifies tasks, manages debate rounds, triggers deploys
  +-- Researcher (RA): market research, fact-checking
  +-- Copy Editor (CE): content writing, critiquing copy
  +-- QA (adversarial): finds reasons to reject output
  +-- Graphic Artist (GA): image gen (Stability AI), Pillow
  +-- Web Designer (WD): modifies React source, Git workflow
  |
  +-- agent-share/workspace/  (file artifacts via Syncthing)
  +-- ~/portfolio-site/src/   (website source, WD agent only)
```

## How Debates Work on the Message Bus

1. Human creates task via dashboard or `POST /tasks`
2. PM picks it up, classifies (campaign/content/visual/research/seo/simple)
3. PM sets debate metadata in task.metadata, assigns primary agent, transitions to ASSIGNED
4. Primary agent polls, sees assignment, begins work
5. Agent posts draft as deliverable message, transitions task to IN_REVIEW
6. PM routes to critics (per CRITIC_ASSIGNMENTS), sends critique requests
7. Critics post feedback messages (reply_to the draft)
8. PM collects critiques, transitions task to REWORK
9. Primary agent revises, resubmits — loop back to step 5
10. After critic round, PM sends to QA for adversarial review
11. QA approves -> ACCEPTED -> CLOSED. QA rejects -> REWORK (if rounds remain)
12. Max rounds hit -> escalation -> mediator/human review

## Debate Tiers (from original plan)

| Task Type | Tier | Max Rounds | Mesh | Critique | Adversarial QA |
|-----------|------|------------|------|----------|----------------|
| campaign | full_tension | 5 | Yes | Yes | Yes |
| content | full_tension | 4 | Yes | Yes | Yes |
| visual | critique_revise | 3 | No | Yes | Yes |
| research | critique_revise | 3 | No | Yes | Yes |
| seo | light_review | 2 | No | Yes | No |
| simple | no_debate | 0 | No | No | No |

## Critic Assignments

| Primary | Critics |
|---------|---------|
| RA | CE, QA |
| GA | CE, QA |
| CE | RA, QA |
| SM | CE, GA, QA |
| SA | CE |
| WD | GA, QA |

## Directory Structure

```text
~/debate-arena/                    # All debate arena code
  docker-compose.yml
  .env                             # ANTHROPIC_API_KEY, STABILITY_API_KEY
  common/                          # Shared library (pip-installable)
    buslib/
      __init__.py
      client.py                    # MessageBusClient (HTTP wrapper)
      agent_base.py                # BaseAgent (poll loop, registration)
      debate.py                    # Debate tiers, critic assignments, metadata model
  agents/
    pm/
      Dockerfile
      requirements.txt
      main.py                      # Entry point
      orchestrator.py              # Task classification, debate routing, escalation
    researcher/
      Dockerfile
      requirements.txt
      main.py
      agent.py                     # Research logic
    copy-editor/
      Dockerfile
      requirements.txt
      main.py
      agent.py                     # Writing + critique logic
    qa/
      Dockerfile
      requirements.txt
      main.py
      agent.py                     # Adversarial review
    graphic-artist/
      Dockerfile
      requirements.txt
      main.py
      agent.py                     # Image generation + manipulation
    web-designer/
      Dockerfile
      requirements.txt
      main.py
      agent.py                     # React source modification
```

## Phase 1: Foundation (Common Library + PM Agent)

Build the shared `buslib` library and the PM/Orchestrator agent.

### buslib/client.py

HTTP wrapper for all message bus endpoints:

- `register_agent(shorthand, name, role, capabilities)`
- `subscribe(topic)`
- `poll(since)` -> returns new messages
- `send_message(recipient, type, payload, task_id, reply_to, topic)`
- `create_task(title, description, assignee, priority, metadata, watchers)`
- `update_task(task_id, state, metadata)`
- `ack_message(msg_id, status)`

Uses `httpx.AsyncClient` targeting `http://message-bus:8585`.

### buslib/agent_base.py

Base class all agents inherit:

- Registers on startup with capabilities
- Subscribes to relevant topics
- Poll loop every 3 seconds
- Dispatches messages to `handle_message()` (override in subclass)
- Built-in critique/revise methods using Anthropic API

### buslib/debate.py

Debate tier configuration (ported from original plan):

- `DEBATE_TIERS` dict
- `CRITIC_ASSIGNMENTS` dict
- `get_tier_for_task()` classifier
- `DebateMetadata` Pydantic model (stored in task.metadata)

### PM Agent

- Registers as PM with capabilities: task_classification, debate_orchestration, escalation
- Subscribes to topics: `task:new`, `debate:review_complete`, `escalation`
- On new task: classify, set debate metadata, assign primary agent
- On review complete: check verdict, loop or approve or escalate
- Docker socket access for website deploys

### Docker Networking

Create shared network `agent-net`. Both message-bus and debate-arena containers join it.

## Phase 2: Content Agents (RA + CE)

Two agents that produce and critique content.

### Researcher Agent (RA)

- Capabilities: market_research, competitor_analysis, content_research, fact_checking
- Execute: Claude API call with research prompt -> structured JSON
- Writes results to `/agent-share/workspace/research/`
- Posts deliverable message with file_path

### Copy Editor Agent (CE)

- Capabilities: copywriting, editing, blog_posts, product_descriptions, proofreading
- Execute: Claude API call for content creation
- Critique mode: reviews other agents' output for clarity, grammar, tone, brand voice

### First End-to-End Debate

Submit "Research wooden toy market trends" -> PM -> RA drafts -> CE critiques -> RA revises -> full cycle through task states.

## Phase 3: Adversarial QA

### QA Agent

- Capabilities: adversarial_review, brand_consistency, quality_assurance
- System prompt: "Your job is to find reasons to REJECT" (from original plan)
- Structured verdict: approve/revise/reject with score, issues, strengths
- PM routes all deliverables to QA after critic round

### Full Debate Loop Test

Content task -> RA -> CE critique -> RA revise -> QA review -> approve or loop.

## Phase 4: Graphic Artist

### GA Agent

- Capabilities: image_generation, image_manipulation, brand_visuals, thumbnails
- Stability AI SD3 endpoint for generation
- Pillow for manipulation
- Writes to `/agent-share/workspace/graphics/`
- Dockerfile includes libjpeg, libpng, libfreetype, fonts

## Phase 5: Web Designer + Website Git Workflow

### Git Init

```bash
cd ~/portfolio-site && git init && git add . && git commit -m "Initial commit"
```

### WD Agent

- Capabilities: react_development, css_styling, component_creation, site_deployment
- Mounts `~/portfolio-site/` read-write
- Workflow: create branch -> modify React source -> commit -> PM triggers rebuild
- PM handles deploy: `docker compose build web && docker compose up -d web`
- Rollback: `git revert HEAD && rebuild`

### Deploy Safety

- Only PM has Docker socket access
- WD only modifies source and commits
- Git branches isolate changes
- QA reviews before deploy is triggered

## Phase 6: Dashboard Enhancements + Polish

Extend the existing dashboard at :8585:

- Debate tab: groups messages by thread showing round progression
- Debate metadata on task cards (tier, round count, primary agent)
- Submit Task shortcut targeting PM
- Agent health indicators from PM healthchecks

## Docker Compose

```yaml
# ~/debate-arena/docker-compose.yml
services:
  pm:
    build: ./agents/pm
    container_name: atg-pm
    env_file: .env
    volumes:
      - ~/agent-share:/agent-share
      - /var/run/docker.sock:/var/run/docker.sock
      - ./common:/common
    networks: [agent-net]
    restart: unless-stopped

  researcher:
    build: ./agents/researcher
    container_name: atg-researcher
    env_file: .env
    volumes:
      - ~/agent-share:/agent-share
      - ./common:/common
    networks: [agent-net]
    restart: unless-stopped

  copy-editor:
    build: ./agents/copy-editor
    container_name: atg-copy-editor
    env_file: .env
    volumes:
      - ~/agent-share:/agent-share
      - ./common:/common
    networks: [agent-net]
    restart: unless-stopped

  qa:
    build: ./agents/qa
    container_name: atg-qa
    env_file: .env
    volumes:
      - ~/agent-share:/agent-share
      - ./common:/common
    networks: [agent-net]
    restart: unless-stopped

  graphic-artist:
    build: ./agents/graphic-artist
    container_name: atg-graphic-artist
    env_file: .env
    volumes:
      - ~/agent-share:/agent-share
      - ./common:/common
    networks: [agent-net]
    restart: unless-stopped

  web-designer:
    build: ./agents/web-designer
    container_name: atg-web-designer
    env_file: .env
    volumes:
      - ~/agent-share:/agent-share
      - ~/portfolio-site:/site
      - ./common:/common
    networks: [agent-net]
    restart: unless-stopped

networks:
  agent-net:
    external: true
```

## Resource Budget

- 6 containers x ~50MB idle = ~300MB RAM baseline
- Active debate (Claude calls): ~500MB peak total
- Well within 32GB RAM budget
- API costs: ~20 Claude calls per full_tension debate (5 rounds x 3 critics + QA)
- Add token budget tracking to PM agent

## What's Preserved from Original Plan

- Debate tier system (full_tension / critique_revise / light_review / no_debate)
- Critic assignments per agent
- Adversarial QA system prompt and behavior
- Agent system prompts (RA, GA, CE, QA)
- Escalation path (mediator -> orchestrator -> human)
- Brand guidelines and ATG context in prompts
- Debate logging for review
