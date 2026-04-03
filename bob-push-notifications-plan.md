# BOB — Push Notifications Build Plan
### *ntfy · self-hosted · Ubuntu server · Android & iOS*

---

## What We're Building

BOB currently tells Rob things through the dashboard and voice. Both require Rob to be looking at a screen or within earshot. This plan adds a phone push notification channel — BOB can reach Rob anywhere, any time, without Rob needing to open anything.

ntfy is an HTTP pub/sub notification service. Publishing a notification is a single POST request to a topic URL. The ntfy app on the phone receives it instantly. It runs in Docker on the existing server alongside everything else. No external service in the loop — notification payloads never leave the home network unless the Cloudflare Tunnel is used for away-from-home access.

### Notification Topics

BOB publishes to four distinct topics so Rob can control which alerts wake him up:

| Topic | What gets sent | Priority |
|---|---|---|
| `bob-critical` | Server down, circuit breaker tripped, Anthropic API unreachable, OOM kill | Urgent — always notify |
| `bob-reviews` | Escalation briefs waiting for Rob's decision | High — notify promptly |
| `bob-status` | Task completions, team spin-up/down, quality flags | Default — notify normally |
| `bob-daily` | Morning briefing delivery | Low — no sound |

Rob subscribes to all four but sets different notification sounds per topic in the ntfy app.

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- Docker + Docker Compose running ✓
- Cloudflare Tunnel operational (from phone access plan) — for away-from-home notifications
- Smartphone with ntfy app installed (Step 3)

---

## Phase 1 — Deploy ntfy on the Server

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Create the ntfy directory and config**

```bash
# [UBUNTU SERVER]
mkdir -p /opt/atg-notifications/ntfy
cd /opt/atg-notifications/ntfy
mkdir -p data cache
```

Create the server config:

```bash
nano server.yml
```

Paste:

```yaml
# ntfy server configuration
# /opt/atg-notifications/ntfy/server.yml

base-url: "http://192.168.1.228:2586"

# Cache — stores messages so the phone gets them even if offline briefly
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "24h"

# Auth — deny all by default, explicit users only
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"

# Attachment storage (for future use — screenshots, logs)
attachment-cache-dir: "/var/cache/ntfy/attachments"
attachment-total-size-limit: "1G"
attachment-file-size-limit: "15M"
attachment-expiry-duration: "24h"

# Rate limiting — generous since this is private/personal use
visitor-request-limit-burst: 1000
visitor-request-limit-replenish: "1s"

# Log level
log-level: "warn"
```

Save and exit.

---

**Step 3 — Create the Docker Compose file**

```bash
nano docker-compose.yml
```

Paste:

```yaml
version: "3.9"

services:
  ntfy:
    image: binwiederhier/ntfy:latest
    container_name: ntfy
    restart: unless-stopped
    command: serve
    ports:
      - "2586:80"
    volumes:
      - ./server.yml:/etc/ntfy/server.yml:ro
      - ntfy-cache:/var/cache/ntfy
      - ntfy-auth:/var/lib/ntfy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:80/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - atg-network

volumes:
  ntfy-cache:
  ntfy-auth:

networks:
  atg-network:
    external: true
    name: atg_default
```

> Replace `atg_default` with your actual Docker network name (`docker network ls` to check).

---

**Step 4 — Start ntfy**

```bash
# [UBUNTU SERVER]
docker compose up -d
```

Verify it's running:

```bash
docker ps | grep ntfy
curl http://localhost:2586/v1/health
```

Should return: `{"healthy":true}`

---

**Step 5 — Create users and access tokens**

```bash
# [UBUNTU SERVER]
# Enter the ntfy container
docker exec -it ntfy sh
```

Inside the container:

```sh
# Create BOB's publisher account (the orchestrator uses this to send)
ntfy user add bob-publisher
# Enter a strong password when prompted — save it, you need it in Step 10

# Create Rob's subscriber account (the phone uses this to receive)
ntfy user add rob
# Enter a password when prompted — save it, you need it in Step 7

# Grant bob-publisher write access to all BOB topics
ntfy access bob-publisher 'bob-*' write

# Grant rob read access to all BOB topics
ntfy access rob 'bob-*' read

# Generate a token for bob-publisher (used in the orchestrator — easier than passwords)
ntfy token add bob-publisher
# Copy the token output — starts with "tk_"

# Exit the container
exit
```

Save the publisher token and rob's password somewhere safe.

---

**Step 6 — Add publisher token to the orchestrator .env**

```bash
# [UBUNTU SERVER]
nano /opt/atg-agents/.env
```

Add:

```env
NTFY_URL=http://ntfy:2586
NTFY_PUBLISHER_TOKEN=tk_your_token_here
```

> `NTFY_URL` uses the container name `ntfy` because the orchestrator and ntfy are on the same Docker network.

---

## Phase 2 — Install ntfy on the Phone

**Step 7 — Install the ntfy app**

**Android:** Install from Google Play or F-Droid (F-Droid version has no Firebase dependency — works without Google Play Services)

```
Play Store: search "ntfy"
F-Droid: search "ntfy" or direct link: https://f-droid.org/packages/io.heckel.ntfy/
```

**iOS:** Install from the App Store

```
App Store: search "ntfy"
```

---

**Step 8 — Configure the ntfy app to use the home server**

Open the ntfy app. The default server is `ntfy.sh` (the public cloud service). Change it to the home server:

**Android:**
1. Tap the three-dot menu → Settings
2. Tap **Default server**
3. Enter: `http://192.168.1.228:2586`
4. Tap Save

**iOS:**
1. Tap Settings (gear icon)
2. Tap **Default server**
3. Enter: `http://192.168.1.228:2586`
4. Tap Save

---

**Step 9 — Subscribe to all four BOB topics**

In the ntfy app, tap the **+** button to add a subscription. Add all four topics:

For each topic, tap **+**, enter the topic name, and set credentials:
- Username: `rob`
- Password: the password you set in Step 5

Add these four topics:
```
bob-critical
bob-reviews
bob-status
bob-daily
```

---

**Step 10 — Configure notification priority per topic**

In the ntfy app, long-press each topic → Edit → set notification settings:

| Topic | Sound | Priority | Use case |
|---|---|---|---|
| `bob-critical` | Loud / custom alarm | Max | Wake Rob up if needed |
| `bob-reviews` | Default chime | High | Needs attention soon |
| `bob-status` | Subtle | Default | FYI — no urgency |
| `bob-daily` | Silent | Min | Morning briefing |

---

**Step 11 — Test from the server**

```bash
# [UBUNTU SERVER]
# Send a test notification to each topic

curl -u bob-publisher:YOUR_PASSWORD \
  -H "Title: BOB Test" \
  -H "Priority: default" \
  -H "Tags: white_check_mark" \
  -d "ntfy is working. BOB can reach your phone." \
  http://localhost:2586/bob-status
```

The phone should receive a notification within 1–2 seconds. Confirm with Rob before proceeding.

---

## Phase 3 — Integrate ntfy into the BOB Orchestrator

**Step 12 — Add the notification module**

```python
# orchestrator/notifications.py

import os
import asyncio
import aiohttp
from enum import Enum

NTFY_URL             = os.getenv("NTFY_URL", "http://ntfy:2586")
NTFY_PUBLISHER_TOKEN = os.getenv("NTFY_PUBLISHER_TOKEN", "")

class NotifyPriority(Enum):
    MIN     = "min"      # Silent — daily briefing
    LOW     = "low"      # Subtle sound
    DEFAULT = "default"  # Normal notification
    HIGH    = "high"     # Prominent sound
    URGENT  = "urgent"   # Loud — wakes screen, bypasses DND

# Map BOB alert levels to topics and priorities
ALERT_ROUTING = {
    # (topic, priority, tags)
    "critical": ("bob-critical", NotifyPriority.URGENT,  ["rotating_light"]),
    "review":   ("bob-reviews",  NotifyPriority.HIGH,    ["clipboard"]),
    "status":   ("bob-status",   NotifyPriority.DEFAULT, ["robot"]),
    "daily":    ("bob-daily",    NotifyPriority.MIN,     ["sunny"]),
}


async def send_notification(
    message:    str,
    title:      str     = "BOB",
    alert_type: str     = "status",
    action_url: str     = None,
) -> bool:
    """
    Send a push notification to Rob's phone via ntfy.

    alert_type: "critical" | "review" | "status" | "daily"
    action_url: optional — tapping the notification opens this URL
    """
    if not NTFY_PUBLISHER_TOKEN:
        return False

    topic, priority, tags = ALERT_ROUTING.get(
        alert_type,
        ALERT_ROUTING["status"]
    )

    headers = {
        "Authorization": f"Bearer {NTFY_PUBLISHER_TOKEN}",
        "Title":         title,
        "Priority":      priority.value,
        "Tags":          ",".join(tags),
    }

    # Add click action if URL provided
    if action_url:
        headers["Click"] = action_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{NTFY_URL}/{topic}",
                headers=headers,
                data=message.encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status in (200, 201)
    except Exception:
        return False   # Notifications are best-effort — never block the main flow


# ── Convenience wrappers — used throughout the orchestrator ──────────────────

async def notify_critical(message: str, title: str = "CRITICAL"):
    """Server down, circuit breaker, OOM kill, Anthropic API unreachable."""
    await send_notification(
        message=message,
        title=title,
        alert_type="critical",
        action_url="http://192.168.1.228:8200",
    )

async def notify_review(message: str, review_id: str = None):
    """Escalation brief or held output waiting for Rob's decision."""
    url = f"http://192.168.1.228:8200/reviews/{review_id}" if review_id else \
          "http://192.168.1.228:8200"
    await send_notification(
        message=message,
        title="Review needed",
        alert_type="review",
        action_url=url,
    )

async def notify_status(message: str, title: str = "BOB"):
    """Task completions, team events, quality flags — informational."""
    await send_notification(
        message=message,
        title=title,
        alert_type="status",
    )

async def notify_daily(message: str):
    """Morning briefing — silent delivery."""
    await send_notification(
        message=message,
        title=f"Morning briefing",
        alert_type="daily",
        action_url="http://192.168.1.228:8200",
    )
```

---

**Step 13 — Replace `bob_proactive_report` with notification-aware version**

Throughout the orchestrator, `bob_proactive_report` currently posts to the dashboard only. Update it to also push to the phone:

```python
# orchestrator/bob.py

from notifications import notify_critical, notify_review, notify_status

async def bob_proactive_report(message: str, alert_level: str = "status"):
    """
    BOB's main report function.
    Posts to dashboard AND sends phone notification.

    alert_level: "critical" | "review" | "status"
    """
    # 1. Post to dashboard (existing behavior)
    await post_to_dashboard(message)

    # 2. Push to phone
    if alert_level == "critical":
        await notify_critical(message)
    elif alert_level == "review":
        await notify_review(message)
    else:
        await notify_status(message)
```

Update all existing `bob_proactive_report` callers to pass the correct `alert_level`:

```python
# Existing calls that need updating:

# In resource_monitor.py — upgrade alerts
await bob_proactive_report(message, alert_level="critical")

# In circuit_breaker.py — breaker trips
await bob_proactive_report(message, alert_level="critical")

# In container_monitor.py — critical containers down
await bob_proactive_report(message, alert_level="critical")

# In network_monitor.py — critical services down
await bob_proactive_report(message, alert_level="critical")

# In task_runner.py — tasks held for review
await bob_proactive_report(message, alert_level="review")

# In debate_monitor.py — debate health flags (non-critical)
await bob_proactive_report(message, alert_level="status")

# In bridge_monitor.py — Syncthing issues
await bob_proactive_report(message, alert_level="status")
```

---

**Step 14 — Update the daily report to push silently**

In `daily_report.py`, update the delivery:

```python
# daily_report.py — in daily_report_loop()

from notifications import notify_daily

report = await compose_daily_report()

# Post to dashboard
await post_to_dashboard(report)

# Push to phone silently — no sound, no interruption
await notify_daily(report[:500] + "..." if len(report) > 500 else report)
# Note: ntfy has a 4096 char limit per message.
# The daily report is longer — send a truncated preview to the phone.
# Full report is always on the dashboard.
```

---

## Phase 4 — Away From Home (Cloudflare Tunnel for ntfy)

When Rob is away from home, the phone can't reach `192.168.1.228:2586` directly. The ntfy app supports a public server URL — expose ntfy through the existing Cloudflare Tunnel.

**Step 15 — Add ntfy to the Cloudflare Tunnel config**

```bash
# [UBUNTU SERVER]
nano ~/.cloudflared/config.yml
```

Update to expose both the dashboard and ntfy:

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /home/blueridge/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: bob.YOUR_SUBDOMAIN.cfargotunnel.com
    service: http://localhost:8200
  - hostname: notify.YOUR_SUBDOMAIN.cfargotunnel.com
    service: http://localhost:2586
  - service: http_status:404
```

Create the DNS route for ntfy:

```bash
cloudflared tunnel route dns bob-dashboard notify.YOUR_SUBDOMAIN.cfargotunnel.com
```

Restart the tunnel:

```bash
sudo systemctl restart cloudflared
```

---

**Step 16 — Update the ntfy app to use the public URL when away**

In the ntfy app settings, update the server URL to the public tunnel address:

```
https://notify.YOUR_SUBDOMAIN.cfargotunnel.com
```

The app will now receive notifications whether Rob is on the home network or mobile data.

Also update `server.yml` to reflect the public base URL:

```bash
# [UBUNTU SERVER]
nano /opt/atg-notifications/ntfy/server.yml
```

Change:
```yaml
base-url: "https://notify.YOUR_SUBDOMAIN.cfargotunnel.com"
```

Restart ntfy:

```bash
cd /opt/atg-notifications/ntfy
docker compose restart ntfy
```

---

## Phase 5 — Add ntfy to the Container Monitor

**Step 17 — Add ntfy to always-on containers**

In `container_monitor.py`, add ntfy to `ALWAYS_ON_CONTAINERS`:

```python
ALWAYS_ON_CONTAINERS = {
    # ... existing containers ...
    "ntfy": {
        "display":  "ntfy (push notifications)",
        "critical": False,   # Not critical — BOB can still use dashboard
        "fix": "docker compose -f /opt/atg-notifications/ntfy/docker-compose.yml up -d ntfy",
    },
}
```

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| ntfy self-hosted on server at `:2586` | ✓ |
| Four priority-tiered topics (critical / reviews / status / daily) | ✓ |
| Authentication — deny-all by default, token-based publishing | ✓ |
| ntfy app on phone subscribed to all four topics | ✓ |
| Per-topic notification sound and priority configured | ✓ |
| All BOB alerts routed to appropriate topic automatically | ✓ |
| Critical alerts bypass DND — urgent priority | ✓ |
| Daily briefing delivered silently to phone | ✓ |
| Tap notification → opens relevant dashboard page | ✓ |
| Away-from-home notifications via Cloudflare Tunnel | ✓ |
| ntfy container monitored alongside other always-on services | ✓ |
| Zero ongoing cost — fully self-hosted | ✓ |

---

### What Rob experiences

**Critical alert (circuit breaker trips at 2 AM):**
Phone buzzes loudly, screen wakes. Notification reads:
> **CRITICAL** — Circuit breaker TRIPPED — anthropic_api. Service is failing. Tasks paused. *[tap to open dashboard]*

**Review waiting (team finished a task):**
Phone chimes normally. Notification reads:
> **Review needed** — Marketing finished the homepage copy. Waiting for your approval before publishing. *[tap to open review]*

**Status update (background task completed):**
Subtle notification. Notification reads:
> **BOB** — Research team completed the patent scan. 3 findings flagged. Quality score: 8.1/10.

**Daily briefing (8 AM, silent):**
No sound, no vibration. Notification sits in the drawer. Reads:
> **Morning briefing** — 6 tasks completed. Cost: $0.38. 2 items need your review. System healthy. *[tap for full report]*

---

*BOB Push Notifications Build Plan v1.0 — 2026-03-18*
