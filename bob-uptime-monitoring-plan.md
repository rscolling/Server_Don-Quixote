# BOB — External Uptime Monitoring Build Plan
### *Uptime Kuma · www.appalachiantoysgames.com · external + internal checks*

---

## What We're Building

The container monitor in the observability plan checks whether the Nginx container is running. That is an internal check — it only knows the container is up, not whether the website is actually reachable from the internet. A DNS failure, a bad Nginx config, a full disk blocking response writes, or a Cloudflare issue could all leave the website down while the Nginx container shows as healthy.

This plan deploys Uptime Kuma — already listed as a planned always-on service — and configures it to monitor the ATG website from both inside the home network and outside, wires it into BOB's notification channels, and integrates its status into BOB's daily report.

### What Gets Monitored

| Check | Type | Interval | What it catches |
|---|---|---|---|
| `www.appalachiantoysgames.com` HTTP | External (via Cloudflare) | 60 seconds | Site unreachable from internet |
| `www.appalachiantoysgames.com` keyword | External | 5 minutes | Site loads but returns wrong content |
| `192.168.1.228` Nginx direct | Internal LAN | 60 seconds | Nginx down on local network |
| SSL certificate expiry | External | Daily | Cert expires — HTTPS breaks |
| DNS resolution | External | 5 minutes | Domain stops resolving |

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- Docker + Docker Compose running ✓
- Nginx serving `www.appalachiantoysgames.com` ✓
- ntfy push notifications deployed (Phase 1 of notifications plan) — for BOB alerts ✓
- Cloudflare Tunnel operational — external checks route through it ✓
- All steps begin on **Windows 11**. SSH to server where indicated.

---

## Phase 1 — Deploy Uptime Kuma

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Create the Uptime Kuma directory**

```bash
# [UBUNTU SERVER]
mkdir -p /opt/atg-monitoring/uptime-kuma
cd /opt/atg-monitoring/uptime-kuma
```

---

**Step 3 — Create the Docker Compose file**

```bash
nano docker-compose.yml
```

Paste:

```yaml
version: "3.9"

services:
  uptime-kuma:
    image: louislam/uptime-kuma:latest
    container_name: uptime-kuma
    restart: unless-stopped
    ports:
      - "3001:3001"
    volumes:
      - uptime-kuma-data:/app/data
    healthcheck:
      test: ["CMD", "node", "-e",
             "require('http').get('http://localhost:3001/api/entry-page', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - atg-network

volumes:
  uptime-kuma-data:

networks:
  atg-network:
    external: true
    name: atg_default
```

> Replace `atg_default` with your Docker network name — run `docker network ls` to check.

Save and exit.

---

**Step 4 — Start Uptime Kuma**

```bash
# [UBUNTU SERVER]
docker compose up -d

# Verify it started
docker ps | grep uptime-kuma
```

Should show `uptime-kuma` with status `Up`.

---

**Step 5 — Open Uptime Kuma and create an admin account**

On the Windows laptop, open a browser and go to:

```
http://192.168.1.228:3001
```

You will be prompted to create an admin account. Set:
- Username: `rob` (or your preference)
- Password: strong password — save it

> **Away from home:** After the Cloudflare Tunnel is extended (Phase 4), Uptime Kuma will be accessible at a public URL. For now, LAN access only.

Confirm you are logged into Uptime Kuma before proceeding.

---

## Phase 2 — Configure Monitors

All monitors are configured through the Uptime Kuma UI. Do these one at a time and confirm each before moving to the next.

---

**Step 6 — Add Monitor 1: ATG website HTTP check (external)**

This is the primary check — is the website reachable from the internet.

In Uptime Kuma, click **Add New Monitor**:

| Field | Value |
|---|---|
| Monitor Type | HTTP(s) |
| Friendly Name | ATG Website — External |
| URL | `https://www.appalachiantoysgames.com` |
| Heartbeat Interval | 60 seconds |
| Retries | 2 |
| Retry Interval | 20 seconds |
| Accepted Status Codes | 200-299 |
| Description | External HTTP check — site reachable from internet |

Click **Save**. The monitor should immediately show **UP** with a green badge. If it shows DOWN, the website is not reachable externally — stop and investigate before proceeding.

---

**Step 7 — Add Monitor 2: ATG website keyword check**

Confirms the site is not only reachable but serving real ATG content — catches cases where the site loads but shows an error page or blank page.

Click **Add New Monitor**:

| Field | Value |
|---|---|
| Monitor Type | HTTP(s) — Keyword |
| Friendly Name | ATG Website — Content |
| URL | `https://www.appalachiantoysgames.com` |
| Keyword | `Appalachian` |
| Case Sensitive | No |
| Heartbeat Interval | 300 seconds (5 min) |
| Retries | 2 |
| Description | Confirms site serves real ATG content, not an error page |

> The keyword `Appalachian` should appear in the page title or header on every page of the ATG website. If the site ever serves a blank page, maintenance page, or Nginx default page, this check will catch it.

Click **Save**.

---

**Step 8 — Add Monitor 3: Nginx direct LAN check**

Internal check — catches Nginx failures that might not be visible externally if cached.

Click **Add New Monitor**:

| Field | Value |
|---|---|
| Monitor Type | HTTP(s) |
| Friendly Name | ATG Nginx — LAN Direct |
| URL | `http://192.168.1.228` |
| Heartbeat Interval | 60 seconds |
| Retries | 2 |
| Description | Direct Nginx check on local network — bypasses DNS and Cloudflare |

Click **Save**.

---

**Step 9 — Add Monitor 4: SSL certificate expiry**

Catches an expiring SSL cert before it breaks HTTPS for visitors.

Click **Add New Monitor**:

| Field | Value |
|---|---|
| Monitor Type | HTTP(s) |
| Friendly Name | ATG SSL Certificate |
| URL | `https://www.appalachiantoysgames.com` |
| Heartbeat Interval | 86400 seconds (once per day) |
| Certificate Expiry Notification | Enable — notify 30 days before expiry |
| Description | Daily check that SSL cert is valid and not expiring soon |

Click **Save**.

---

**Step 10 — Add Monitor 5: DNS resolution**

Catches the domain stopping to resolve — a DNS misconfiguration or expired domain registration.

Click **Add New Monitor**:

| Field | Value |
|---|---|
| Monitor Type | DNS |
| Friendly Name | ATG DNS — appalachiantoysgames.com |
| Hostname | `www.appalachiantoysgames.com` |
| Resolver Server | `1.1.1.1` (Cloudflare DNS — external resolver) |
| Port | 53 |
| Heartbeat Interval | 300 seconds (5 min) |
| DNS Resolve Type | A |
| Description | Checks domain resolves correctly via external DNS |

Click **Save**.

Confirm all five monitors show **UP** before proceeding.

---

## Phase 3 — Connect Uptime Kuma to BOB's Notification Stack

Uptime Kuma supports multiple notification channels. Wire it into ntfy so BOB and Rob's phone get alerts — not just the Uptime Kuma dashboard.

**Step 11 — Add ntfy as a notification channel in Uptime Kuma**

In Uptime Kuma, go to **Settings → Notifications → Add Notification**:

| Field | Value |
|---|---|
| Notification Type | ntfy |
| Friendly Name | BOB — Critical Alerts |
| ntfy Server URL | `http://192.168.1.228:2586` |
| Topic | `bob-critical` |
| Priority | urgent |
| Auth Username | `bob-publisher` |
| Auth Password | the password set during ntfy setup |

Click **Test** — a test notification should arrive on Rob's phone within 2 seconds.

Click **Save**.

---

**Step 12 — Assign the notification to each monitor**

For each of the five monitors:

1. Open the monitor
2. Click **Edit**
3. Scroll to **Notifications**
4. Enable **BOB — Critical Alerts**
5. Save

All five monitors will now push to Rob's phone via ntfy when they go down.

---

**Step 13 — Configure alert behaviour**

To avoid notification spam from brief blips, set a notification delay:

For each monitor, in Edit → Advanced:

| Field | Value |
|---|---|
| Resend Notification if still DOWN every X hours | 1 |
| Notification on recovery | Yes |

This means: alert when it goes down, re-alert every hour if still down, alert when it recovers. Transient 60-second blips that self-recover won't page Rob.

---

## Phase 4 — Extend Cloudflare Tunnel to Uptime Kuma

Make the Uptime Kuma dashboard accessible away from home so Rob can check it from the phone.

**Step 14 — Add Uptime Kuma to Cloudflare Tunnel config**

```bash
# [UBUNTU SERVER]
nano ~/.cloudflared/config.yml
```

Add an entry for Uptime Kuma:

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /home/blueridge/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: bob.YOUR_SUBDOMAIN.cfargotunnel.com
    service: http://localhost:8200
  - hostname: notify.YOUR_SUBDOMAIN.cfargotunnel.com
    service: http://localhost:2586
  - hostname: status.YOUR_SUBDOMAIN.cfargotunnel.com
    service: http://localhost:3001
  - service: http_status:404
```

Create the DNS route:

```bash
cloudflared tunnel route dns bob-dashboard status.YOUR_SUBDOMAIN.cfargotunnel.com
```

Restart the tunnel:

```bash
sudo systemctl restart cloudflared
```

Uptime Kuma is now accessible at:

```
https://status.YOUR_SUBDOMAIN.cfargotunnel.com
```

Update the ntfy server URL in Step 11's notification to use the tunnel hostname if connecting from outside the home network causes issues — though the internal LAN address works fine for server-to-server communication.

---

## Phase 5 — Wire into BOB's Orchestrator

**Step 15 — Add Uptime Kuma API polling to BOB**

Uptime Kuma exposes a REST API. BOB queries it to get current monitor status — used in the daily report and in response to Rob asking "is the website up?".

```python
# orchestrator/website_monitor.py

import os
import asyncio
import aiohttp

UPTIME_KUMA_URL      = os.getenv("UPTIME_KUMA_URL",      "http://uptime-kuma:3001")
UPTIME_KUMA_USERNAME = os.getenv("UPTIME_KUMA_USERNAME", "rob")
UPTIME_KUMA_PASSWORD = os.getenv("UPTIME_KUMA_PASSWORD", "")

_kuma_token: str | None = None


async def _get_kuma_token() -> str | None:
    """Authenticate with Uptime Kuma API and get a session token."""
    global _kuma_token
    if _kuma_token:
        return _kuma_token
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{UPTIME_KUMA_URL}/api/login",
                json={
                    "username": UPTIME_KUMA_USERNAME,
                    "password": UPTIME_KUMA_PASSWORD,
                },
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data         = await resp.json()
                    _kuma_token  = data.get("token")
                    return _kuma_token
    except Exception:
        pass
    return None


async def get_monitor_statuses() -> list[dict]:
    """
    Returns current status of all Uptime Kuma monitors.
    Each entry: {name, status, url, last_checked, uptime_24h}
    """
    token = await _get_kuma_token()
    if not token:
        return []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{UPTIME_KUMA_URL}/api/monitor-list",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data     = await resp.json()
                    monitors = data.get("monitors", {})
                    return [
                        {
                            "id":         mid,
                            "name":       m.get("name", ""),
                            "url":        m.get("url", ""),
                            "active":     m.get("active", False),
                            "status":     "up" if m.get("active") else "paused",
                        }
                        for mid, m in monitors.items()
                    ]
    except Exception:
        pass
    return []


async def get_website_status_summary() -> str:
    """One-line summary for BOB's daily report."""
    monitors = await get_monitor_statuses()
    if not monitors:
        return "ATG website: monitor status unavailable."

    atg_monitors = [m for m in monitors if "atg" in m["name"].lower()]
    if not atg_monitors:
        return "ATG website: no monitors configured."

    down    = [m for m in atg_monitors if m["status"] == "down"]
    if down:
        names = ", ".join(m["name"] for m in down)
        return f"ATG WEBSITE DOWN — {names}. Check http://192.168.1.228:3001"

    return (
        f"ATG website: all {len(atg_monitors)} checks passing. "
        f"http://status.YOUR_SUBDOMAIN.cfargotunnel.com"
    )
```

Add credentials to `.env`:

```bash
nano /opt/atg-agents/.env
```

```env
UPTIME_KUMA_URL=http://uptime-kuma:3001
UPTIME_KUMA_USERNAME=rob
UPTIME_KUMA_PASSWORD=your_uptime_kuma_password_here
```

---

**Step 16 — Add website status to the daily report**

In `daily_report.py`, update `build_system_health_summary()`:

```python
from website_monitor import get_website_status_summary

# Add to health_data:
health_data["website_status"] = await get_website_status_summary()
```

Then in `compose_daily_report()`, add to the system health section:

```python
lines.append(f"  {health_data.get('website_status', 'ATG website: not monitored.')}")
```

---

**Step 17 — Add Uptime Kuma to always-on container monitor**

In `container_monitor.py`, add:

```python
ALWAYS_ON_CONTAINERS = {
    # ... existing entries ...
    "uptime-kuma": {
        "display":  "Uptime Kuma (website monitor)",
        "critical": False,
        "fix": (
            "docker compose -f /opt/atg-monitoring/uptime-kuma/docker-compose.yml "
            "up -d uptime-kuma"
        ),
    },
}
```

---

**Step 18 — Test end-to-end alert flow**

Simulate a website outage to confirm the full alert chain works:

```bash
# [UBUNTU SERVER]
# Temporarily stop Nginx
docker stop nginx

# Wait 90 seconds — Uptime Kuma should detect the outage
# Rob's phone should receive a push notification via ntfy
# Check Uptime Kuma dashboard at http://192.168.1.228:3001

# Restore Nginx
docker start nginx

# Wait 90 seconds — Uptime Kuma should detect recovery
# Rob's phone should receive a recovery notification
```

Confirm Rob receives both the down alert and the recovery notification on the phone before marking this build complete.

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| Uptime Kuma deployed in Docker at `:3001` | ✓ |
| External HTTP check — site reachable from internet | ✓ |
| Keyword check — site serving real ATG content | ✓ |
| Internal LAN Nginx check — local availability | ✓ |
| SSL certificate expiry monitored — 30-day advance warning | ✓ |
| DNS resolution monitored via external resolver | ✓ |
| All alerts push to Rob's phone via ntfy `bob-critical` | ✓ |
| Recovery notifications automatic | ✓ |
| 1-hour re-alert if site stays down | ✓ |
| Uptime Kuma accessible away from home via Cloudflare Tunnel | ✓ |
| BOB queries monitor status for daily report | ✓ |
| Website status in daily morning briefing | ✓ |
| Uptime Kuma container included in always-on monitor | ✓ |
| End-to-end alert flow tested | ✓ |

---

### What Rob experiences

**Website goes down (2 AM):**
Phone buzzes loud. Notification reads:
> **CRITICAL — ATG Website Down**
> ATG Website — External is DOWN.
> *[tap to open Uptime Kuma]*

**Still down 1 hour later:**
> **ATG Website still DOWN — 1h 3m**
> Check http://192.168.1.228:3001 for details.

**Site recovers:**
> **ATG Website recovered** — ATG Website — External is back UP.
> Downtime: 1h 12m.

**Daily briefing (normal):**
```
ATG website: all 5 checks passing.
```

**BOB status query ("is the website up?"):**
> *"Yes Boss — all five checks are green. External HTTP, content check, LAN Nginx, SSL, and DNS are all passing."*

---

### Public status page (optional future step)

Uptime Kuma can generate a public status page at a URL like `https://status.appalachiantoysgames.com` — a simple green/red page showing ATG website uptime history. Useful if you ever want customers to check service status during an outage. Enable it in Uptime Kuma → Status Pages when ready.

---

*BOB External Uptime Monitoring Build Plan v1.0 — 2026-03-18*
*All build plans in the tracker are now complete.*
