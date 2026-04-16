# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Context

This is the source-of-truth checkout for **Don Quixote**, a self-hosted multi-agent AI platform that runs on a separate Ubuntu server (`don-quixote`, LAN `192.168.1.228`, Tailscale `100.105.16.120`, SSH user `blueridge`). Code is edited locally on Windows and deployed to the server via `scp` — **the running system is not on this machine**. Always think of edits here as "patches in flight" until they have been copied to the server and the relevant container restarted (see [MCP_DEPLOYMENT_NOTES.md](MCP_DEPLOYMENT_NOTES.md) for the canonical deploy pattern).

The repo contains four independent Docker Compose stacks that share an external `agent-net` bridge network. They depend on each other at runtime but are versioned, built, and brought up separately.

## High-Level Architecture

Four cooperating substrates (full narrative in [README.md](README.md), operations details in [INFRASTRUCTURE.md](INFRASTRUCTURE.md)):

1. **[bob-orchestrator/](bob-orchestrator/)** — `atg-bob` container, port 8100 (FastAPI + chat + dashboard) and 8108 (BOB-as-MCP server). LangGraph ReAct agent with 40+ native tools plus dynamically-loaded MCP tools. Owns the only ChromaDB write surface. Runs alongside `chromadb` (port 8000).
2. **[message-bus/](message-bus/)** — `message-bus` container, port 8585. FastAPI + SQLite implementation of a task state machine (`CREATED → ASSIGNED → IN_PROGRESS → IN_REVIEW → ACCEPTED/REWORK → CLOSED`). Transitions are server-enforced via `VALID_TRANSITIONS` in [message-bus/app/models.py](message-bus/app/models.py). All inter-agent coordination flows through this bus.
3. **[debate-arena/](debate-arena/)** — Eight specialist Sonnet 4.5 agents (PM/RA/CE/QA/SE/RE/FE/BE on ports 8101–8107, 8109) plus three ops services: `code-sandbox` (FE/BE validation), `promotion-gate` (approve-before-write for files landing in live targets), `host-metrics` + read-only `docker-proxy` (psutil/Docker telemetry without write access to the socket). Agents read shared memory but propose writes through BOB.
4. **[bob-voice-updates/](bob-voice-updates/)** and **[bob-widget/](bob-widget/)** — Voice PWA bridge (Deepgram STT → BOB → ElevenLabs TTS over WebSocket) and an embeddable JS chat widget for public sites.

### Critical Architectural Invariants

These are load-bearing rules that the system depends on. Violating them silently breaks production:

- **BOB is the sole ChromaDB writer.** Debate-arena agents read via the allowlisted client in [debate-arena/common/buslib/buslib/memory.py](debate-arena/common/buslib/buslib/memory.py) and propose writes through [bob-orchestrator/app/memory_proposals.py](bob-orchestrator/app/memory_proposals.py). Do not add direct write paths from arena agents.
- **Every tool call passes through the firewall.** [bob-orchestrator/app/firewall.py](bob-orchestrator/app/firewall.py) classifies each call as `LOW` (execute, quiet log), `MEDIUM` (execute, loud log), or `HIGH` (block pending mobile confirmation within 2 minutes). When you add a tool to [bob-orchestrator/app/tools.py](bob-orchestrator/app/tools.py), you **must** add it to `TOOL_REGISTRY` in `firewall.py` — unregistered tools are blocked. The same firewall applies to MCP-fetched tools.
- **Task state transitions are server-side.** Agents cannot jump a task from `CREATED` to `ACCEPTED`. If an agent appears stuck in `ACCEPTED`, that is a bug — tasks must auto-close to `CLOSED`. Honor the state machine in [message-bus/app/models.py](message-bus/app/models.py:1) when writing new agent loops.
- **Debate tier is a property of task type.** Tier and critic assignments live in [debate-arena/common/buslib/buslib/debate.py](debate-arena/common/buslib/buslib/debate.py) (`DEBATE_TIERS`, `CRITIC_ASSIGNMENTS`). Final critic for infra/code is `RE`; for creative work it is `QA`. Don't hardcode critics in agent code.
- **No inbound ports are open to the internet.** All public hostnames reach BOB via Cloudflare Tunnel ([cloudflared/config.yml](cloudflared/config.yml)) with Zero Trust OIDC at the edge. Don't add `ports:` mappings expecting them to be reachable from outside the LAN.
- **Personality is swappable but never removed.** [bob-orchestrator/app/personality.py](bob-orchestrator/app/personality.py) loads from `bob_context/personalities/`. The sardonic Bob-the-Skull tone is intentional (see [CONTRIBUTING.md](bob-orchestrator/CONTRIBUTING.md) — "Don't change the personality. Seriously.").

### Where the Cross-File Coupling Lives

Things that look local but are actually system-wide contracts:

- `agent-net` is `external: true` in every compose file. **Create it once before bringing up any stack:** `docker network create agent-net`.
- The `bob-orchestrator` and `debate-arena` source trees are **read-mounted into SE/BE/FE containers** as `/configs/*` and `/bob-src`, `/debate-src`, `/website-src`. Renaming top-level directories breaks SE's analyses and BE's diff context — see volume mounts in [debate-arena/docker-compose.yml](debate-arena/docker-compose.yml).
- The `~/agent-share` host directory is shared across all arena agents and the `promotion-gate` (read-only there). It is the artifact handoff surface — generated files live here until promoted.
- BOB is both an MCP **client** ([bob-orchestrator/app/mcp_client.py](bob-orchestrator/app/mcp_client.py), driven by `mcp_servers.json`) **and** an MCP **server** ([bob-orchestrator/app/mcp_server.py](bob-orchestrator/app/mcp_server.py), exposed on `:8108` to Claude Desktop/Cursor/goose).

## Common Commands

### Bring stacks up (in dependency order)

```bash
docker network create agent-net   # one-time, before first `up`
docker compose -f message-bus/docker-compose.yml      up -d
docker compose -f bob-orchestrator/docker-compose.yml up -d
docker compose -f debate-arena/docker-compose.yml     up -d
docker compose -f docker-compose.yml                  up -d   # syncthing
```

### Health checks

```bash
curl http://localhost:8585/health              # message bus
curl http://localhost:8100/health              # BOB
curl http://localhost:8000/api/v1/heartbeat    # ChromaDB
curl http://localhost:8100/status              # BOB extended status
curl http://localhost:8100/mcp/status          # BOB MCP client/server status
```

### Lint and compile (no formal test suite — manual smoke + static checks)

From `bob-orchestrator/`:

```bash
flake8 app/ --max-line-length 120 --ignore=E501,W503,E402,F401
python -m py_compile app/*.py
```

### Smoke-test BOB

```bash
curl -X POST http://localhost:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Research what MCP is, then write me a Python hello-world.","thread_id":"smoke-1","user":"rob"}'
```

### Deploy edits to the server

The pattern is `scp` to `blueridge@192.168.1.228:/home/blueridge/<stack>/` followed by `docker compose restart <service>` over SSH. See [MCP_DEPLOYMENT_NOTES.md](MCP_DEPLOYMENT_NOTES.md) for the file-by-file recipe used last deploy. Pre-approved SCP commands are listed in [.claude/settings.local.json](.claude/settings.local.json).

## When You Add A Tool to BOB

Bare minimum (from [bob-orchestrator/CONTRIBUTING.md](bob-orchestrator/CONTRIBUTING.md)):

1. Function with a clear docstring (the docstring is the LLM-facing description — write it for the model).
2. Entry in `firewall.py:TOOL_REGISTRY` with the appropriate `RiskLevel`.
3. Add to `_TOOLS` in [bob-orchestrator/app/tools.py](bob-orchestrator/app/tools.py).
4. Async by default. Type hints on public surface. Errors → `{"error": "...", "detail": "..."}` for user errors, raise for programmer errors.

## Operator Profile

User is the sole operator and original author. They are familiar with every subsystem and prefer terse communication, root-cause fixes over workarounds, and explicit confirmation before any destructive or remote-affecting action. The server is production for a one-person operation — treat outages and broken state machines as real incidents, not lab problems.
