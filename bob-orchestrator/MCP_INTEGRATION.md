# MCP Integration

BOB speaks the **Model Context Protocol** (MCP) — both as a client (consuming external MCP tools) and as a server (exposing his capabilities to other AI clients).

This document covers what's wired up, how to configure it, and how to test it.

---

## Why MCP

Two reasons.

**As a client:** Every new capability used to mean writing custom Python code (Gmail, ElevenLabs, scheduler). With MCP, BOB can consume any of the hundreds of pre-built MCP servers — GitHub, Linear, Notion, Slack, Postgres, Stripe, Sentry, Filesystem, Fetch, Memory, etc. — by adding a config entry. No new code, no deploy cycle.

**As a server:** Other AI clients (Claude Desktop, Cursor, goose, another BOB instance) can now call BOB's debate arena, query his shared memory, check infrastructure health, and generate briefings. BOB stops being a closed product and becomes infrastructure other clients build on.

---

## Architecture

```
External MCP servers (GitHub, Filesystem, etc.)
        │
        ▼  (langchain-mcp-adapters)
┌───────────────────────────┐
│  BOB MCP Client           │
│  (mcp_client.py)          │ ──── tools fetched at startup
└──────────┬────────────────┘
           ▼
┌───────────────────────────┐
│  Firewall wrapper         │ ──── MCP tools registered as MEDIUM risk
│  (wrap_mcp_tool)          │
└──────────┬────────────────┘
           ▼
┌───────────────────────────┐
│  LangGraph agent          │ ──── ALL_TOOLS + MCP tools
│  (BOB)                    │
└──────────┬────────────────┘
           ▼
┌───────────────────────────┐    ┌─────────────────────────────┐
│  BOB MCP Server           │ ──>│  External AI clients        │
│  (mcp_server.py, port 8101)│    │  (Claude Desktop, Cursor,   │
│  Exposes: delegate, recall,│    │   goose, another BOB, etc.) │
│  health, briefing, paused │    └─────────────────────────────┘
└───────────────────────────┘
```

---

## Files

| File | Purpose |
|---|---|
| `app/mcp_client.py` | Fetches tools from external MCP servers at startup |
| `app/mcp_server.py` | Exposes BOB's high-level capabilities as MCP tools (FastMCP server) |
| `app/config.py` | MCP config — paths, ports, enable/disable flags |
| `app/graph.py` | `build_graph()` accepts `extra_tools` for fetched MCP tools |
| `app/tools.py` | `wrap_mcp_tool()` applies the firewall to MCP tools |
| `app/main.py` | Lifespan: fetch MCP tools → build graph → start MCP server |
| `mcp_servers.example.json` | Example config showing all transports |
| `MCP_INTEGRATION.md` | This file |

---

## Configuration

All MCP config lives in `app/config.py` and is overridable via env vars.

### MCP client (consume external tools)

| Env var | Default | Purpose |
|---|---|---|
| `MCP_CLIENT_ENABLED` | `true` | Set to `false` to disable MCP client entirely |
| `MCP_CLIENT_CONFIG_PATH` | `/app/data/mcp_servers.json` | Path to JSON file listing servers BOB connects to |
| `MCP_CLIENT_FETCH_TIMEOUT` | `15.0` | Seconds to wait for tool fetch on startup |

### MCP server (expose BOB to other clients)

| Env var | Default | Purpose |
|---|---|---|
| `MCP_SERVER_ENABLED` | `true` | Set to `false` to disable BOB's MCP server |
| `MCP_SERVER_PORT` | `8108` | Port for the MCP server (8101-8104 reserved for debate arena) |
| `MCP_SERVER_TRANSPORT` | `sse` | `sse` or `streamable-http` |
| `MCP_SERVER_AUTH_TOKEN` | _(empty)_ | Optional bearer token. Leave empty if behind Cloudflare Tunnel |

---

## Setting Up MCP Servers BOB Connects To

Create `/home/blueridge/bob-orchestrator/mcp_servers.json` (or whatever path matches `MCP_CLIENT_CONFIG_PATH`). The format is a JSON array of server configs.

### Example: Filesystem server (stdio)

Lets BOB read/write files in a specific directory.

```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data/shared"]
  }
]
```

### Example: GitHub server (SSE)

```json
[
  {
    "name": "github",
    "transport": "sse",
    "url": "https://mcp.example.com/github/sse",
    "headers": {
      "Authorization": "Bearer ghp_xxxxxxxxxxxxxxxxxxxx"
    }
  }
]
```

### Example: Multiple servers at once

```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data/shared"]
  },
  {
    "name": "fetch",
    "transport": "stdio",
    "command": "uvx",
    "args": ["mcp-server-fetch"]
  },
  {
    "name": "postgres",
    "transport": "streamable-http",
    "url": "http://postgres-mcp:9001/mcp"
  }
]
```

See `mcp_servers.example.json` for a working template.

---

## How BOB Uses MCP Tools

When BOB starts up, the lifespan handler does this in order:

1. Initialize ChromaDB collections
2. Register on the message bus
3. **Fetch MCP tools** from all configured servers via `init_mcp_client()`
4. Build the LangGraph agent with `ALL_TOOLS + mcp_tools`
5. Start the scheduler, Gmail monitor, recovery monitor
6. **Start the MCP server** on `MCP_SERVER_PORT` (default 8101)
7. Yield to FastAPI

If MCP tool fetch fails (server unreachable, timeout, malformed config), BOB logs a warning and starts without those tools. The native tools always work.

Every MCP tool that gets loaded passes through `wrap_mcp_tool()`, which:

- Adds the tool name to the firewall `TOOL_REGISTRY` at MEDIUM risk by default
- Wraps the tool's coroutine with `_firewall_wrap()` so every call goes through the gate
- Audit-logs every invocation alongside native tool calls

If you want to mark a specific MCP tool as LOW risk (read-only) or HIGH risk (requires confirmation), edit `firewall.py` and add an explicit entry:

```python
TOOL_REGISTRY = {
    # ...
    "github_create_pull_request": RiskLevel.HIGH,
    "filesystem_read_file": RiskLevel.LOW,
}
```

---

## How Other Clients Talk to BOB

BOB's MCP server runs on `:8101` by default and exposes these tools:

| Tool | What it does |
|---|---|
| `delegate_to_bob_team` | Delegate a task to BOB's debate arena with auto-generated brief |
| `recall_bob_memory` | Search BOB's shared memory (brand_voice, decisions, etc.) |
| `list_bob_memory_collections` | List all available memory collections |
| `check_bob_system_health` | Check status of all infrastructure services |
| `generate_bob_briefing` | Generate the daily operational briefing |
| `list_bob_paused_tasks` | List tasks paused waiting for service recovery |

Plus two MCP **resources**:

| Resource URI | What it returns |
|---|---|
| `bob://mission` | BOB's current mission and project context (MISSION.md) |
| `bob://personality` | BOB's personality definition (00_personality.md) |

### Connecting Claude Desktop to BOB

Add this to Claude Desktop's MCP config:

```json
{
  "mcpServers": {
    "bob": {
      "url": "https://bob.appalachiantoysgames.com:8101/sse"
    }
  }
}
```

Claude Desktop will fetch BOB's tools and resources, and you can call them directly from a Claude Desktop conversation.

### Connecting Cursor to BOB

Cursor's `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "bob": {
      "url": "https://bob.appalachiantoysgames.com:8101/sse"
    }
  }
}
```

---

## Verification

### Check MCP status from the dashboard

```bash
curl http://localhost:8100/mcp/status | jq
```

Should return both client and server state, including the list of loaded tool names.

### List all MCP tools BOB has loaded

```bash
curl http://localhost:8100/mcp/tools | jq
```

### Test BOB's MCP server is reachable

```bash
curl http://localhost:8101/sse
```

Should respond with an SSE stream (or 404 if the server isn't running).

### Manual test of an MCP tool

In BOB's chat interface, ask him to use a tool from one of your configured MCP servers. For example, if you have the filesystem server connected:

> "BOB, list the files in /data/shared and tell me what's there."

BOB should call the appropriate MCP tool and return the results.

---

## Security Considerations

1. **Every MCP tool passes through the firewall.** Even though MCP tools come from external code, they can't bypass the security gate. Every call is audit-logged.

2. **MCP tools default to MEDIUM risk.** That means they execute but get logged prominently. Promote sensitive ones to HIGH (requires confirmation) by editing `TOOL_REGISTRY` in `firewall.py`.

3. **The MCP server should be behind Cloudflare Zero Trust** when exposed publicly. Set `MCP_SERVER_AUTH_TOKEN` only if you need an additional layer for direct in-network calls.

4. **Don't trust MCP server descriptions blindly.** A malicious or buggy MCP server could put dangerous instructions in tool descriptions. The firewall's prompt injection scanner catches the obvious patterns.

5. **stdio transport runs subprocesses.** Be deliberate about which `command` values you allow in your config — they're executed as the BOB user inside the container.

---

## Troubleshooting

**MCP tools not loading at startup**

- Check `MCP_CLIENT_ENABLED=true`
- Check the config file exists at `MCP_CLIENT_CONFIG_PATH`
- Check the JSON is valid (`jq < mcp_servers.json`)
- Check container logs for "MCP client loaded N tools" or warning messages
- For stdio servers, make sure the command (`npx`, `uvx`, etc.) is installed in the container

**MCP server not reachable from outside**

- Confirm `MCP_SERVER_ENABLED=true`
- Check `docker ps` shows port 8101 mapped
- Update `docker-compose.yml` to publish port 8101
- Add a Cloudflare Tunnel rule for the MCP subdomain if exposing publicly

**Tool calls returning errors**

- Check `/firewall/audit` for audit log entries
- Check `/mcp/status` to confirm the tool is loaded
- Check the upstream MCP server logs (BOB doesn't see those — go to the source)

**Importing `langchain_mcp_adapters` fails**

- Make sure `requirements.txt` has `langchain-mcp-adapters>=0.1.0` and you've rebuilt the container
- Check `docker exec atg-bob pip show langchain-mcp-adapters`

---

## What's Not Done Yet

- **Per-MCP-tool risk overrides via config file.** Today you have to edit `firewall.py` to promote a tool to HIGH risk. A future enhancement could read these from a `mcp_risk_overrides.json` alongside the server config.
- **Hot reload of MCP servers.** Adding a new server today requires a BOB restart. Hot reload would require watching the config file and reconnecting.
- **MCP server rate limiting.** The MCP server itself doesn't rate-limit incoming calls. The native `/chat` endpoint does, via `rate_limit.py`. Adding it to MCP would need a wrapper around each exposed tool.
- **Bidirectional MCP federation.** Today BOB can talk to other MCP servers (client) and other clients can talk to BOB (server). The next step is a "BOB-to-BOB" pattern where two BOB instances share work via MCP. The infrastructure exists; the orchestration logic doesn't.

---

*Yes Boss. MCP is wired in. Drop a config file and rebuild. — BOB*
