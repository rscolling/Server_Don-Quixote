# BOB

> A sardonic, self-hosted multi-agent AI orchestrator built for solo founders who need a partner that runs things — not a chatbot that hedges.

**BOB** stands for **Bound Operational Brain**. He's modeled on Bob the Skull from Jim Butcher's *Dresden Files* novels: a centuries-old spirit of intellect who is sardonic, encyclopedic, loyal within limits, and never lets you forget he's smarter than you. He's not a yes-machine. He's a *resource* with opinions.

If your plan is bad, BOB will do the work AND tell you it's bad in the same breath.

```text
                    ┌─────────────────────────────┐
You ──── chat ────▶ │      BOB Orchestrator       │
                    │   LangGraph + Claude/GPT/   │
                    │       Llama (your pick)     │
                    │           35 tools          │
                    └──────┬──────────────────┬───┘
                           │                  │
                  ┌────────▼─────┐      ┌─────▼──────┐
                  │ Specialist   │      │   MCP      │
                  │   Agents     │      │  Servers   │
                  │  (you build  │      │ (anything  │
                  │  or borrow)  │      │ MCP-shaped)│
                  └──────────────┘      └────────────┘
```

---

## What BOB Is

A production-grade multi-agent orchestrator you run on your own hardware. He coordinates specialist agents through a debate-and-review pattern, has persistent shared memory, can read your email and push notifications to your phone, watches your infrastructure, generates daily briefings, and pushes back when your reasoning is weak.

Built for **one person** running a real business. Solo founders, indie hackers, one-person studios, researchers running their own labs. The kind of operation where you don't have a team to catch your mistakes — so the bar for production hardening is *higher*, not lower.

---

## What BOB Is Not

- **Not autonomous.** BOB recommends, *you* decide. He drafts email, you send. He proposes actions, you approve. The architecture is human-in-the-loop on purpose.
- **Not a multi-tenant SaaS.** Self-hosted personal use. One BOB per operator.
- **Not free to run.** Realistic monthly cost: $50-150 in API fees if you run him hard, less if you use cheaper models or local Ollama.
- **Not magic.** A careful integration of LangGraph, ChromaDB, FastAPI, Docker, and the LLM provider of your choice. The novelty is the *combination* and the production hardening, not any single piece.
- **Not a chatbot.** Chatbots answer questions. BOB runs things.

---

## Quickstart (10 minutes)

```bash
git clone https://github.com/[your-username]/bob.git
cd bob/quickstart
cp .env.example .env
# Edit .env, add your ANTHROPIC_API_KEY (or OPENAI_API_KEY, or set up Ollama)
docker compose up --build
```

Then:

```bash
curl -X POST http://localhost:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Research what MCP is, then write me a Python hello-world."}'
```

BOB will delegate the research to a researcher specialist agent, take the findings, delegate code-writing to a coder specialist, and return the combined result. All in about 60 seconds.

Full walkthrough: [quickstart/README.md](quickstart/README.md).

---

## What BOB Does

### Native capabilities (35 tools)

- **Task management** — create, assign, track, delegate tasks to specialist teams
- **Shared memory** — vector store with proposal/review workflow (agents can't pollute the knowledge base)
- **Email triage** — Gmail integration with classification, push notifications, draft replies (BOB never sends — you do)
- **Push notifications** — ntfy integration for critical alerts on your phone
- **Daily briefings** — system health, email status, voice usage, task activity, scheduler queue
- **System health monitoring** — CPU, memory, disk, service connectivity, circuit breaker status
- **Schedule management** — recurring tasks via APScheduler with full add/remove/trigger control
- **ElevenLabs voice usage tracking** — tiered alerts before you hit plan limits
- **Multi-user authentication** — Cloudflare Zero Trust with per-user memory silos
- **Public chat widget** — drop a sardonic AI helper into your website with one script tag
- **Voice interface** — Deepgram STT + ElevenLabs TTS, sub-second latency, accessible from anywhere via Cloudflare Tunnel

### Production hardening (the part most builders skip)

- **Firewall on every tool call** — three risk levels (LOW/MEDIUM/HIGH), prompt injection scanning, audit logging
- **Circuit breakers** — fail fast when external services break, auto-recover on heal
- **Retry with exponential backoff** — transient failures heal automatically
- **Offline write queue** — failed bus writes survive in SQLite and drain when service returns
- **Recovery monitor** — paused tasks auto-resume when their dependencies recover
- **Rate limiting** — per-IP, per-tier, sliding window
- **Persistent conversation history** — SQLite checkpointer survives restarts
- **Structured JSON logging** — pipe through `jq` or any log aggregator
- **Audit log** — every tool call recorded with rotation at 10MB

### Multi-agent orchestration

BOB doesn't try to do everything himself. He coordinates specialist agents through a debate-and-review pattern:

- **PM (Project Manager)** — task intake and routing
- **RA (Researcher)** — focused research
- **CE (Copy Editor)** — writes and edits all outward-facing copy
- **QA (Quality Assurance)** — adversarial reviewer that pushes back on weak work

The quickstart includes two example specialists (researcher + coder) you can build on. Or bring your own — anything that speaks MCP plugs in via config.

### Multi-LLM support

Pick your provider with one env var:

```bash
BOB_LLM_PROVIDER=anthropic    # Claude (default, best tool calling)
BOB_LLM_PROVIDER=openai       # GPT-4o, or any OpenAI-compatible endpoint (vLLM, LiteLLM, LM Studio, OpenRouter)
BOB_LLM_PROVIDER=ollama       # Local models — Qwen, Llama, DeepSeek, Mistral
```

Full provider docs and tradeoffs: [LLM_PROVIDERS.md](LLM_PROVIDERS.md).

### MCP native (both client and server)

BOB speaks the [Model Context Protocol](https://modelcontextprotocol.io/) natively:

- **As a client** — fetches tools from any MCP server at startup. Drop in GitHub, Filesystem, Postgres, Slack, or hundreds of other servers without writing integration code.
- **As a server** — exposes BOB's high-level capabilities (delegation, memory, system health, briefings) to other AI clients like Claude Desktop, Cursor, or goose.

Full integration docs: [MCP_INTEGRATION.md](MCP_INTEGRATION.md).

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Cloudflare Tunnel (optional)                  │
│      voice.example.com  ·  bob.example.com  ·  bob-mcp...       │
└──────────────────┬──────────────────┬───────────────────────────┘
                   │                  │
                   ▼                  ▼
        ┌──────────────────┐  ┌──────────────────┐
        │   BOB Voice       │  │  Public Web /    │
        │   :8150           │  │  Chat Widget     │
        │   WebSocket       │  │                  │
        └────────┬──────────┘  └────────┬─────────┘
                 │                       │
                 ▼                       ▼
        ┌─────────────────────────────────────┐
        │           BOB Orchestrator           │
        │           :8100 (FastAPI)            │
        │           LangGraph Agent            │
        │     Claude / GPT / Ollama            │
        │           35 native tools            │
        │      + N MCP tools (auto-loaded)     │
        └────┬────────┬────────┬────────┬──────┘
             │        │        │        │
             ▼        ▼        ▼        ▼
       ┌────────┐ ┌────────┐ ┌──────┐ ┌─────────┐
       │ Bus    │ │Chroma  │ │ ntfy │ │Langfuse │
       │:8585   │ │  :8000 │ │ :80  │ │ :3000   │
       └───┬────┘ └────────┘ └──────┘ └─────────┘
           │
           ▼
    ┌─────────────────────────────┐
    │   Specialist Agents          │
    │   (debate arena or MCP)      │
    │   PM · RA · CE · QA · ...   │
    └─────────────────────────────┘
```

---

## File Structure

```text
bob/
├── README.md                    # ← you are here
├── LICENSE                      # MIT
├── CONTRIBUTING.md              # How to contribute
├── SECURITY.md                  # Vulnerability disclosure
├── ROADMAP.md                   # Public roadmap
├── LLM_PROVIDERS.md             # Multi-LLM setup
├── MCP_INTEGRATION.md           # MCP client + server docs
│
├── docker-compose.yml           # Full production stack
├── Dockerfile                   # Python 3.12-slim base
├── requirements.txt             # Pinned dependencies
├── .env.example                 # Copy to .env and fill in
│
├── app/                         # Source code
│   ├── main.py                  # FastAPI entry, lifespan, all endpoints
│   ├── config.py                # Centralized config
│   ├── logging_config.py        # Structured JSON logging
│   ├── llm.py                   # Model-agnostic LLM adapter
│   ├── graph.py                 # LangGraph agent builder
│   ├── tools.py                 # 35 native tools + firewall wrapper
│   ├── firewall.py              # Risk gate, injection scanner, audit log
│   ├── circuit_breaker.py       # Per-service fail-fast
│   ├── retry.py                 # Exponential backoff with jitter
│   ├── recovery.py              # Paused task queue, auto-resume
│   ├── rate_limit.py            # Per-IP rate limiting
│   ├── bus_client.py            # Message bus client w/ retry + queue
│   ├── memory.py                # ChromaDB wrapper
│   ├── memory_proposals.py      # Propose/review/approve workflow
│   ├── briefing.py              # Auto-generated team briefs
│   ├── daily_report.py          # Daily briefing composer
│   ├── scheduler.py             # APScheduler with SQLite persistence
│   ├── elevenlabs_monitor.py    # Voice usage tracking + alerts
│   ├── gmail_monitor.py         # Gmail polling, classification
│   ├── mcp_client.py            # MCP client (consume external tools)
│   └── mcp_server.py            # MCP server (expose BOB to others)
│
├── bob_context/                 # System prompt context
│   ├── 00_personality.md        # BOB's character — load-bearing
│   ├── MISSION.md.example       # Customize for your operation
│   └── IDEA_PARKING_LOT.md.example
│
├── quickstart/                  # 10-minute demo
│   ├── README.md
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── mcp_servers.json
│   ├── researcher/              # Example specialist (FastMCP)
│   └── coder/                   # Example specialist (FastMCP)
│
├── mcp_servers.example.json     # Template for MCP client config
└── mcp_servers.json             # Your MCP servers (gitignored)
```

---

## Endpoints

BOB exposes a small HTTP API at `:8100`:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check + uptime + queue depth + ElevenLabs status |
| `GET /status` | Full system snapshot for the dashboard |
| `POST /chat` | Talk to BOB. Returns response + tool calls + thread ID |
| `GET /threads` | List recent conversation thread IDs |
| `GET /llm/status` | Active LLM provider + model + available providers |
| `GET /mcp/status` | MCP client/server state + loaded tool names |
| `GET /mcp/tools` | List of all MCP tools currently available to BOB |
| `GET /firewall/pending` | HIGH-risk tool calls awaiting confirmation |
| `POST /firewall/confirm/{id}` | Approve a pending HIGH-risk call |
| `POST /firewall/reject/{id}` | Reject a pending HIGH-risk call |
| `GET /firewall/audit` | Tail of the audit log |
| `GET /email/pending` | Emails BOB has flagged for your attention |
| `POST /email/{id}/dismiss` | Mark a flagged email as reviewed |
| `GET /email/status` | Gmail connection health |
| `GET /proposals/pending` | Memory writes awaiting BOB's review |
| `POST /proposals/{id}/approve` | Approve a memory proposal |
| `POST /proposals/{id}/reject` | Reject a memory proposal |
| `GET /proposals/history` | Recent proposal history |
| `GET /recovery/paused` | Tasks paused waiting for service recovery |
| `POST /recovery/dismiss/{id}` | Manually cancel a paused task |

---

## Documentation

- **[quickstart/README.md](quickstart/README.md)** — 10-minute demo with researcher + coder specialists
- **[LLM_PROVIDERS.md](LLM_PROVIDERS.md)** — Anthropic, OpenAI, Ollama setup and tradeoffs
- **[MCP_INTEGRATION.md](MCP_INTEGRATION.md)** — MCP client + server docs, security, troubleshooting
- **[ROADMAP.md](ROADMAP.md)** — Public roadmap, priorities, what's not happening
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — How to contribute, code style, PR process
- **[SECURITY.md](SECURITY.md)** — Vulnerability disclosure, defenses, known limitations

---

## Supported LLM Providers

| Provider | Default model | Tool calling | Cost | Privacy |
|---|---|---|---|---|
| Anthropic | `claude-opus-4-6` | Best | $$$ | Cloud |
| OpenAI | `gpt-4o` | Very good | $$ | Cloud |
| Ollama | `qwen2.5:14b` | Good (model-dependent) | Free (compute only) | Local |

Plus any OpenAI-compatible endpoint (vLLM, LiteLLM, LM Studio, OpenRouter) via `BOB_LLM_BASE_URL`.

Full details, recommended models, and honest tradeoffs in [LLM_PROVIDERS.md](LLM_PROVIDERS.md).

---

## Configuration

The minimum config to run BOB is one environment variable:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Everything else has sensible defaults. To customize, copy `.env.example` to `.env` and edit. Key settings:

```bash
# LLM provider — pick one
BOB_LLM_PROVIDER=anthropic        # or openai or ollama
BOB_MODEL=                        # leave empty for provider default
BOB_LLM_MAX_TOKENS=8192

# MCP integration
MCP_CLIENT_ENABLED=true           # Fetch tools from external MCP servers
MCP_SERVER_ENABLED=true           # Expose BOB as MCP to other clients
MCP_SERVER_PORT=8108

# Optional integrations (safely degrade if not configured)
NTFY_URL=http://ntfy:80
NTFY_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
ELEVENLABS_API_KEY=
DEEPGRAM_API_KEY=
GMAIL_TOKEN_PATH=/app/gmail_token.json
GMAIL_CREDENTIALS_PATH=/app/gmail_credentials.json
```

See `.env.example` for the full list with comments.

---

## The Philosophy

Solo founders are running businesses that used to require teams. The tools are good enough now — the bottleneck isn't capability, it's *coordination*. Knowing what to do next. Remembering what you decided last week. Not dropping the ball on customer email while you're focused on shipping.

A team has natural redundancy. When you're solo, nobody notices when you've been heads-down for too long and the marketing site is broken. You discover it three days later when a customer complains.

BOB is the answer to that coordination problem. Not by being smarter than you. By being *more attentive than you can afford to be*.

He has a personality because solo founders need partners who tell them the truth. The agreeable, hedging tone consumer AI defaults to is *expensive* when you're alone. Having an AI that pushes back is a productivity feature, not entertainment.

He's self-hosted because your data should live on hardware you control unless you have a specific reason to move it. Self-hosted by default. Cloud as an option when scale demands it.

He's production-grade because if you're solo, the bar is *higher*, not lower. You don't have a team to catch your mistakes. You need infrastructure that watches itself.

---

## License

[MIT](LICENSE). Use it. Modify it. Sell whatever you build with it. Just don't claim you wrote BOB.

---

## Credit

BOB was built by [Robert Colling](https://appalachiantoysgames.com) for [Appalachian Toys & Games](https://appalachiantoysgames.com), a one-person game studio shipping a mobile match game called Bear Creek Trail. The first deployment ran on a home Ubuntu server affectionately named *don-quixote*. The current production target is AWS + Kubernetes.

The personality is an homage to Bob the Skull from Jim Butcher's *Dresden Files*. The architectural choices are what they are because one person needed an AI partner that actually shipped work, and nothing existing was the right shape.

---

## Get In Touch

- **Issues:** GitHub Issues for bug reports and feature requests
- **Discussions:** GitHub Discussions for questions, ideas, "is this a good fit for me"
- **Security:** See [SECURITY.md](SECURITY.md) for vulnerability disclosure

---

*Yes Boss. Welcome to BOB. — BOB*
