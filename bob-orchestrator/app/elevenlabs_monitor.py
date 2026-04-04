"""ElevenLabs usage tracking — voice minutes and character consumption.

Polls ElevenLabs API every 6 hours. Alerts Rob via ntfy when approaching
plan limits. Surfaces usage in /health and daily briefings.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("bob.elevenlabs")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

# Alert thresholds (percentage of plan limit consumed)
THRESHOLDS = {
    "voice_warn_pct": 70,
    "voice_critical_pct": 85,
    "voice_hard_cap_pct": 95,
    "char_warn_pct": 75,
    "char_critical_pct": 90,
}

# Plan minute limits by tier — ElevenLabs doesn't expose remaining
# Conversational AI minutes directly, so we derive from tier
PLAN_VOICE_MINUTES = {
    "free": 0,
    "starter": 30,
    "creator": 250,
    "pro": 1100,
    "scale": 3600,
    "business": 13750,
}

# Track whether alerts have been sent to avoid spam
_alert_state = {
    "voice_warn_sent": False,
    "voice_critical_sent": False,
    "char_warn_sent": False,
    "char_critical_sent": False,
}

# Cached last sweep result for the /health endpoint
_last_sweep: dict | None = None

# Notify callback — set by main.py at startup
_notify_callback = None


def set_notify_callback(callback):
    global _notify_callback
    _notify_callback = callback


# ── API helpers ─────────────────────────────────────────────────────────────

async def fetch_subscription() -> dict | None:
    """GET /v1/user/subscription — returns plan info, character usage."""
    if not ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY not set — skipping usage check")
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ELEVENLABS_API_BASE}/user/subscription",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Subscription endpoint returned {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch subscription: {e}")
        return None


async def fetch_conversations(limit: int = 200) -> list[dict]:
    """GET /v1/convai/conversations — recent voice sessions for minute calc."""
    if not ELEVENLABS_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ELEVENLABS_API_BASE}/convai/conversations",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                params={"page_size": limit},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("conversations", [])
            return []
    except Exception:
        return []


# ── Usage calculation ───────────────────────────────────────────────────────

def _voice_minutes_this_period(conversations: list[dict], period_start: datetime) -> float:
    """Sum conversation durations from the current billing period."""
    total_seconds = 0.0
    for conv in conversations:
        started_at = conv.get("start_time_unix_secs")
        if started_at:
            try:
                started = datetime.fromtimestamp(float(started_at), tz=timezone.utc)
                if started >= period_start:
                    total_seconds += float(conv.get("call_duration_secs", 0) or 0)
            except (ValueError, TypeError):
                pass
    return round(total_seconds / 60, 2)


def _upgrade_guidance(current_tier: str) -> str:
    next_tiers = {
        "free": ("starter", "$5/mo", "30 minutes"),
        "starter": ("creator", "$11/mo", "250 minutes"),
        "creator": ("pro", "$99/mo", "1,100 minutes"),
        "pro": ("scale", "$330/mo", "3,600 minutes"),
        "scale": ("business", "contact sales", "13,750 minutes"),
    }
    if current_tier in next_tiers:
        name, price, mins = next_tiers[current_tier]
        return f"Next tier: {name} at {price} — {mins}/month. https://elevenlabs.io/subscription"
    return "Check https://elevenlabs.io/subscription for options."


# ── Main sweep ──────────────────────────────────────────────────────────────

async def run_usage_sweep() -> dict:
    """Poll ElevenLabs for current usage. Fire alerts if thresholds exceeded."""
    global _last_sweep

    sub = await fetch_subscription()
    if not sub:
        return {"error": "Could not fetch ElevenLabs subscription data"}

    char_used = sub.get("character_count", 0)
    char_limit = sub.get("character_limit", 1)
    char_pct = round((char_used / char_limit) * 100, 1) if char_limit else 0
    tier = sub.get("tier", "unknown").lower()
    plan_minutes = PLAN_VOICE_MINUTES.get(tier, 0)

    # Billing period start — default to 1st of month
    period_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )

    conversations = await fetch_conversations()
    voice_used = _voice_minutes_this_period(conversations, period_start)
    voice_pct = round((voice_used / plan_minutes) * 100, 1) if plan_minutes else 0
    voice_remaining = max(0, plan_minutes - voice_used)

    # Log to Langfuse if available
    try:
        from langfuse import Langfuse
        from app.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            lf = Langfuse(public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, host=LANGFUSE_HOST)
            trace_id = f"elevenlabs_usage_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
            lf.score(trace_id=trace_id, name="elevenlabs_voice_minutes_used", value=voice_used,
                     comment=f"{voice_used}/{plan_minutes} min ({voice_pct}%)")
            lf.score(trace_id=trace_id, name="elevenlabs_characters_pct", value=char_pct,
                     comment=f"{char_used:,}/{char_limit:,} chars ({char_pct}%)")
    except Exception:
        pass  # Langfuse is optional

    # Fire alerts
    alerts = []

    if plan_minutes > 0:
        if voice_pct >= THRESHOLDS["voice_hard_cap_pct"] and not _alert_state["voice_critical_sent"]:
            _alert_state["voice_critical_sent"] = True
            alerts.append((
                "critical",
                f"ElevenLabs voice at {voice_pct:.0f}% — only {voice_remaining:.0f} min left. "
                f"BOB will keep conversations brief. {_upgrade_guidance(tier)}"
            ))
        elif voice_pct >= THRESHOLDS["voice_critical_pct"] and not _alert_state["voice_critical_sent"]:
            _alert_state["voice_critical_sent"] = True
            alerts.append((
                "critical",
                f"ElevenLabs voice at {voice_pct:.0f}% — {voice_remaining:.0f} min left this month. "
                f"{_upgrade_guidance(tier)}"
            ))
        elif voice_pct >= THRESHOLDS["voice_warn_pct"] and not _alert_state["voice_warn_sent"]:
            _alert_state["voice_warn_sent"] = True
            alerts.append((
                "warning",
                f"ElevenLabs voice at {voice_pct:.0f}% — {voice_remaining:.0f} min remaining."
            ))
        elif voice_pct < THRESHOLDS["voice_warn_pct"]:
            _alert_state["voice_warn_sent"] = False
            _alert_state["voice_critical_sent"] = False

    if char_pct >= THRESHOLDS["char_critical_pct"] and not _alert_state["char_critical_sent"]:
        _alert_state["char_critical_sent"] = True
        alerts.append((
            "critical",
            f"ElevenLabs characters at {char_pct:.0f}% ({char_used:,}/{char_limit:,}). "
            f"TTS will fail at limit. {_upgrade_guidance(tier)}"
        ))
    elif char_pct >= THRESHOLDS["char_warn_pct"] and not _alert_state["char_warn_sent"]:
        _alert_state["char_warn_sent"] = True
        alerts.append((
            "warning",
            f"ElevenLabs characters at {char_pct:.0f}% ({char_used:,}/{char_limit:,})."
        ))
    elif char_pct < THRESHOLDS["char_warn_pct"]:
        _alert_state["char_warn_sent"] = False
        _alert_state["char_critical_sent"] = False

    # Send alerts via ntfy
    for level, message in alerts:
        if _notify_callback:
            try:
                topic = "bob-critical" if level == "critical" else "bob-status"
                priority = "urgent" if level == "critical" else "default"
                await _notify_callback(topic, "ElevenLabs Usage Alert", message, priority)
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")

    result = {
        "tier": tier,
        "voice_minutes_used": voice_used,
        "voice_minutes_plan": plan_minutes,
        "voice_minutes_remaining": voice_remaining,
        "voice_pct": voice_pct,
        "char_used": char_used,
        "char_limit": char_limit,
        "char_pct": char_pct,
        "alerts_fired": len(alerts),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    _last_sweep = result
    return result


def get_last_sweep() -> dict | None:
    """Return cached last sweep for health endpoint. No API call."""
    return _last_sweep


async def get_status_summary() -> str:
    """One-line summary for daily briefing."""
    result = _last_sweep or await run_usage_sweep()
    if not result or "error" in result:
        return "ElevenLabs: unavailable (check API key)."
    if result["voice_minutes_plan"] > 0:
        return (
            f"ElevenLabs: {result['voice_minutes_used']:.0f}/"
            f"{result['voice_minutes_plan']} voice min "
            f"({result['voice_pct']:.0f}%) · "
            f"Chars: {result['char_pct']:.0f}%"
        )
    return f"ElevenLabs: Characters at {result['char_pct']:.0f}% of plan."


# ── Background loop ────────────────────────────────────────────────────────

async def monitoring_loop():
    """Poll every 6 hours. Reset alert state daily for billing cycle resets."""
    last_reset_day = datetime.now(timezone.utc).day

    # Run initial sweep immediately
    try:
        await run_usage_sweep()
        logger.info("Initial ElevenLabs usage sweep complete")
    except Exception as e:
        logger.warning(f"Initial ElevenLabs sweep failed: {e}")

    while True:
        await asyncio.sleep(21600)  # 6 hours

        today = datetime.now(timezone.utc).day
        if today != last_reset_day:
            for key in _alert_state:
                _alert_state[key] = False
            last_reset_day = today

        try:
            await run_usage_sweep()
        except Exception as e:
            logger.error(f"ElevenLabs usage sweep failed: {e}")
