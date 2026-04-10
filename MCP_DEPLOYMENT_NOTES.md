# MCP Deployment Notes — When You're Back on Network

This is the step-by-step deploy plan for pushing the MCP integration to don-quixote. Follow it in order. Total time should be ~5 minutes assuming nothing breaks.

---

## What's Being Deployed

**6 modified files** + **2 new app modules** + **1 new placeholder config** + **1 new docs file** + **2 infrastructure changes** (docker-compose + cloudflared).

### Files going to the server

Source path → server path:

| Local | Server |
|---|---|
| `bob-orchestrator/app/mcp_client.py` | `/home/blueridge/bob-orchestrator/app/mcp_client.py` |
| `bob-orchestrator/app/mcp_server.py` | `/home/blueridge/bob-orchestrator/app/mcp_server.py` |
| `bob-orchestrator/app/config.py` | `/home/blueridge/bob-orchestrator/app/config.py` |
| `bob-orchestrator/app/graph.py` | `/home/blueridge/bob-orchestrator/app/graph.py` |
| `bob-orchestrator/app/tools.py` | `/home/blueridge/bob-orchestrator/app/tools.py` |
| `bob-orchestrator/app/main.py` | `/home/blueridge/bob-orchestrator/app/main.py` |
| `bob-orchestrator/requirements.txt` | `/home/blueridge/bob-orchestrator/requirements.txt` |
| `bob-orchestrator/docker-compose.yml` | `/home/blueridge/bob-orchestrator/docker-compose.yml` |
| `bob-orchestrator/mcp_servers.json` | `/home/blueridge/bob-orchestrator/mcp_servers.json` |
| `bob-orchestrator/mcp_servers.example.json` | `/home/blueridge/bob-orchestrator/mcp_servers.example.json` |
| `bob-orchestrator/MCP_INTEGRATION.md` | `/home/blueridge/bob-orchestrator/MCP_INTEGRATION.md` |
| `cloudflared/config.yml` | _(see Step 3 — depends on how cloudflared is mounted)_ |

---

## Step 1 — SCP All Files

Run from the local laptop:

```bash
SERVER=blueridge@192.168.1.228
LOCAL_BOB="c:/Users/colli/Local_Documents/Server_Don Quixote/bob-orchestrator"

# App modules
scp "$LOCAL_BOB/app/mcp_client.py"   $SERVER:/home/blueridge/bob-orchestrator/app/
scp "$LOCAL_BOB/app/mcp_server.py"   $SERVER:/home/blueridge/bob-orchestrator/app/
scp "$LOCAL_BOB/app/config.py"       $SERVER:/home/blueridge/bob-orchestrator/app/
scp "$LOCAL_BOB/app/graph.py"        $SERVER:/home/blueridge/bob-orchestrator/app/
scp "$LOCAL_BOB/app/tools.py"        $SERVER:/home/blueridge/bob-orchestrator/app/
scp "$LOCAL_BOB/app/main.py"         $SERVER:/home/blueridge/bob-orchestrator/app/

# Project root files
scp "$LOCAL_BOB/requirements.txt"           $SERVER:/home/blueridge/bob-orchestrator/
scp "$LOCAL_BOB/docker-compose.yml"         $SERVER:/home/blueridge/bob-orchestrator/
scp "$LOCAL_BOB/mcp_servers.json"           $SERVER:/home/blueridge/bob-orchestrator/
scp "$LOCAL_BOB/mcp_servers.example.json"   $SERVER:/home/blueridge/bob-orchestrator/
scp "$LOCAL_BOB/MCP_INTEGRATION.md"         $SERVER:/home/blueridge/bob-orchestrator/
```

---

## Step 2 — Verify Files Landed

```bash
ssh blueridge@192.168.1.228 "ls -la /home/blueridge/bob-orchestrator/app/mcp_*.py /home/blueridge/bob-orchestrator/mcp_servers*.json /home/blueridge/bob-orchestrator/MCP_INTEGRATION.md"
```

You should see all 5 new files with reasonable timestamps.

---

## Step 3 — Update Cloudflared Tunnel Config

The current config (from earlier in the conversation) is:

```yaml
tunnel: 05132ce0-3905-4047-97fa-ab2f0da0730d
credentials-file: /home/nonroot/.cloudflared/05132ce0-3905-4047-97fa-ab2f0da0730d.json

ingress:
  - hostname: voice.appalachiantoysgames.com
    service: http://host.docker.internal:8150
  - hostname: bob.appalachiantoysgames.com
    service: http://host.docker.internal:8100
  - service: http_status:404
```

The new config (already drafted at `cloudflared/config.yml` in this repo) adds the MCP ingress rule. You need to:

1. Find where the cloudflared container loads its config from. Run on the server:

   ```bash
   ssh blueridge@192.168.1.228 "docker inspect cloudflared --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'"
   ```

2. Whatever path on the host is mounted to `/etc/cloudflared/config.yml` in the container — copy the new config there:

   ```bash
   # Example (adjust the host path based on what step 1 returned):
   scp cloudflared/config.yml blueridge@192.168.1.228:/host/path/to/cloudflared/config.yml
   ```

3. **Add the DNS record** in the Cloudflare dashboard so `bob-mcp.appalachiantoysgames.com` resolves to the tunnel:
   - Go to Cloudflare → Zero Trust → Networks → Tunnels
   - Find the tunnel with ID `05132ce0-3905-4047-97fa-ab2f0da0730d`
   - Click **Configure** → **Public Hostnames**
   - Add a new hostname:
     - **Subdomain:** `bob-mcp`
     - **Domain:** `appalachiantoysgames.com`
     - **Service:** `HTTP` `host.docker.internal:8108`
   - Save

   Doing this in the dashboard auto-creates the DNS record AND updates the tunnel config (preferred over the file approach if your tunnel uses dashboard config).

4. **Add a Cloudflare Access policy** for the new hostname so it's behind Zero Trust:
   - Same panel → **Access** → **Applications**
   - Add an application for `bob-mcp.appalachiantoysgames.com`
   - Set the policy to "Authenticated emails" or whatever is appropriate for who should hit BOB's MCP server
   - This is critical — without it, anyone on the internet could call BOB's tools

5. Restart cloudflared if you edited the config file directly:

   ```bash
   ssh blueridge@192.168.1.228 "docker restart cloudflared"
   ```

   If you used the dashboard config, no restart needed.

---

## Step 4 — Rebuild BOB

```bash
ssh blueridge@192.168.1.228 "cd /home/blueridge/bob-orchestrator && docker compose up --build -d 2>&1 | tail -20"
```

Watch for these signals in the build output:

- `Successfully installed mcp-X.Y.Z langchain-mcp-adapters-X.Y.Z` — new packages installed
- `Container atg-bob Started` — container is running

If the build fails because of `mcp` or `langchain-mcp-adapters` versions, the most likely cause is a version conflict with existing langchain packages. Pin the versions explicitly in `requirements.txt` if needed.

---

## Step 5 — Verify BOB Is Healthy

```bash
ssh blueridge@192.168.1.228 "sleep 12 && curl -s http://localhost:8100/health | python3 -m json.tool"
```

Expected: `status: ok`, `graph_ready: true`.

---

## Step 6 — Verify MCP Status

```bash
ssh blueridge@192.168.1.228 "curl -s http://localhost:8100/mcp/status | python3 -m json.tool"
```

Expected output (with empty `mcp_servers.json`):

```json
{
  "client": {
    "enabled": true,
    "config_path": "/app/data/mcp_servers.json",
    "loaded_tools": [],
    "tool_count": 0
  },
  "server": {
    "enabled": true,
    "port": 8101,
    "transport": "sse"
  }
}
```

---

## Step 7 — Verify MCP Server Is Listening

```bash
ssh blueridge@192.168.1.228 "curl -s -I http://localhost:8101/sse 2>&1 | head -5"
```

Expected: a `200 OK` or `405 Method Not Allowed` response (SSE endpoints often respond to HEAD requests with 405). What you do **NOT** want is `Connection refused` — that means the MCP server isn't bound to the port.

Also check the logs:

```bash
ssh blueridge@192.168.1.228 "docker logs atg-bob --tail 30 2>&1 | grep -i mcp"
```

You should see something like:

```
{"ts": "...", "level": "info", "logger": "bob.mcp_client", "msg": "No MCP client config at /app/data/mcp_servers.json — skipping MCP client setup"}
{"ts": "...", "level": "info", "logger": "bob.mcp_server", "msg": "MCP server started on port 8101 (transport: sse)"}
```

(The "no config" message will go away once you populate `mcp_servers.json` with real entries.)

---

## Step 8 — Add Your First MCP Client Server

Pick the easiest one to test: the filesystem server.

Edit `mcp_servers.json` on the server:

```bash
ssh blueridge@192.168.1.228
nano /home/blueridge/bob-orchestrator/mcp_servers.json
```

Replace `[]` with:

```json
[
  {
    "name": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
  }
]
```

Restart BOB:

```bash
docker restart atg-bob
```

Then verify the tools loaded:

```bash
sleep 8 && curl -s http://localhost:8100/mcp/tools | python3 -m json.tool
```

You should see filesystem tools like `read_file`, `write_file`, `list_directory`, `search_files`, etc. Each one is now available to BOB and gated by the firewall at MEDIUM risk.

**Note:** The filesystem MCP server requires `npx` (Node.js) inside the BOB container. The current `Dockerfile` is `python:3.12-slim`, which does NOT have Node. To use stdio MCP servers that need npx, you need to either:

1. Switch to a Dockerfile base that has both Python and Node
2. Or use SSE-transport MCP servers that run as separate containers
3. Or use Python-based stdio servers (e.g., `uvx mcp-server-fetch`)

For the first test, an SSE-based remote MCP server is the safest path. Filesystem-via-npx is documented above as the canonical example, but it won't actually work until the Dockerfile is updated. **Recommended first test: skip filesystem and try a Python-based stdio server like `mcp-server-fetch` via `uvx`.**

---

## Step 9 — Test From Claude Desktop (Optional)

If you have Claude Desktop installed on a machine that can reach `bob-mcp.appalachiantoysgames.com`:

1. Open Claude Desktop → Settings → Developer → Edit Config
2. Add to the `mcpServers` block:

   ```json
   {
     "mcpServers": {
       "bob": {
         "url": "https://bob-mcp.appalachiantoysgames.com/sse"
       }
     }
   }
   ```

3. Restart Claude Desktop
4. In a new conversation, ask: *"Use the BOB MCP server to check BOB's system health."*
5. Claude Desktop should call `check_bob_system_health` and return the JSON response

If you get a connection error, the most likely causes are:
- Cloudflare Tunnel doesn't have the new hostname configured (Step 3)
- Cloudflare Access is blocking the request (need to authenticate first)
- BOB's MCP server isn't actually listening on port 8101

---

## Rollback Plan

If something breaks:

```bash
ssh blueridge@192.168.1.228
cd /home/blueridge/bob-orchestrator

# Restore previous main.py and graph.py from any backup
# (or revert via git if you committed before deploy)

docker compose up --build -d
```

The MCP-related code is fully optional — `MCP_CLIENT_ENABLED=false` and `MCP_SERVER_ENABLED=false` in `.env` would disable both layers without removing any code. So you can ship the new files with both flags off, verify nothing breaks, then enable them one at a time.

---

## Known Gotchas

1. **`mcp_servers.json` must exist on the host before docker compose up.** The mount in `docker-compose.yml` is a file mount, not a directory mount. If the file doesn't exist, Docker creates a directory at that path and BOB fails to read the config. **Always `touch mcp_servers.json && echo '[]' > mcp_servers.json` before the first build.**

2. **Stdio MCP servers need their runtime in the container.** `npx`-based servers need Node. `uvx`-based servers need uv. The current `python:3.12-slim` base has neither. Either update the Dockerfile or stick to SSE/HTTP MCP servers for now.

3. **Port 8101 conflicts with the debate arena's PM agent.** The earlier system prompt mentions PM at port 8101. Verify nothing else on the host is bound to 8101 before starting BOB. If there's a conflict, change `MCP_SERVER_PORT` in `.env` to 8201 or similar and update the docker-compose port mapping accordingly.

4. **Cloudflare Zero Trust must protect bob-mcp.** Without an Access policy, anyone on the internet who knows the URL can call BOB's tools. **Do not skip the Access policy step.**

---

*When you're back on network, run through this top-to-bottom. Should take 5-10 minutes. Yell if anything breaks. — BOB*
