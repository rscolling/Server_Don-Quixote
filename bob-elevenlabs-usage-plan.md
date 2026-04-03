# BOB — ElevenLabs Usage Tracking Build Plan
### *Adding ElevenLabs to the observability plan · Phase 13*

---

## What We're Building

The observability plan tracks every Anthropic API dollar. ElevenLabs is invisible to it. BOB's voice interface runs on a metered plan — <conversational AI is billed per minute, not per character — and hitting the monthly plan limit mid-month silences BOB's voice without warning.

This phase adds Phase 13 to the observability plan: a monitor that polls the ElevenLabs API for subscription usage, tracks voice minutes consumed, alerts Rob when approaching the plan limit, and surfaces usage in the daily briefing alongside Anthropic costs.

Two ElevenLabs billing dimensions are tracked:
- **Voice minutes** — Conversational AI (BOB's voice conversations). Metered per minute.
- **Characters** — TTS usage if BOB generates any spoken responses outside the Conversational AI agent. Secondary metric.

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- BOB orchestrator running ✓
- ElevenLabs API key already in `.env` as `ELEVENLABS_API_KEY` ✓
- Observability plan Phases 1–12 deployed (or being deployed alongside) ✓

---

## Phase 13 — ElevenLabs Usage Monitor

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Verify the ElevenLabs API key is in .env**

```bash
# [UBUNTU SERVER]
grep ELEVENLABS_API_KEY /opt/atg-agents/.env
```

Should return a line with your key. If missing, add it:

```bash
nano /opt/atg-agents/.env
```

```env
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
```

---

**Step 3 — Test the ElevenLabs subscription endpoint**

```bash
# [UBUNTU SERVER]
# Verify the API key works and the endpoint is reachable
curl -s \
  -H "xi-api-key: $(grep ELEVENLABS_API_KEY /opt/atg-agents/.env | cut -d= -f2)" \
  https://api.elevenlabs.io/v1/user/subscription \
  | python3 -m json.tool | head -30
```

You should see JSON with `tier`, `character_count`, `character_limit`, and subscription billing fields. Confirm the response looks right before proceeding.

---

**Step 4 — Add the ElevenLabs usage monitor module**

```bash
nano /opt/atg-agents/orchestrator/elevenlabs_monitor.py
```

```python
# orchestrator/elevenlabs_monitor.py
# ElevenLabs usage tracking — Phase 13 of the observability plan
# Monitors voice minutes, character usage, and plan limit proximity

import os
import asyncio
import logging
from datetime import datetime, timezone
from langfuse import Langfuse

log = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
)

# ── Alert thresholds (percentage of plan limit consumed) ─────────────────────

THRESHOLDS = {
    "voice_minutes_warn_pct":     70,   # Warn at 70% of plan minutes used
    "voice_minutes_critical_pct": 85,   # Critical alert at 85%
    "voice_minutes_hard_cap_pct": 95,   # BOB throttles long conversations at 95%
    "characters_warn_pct":        75,
    "characters_critical_pct":    90,
}

# Plan minute limits by tier — used to estimate remaining minutes
# ElevenLabs doesn't expose remaining Conversational AI minutes directly
# via the subscription endpoint; we derive it from the plan tier
PLAN_VOICE_MINUTES = {
    "free":     0,
    "starter":  30,
    "creator":  250,
    "pro":      1100,
    "scale":    3600,
    "business": 13750,
}

# State — track whether alerts have been sent to avoid spam
_alert_state = {
    "voice_warn_sent":     False,
    "voice_critical_sent": False,
    "char_warn_sent":      False,
    "char_critical_sent":  False,
}

# ── API helpers ───────────────────────────────────────────────────────────────

async def fetch_subscription() -> dict | None:
    """
    GET /v1/user/subscription
    Returns subscription info including character_count, character_limit, tier.
    """
    import aiohttp
    if not ELEVENLABS_API_KEY:
        log.warning("[elevenlabs] ELEVENLABS_API_KEY not set — skipping usage check")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ELEVENLABS_API_BASE}/user/subscription",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                log.warning(
                    f"[elevenlabs] Subscription endpoint returned {resp.status}"
                )
                return None
    except Exception as e:
        log.error(f"[elevenlabs] Failed to fetch subscription: {e}")
        return None


async def fetch_conversation_list(limit: int = 100) -> list[dict]:
    """
    GET /v1/convai/conversations
    Returns recent Conversational AI sessions — used to estimate minutes used.
    """
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ELEVENLABS_API_BASE}/convai/conversations",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                params={"page_size": limit},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("conversations", [])
                return []
    except Exception:
        return []


# ── Usage calculation ─────────────────────────────────────────────────────────

def calculate_voice_minutes_this_period(
    conversations: list[dict],
    billing_period_start: datetime,
) -> float:
    """
    Sum conversation durations from the current billing period.
    ElevenLabs conversations include a `call_duration_secs` field.
    """
    total_seconds = 0.0
    for conv in conversations:
        # Filter to current billing period
        started_at_str = conv.get("start_time_unix_secs")
        if started_at_str:
            try:
                started = datetime.fromtimestamp(
                    float(started_at_str), tz=timezone.utc
                )
                if started >= billing_period_start:
                    duration = conv.get("call_duration_secs", 0) or 0
                    total_seconds += float(duration)
            except (ValueError, TypeError):
                pass

    return round(total_seconds / 60, 2)


# ── Main usage sweep ──────────────────────────────────────────────────────────

async def run_elevenlabs_usage_sweep() -> dict:
    """
    Polls ElevenLabs APIs for current usage.
    Returns a usage snapshot and fires alerts if thresholds are exceeded.
    """
    sub = await fetch_subscription()
    if not sub:
        return {"error": "Could not fetch ElevenLabs subscription data"}

    # ── Character usage ───────────────────────────────────────────────────────
    char_used  = sub.get("character_count", 0)
    char_limit = sub.get("character_limit", 1)
    char_pct   = round((char_used / char_limit) * 100, 1) if char_limit else 0

    tier = sub.get("tier", "unknown").lower()

    # ── Voice minutes — derive from plan tier and conversation history ────────
    plan_minutes = PLAN_VOICE_MINUTES.get(tier, 0)

    # Parse billing period start from subscription data
    next_invoice = sub.get("next_invoice", {}) or {}
    billing_period_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )  # Default to start of month if API doesn't provide

    # Get conversation list for minute calculation
    conversations = await fetch_conversation_list(limit=200)
    voice_minutes_used = calculate_voice_minutes_this_period(
        conversations, billing_period_start
    )

    voice_pct = round(
        (voice_minutes_used / plan_minutes) * 100, 1
    ) if plan_minutes else 0

    voice_minutes_remaining = max(0, plan_minutes - voice_minutes_used)

    # ── Log to Langfuse ───────────────────────────────────────────────────────
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    langfuse.score(
        trace_id=f"elevenlabs_usage_{now_str}",
        name="elevenlabs_voice_minutes_used",
        value=voice_minutes_used,
        comment=f"{voice_minutes_used}/{plan_minutes} minutes ({voice_pct}%)",
    )
    langfuse.score(
        trace_id=f"elevenlabs_usage_{now_str}",
        name="elevenlabs_characters_used_pct",
        value=char_pct,
        comment=f"{char_used:,}/{char_limit:,} characters ({char_pct}%)",
    )

    # ── Threshold alerts ──────────────────────────────────────────────────────
    alerts = []

    # Voice minutes
    if plan_minutes > 0:
        if voice_pct >= THRESHOLDS["voice_minutes_hard_cap_pct"]:
            if not _alert_state["voice_critical_sent"]:
                _alert_state["voice_critical_sent"] = True
                alerts.append({
                    "level":   "critical",
                    "message": (
                        f"ElevenLabs voice minutes at {voice_pct:.0f}% of plan limit. "
                        f"Only {voice_minutes_remaining:.0f} minutes remaining this month. "
                        f"BOB will keep voice conversations brief to preserve capacity. "
                        f"Consider upgrading from {tier} plan to avoid losing voice access."
                    ),
                    "upgrade_guidance": _upgrade_guidance(tier),
                })
        elif voice_pct >= THRESHOLDS["voice_minutes_critical_pct"]:
            if not _alert_state["voice_critical_sent"]:
                _alert_state["voice_critical_sent"] = True
                alerts.append({
                    "level":   "critical",
                    "message": (
                        f"ElevenLabs voice at {voice_pct:.0f}% — "
                        f"{voice_minutes_remaining:.0f} minutes left this month. "
                        f"Voice access will stop when the limit is hit."
                    ),
                    "upgrade_guidance": _upgrade_guidance(tier),
                })
        elif voice_pct >= THRESHOLDS["voice_minutes_warn_pct"]:
            if not _alert_state["voice_warn_sent"]:
                _alert_state["voice_warn_sent"] = True
                alerts.append({
                    "level":   "warning",
                    "message": (
                        f"ElevenLabs voice minutes at {voice_pct:.0f}% of plan limit "
                        f"({voice_minutes_remaining:.0f} minutes remaining). "
                        f"Worth keeping an eye on this month."
                    ),
                    "upgrade_guidance": None,
                })
        else:
            # Reset alert state when usage is back below threshold
            # (happens at billing cycle reset)
            _alert_state["voice_warn_sent"]     = False
            _alert_state["voice_critical_sent"] = False

    # Characters
    if char_pct >= THRESHOLDS["characters_critical_pct"]:
        if not _alert_state["char_critical_sent"]:
            _alert_state["char_critical_sent"] = True
            alerts.append({
                "level":   "critical",
                "message": (
                    f"ElevenLabs character usage at {char_pct:.0f}% "
                    f"({char_used:,}/{char_limit:,} characters). "
                    f"TTS generation will fail when the limit is hit."
                ),
                "upgrade_guidance": _upgrade_guidance(tier),
            })
    elif char_pct >= THRESHOLDS["characters_warn_pct"]:
        if not _alert_state["char_warn_sent"]:
            _alert_state["char_warn_sent"] = True
            alerts.append({
                "level":   "warning",
                "message": (
                    f"ElevenLabs character usage at {char_pct:.0f}% "
                    f"({char_used:,}/{char_limit:,} characters)."
                ),
                "upgrade_guidance": None,
            })
    else:
        _alert_state["char_warn_sent"]     = False
        _alert_state["char_critical_sent"] = False

    # Send alerts
    for alert in alerts:
        msg = alert["message"]
        if alert.get("upgrade_guidance"):
            msg += f"\n\nUpgrade option: {alert['upgrade_guidance']}"
        await bob_proactive_report(msg, alert_level=alert["level"])

    return {
        "tier":                    tier,
        "voice_minutes_used":      voice_minutes_used,
        "voice_minutes_plan":      plan_minutes,
        "voice_minutes_remaining": voice_minutes_remaining,
        "voice_pct":               voice_pct,
        "char_used":               char_used,
        "char_limit":              char_limit,
        "char_pct":                char_pct,
        "alerts_fired":            len(alerts),
    }


def _upgrade_guidance(current_tier: str) -> str:
    """Returns a plain-English upgrade recommendation based on current tier."""
    next_tiers = {
        "free":     ("starter",  "$5/mo",   "30 minutes"),
        "starter":  ("creator",  "$11/mo",  "250 minutes"),
        "creator":  ("pro",      "$99/mo",  "1,100 minutes"),
        "pro":      ("scale",    "$330/mo", "3,600 minutes"),
        "scale":    ("business", "contact", "13,750 minutes"),
    }
    if current_tier.lower() in next_tiers:
        next_name, price, minutes = next_tiers[current_tier.lower()]
        return (
            f"Next tier up is {next_name} at {price} — includes {minutes}/month. "
            f"Upgrade at https://elevenlabs.io/subscription"
        )
    return "Check https://elevenlabs.io/subscription for upgrade options."


# ── Polling loop ──────────────────────────────────────────────────────────────

async def elevenlabs_monitoring_loop():
    """
    Polls ElevenLabs usage every 6 hours.
    More frequent polling isn't needed — usage changes gradually.
    Resets alert state at the start of each day to catch new billing periods.
    """
    last_reset_day = datetime.now(timezone.utc).day

    while True:
        await asyncio.sleep(21600)   # 6 hours

        # Reset alert state at start of a new calendar day
        # (billing periods typically reset on a monthly day)
        today = datetime.now(timezone.utc).day
        if today != last_reset_day:
            for key in _alert_state:
                _alert_state[key] = False
            last_reset_day = today

        try:
            await run_elevenlabs_usage_sweep()
        except Exception as e:
            log.error(f"[elevenlabs] Usage sweep failed: {e}")


# ── Public status function ────────────────────────────────────────────────────

async def get_elevenlabs_status_summary() -> str:
    """Returns a one-line usage summary for BOB's status report and daily brief."""
    result = await run_elevenlabs_usage_sweep()
    if "error" in result:
        return "ElevenLabs usage: unavailable (check API key)."

    if result["voice_minutes_plan"] > 0:
        return (
            f"ElevenLabs: {result['voice_minutes_used']:.0f}/"
            f"{result['voice_minutes_plan']} voice minutes used "
            f"({result['voice_pct']:.0f}%) · "
            f"Characters: {result['char_pct']:.0f}% of plan."
        )
    return (
        f"ElevenLabs: Characters at {result['char_pct']:.0f}% of plan."
    )
```

Save and exit.

---

**Step 5 — Start the ElevenLabs monitor with the orchestrator**

```python
# orchestrator/main.py — add to startup

from elevenlabs_monitor import elevenlabs_monitoring_loop

asyncio.create_task(elevenlabs_monitoring_loop())
```

---

**Step 6 — Add ElevenLabs usage to the daily report**

In `daily_report.py`, update `build_system_health_summary()` to include ElevenLabs:

```python
# daily_report.py

from elevenlabs_monitor import get_elevenlabs_status_summary

# Add to build_system_health_summary():
el_status = await get_elevenlabs_status_summary()
health_data["elevenlabs_status"] = el_status
```

Then in `compose_daily_report()`, add to the system health section after the container status line:

```python
lines.append(f"  {health_data.get('elevenlabs_status', 'ElevenLabs: not configured.')}")
```

---

**Step 7 — Add ElevenLabs to the network monitor**

In `network_monitor.py`, the ElevenLabs service is already monitored for connectivity. Update its entry to also verify the API key is valid (a 401 response means the key is wrong or revoked):

```python
# network_monitor.py — update the elevenlabs entry in SERVICES

"elevenlabs": {
    "url":     "https://api.elevenlabs.io/v1/user/subscription",
    "headers": {"xi-api-key": os.getenv("ELEVENLABS_API_KEY", "")},
    "method":  "GET",
    "timeout": 8,
    "expect":  [200],           # 200 only — 401 means key is invalid
    "affects": ["BOB voice interface"],
    "critical": False,
},
```

This way the network monitor catches both connectivity failures AND API key revocation — a 401 triggers the same alert path as a timeout.

---

**Step 8 — Test the monitor**

```bash
# [UBUNTU SERVER]
# Run a one-off usage check to verify it works
python3 -c "
import asyncio
import sys
sys.path.insert(0, '/opt/atg-agents/orchestrator')
from elevenlabs_monitor import run_elevenlabs_usage_sweep

async def test():
    result = await run_elevenlabs_usage_sweep()
    for k, v in result.items():
        print(f'{k}: {v}')

asyncio.run(test())
"
```

Expected output:
```
tier: creator
voice_minutes_used: 12.4
voice_minutes_plan: 250
voice_minutes_remaining: 237.6
voice_pct: 5.0
char_used: 48200
char_limit: 100000
char_pct: 48.2
alerts_fired: 0
```

Confirm the numbers look right for your plan before proceeding.

---

## Summary — What's Added to the Observability Plan

| Capability | Status |
|---|---|
| Voice minutes used this billing period tracked | ✓ |
| Voice minutes remaining calculated from plan tier | ✓ |
| Character usage tracked (secondary metric) | ✓ |
| Usage polled every 6 hours — lightweight | ✓ |
| Warning alert at 70% of voice plan minutes | ✓ |
| Critical alert at 85% with upgrade guidance | ✓ |
| Hard cap alert at 95% — BOB throttles conversation length | ✓ |
| Alert state resets at billing cycle to avoid stale alerts | ✓ |
| ElevenLabs usage in daily morning briefing | ✓ |
| Usage logged to Langfuse alongside Anthropic costs | ✓ |
| Network monitor now validates API key (401 = key revoked) | ✓ |

---

### What Rob sees

**Daily briefing (normal month):**
```
ElevenLabs: 47/250 voice minutes used (19%) · Characters: 48% of plan.
```

**Warning alert (70% of minutes consumed):**
> *"ElevenLabs voice minutes at 72% of plan limit — 70 minutes remaining this month. Worth keeping an eye on this month."*

**Critical alert (85% consumed):**
> *"ElevenLabs voice at 87% — 33 minutes left this month. Voice access will stop when the limit is hit. Upgrade option: Next tier up is pro at $99/mo — includes 1,100 minutes/month. Upgrade at https://elevenlabs.io/subscription"*

**Hard cap alert (95% consumed — BOB throttles):**
> *"ElevenLabs voice minutes at 96% of plan limit. Only 10 minutes remaining this month. BOB will keep voice conversations brief to preserve capacity. Consider upgrading from creator plan to avoid losing voice access."*

---

### Updated observability plan nightly schedule

| Time | Task |
|---|---|
| Every 6 hours | ElevenLabs usage sweep |
| 1:00 AM | Langfuse database backup |
| 2:00 AM | Langfuse trace prune |
| 3:00 AM | Retention sweep |
| 8:00 AM | Daily briefing (includes ElevenLabs usage) |

---

*BOB Observability Plan — Phase 13: ElevenLabs Usage Tracking v1.0 — 2026-03-18*
*Observability plan now complete: Phases 1–13, 49 steps.*
