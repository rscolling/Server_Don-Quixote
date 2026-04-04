"""Daily briefing composer — pulls from all BOB data sources.

Called by the daily_briefing scheduled task. Compiles system health,
email activity, voice usage, server resources, bus stats, and
pending tasks into a single report for Rob.
"""

import logging
import os
from datetime import datetime, timezone

import httpx
import psutil

logger = logging.getLogger("bob.daily")


async def compose_daily_report() -> str:
    """Build BOB's daily morning briefing."""
    now = datetime.now(timezone.utc)
    lines = [
        f"# Daily Briefing — {now.strftime('%A, %B %d, %Y')}",
        "",
    ]

    # ── System Health ───────────────────────────────────────────────────────
    lines.append("## System Health")

    # Server resources
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        lines.append(f"  CPU: {cpu}% | Memory: {mem.percent}% ({mem.used // (1024**3)}/{mem.total // (1024**3)} GB) | Disk: {disk.percent}%")
        warnings = []
        if cpu > 80:
            warnings.append(f"CPU high at {cpu}%")
        if mem.percent > 80:
            warnings.append(f"Memory high at {mem.percent}%")
        if disk.percent > 80:
            warnings.append(f"Disk high at {disk.percent}%")
        if warnings:
            lines.append(f"  ⚠ {', '.join(warnings)}")
    except Exception as e:
        lines.append(f"  Server resources: unavailable ({e})")

    # Service connectivity
    from app.config import MESSAGE_BUS_URL, CHROMADB_URL
    services = {
        "Message Bus": MESSAGE_BUS_URL + "/stats",
        "ChromaDB": CHROMADB_URL + "/api/v1/heartbeat",
    }
    service_status = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                await client.get(url)
                service_status.append(f"{name}: ok")
            except Exception:
                service_status.append(f"{name}: DOWN")
    lines.append(f"  Services: {' | '.join(service_status)}")

    # Bus queue depth
    from app.bus_client import get_queue_depth
    queue = get_queue_depth()
    if queue > 0:
        lines.append(f"  ⚠ Bus offline queue: {queue} pending requests")

    lines.append("")

    # ── Email ───────────────────────────────────────────────────────────────
    lines.append("## Email")
    try:
        from app.gmail_monitor import check_inbox, _get_gmail_service
        service = _get_gmail_service()
        if service:
            profile = service.users().getProfile(userId="me").execute()
            lines.append(f"  Account: {profile.get('emailAddress')} | Token: valid")

            # Count unread
            try:
                results = service.users().messages().list(
                    userId="me", q="is:unread", maxResults=1
                ).execute()
                unread_estimate = results.get("resultSizeEstimate", 0)
                lines.append(f"  Unread: ~{unread_estimate}")
            except Exception:
                pass
        else:
            lines.append("  Gmail: disconnected — token may need refresh")
    except Exception as e:
        lines.append(f"  Gmail: error — {e}")

    lines.append("")

    # ── ElevenLabs Voice Usage ──────────────────────────────────────────────
    lines.append("## Voice Usage")
    try:
        from app.elevenlabs_monitor import get_status_summary
        el_summary = await get_status_summary()
        lines.append(f"  {el_summary}")
    except Exception:
        lines.append("  ElevenLabs: not configured or unavailable")

    lines.append("")

    # ── Message Bus Activity ────────────────────────────────────────────────
    lines.append("## Task Activity")
    try:
        from app import bus_client
        stats = await bus_client.get_stats()
        if isinstance(stats, dict) and "error" not in stats:
            lines.append(f"  Total tasks: {stats.get('total_tasks', '?')} | Messages: {stats.get('total_messages', '?')}")
        else:
            lines.append("  Message bus: unreachable")

        # Pending tasks
        tasks = await bus_client.get_tasks(state="IN_PROGRESS")
        if isinstance(tasks, list) and tasks:
            lines.append(f"  In progress: {len(tasks)}")
            for t in tasks[:5]:
                lines.append(f"    - {t.get('title', '?')}")

        tasks_review = await bus_client.get_tasks(state="IN_REVIEW")
        if isinstance(tasks_review, list) and tasks_review:
            lines.append(f"  Awaiting review: {len(tasks_review)}")
            for t in tasks_review[:5]:
                lines.append(f"    - {t.get('title', '?')}")
    except Exception as e:
        lines.append(f"  Bus stats: unavailable ({e})")

    lines.append("")

    # ── Scheduled Jobs ──────────────────────────────────────────────────────
    lines.append("## Upcoming Scheduled Tasks")
    try:
        from app.scheduler import list_jobs
        jobs = list_jobs()
        for job in sorted(jobs, key=lambda j: j.get("next_run") or ""):
            next_run = job.get("next_run", "paused")
            if next_run and next_run != "paused":
                # Format to readable time
                try:
                    dt = datetime.fromisoformat(next_run)
                    next_run = dt.strftime("%a %b %d %I:%M %p")
                except Exception:
                    pass
            lines.append(f"  {job.get('name', job.get('job_id'))}: {next_run}")
    except Exception:
        lines.append("  Scheduler: unavailable")

    lines.append("")
    lines.append("---")
    lines.append("*End of daily briefing. Yes Boss, that's the state of things.*")

    return "\n".join(lines)
