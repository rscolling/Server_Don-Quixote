# Don-Quixote Infrastructure Documentation

Server infrastructure for a multi-agent AI system. BOB (the skull) is Rob's primary interface — he activates agent teams, monitors health, and manages escalations. All services run as Docker containers on `don-quixote` (192.168.1.228, Ubuntu 24.04, Dell OptiPlex 5050, 32GB RAM).

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Server Overview](#server-overview)
3. [BOB — Orchestrator](#bob--orchestrator)
4. [Message Bus — Nervous System](#message-bus--nervous-system)
5. [Debate Arena — Agent Team](#debate-arena--agent-team)
6. [Syncthing — Artifact Storage](#syncthing--artifact-storage)
7. [Observability — Langfuse + Monitors](#observability--langfuse--monitors)
8. [Peer-to-Peer Upgrades](#peer-to-peer-upgrades-all-phases-built)
9. [Deployment and Operations](#deployment-and-operations)

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────┐
│                      Rob (Human)                     │
│                         │                            │
│                    ┌────▼────┐                       │
│                    │   BOB   │  ◄── Main interface   │
│                    │ (skull) │      Orchestrator      │
│                    └────┬────┘                       │
│                         │                            │
│              ┌──────────▼──────────┐                 │
│              │    Message Bus      │  ◄── Port 8585  │
│              │  (nervous system)   │                  │
│              └──┬───┬───┬───┬─────┘                  │
│                 │   │   │   │                        │
│            ┌────▼┐ ┌▼──┐┌▼──┐┌▼──┐                  │
│            │ PM  │ │RA ││CE ││QA │ ◄── Debate Arena  │
│            └─────┘ └───┘└───┘└───┘     Agent Team    │
│                                                      │
│  ┌───────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Syncthing │  │ Langfuse │  │ Resource Monitors│  │
│  │  (files)  │  │ (traces) │  │  (health/cost)   │  │
│  └───────────┘  └──────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**How it works:**

1. Rob talks to BOB (the skull) — voice, text, or dashboard
2. BOB decides what needs doing and posts tasks to the message bus
3. The message bus routes messages between BOB and agent teams
4. The Debate Arena team (PM, RA, CE, QA) handles content/marketing tasks through structured debate rounds
5. Agents read/write file artifacts via Syncthing shared folders
6. Langfuse + monitors track every LLM call, cost, and system health
7. BOB surfaces alerts, daily reports, and escalations back to Rob

---

## Server Overview

| Property  | Value                             |
|-----------|-----------------------------------|
| Hostname  | don-quixote                       |
| OS        | Ubuntu 24.04.4 LTS                |
| Hardware  | Dell OptiPlex 5050, 32GB RAM      |
| LAN IP    | 192.168.1.228                     |
| SSH user  | blueridge (UID 1000)              |
| Disk free | ~79GB (16% used as of 2026-03-17) |

### Other Services (do not disturb)

| Service        | Type   | Ports        | Notes                        |
|----------------|--------|--------------|------------------------------|
| Portfolio site | Docker | 80, 443      | `appalachian-toys` container |
| Jellyfin       | Native | 8096 (LAN)   | Media server                 |
| OpenClaw       | Docker | 18789, 18790 | Outbound API calls only      |

### Firewall (UFW)

Open: 22 (SSH), 80, 443, 8096 (LAN), 22000/tcp+udp (LAN), 21027/udp (LAN), 8585 (pending).
Port 8384 NOT opened — Syncthing GUI is localhost-only via SSH tunnel.

---

## BOB — Orchestrator

BOB is the skull — Rob's primary point of contact for the entire system. BOB is the top-level orchestrator that activates agent teams, monitors system health, handles escalations, and delivers daily briefings.

### Role

- Receives instructions from Rob (voice, text, or dashboard)
- Creates tasks on the message bus and assigns them to agent teams
- Monitors debate progress and intervenes on escalation
- Aggregates observability data (Langfuse traces, resource metrics, network health)
- Delivers daily summary reports
- Controls the appalachiantoysgames.com website through agent teams

### How BOB Activates Agent Teams

1. Rob gives BOB a goal (e.g., "write a product page for the new board game")
2. BOB creates a task on the message bus (`POST /tasks`)
3. The Debate Arena PM agent picks up the task and classifies it
4. PM routes the task through the debate tier system (RA researches, CE writes, QA reviews)
5. On completion, BOB receives the final deliverable
6. On escalation, BOB mediates or surfaces to Rob

### Message Bus Identity

BOB registers as agent `BOB` on the message bus with capabilities:

- `orchestration` — top-level task management
- `escalation_handler` — receives escalations from PM
- `health_monitoring` — system health alerts
- `daily_reporting` — aggregated reports

### Status

**Not yet deployed.** BOB's orchestrator service needs to be built. Currently, tasks are created manually via the message bus API/dashboard. The debate arena agents operate autonomously once a task exists.

### Planned Container

| Property  | Value                                      |
|-----------|--------------------------------------------|
| Container | `atg-bob`                                  |
| Port      | 8100                                       |
| Network   | `agent-net`                                |
| Image     | Custom Python + Anthropic SDK              |
| Model     | Claude Opus (for orchestration decisions)  |

---

## Syncthing — Artifact Storage

### Purpose

Shared filesystem for agents to read/write artifacts. Synced over LAN to Rob's phone and laptop via Syncthing.

### Syncthing Deployment

- **Location on server**: `~/syncthing/docker-compose.yml`
- **Local copy**: `Server_Don Quixote/docker-compose.yml`
- **Image**: `syncthing/syncthing:latest`
- **Container name**: `syncthing`

### Syncthing Docker Compose

```yaml
services:
  syncthing:
    image: syncthing/syncthing:latest
    container_name: syncthing
    hostname: don-quixote
    restart: unless-stopped
    environment:
      - PUID=1000
      - PGID=1000
    volumes:
      - ./config:/var/syncthing/config    # bind mount, not named volume
      - ~/agent-share:/var/syncthing/agent-share
    ports:
      - "127.0.0.1:8384:8384"   # Web UI — localhost only
      - "22000:22000/tcp"        # Syncthing protocol
      - "22000:22000/udp"        # Syncthing protocol
      - "21027:21027/udp"        # Local discovery
```

### Syncthing Configuration

| Setting          | Value                   | Reason                           |
|------------------|-------------------------|----------------------------------|
| GUI auth         | blueridge / wehave6kids | Prevent unauth access            |
| Global discovery | Disabled                | LAN only                         |
| Relaying         | Disabled                | LAN only                         |
| Local discovery  | Enabled                 | Default, needed for pairing      |
| Folder version   | Staggered               | Safety net for agent file writes |

**Device ID**: `O2LN6N5-ANZY4EO-EMUTVZ4-VZ2JMYT-SNA6VSQ-LJZMY3D-5M4MPIL-DWZMVAH`

### Agent-Share Directory Structure

```text
~/agent-share/
  inbox/        # Agents drop files here for Rob (human) to review
  outbox/       # Rob drops files here for agents to pick up
  workspace/    # Agents use between themselves — deliverables, working docs
  archive/      # Completed work gets moved here
  logs/         # Agent activity logs
```

### File Naming Convention

```text
{agent_shorthand}_{descriptor}_{ISO-date}.{ext}
```

Examples: `SE_system-design_2026-03-17.md`, `QC_review-notes_2026-03-17.md`

### Accessing the Syncthing GUI

SSH tunnel from laptop:

```bash
ssh -L 8384:127.0.0.1:8384 blueridge@192.168.1.228
```

Then open `http://localhost:8384` in browser.

---

## Message Bus — Nervous System

### Bus Purpose

REST API for multi-agent messaging, task management, and agent registration. Agents send typed JSON messages, create/transition tasks through a state machine, and poll for new messages.

### Bus Deployment

- **Location on server**: `~/message-bus/`
- **Local copy**: `Server_Don Quixote/message-bus/`
- **Container name**: `message-bus`
- **Port**: 8585
- **Dashboard**: `http://192.168.1.228:8585/`
- **API docs**: `http://192.168.1.228:8585/docs`

### Bus Stack

| Component   | Version/Detail          |
|-------------|-------------------------|
| Runtime     | Python 3.12-slim        |
| Framework   | FastAPI 0.115.6         |
| ASGI server | Uvicorn 0.34.0          |
| Database    | SQLite (aiosqlite 0.20) |
| Templates   | Jinja2 3.1.5            |
| Frontend    | Alpine.js 3.x (CDN)     |
| User        | appuser (UID 1000)      |

### Bus Docker Compose

```yaml
services:
  message-bus:
    build: .
    container_name: message-bus
    restart: unless-stopped
    ports:
      - "8585:8585"
    volumes:
      - ./data:/app/data                  # SQLite DB persists here
      - ~/agent-share:/agent-share:ro     # Read-only access to shared files
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8585/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

### Bus Dockerfile

```dockerfile
FROM python:3.12-slim
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
RUN mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 8585
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8585"]
```

### Bus File Structure

```text
message-bus/
  Dockerfile
  .dockerignore
  requirements.txt
  docker-compose.yml
  data/                     # SQLite DB (persisted volume)
    messagebus.db
  app/
    __init__.py
    config.py               # DB_PATH, AGENT_SHARE_PATH, PORT
    database.py             # Schema, migrations, all query functions
    models.py               # Pydantic models, enums, state machine
    main.py                 # FastAPI app, lifespan, CORS, routers, WS wiring
    routes/
      __init__.py
      system.py             # /health, /stats, /ws (WebSocket)
      agents.py             # /agents, /agents/{shorthand}, capabilities
      messages.py           # /messages, poll, thread, ack
      tasks.py              # /tasks, watchers
      capabilities.py       # /capabilities discovery
      subscriptions.py      # /subscriptions, /subscriptions/topics
    templates/
      dashboard.html        # Alpine.js SPA dashboard v2.0
```

### Database Schema

SQLite with WAL mode and foreign keys enabled. Seven tables total.

#### Messages Table

| Column       | Type    | Notes                          |
|--------------|---------|--------------------------------|
| id           | INTEGER | Primary key, autoincrement     |
| sender       | TEXT    | Agent shorthand (e.g. "SE")    |
| recipient    | TEXT    | Agent shorthand or "ALL"       |
| message_type | TEXT    | See MessageType enum           |
| priority     | TEXT    | low / normal / high / critical |
| payload      | TEXT    | JSON object                    |
| context      | TEXT    | JSON object                    |
| task_id      | INTEGER | Optional FK to tasks.id        |
| timestamp    | TEXT    | ISO-8601 UTC                   |
| reply_to     | INTEGER | ID of parent message (Phase 1) |
| thread_id    | INTEGER | Root message ID (Phase 1)      |
| topic        | TEXT    | Topic name (Phase 3)           |

Indexes: `(recipient, timestamp)`, `(sender)`, `(task_id)`, `(thread_id)`, `(topic)`

#### Tasks Table

| Column      | Type    | Notes                          |
|-------------|---------|--------------------------------|
| id          | INTEGER | Primary key, autoincrement     |
| title       | TEXT    | Required                       |
| description | TEXT    | Optional                       |
| assignee    | TEXT    | Agent shorthand, nullable      |
| state       | TEXT    | See TaskState enum             |
| priority    | TEXT    | low / normal / high / critical |
| file_paths  | TEXT    | JSON array of strings          |
| metadata    | TEXT    | JSON object                    |
| created_at  | TEXT    | ISO-8601 UTC                   |
| updated_at  | TEXT    | ISO-8601 UTC                   |

Indexes: `(state)`, `(assignee)`

#### Agents Table

| Column        | Type | Notes                        |
|---------------|------|------------------------------|
| shorthand     | TEXT | Primary key (e.g. "SE")      |
| name          | TEXT | Full name                    |
| role          | TEXT | Free-text description        |
| status        | TEXT | "active" by default          |
| registered_at | TEXT | ISO-8601 UTC                 |
| last_seen     | TEXT | Updated on each message sent |

#### Acks Table (Phase 1)

| Column     | Type    | Notes                          |
|------------|---------|--------------------------------|
| id         | INTEGER | Primary key, autoincrement     |
| message_id | INTEGER | FK to messages.id              |
| agent      | TEXT    | Who acknowledged               |
| status     | TEXT    | received / read / acted        |
| acked_at   | TEXT    | ISO-8601 UTC                   |

Unique constraint: `(message_id, agent)`

#### Capabilities Table (Phase 2)

| Column   | Type    | Notes                      |
|----------|---------|----------------------------|
| id       | INTEGER | Primary key, autoincrement |
| agent    | TEXT    | FK to agents.shorthand     |
| name     | TEXT    | Capability name            |
| version  | TEXT    | Default "1.0"              |
| metadata | TEXT    | JSON object                |

Unique constraint: `(agent, name)`

#### Subscriptions Table (Phase 3)

| Column     | Type    | Notes                      |
|------------|---------|----------------------------|
| id         | INTEGER | Primary key, autoincrement |
| agent      | TEXT    | Subscriber shorthand       |
| topic      | TEXT    | Topic name                 |
| created_at | TEXT    | ISO-8601 UTC               |

Unique constraint: `(agent, topic)`

#### Task Watchers Table (Phase 4)

| Column  | Type    | Notes              |
|---------|---------|--------------------|
| task_id | INTEGER | FK to tasks.id     |
| agent   | TEXT    | Watcher shorthand  |

Primary key: `(task_id, agent)`

### Enums

**MessageType**: `task_assignment`, `status_update`, `deliverable`, `feedback`, `question`, `escalation`, `state_change`

**Priority**: `low`, `normal`, `high`, `critical`

**AckStatus**: `received`, `read`, `acted`

**TaskState** — state machine:

```text
CREATED -> ASSIGNED -> IN_PROGRESS -> IN_REVIEW -> ACCEPTED -> CLOSED
                                       \-> REWORK -> IN_PROGRESS (loop)
            ASSIGNED -> CREATED (rollback)
```

| From        | To                   |
|-------------|----------------------|
| CREATED     | ASSIGNED             |
| ASSIGNED    | IN_PROGRESS, CREATED |
| IN_PROGRESS | IN_REVIEW            |
| IN_REVIEW   | ACCEPTED, REWORK     |
| REWORK      | IN_PROGRESS          |
| ACCEPTED    | CLOSED               |
| CLOSED      | (terminal)           |

State changes auto-generate a `state_change` message published to the `task:{id}` topic, reaching all watchers.

### System Endpoints

| Method    | Path    | Description                                                    |
|-----------|---------|----------------------------------------------------------------|
| GET       | /       | Dashboard (HTML)                                               |
| GET       | /health | Health check + uptime + DB size                                |
| GET       | /stats  | Message/task/agent/sub counts                                  |
| GET       | /docs   | Swagger UI (auto-generated)                                    |
| WebSocket | /ws     | Real-time push of all state (3s interval + mutation-triggered) |

### Message Endpoints

| Method | Path                  | Description                                          |
|--------|-----------------------|------------------------------------------------------|
| POST   | /messages             | Send a message (supports reply_to, topic)            |
| GET    | /messages             | List (filter: sender, recipient, type, since, topic) |
| GET    | /messages/poll        | Poll new messages (params: agent, since, limit)      |
| GET    | /messages/{id}        | Get single message                                   |
| GET    | /messages/{id}/thread | Get all messages in a thread                         |
| POST   | /messages/{id}/ack    | Acknowledge a message (body: agent, status)          |
| GET    | /messages/{id}/acks   | Get acknowledgments for a message                    |

### Task Endpoints

| Method | Path                         | Description                                    |
|--------|------------------------------|------------------------------------------------|
| POST   | /tasks                       | Create task (auto state_change, auto watchers) |
| GET    | /tasks                       | List (filter: state, assignee, priority)       |
| GET    | /tasks/{id}                  | Get single task (includes watchers)            |
| PATCH  | /tasks/{id}                  | Update task, validates state transitions       |
| GET    | /tasks/{id}/watchers         | List watchers                                  |
| POST   | /tasks/{id}/watchers         | Add a watcher (body: agent)                    |
| DELETE | /tasks/{id}/watchers/{agent} | Remove a watcher                               |

### Agent Endpoints

| Method | Path                             | Description                       |
|--------|----------------------------------|-----------------------------------|
| POST   | /agents                          | Register/update agent (with caps) |
| GET    | /agents                          | List all agents + capabilities    |
| GET    | /agents/{shorthand}              | Get single agent                  |
| POST   | /agents/{shorthand}/capabilities | Set capabilities                  |
| GET    | /agents/{shorthand}/capabilities | Get capabilities                  |

### Capability Endpoints

| Method | Path                        | Description                    |
|--------|-----------------------------|--------------------------------|
| GET    | /capabilities               | List all distinct capabilities |
| GET    | /capabilities/{name}/agents | Find agents with a capability  |

### Subscription Endpoints

| Method | Path                  | Description                               |
|--------|-----------------------|-------------------------------------------|
| POST   | /subscriptions        | Subscribe an agent to a topic             |
| DELETE | /subscriptions        | Unsubscribe (query: agent, topic)         |
| GET    | /subscriptions        | List subscriptions (filter: agent, topic) |
| GET    | /subscriptions/topics | List all topics with subscriber counts    |

**Agent activity**: `is_active` is true if the agent sent a message within the last 300 seconds (5 minutes). Checked at query time, not stored.

### Dashboard

Single-page Alpine.js app at `/`. Features:

- **WebSocket real-time updates** via `/ws` endpoint — replaces all polling. Dashboard connects on load, auto-reconnects on disconnect. Connection status shown as green/red dot in header. Mutations trigger instant broadcast to all connected clients.
- **Stats bar**: total messages, tasks, agents, active agents, topics count
- **Messages tab**: search/filter bar, type/priority badges, thread links, topic badges, reply indicators. Click "thread" to expand inline thread view.
- **Tasks tab**: Kanban board with drag-and-drop state transitions. Drag a task card to a new column to trigger a PATCH. Shows progress bar per card, watchers list. Search/filter bar.
- **Agents tab**: grid of registered agents with active/inactive indicators, capability badges, relative timestamps
- **Topics tab**: lists all topic subscriptions with subscriber agents, subscribe form
- **Send tab**: forms to send messages (with topic and reply-to fields), create tasks, register agents
- **Toast notifications**: slide-in toasts when new messages/tasks arrive, color-coded by type, auto-dismiss after 3.5s
- **Unread badges**: tab badges show count of new items that arrived while viewing a different tab
- **Keyboard shortcuts**: `1-5` switch tabs, `r` refresh, `/` focus search, `?` toggle help overlay, `Esc` close
- **Relative timestamps**: "just now", "5m ago", "2h ago" — falls back to date for older items
- **CSS custom properties**: full color system via `:root` variables for easy theming
- **Mobile responsive**: grid stats on small screens, scrollable tab bar, stacked form inputs

Dark theme. Mobile-responsive grid layout.

### CORS

Wide open (`allow_origins=["*"]`). Appropriate for LAN-only internal service.

### Syncthing Integration

The message bus mounts `~/agent-share` read-only at `/agent-share`. Agents reference file paths in message payloads:

```json
{
  "sender": "SE",
  "recipient": "QC",
  "message_type": "deliverable",
  "payload": {"file_path": "/agent-share/workspace/system-design-v2.md"}
}
```

**Note**: The mount is read-only (`:ro`). The message bus cannot write to agent-share (e.g., logs). Change to `:rw` if the bus needs write access.

---

## Debate Arena — Agent Team

Four AI agents deployed as Docker containers, communicating through the message bus. Managed from `~/debate-arena/` on the server, local copy at `Server_Don Quixote/debate-arena/`.

### Deployed Agents

| Agent             | Shorthand | Container       | Port | Role                                             |
|-------------------|-----------|-----------------|------|--------------------------------------------------|
| Project Manager   | PM        | atg-pm          | 8101 | Task classification, debate routing, escalation  |
| Researcher        | RA        | atg-researcher  | 8102 | Market research, fact-checking, content research |
| Copy Editor       | CE        | atg-copy-editor | 8103 | Copywriting, editing, critique, brand voice      |
| Quality Assurance | QA        | atg-qa          | 8104 | Adversarial review, brand consistency, quality   |

### How Agents Work

Each agent is a FastAPI service that:

1. Registers with the message bus on startup (`POST /agents` with capabilities)
2. Subscribes to relevant topics (`POST /subscriptions`)
3. Polls `GET /messages/poll` every 3 seconds for new work
4. Processes messages and sends results back through the bus
5. Writes file artifacts to `/agent-share/workspace/`

### Debate Flow

1. Human creates task via dashboard or API
2. PM classifies task type (campaign/content/visual/research/seo/simple)
3. PM sets debate tier and assigns primary agent via `PATCH /tasks/{id}`
4. Primary agent executes, posts deliverable, transitions task to IN_REVIEW
5. PM routes to critics per CRITIC_ASSIGNMENTS
6. Critics post feedback messages (reply_to chains)
7. If revisions needed, PM transitions to REWORK, agent revises
8. QA performs adversarial review as final gate
9. QA approves -> ACCEPTED -> CLOSED, or rejects -> loop back
10. Max rounds hit -> escalation (mediator -> orchestrator -> human)

### Debate Tiers

| Task Type | Tier            | Max Rounds | Critics       |
|-----------|-----------------|------------|---------------|
| campaign  | full_tension    | 5          | All available |
| content   | full_tension    | 4          | All available |
| visual    | critique_revise | 3          | CE, QA        |
| research  | critique_revise | 3          | CE, QA        |
| seo       | light_review    | 2          | CE            |
| simple    | no_debate       | 0          | None          |

### Shared Library (buslib)

All agents share a common Python library at `~/debate-arena/common/buslib/`:

- `client.py` — async HTTP wrapper for all message bus endpoints
- `agent_base.py` — BaseAgent with poll loop, registration, retry, Claude helpers
- `debate.py` — debate tiers, critic assignments, task classifier, DebateMetadata model

Mounted read-only into each container at `/common`, installed via `pip install /common` at startup.

### Docker Compose

```yaml
# ~/debate-arena/docker-compose.yml
# All agents join the agent-net network shared with message-bus
services:
  pm:        # atg-pm, PORT=8101
  researcher: # atg-researcher, PORT=8102
  copy-editor: # atg-copy-editor, PORT=8103
  qa:        # atg-qa, PORT=8104

networks:
  agent-net:
    external: true
```

### Docker Network

All agent containers and the message bus share the `agent-net` Docker network. Created with `docker network create agent-net`. Both `~/message-bus/docker-compose.yml` and `~/debate-arena/docker-compose.yml` reference it as external.

### Environment Variables

`~/debate-arena/.env`:

- `ANTHROPIC_API_KEY` — required for all Claude API calls
- `MESSAGE_BUS_URL` — defaults to `http://message-bus:8585`
- `LOG_LEVEL` — defaults to `INFO`

### Deploying Agent Changes

```bash
# From Windows laptop:
scp -r "debate-arena/common/buslib" blueridge@192.168.1.228:~/debate-arena/common/buslib
scp -r "debate-arena/agents/pm" blueridge@192.168.1.228:~/debate-arena/agents/pm

# On server:
cd ~/debate-arena && docker compose restart
# Or rebuild if Dockerfile/requirements changed:
cd ~/debate-arena && docker compose build && docker compose up -d
```

### Planned Agents (Not Yet Built)

| Agent          | Shorthand | Role                                                  |
|----------------|-----------|-------------------------------------------------------|
| Graphic Artist | GA        | Image generation (Stability AI), Pillow manipulation  |
| Web Designer   | WD        | React source modification, Git workflow, site deploy  |

### Arena Known Issues

1. **Startup pip install** — each container runs `pip install /common` on every restart (~5-10s delay). This is because the common library is volume-mounted, not baked into the image.
2. **`is_active` always false** — agents poll but don't send messages as "sender", so `last_seen` doesn't update. The bus updates `last_seen` only when an agent sends a message, not when it polls.

---

## Observability — Langfuse + Monitors

Self-hosted observability stack. Every LLM call, every token, every dollar — logged, traceable, and visible. Adapted from `bob-observability-plan.md`.

### Deployment Status

**Langfuse deployed.** Tracing active via BOB's LangGraph callback handler.

### ntfy — Push Notifications

| Property   | Value                              |
|------------|------------------------------------|
| Container  | `ntfy`                             |
| Port       | 2586                               |
| Network    | `agent-net`                        |
| Auth       | deny-all default, explicit users   |

BOB publishes to four topics:

| Topic          | Use                              | Priority |
|----------------|----------------------------------|----------|
| `bob-critical` | Server down, API unreachable     | Urgent   |
| `bob-reviews`  | Escalations needing Rob's input  | High     |
| `bob-status`   | Task completions, team activity  | Default  |
| `bob-daily`    | Morning briefing                 | Low      |

Users: `bob-publisher` (write, token auth), `rob` (read, password auth). Publisher token stored in BOB's .env.

### Langfuse (Trace & Cost Tracking)

| Property   | Value                                             |
|------------|---------------------------------------------------|
| Container  | `langfuse` + `langfuse-db` (PostgreSQL 15)        |
| Port       | 3000                                              |
| Network    | `agent-net`                                       |
| Cost       | $0/month (self-hosted)                            |
| RAM        | ~500MB (Langfuse + PostgreSQL)                    |
| Retention  | 90 days (auto-pruned at 2 AM daily)               |

What Langfuse captures:

- Every Anthropic API call (tokens in/out, cost, latency, model)
- Traces grouped by task_id (linked to message bus tasks)
- Agent-level cost breakdowns
- Debate round traces (full conversation thread per debate)

### Resource Monitors

Six monitors run as background async tasks, adapted for the message bus (no longer tied to BOB orchestrator loop):

| Monitor              | Interval | What It Watches                                    |
|----------------------|----------|----------------------------------------------------|
| Resource Monitor     | 5 min    | CPU, RAM, disk, swap — thresholds trigger alerts   |
| Quality Scorer       | Per task | Output quality on 5 dimensions via Claude Haiku    |
| Debate Health        | Per round| Participation, loops, escalations, timeouts        |
| Network Connectivity | 60 sec   | Anthropic API, external services, internet         |
| Syncthing Bridge     | 2 min    | Sync status, pending changes, device connectivity  |
| Container Health     | 90 sec   | Docker container status, restarts, crash loops     |

### Alert Thresholds

| Resource | Warning | Critical | Upgrade Recommended |
|----------|---------|----------|---------------------|
| RAM      | 75%     | 88%      | 92%                 |
| CPU      | 70%     | 85%      | 90%                 |
| Disk     | 75%     | 88%      | 92%                 |
| Swap     | 20%     | —        | 40%                 |

### Daily Report (8:00 AM)

BOB delivers a morning briefing to Rob:

- Yesterday's tasks: completed, failed, in-progress
- Total cost breakdown by agent and model
- Quality scores summary
- Pending reviews requiring human input
- System health status (containers, network, disk)
- Alerts fired in the last 24 hours

### Nightly Maintenance

| Time   | Job                                                        |
|--------|------------------------------------------------------------|
| 1 AM   | Langfuse DB backup (gzip to /opt/atg-observability/backups)|
| 2 AM   | Prune Langfuse traces older than 90 days                   |
| 3 AM   | Archive debate transcripts, prune stale notes, check logs  |
| 8 AM   | Daily briefing to Rob via BOB                              |

### Data Retention

| Data               | Retention                     | Location                           |
|--------------------|-------------------------------|------------------------------------|
| Langfuse traces    | 90 days                       | PostgreSQL                         |
| Docker logs        | 50MB / 5 files                | Per container (json-file driver)   |
| Debate transcripts | 90 days active, then archived | Syncthing shared                   |
| Langfuse backups   | 30 daily                      | /opt/atg-observability/backups/    |

### Environment Variables (for .env)

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://langfuse:3000
SYNCTHING_API_KEY=...
```

---

## Peer-to-Peer Upgrades (All Phases Built)

All four phases have been implemented and deployed. Migrations run at startup and are idempotent.

### Phase 1 — Threading, Acknowledgments, Poll Limits

Enable agents to hold conversations and confirm message receipt.

- Added `reply_to` and `thread_id` columns to messages
- Created `acks` table (received/read/acted)
- Threading logic: reply_to resolves thread_id from parent chain
- Poll gains `limit` parameter (default 100, max 500)
- Validates reply_to exists (422 if not)

### Phase 2 — Agent Capabilities and Discovery

Let agents find "who can do X?" without hardcoding the team.

- Created `capabilities` table (agent, name, version, metadata)
- Capabilities accepted inline during agent registration
- Discovery via `GET /capabilities/{name}/agents`

Example:

```bash
# Register with capabilities
curl -X POST http://192.168.1.228:8585/agents \
  -H 'Content-Type: application/json' \
  -d '{"shorthand":"SE","name":"Software Engineer","capabilities":[{"name":"python"},{"name":"code_review"}]}'

# Find who can review code
curl http://192.168.1.228:8585/capabilities/code_review/agents
```

### Phase 3 — Topic Subscriptions and Fan-Out

Pub/sub alongside direct messaging.

- Created `subscriptions` table (agent, topic)
- Added `topic` column to messages
- Poll query expanded: includes messages matching agent's subscribed topics
- Agents receive topic-addressed messages without being named as recipient

### Phase 4 — Task Watchers

Replace ORCH-centric state-change notifications with a watcher model.

- Created `task_watchers` table (task_id, agent)
- Task creation auto-adds assignee + ORCH as watchers
- State-change messages publish to `task:{id}` topic via Phase 3 fan-out
- New assignees auto-added as watchers on PATCH

### Phase Summary

| Phase | Depends on | New tables      | Altered tables     | Endpoints |
|-------|------------|-----------------|--------------------|-----------|
| 1     | —          | `acks`          | `messages` +2 cols | 3         |
| 2     | —          | `capabilities`  | —                  | 4         |
| 3     | —          | `subscriptions` | `messages` +1 col  | 5         |
| 4     | Phase 3    | `task_watchers` | —                  | 3         |

Phases 1-3 are fully independent. Phase 4 uses Phase 3 topic fan-out.

---

## Deployment and Operations

### Building and Deploying

From the server (`~/message-bus/` or `~/syncthing/`):

```bash
# Rebuild and restart message bus
cd ~/message-bus
docker compose build && docker compose up -d

# Restart syncthing
cd ~/syncthing
docker compose up -d
```

### Verifying Health

```bash
# Message bus
curl http://192.168.1.228:8585/health
curl http://192.168.1.228:8585/stats

# Syncthing (from server only, or via SSH tunnel)
curl http://127.0.0.1:8384/rest/system/status

# Docker status
docker ps
docker logs message-bus --tail 20
docker logs syncthing --tail 20
```

### Copying Updated Code to Server

From the Windows laptop — delete remote app dir first to avoid SCP nesting:

```bash
ssh blueridge@192.168.1.228 "rm -rf ~/message-bus/app"
scp -r "Server_Don Quixote/message-bus/app" blueridge@192.168.1.228:~/message-bus/app
```

Then SSH in and rebuild:

```bash
ssh blueridge@192.168.1.228
cd ~/message-bus && docker compose build --no-cache && docker compose up -d
```

### Database Details

- **Path on server**: `~/message-bus/data/messagebus.db`
- **Path in container**: `/app/data/messagebus.db`
- **Mode**: WAL (write-ahead logging) for concurrent reads
- **Backup**: Copy the `.db`, `.db-wal`, and `.db-shm` files together

### Known Issues

1. **agent-share mount is read-only** in the message-bus container. Change `:ro` to `:rw` if the bus needs write access.
2. **No authentication** on the message bus API. Fine for LAN-only use.
3. **Single DB connection** — works for single-worker uvicorn but won't scale to multiple workers.
4. **UFW rule for port 8585** may still be pending — verify with `sudo ufw status`.
5. **SCP trailing slash** causes directory nesting. Always delete remote dir first or omit trailing slash.
