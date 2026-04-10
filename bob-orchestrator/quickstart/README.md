# BOB Quickstart

**Goal:** Get BOB running with two specialist agents in under 10 minutes.

By the end of this walkthrough you'll have:

- BOB orchestrator running locally
- A researcher agent specialized in focused research
- A coder agent specialized in writing and reviewing code
- BOB consuming both specialists via MCP, delegating work to them, and combining their outputs in a single conversation

This is the simplest possible BOB stack — no message bus, no debate arena, no voice service, no monitoring. Just the orchestration pattern. For the full production stack, see `../docker-compose.yml`.

---

## Prerequisites

- **Docker + Docker Compose** (Docker Desktop on Mac/Windows, or native on Linux)
- **An Anthropic API key.** Get one at https://console.anthropic.com/. The free credits are enough for the quickstart demo.
- **5 minutes of patience** while images build the first time.

That's it. No Python install needed locally — everything runs in Docker.

---

## Step 1 — Clone and Configure (1 minute)

```bash
git clone https://github.com/[username]/bob.git
cd bob/bob-orchestrator/quickstart

cp .env.example .env
```

Now edit `.env` and add your Anthropic API key:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Save and close. The other variables have sensible defaults — you can leave them alone for the quickstart.

---

## Step 2 — Build and Start (3-5 minutes first time, <30 seconds after)

```bash
docker compose up --build
```

You'll see four containers building:

- **chromadb** — shared memory store
- **researcher** — research specialist agent
- **coder** — code specialist agent
- **bob** — the orchestrator

First build pulls the Python and ChromaDB images, which takes 3-5 minutes on a fresh machine. Subsequent runs reuse the cached layers and start in under 30 seconds.

When everything is ready, you'll see logs like:

```text
bob-quickstart           | INFO  Recovery monitor started
bob-quickstart           | INFO  MCP client loaded 5 tools from 2 server(s): ['researcher', 'coder']
bob-quickstart           | INFO  LangGraph agent built. BOB is online.
bob-quickstart           | INFO  Application startup complete.
bob-quickstart           | INFO  Uvicorn running on http://0.0.0.0:8100
```

The line that matters: **"MCP client loaded 5 tools from 2 server(s): ['researcher', 'coder']"**. That's BOB discovering the specialist agents and adding their tools to his toolkit. Without that line, MCP isn't working.

---

## Step 3 — Verify BOB Is Healthy (10 seconds)

In a new terminal:

```bash
curl http://localhost:8100/health
```

Expected response:

```json
{
  "status": "ok",
  "persona": "BOB the Skull",
  "uptime_seconds": 12,
  "graph_ready": true,
  "bus_queue_depth": 0
}
```

If you see `graph_ready: true`, BOB is alive and ready to chat.

Check the MCP status too:

```bash
curl http://localhost:8100/mcp/status | jq
```

You should see both the researcher and coder listed under `client.loaded_tools`.

---

## Step 4 — Talk to BOB (1 minute)

Send your first chat message:

```bash
curl -X POST http://localhost:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hi BOB, who are you?"}'
```

BOB will respond. Sardonic, dry, in character. Example:

```json
{
  "response": "Yes Boss. I'm BOB — Bound Operational Brain. Self-hosted multi-agent orchestrator. I have 35 native tools plus 5 more loaded from two specialist agents (researcher and coder). I push back when your plans are bad. What do you need?",
  "thread_id": "chat-1-1775xxxxxx",
  "tool_calls": null
}
```

If you got a response in BOB's voice, the orchestrator is working.

---

## Step 5 — Watch BOB Delegate to the Specialists (2 minutes)

Now the demo. Ask BOB to do something that requires both specialists:

```bash
curl -X POST http://localhost:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Research what the Model Context Protocol is, then write me a Python function that connects to an MCP server using the official SDK. Brief explanation only."}'
```

What happens under the hood:

1. **BOB receives the message.** He sees two tasks: research, then code.
2. **BOB calls the `research` tool** (from the researcher agent, fetched via MCP). The researcher uses Claude Haiku to compile findings about MCP.
3. **BOB receives the research output.** He uses it as context for the next step.
4. **BOB calls the `write_code` tool** (from the coder agent). The coder uses Claude Sonnet to produce a Python function based on BOB's spec.
5. **BOB combines both outputs** into a single response and returns it.

In the response JSON, you'll see the `tool_calls` array showing both delegations:

```json
{
  "response": "Here's what I found and the code you asked for...",
  "thread_id": "chat-2-1775xxxxxx",
  "tool_calls": [
    {"name": "research", "args": {"topic": "Model Context Protocol", "depth": "standard"}},
    {"name": "write_code", "args": {"spec": "...", "language": "python"}}
  ]
}
```

That's the orchestration pattern in action. **BOB doesn't write the research himself. He doesn't write the code himself. He coordinates two specialists and brings you the combined result.**

---

## Step 6 — Watch It Live (Optional)

Want to watch the action in real-time? In another terminal:

```bash
docker compose logs -f bob researcher coder
```

Then send another chat message and watch all three containers cooperate. You'll see the researcher and coder log their tool invocations as BOB calls them.

---

## What's Actually Happening

```text
You ──> POST /chat ──> BOB orchestrator
                          │
                          │ (LangGraph reasoning loop)
                          │
                          ├──> MCP call ──> researcher agent ──> Claude Haiku
                          │                       │
                          │ <─── findings ────────┘
                          │
                          ├──> MCP call ──> coder agent ──> Claude Sonnet
                          │                       │
                          │ <─── code ────────────┘
                          │
                          │ (combine + format)
                          │
You <─── response <───────┘
```

Every MCP tool call passes through BOB's firewall layer (`firewall.py`), which logs it to the audit trail and gates it by risk level. MCP-fetched tools default to MEDIUM risk — they execute but get logged prominently.

You can verify the audit log:

```bash
docker exec bob-quickstart cat /app/data/bob-audit.jsonl | head -10
```

Every tool call is there with timestamp, tool name, risk level, and the audit ID.

---

## Step 7 — Customize It

Want to make this real? Try these:

### Add a third specialist

Copy the `researcher/` directory to `marketer/`. Edit `marketer/server.py` to expose a `write_marketing_copy` tool. Add it to `mcp_servers.json`. Rebuild. BOB now has three specialists.

### Change the models

Edit `.env` and use cheaper or stronger models:

```bash
BOB_MODEL=claude-sonnet-4-5      # Cheaper orchestrator
RESEARCHER_MODEL=claude-haiku-4-5  # Fast research
CODER_MODEL=claude-opus-4-6       # Best code quality
```

Restart with `docker compose restart`.

### Connect to a real MCP server

Edit `mcp_servers.json` and add a public MCP server, like the official filesystem or fetch server. Now BOB has access to those tools too. See `../mcp_servers.example.json` for the format.

### Talk to BOB in a longer conversation

Use the `thread_id` from the response to continue the same conversation:

```bash
curl -X POST http://localhost:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Now review the code you just wrote.", "thread_id":"chat-2-1775xxxxxx"}'
```

BOB will remember the previous turn and call `review_code` on the coder agent.

---

## Stopping the Stack

```bash
# Stop containers but keep data
docker compose stop

# Stop and remove containers, networks (keeps named volumes)
docker compose down

# Stop, remove containers, AND wipe ChromaDB / BOB data
docker compose down -v
```

---

## Troubleshooting

**"MCP client loaded 0 tools" in BOB logs.**
The researcher and coder containers probably aren't reachable. Run `docker compose ps` and confirm both are `Up`. Then check the URLs in `mcp_servers.json` match the service names in `docker-compose.yml`.

**"ANTHROPIC_API_KEY missing" errors.**
You forgot to copy `.env.example` to `.env` or didn't add your key. Run `cat .env` and confirm the key is there and starts with `sk-ant-`.

**BOB starts but `/chat` returns 503.**
Wait 10 more seconds. BOB takes a moment to fetch the MCP tools and build the graph. The 503 means he's still waking up. The `/health` endpoint will return `graph_ready: false` until he's ready.

**"Address already in use" error during build.**
Another service is already using port 8100, 8000, 9001, or 9002. Stop it or change the ports in `docker-compose.yml`.

**Build is incredibly slow.**
First build downloads Python and ChromaDB images (~500MB). Subsequent builds reuse the cache and take seconds. If you're rebuilding constantly, use `docker compose up` (without `--build`) once the images are cached.

**Researcher / coder responses look wrong.**
The specialists use cheaper models by default to save tokens. If quality matters more than cost, set `RESEARCHER_MODEL` and `CODER_MODEL` to `claude-opus-4-6` in `.env` and restart.

---

## What This Doesn't Include

The quickstart is intentionally minimal. The full production stack adds:

- **Message bus** for pub/sub between agents (not just direct MCP calls)
- **Debate arena** with PM, RA, CE, QA agents that handle structured back-and-forth
- **Voice interface** with Deepgram + ElevenLabs and multi-user authentication
- **Public website chat widget**
- **ntfy push notifications** for critical events
- **Langfuse** for LLM observability and cost tracking
- **Uptime Kuma** for service monitoring
- **Gmail integration** for email triage
- **APScheduler** for recurring tasks
- **Daily briefings**
- **Recovery monitor** for paused tasks

To run the full stack, see `../docker-compose.yml` and `../README.md`. Note that the full stack requires more configuration (Cloudflare Tunnel, Gmail OAuth, ntfy setup, etc.) and is intended for self-hosted production use, not local development.

---

## Next Steps

If you got this far, you're ready for one of these:

- **Read [`MCP_INTEGRATION.md`](../MCP_INTEGRATION.md)** to understand how MCP works in BOB and how to add your own MCP servers.
- **Read [`ROADMAP.md`](../ROADMAP.md)** to see what's coming next.
- **Read [`CONTRIBUTING.md`](../CONTRIBUTING.md)** if you want to help build BOB.
- **Read [`../README.md`](../README.md)** for the full architecture and the production setup guide.

Or just keep playing with the quickstart. Add specialists, change models, see what BOB does when you give him conflicting instructions. He'll push back. That's the point.

---

*Yes Boss. You're up and running. — BOB*
