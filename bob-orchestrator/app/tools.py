"""LangGraph tools — what BOB can do."""

import asyncio
import json
import functools
import os
import inspect
import logging
from datetime import datetime, timezone
import httpx
from langchain_core.tools import tool
from app import bus_client, memory
from app.firewall import gate, FirewallDecision

logger = logging.getLogger("bob.tools")


@tool
async def create_task(title: str, description: str, assignee: str = "", priority: str = "normal") -> str:
    """Create a new task on the message bus. Assignee is an agent shorthand (PM, RA, CE, QA, etc.) or empty for unassigned."""
    result = await bus_client.create_task(
        title=title,
        description=description,
        assignee=assignee or None,
        priority=priority,
    )
    return json.dumps(result)


@tool
async def send_message(recipient: str, message_type: str, text: str,
                       topic: str = "", task_id: str = "", priority: str = "normal") -> str:
    """Send a message through the bus. recipient is agent shorthand or ALL. message_type: directive, question, feedback, status_update, escalation."""
    result = await bus_client.send_message(
        recipient=recipient,
        message_type=message_type,
        payload={"text": text},
        topic=topic or None,
        task_id=task_id or None,
        priority=priority,
    )
    return json.dumps(result)


@tool
async def check_tasks(state: str = "") -> str:
    """Get tasks from the message bus. Filter by state: CREATED, ASSIGNED, IN_PROGRESS, IN_REVIEW, REWORK, ACCEPTED, CLOSED."""
    result = await bus_client.get_tasks(state=state or None)
    return json.dumps(result)


@tool
async def check_agents() -> str:
    """List all registered agents and their status."""
    result = await bus_client.get_agents()
    return json.dumps(result)


@tool
async def check_stats() -> str:
    """Get message bus statistics — message counts, task counts, agent counts."""
    result = await bus_client.get_stats()
    return json.dumps(result)


@tool
async def poll_messages() -> str:
    """Check for new messages addressed to BOB or topics BOB subscribes to."""
    result = await bus_client.poll_messages()
    return json.dumps(result)


@tool
async def view_thread(message_id: int) -> str:
    """View a full message thread by the root message ID."""
    result = await bus_client.get_thread(message_id)
    return json.dumps(result)


@tool
def remember(collection: str, doc_id: str, text: str, metadata_json: str = "{}") -> str:
    """Store something in shared memory. Collections: brand_voice, decisions, research, product_specs, project_context."""
    metadata = json.loads(metadata_json)
    metadata["stored_by"] = "BOB"
    metadata["stored_at"] = datetime.now(timezone.utc).isoformat()
    memory.store(collection, doc_id, text, metadata)
    return f"Stored in {collection}/{doc_id}"


@tool
def recall(collection: str, query: str, n_results: int = 5) -> str:
    """Search shared memory for relevant information. Collections: brand_voice, decisions, research, product_specs, project_context."""
    results = memory.query(collection, query, n_results)
    return json.dumps(results)


@tool
def recall_all(collection: str) -> str:
    """Get all documents from a memory collection."""
    results = memory.get_all(collection)
    return json.dumps(results)


@tool
async def notify_rob(topic: str, title: str, message: str, priority: str = "default") -> str:
    """Send a push notification to Rob's phone via ntfy. Topics: bob-critical (urgent), bob-reviews (high), bob-status (default), bob-daily (low). Priority: min, low, default, high, urgent."""
    import os
    from app.retry import with_retry

    ntfy_url = os.getenv("NTFY_URL", "http://ntfy:80")
    ntfy_token = os.getenv("NTFY_TOKEN", "")
    headers = {"Title": title, "Priority": priority}
    if ntfy_token:
        headers["Authorization"] = f"Bearer {ntfy_token}"

    @with_retry(service="default", task_id="notify_rob")
    async def _send():
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{ntfy_url}/{topic}", content=message, headers=headers)
            resp.raise_for_status()

    await _send()
    return f"Notification sent to {topic}: {title}"


@tool
def list_scheduled_jobs() -> str:
    """List all recurring scheduled jobs with their next run time."""
    from app.scheduler import list_jobs
    jobs = list_jobs()
    return json.dumps(jobs)


@tool
def pause_scheduled_job(job_id: str) -> str:
    """Pause a recurring scheduled job. Use list_scheduled_jobs to see available job IDs."""
    from app.scheduler import pause_job
    return json.dumps(pause_job(job_id))


@tool
def resume_scheduled_job(job_id: str) -> str:
    """Resume a paused scheduled job."""
    from app.scheduler import resume_job
    return json.dumps(resume_job(job_id))


@tool
def add_scheduled_job(job_id: str, label: str, task: str, cron_json: str, priority: str = "normal") -> str:
    """Add a new recurring scheduled job. cron_json is a JSON object with APScheduler cron fields like {"day_of_week": "mon", "hour": 9, "minute": 0} or {"hour": 8, "minute": 30} for daily."""
    from app.scheduler import add_job
    cron = json.loads(cron_json)
    return json.dumps(add_job(job_id, label, task, cron, priority))


@tool
def remove_scheduled_job(job_id: str) -> str:
    """Remove a recurring scheduled job permanently. Use list_scheduled_jobs to see available job IDs."""
    from app.scheduler import remove_job
    return json.dumps(remove_job(job_id))


@tool
def trigger_job_now(job_id: str) -> str:
    """Run a scheduled job immediately without waiting for its next scheduled time. Does not affect the normal schedule."""
    from app.scheduler import run_job_now
    return json.dumps(run_job_now(job_id))


@tool
async def check_email() -> str:
    """Check the ATG Gmail inbox for new unread emails. Returns classified email summaries."""
    from app.gmail_monitor import check_inbox
    emails = await check_inbox()
    if not emails:
        return "No new unread emails."
    return json.dumps(emails)


@tool
async def delegate_task(
    title: str,
    description: str,
    team: str = "",
    priority: str = "normal",
    deadline: str = "",
    constraints: str = "",
    deliverables: str = "",
) -> str:
    """Delegate a task to an agent team with an auto-generated structured brief. This is the preferred way to assign work — it pulls brand guidelines, relevant context from memory, and standing orders automatically.

    team: PM, Marketing, Engineering, Research, or empty for unassigned.
    constraints: comma-separated list of constraints (optional).
    deliverables: comma-separated list of expected deliverables (optional).
    deadline: date string like '2026-04-10' (optional).
    """
    from app.briefing import generate_brief, format_brief_as_text

    constraint_list = [c.strip() for c in constraints.split(",") if c.strip()] if constraints else None
    deliverable_list = [d.strip() for d in deliverables.split(",") if d.strip()] if deliverables else None

    brief = generate_brief(
        title=title,
        description=description,
        team=team,
        priority=priority,
        deadline=deadline,
        constraints=constraint_list,
        deliverables=deliverable_list,
    )

    brief_text = format_brief_as_text(brief)

    result = await bus_client.create_task(
        title=title,
        description=brief_text,
        assignee=team or None,
        priority=priority,
        metadata={"brief": brief},
    )
    return json.dumps({
        "status": "delegated",
        "task": result,
        "brief_summary": f"Brief generated with {len(brief.get('context', []))} context items, brand guidelines included.",
    })


@tool
async def generate_daily_briefing() -> str:
    """Compile the daily morning briefing — system health, email status, voice usage, task activity, and upcoming scheduled work. Use this for the daily report or when Rob asks for a status update."""
    from app.daily_report import compose_daily_report
    return await compose_daily_report()


@tool
def email_mark_read(msg_id: str) -> str:
    """Mark a Gmail message as read. Use the message ID from check_email results."""
    from app.gmail_monitor import mark_as_read
    success = mark_as_read(msg_id)
    return json.dumps({"status": "marked_read" if success else "failed", "msg_id": msg_id})


@tool
def email_archive(msg_id: str) -> str:
    """Archive a Gmail message (removes from inbox). Use the message ID from check_email results."""
    from app.gmail_monitor import archive_message
    success = archive_message(msg_id)
    return json.dumps({"status": "archived" if success else "failed", "msg_id": msg_id})


@tool
def email_add_label(msg_id: str, label: str) -> str:
    """Add a label to a Gmail message. Creates the label if it doesn't exist. Useful for organizing: 'BOB-Reviewed', 'Needs-Reply', 'Player-Support', etc."""
    from app.gmail_monitor import add_label
    result = add_label(msg_id, label)
    return json.dumps(result)


@tool
def email_list_labels() -> str:
    """List all Gmail labels available on the ATG account."""
    from app.gmail_monitor import list_labels
    labels = list_labels()
    return json.dumps(labels)


@tool
def check_server_resources() -> str:
    """Check server CPU, memory, and disk usage. Flags anything above 80% as a warning."""
    import psutil
    cpu_pct = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    warnings = []
    if cpu_pct > 80:
        warnings.append(f"CPU at {cpu_pct}%")
    if mem.percent > 80:
        warnings.append(f"Memory at {mem.percent}%")
    if disk.percent > 80:
        warnings.append(f"Disk at {disk.percent}%")

    return json.dumps({
        "cpu_percent": cpu_pct,
        "memory": {
            "total_gb": round(mem.total / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "percent": disk.percent,
        },
        "warnings": warnings or None,
        "status": "warning" if warnings else "healthy",
    })


@tool
async def check_system_health() -> str:
    """Check the health of all infrastructure services — message bus, ChromaDB, Langfuse, ntfy, ElevenLabs API. Returns status for each service."""
    import os
    services = {
        "message_bus": os.getenv("MESSAGE_BUS_URL", "http://message-bus:8585") + "/stats",
        "chromadb": os.getenv("CHROMADB_URL", "http://chromadb:8000") + "/api/v1/heartbeat",
        "langfuse": os.getenv("LANGFUSE_HOST", "http://langfuse:3000") + "/api/public/health",
        "ntfy": os.getenv("NTFY_URL", "http://ntfy:80") + "/v1/health",
    }

    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                resp = await client.get(url)
                results[name] = {
                    "status": "ok" if resp.status_code < 400 else "degraded",
                    "code": resp.status_code,
                }
            except httpx.ConnectError:
                results[name] = {"status": "down", "error": "connection refused"}
            except httpx.TimeoutException:
                results[name] = {"status": "down", "error": "timeout"}
            except Exception as e:
                results[name] = {"status": "unknown", "error": str(e)}

    # ElevenLabs API (external)
    el_key = os.getenv("ELEVENLABS_API_KEY", "")
    if el_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://api.elevenlabs.io/v1/user/subscription",
                    headers={"xi-api-key": el_key},
                )
                if resp.status_code == 200:
                    results["elevenlabs"] = {"status": "ok", "code": 200}
                elif resp.status_code == 401:
                    results["elevenlabs"] = {"status": "auth_failed", "code": 401}
                else:
                    results["elevenlabs"] = {"status": "degraded", "code": resp.status_code}
        except Exception as e:
            results["elevenlabs"] = {"status": "unreachable", "error": str(e)}

    # Bus queue depth
    from app.bus_client import get_queue_depth
    results["bus_offline_queue"] = get_queue_depth()

    # Overall
    down = [k for k, v in results.items() if isinstance(v, dict) and v.get("status") == "down"]
    results["overall"] = "degraded" if down else "healthy"

    return json.dumps(results)


@tool
async def check_voice_usage() -> str:
    """Check ElevenLabs voice minute and character usage for the current billing period. Shows plan tier, minutes used/remaining, and character consumption."""
    from app.elevenlabs_monitor import run_usage_sweep
    result = await run_usage_sweep()
    return json.dumps(result)


@tool
def propose_memory(collection: str, doc_id: str, text: str,
                   proposed_by: str = "", reason: str = "",
                   metadata_json: str = "{}") -> str:
    """Propose a write to shared memory for BOB's review. Agent teams should use this instead of remember() for important shared knowledge. Collections: brand_voice, decisions, research, product_specs, project_context."""
    from app.memory_proposals import propose
    metadata = json.loads(metadata_json)
    result = propose(
        collection=collection,
        doc_id=doc_id,
        text=text,
        metadata=metadata,
        proposed_by=proposed_by,
        reason=reason,
    )
    return json.dumps(result)


@tool
def review_pending_proposals() -> str:
    """List all pending memory proposals awaiting BOB's review."""
    from app.memory_proposals import get_pending
    pending = get_pending()
    if not pending:
        return json.dumps({"pending": [], "message": "No pending proposals."})
    # Trim text for readability
    for p in pending:
        if len(p.get("text", "")) > 200:
            p["text_preview"] = p["text"][:200] + "..."
            del p["text"]
    return json.dumps({"pending": pending, "count": len(pending)})


@tool
def approve_proposal(proposal_id: str, note: str = "") -> str:
    """Approve a memory proposal — commits the data to ChromaDB shared memory."""
    from app.memory_proposals import approve
    return json.dumps(approve(proposal_id, reviewed_by="BOB", note=note))


@tool
def reject_proposal(proposal_id: str, note: str = "") -> str:
    """Reject a memory proposal — data is discarded, not written to shared memory."""
    from app.memory_proposals import reject
    return json.dumps(reject(proposal_id, reviewed_by="BOB", note=note))


@tool
def check_paused_tasks() -> str:
    """Check if any tasks are paused waiting for service recovery. Shows task ID, reason, what service it's waiting for, and retry count."""
    from app.recovery import get_paused_tasks
    tasks = get_paused_tasks()
    if not tasks:
        return json.dumps({"paused_tasks": [], "message": "No paused tasks."})
    return json.dumps({"paused_tasks": tasks, "count": len(tasks)})


@tool
def dismiss_paused_task(task_id: str) -> str:
    """Manually remove a paused task from the recovery queue. Use when a task is no longer needed or Rob wants to cancel it."""
    from app.recovery import remove_paused_task
    removed = remove_paused_task(task_id)
    if removed:
        return json.dumps({"status": "dismissed", "task_id": task_id})
    return json.dumps({"status": "not_found", "task_id": task_id})


@tool
async def check_confirmation(confirmation_id: str) -> str:
    """Check the status of a HIGH-risk tool confirmation. Use this after a tool was blocked pending Rob's approval. Returns: approved, rejected, expired, or pending."""
    from app.firewall import _pending
    conf = _pending.get(confirmation_id)
    if not conf:
        return json.dumps({"status": "not_found", "confirmation_id": confirmation_id})
    if conf.is_expired and conf.status == "pending":
        conf.status = "expired"
    return json.dumps({
        "status": conf.status,
        "confirmation_id": confirmation_id,
        "tool": conf.tool_name,
        "seconds_remaining": conf.seconds_remaining,
    })


def _firewall_wrap(tool_fn):
    """Wrap a LangGraph tool so every call passes through the firewall gate.

    LOW/MEDIUM: execute normally (with audit logging).
    HIGH: block execution, return a message with the confirmation ID.
    INJECTION: deny execution entirely.
    """
    original_func = tool_fn.coroutine if hasattr(tool_fn, 'coroutine') else tool_fn.func

    if inspect.iscoroutinefunction(original_func):
        @functools.wraps(original_func)
        async def wrapper(*args, **kwargs):
            result = gate(tool_fn.name, kwargs)
            if result.decision == FirewallDecision.DENY_INJECTION:
                return json.dumps({"error": "BLOCKED", "reason": result.reason})
            if result.decision == FirewallDecision.DENY_LOOP:
                return json.dumps({
                    "error": "LOOP_DETECTED",
                    "reason": result.reason,
                    "loop_signal": result.loop_signal,
                    "instruction": (
                        "STOP. You are in a loop. Do not retry this tool. "
                        "Either change your approach entirely or escalate to Rob "
                        "and explain what you were trying to do and why it didn't work."
                    ),
                })
            if result.decision == FirewallDecision.PENDING:
                return json.dumps({
                    "status": "BLOCKED_PENDING_CONFIRMATION",
                    "confirmation_id": result.confirmation_id,
                    "reason": result.reason,
                    "instruction": "Tell Rob this action requires his approval. He can confirm via the dashboard or API: POST /firewall/confirm/" + result.confirmation_id,
                })
            return await original_func(*args, **kwargs)
        tool_fn.coroutine = wrapper
    else:
        @functools.wraps(original_func)
        def wrapper(*args, **kwargs):
            result = gate(tool_fn.name, kwargs)
            if result.decision == FirewallDecision.DENY_INJECTION:
                return json.dumps({"error": "BLOCKED", "reason": result.reason})
            if result.decision == FirewallDecision.DENY_LOOP:
                return json.dumps({
                    "error": "LOOP_DETECTED",
                    "reason": result.reason,
                    "loop_signal": result.loop_signal,
                    "instruction": (
                        "STOP. You are in a loop. Do not retry this tool. "
                        "Either change your approach entirely or escalate to Rob."
                    ),
                })
            if result.decision == FirewallDecision.PENDING:
                return json.dumps({
                    "status": "BLOCKED_PENDING_CONFIRMATION",
                    "confirmation_id": result.confirmation_id,
                    "reason": result.reason,
                    "instruction": "Tell Rob this action requires his approval. He can confirm via the dashboard or API: POST /firewall/confirm/" + result.confirmation_id,
                })
            return original_func(*args, **kwargs)
        tool_fn.func = wrapper

    return tool_fn


@tool
async def get_weather(location: str) -> str:
    """Get current weather and a 3-day forecast for a location.

    Uses Open-Meteo (free, no API key). Pass a place name like 'Asheville NC',
    'Boone, NC', 'Raleigh', etc. Returns temperature, conditions, wind, and a
    short forecast. Use this when the user asks about weather, forecast,
    "is it going to rain", outdoor conditions, etc.
    """
    try:
        # Open-Meteo geocoding rejects commas, so use just the city portion
        # for the lookup but keep the original for display fallback.
        lookup_name = location.split(",")[0].strip()
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": lookup_name, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            geo_data = geo.json()
            results = geo_data.get("results") or []
            if not results:
                return json.dumps({"error": f"Location not found: {location}"})
            place = results[0]
            lat, lon = place["latitude"], place["longitude"]
            display = f"{place.get('name','')}, {place.get('admin1','')}, {place.get('country_code','')}".strip(", ")

            wx = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
                    "timezone": "auto",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "precipitation_unit": "inch",
                    "forecast_days": 3,
                },
            )
            wx.raise_for_status()
            data = wx.json()

        # WMO weather code → human label
        codes = {
            0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
            45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
            55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
            71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
            81: "heavy showers", 82: "violent showers", 95: "thunderstorm",
            96: "thunderstorm w/ hail", 99: "severe thunderstorm w/ hail",
        }
        cur = data.get("current", {})
        daily = data.get("daily", {})
        forecast = []
        for i, day in enumerate(daily.get("time", [])):
            forecast.append({
                "date": day,
                "high_f": daily["temperature_2m_max"][i],
                "low_f": daily["temperature_2m_min"][i],
                "conditions": codes.get(daily["weather_code"][i], f"code {daily['weather_code'][i]}"),
                "precip_chance_pct": daily["precipitation_probability_max"][i],
                "precip_inches": daily["precipitation_sum"][i],
                "max_wind_mph": daily["wind_speed_10m_max"][i],
            })
        return json.dumps({
            "location": display,
            "current": {
                "temp_f": cur.get("temperature_2m"),
                "feels_like_f": cur.get("apparent_temperature"),
                "humidity_pct": cur.get("relative_humidity_2m"),
                "conditions": codes.get(cur.get("weather_code"), "?"),
                "wind_mph": cur.get("wind_speed_10m"),
                "is_day": bool(cur.get("is_day")),
            },
            "forecast": forecast,
        })
    except Exception as e:
        logger.exception("get_weather failed")
        return json.dumps({"error": str(e), "location": location})


@tool
async def search_web(query: str, max_results: int = 5) -> str:
    """Search the live internet for current information.

    Uses DuckDuckGo (free, no API key). Returns up to max_results search results
    with title, URL, and snippet. Use this when the user asks about current events,
    recent news, real-time facts, anything that needs the live web. Do NOT use
    this for things you already know from training — only for things that need
    fresh information.
    """
    try:
        from ddgs import DDGS

        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        results = await asyncio.to_thread(_search)
        cleaned = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")[:400],
            }
            for r in (results or [])
        ]
        return json.dumps({"query": query, "results": cleaned, "count": len(cleaned)})
    except Exception as e:
        logger.exception("search_web failed")
        return json.dumps({"error": str(e), "query": query})


@tool
async def analyze_photo(photo_id: str, question: str) -> str:
    """Re-run vision on a previously remembered photo with a new question.
    Use this when the user says "look at the photo I uploaded" or asks a
    follow-up about an image. The photo must have been persisted via
    'remember this' — temp uploads are auto-purged after 60 seconds.
    """
    from app import photo_intake
    try:
        result = await photo_intake.analyze_existing(photo_id, question, user="rob")
        return json.dumps({"photo_id": photo_id, "answer": result["text"],
                          "cost_usd": result["cost_usd"]})
    except Exception as e:
        return json.dumps({"error": str(e), "photo_id": photo_id})


@tool
async def list_recent_photos(limit: int = 10) -> str:
    """List recent photos that were uploaded and remembered. Returns photo IDs,
    upload mode, analysis previews, and timestamps. Use the photo_id with
    analyze_photo to ask follow-up questions about a specific image.
    """
    from app import photo_intake
    photos = photo_intake.list_recent(user=None, limit=limit, only_persisted=True)
    return json.dumps(photos)



# ─────────────────────────── Promotion Gate Tools ────────────────────────────
# Surface the atg-promotion-gate service through BOB chat. Agents (FE/BE) write
# files into proposals/. Rob (or BOB on his behalf) reviews and approves before
# anything lands in the live target tree.
PROMOTION_GATE_URL = os.environ.get("PROMOTION_GATE_URL", "http://promotion-gate:8112")
PROMOTION_GATE_TIMEOUT = 15.0


async def _promotion_get(path: str, params: dict | None = None) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=PROMOTION_GATE_TIMEOUT) as client:
            r = await client.get(f"{PROMOTION_GATE_URL}{path}", params=params or {})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": f"promotion-gate GET {path} failed: {e}"}


async def _promotion_post(path: str, body: dict) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=PROMOTION_GATE_TIMEOUT) as client:
            r = await client.post(f"{PROMOTION_GATE_URL}{path}", json=body)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": f"promotion-gate POST {path} failed: {e}"}


@tool
async def list_pending_promotions() -> str:
    """List all pending file promotions waiting for Rob's approval.

    Returns each promotion's id, source path (under /agent-share/workspace/*/proposals/),
    target path (the live destination), the agent that requested it, the reason, and
    when it was created. Use this when Rob asks "what's waiting for me?" or
    "any pending promotions?". This is a READ-ONLY operation — it does not change anything.
    """
    data = await _promotion_get("/promotions", params={"state": "pending", "limit": 50})
    if "error" in data:
        return json.dumps(data)
    out = []
    for p in data.get("promotions", []):
        out.append({
            "id": p.get("id"),
            "agent": p.get("agent"),
            "source": p.get("source_path"),
            "target": p.get("target_path"),
            "reason": (p.get("reason") or "")[:200],
            "task_id": p.get("task_id"),
            "created_at": p.get("created_at"),
        })
    return json.dumps({"count": len(out), "pending": out})


@tool
async def get_promotion_details(promotion_id: int) -> str:
    """Get the full record for a single promotion by id, including state and timestamps.

    Use this when Rob references a promotion by id and wants more context (who requested it,
    when, what state it is in, who decided it, what the resolution note said). This is
    READ-ONLY — it does not change anything.
    """
    data = await _promotion_get(f"/promotions/{int(promotion_id)}")
    return json.dumps(data)


@tool
async def get_promotion_diff(promotion_id: int) -> str:
    """Get a unified diff preview of a pending promotion: source vs current target.

    Walks both trees file by file. Returns a per-file summary (added / modified /
    unchanged / removed_from_source / binary_skipped) plus the actual unified diff
    text for modified files. Use this BEFORE approving anything so Rob can see what
    will actually change. READ-ONLY.
    """
    data = await _promotion_get(f"/promotions/{int(promotion_id)}/diff")
    if "error" in data:
        return json.dumps(data)
    # Slim the per-file diffs to summary + first 2 modified previews to keep
    # the tool response readable. The full diffs live on the gate.
    summary = data.get("summary", {})
    diffs = data.get("diffs", [])
    preview = []
    modified_shown = 0
    for d in diffs:
        if d.get("kind") == "modified" and modified_shown < 2:
            preview.append(d)
            modified_shown += 1
        elif d.get("kind") != "modified":
            preview.append({"path": d.get("path"), "kind": d.get("kind")})
    return json.dumps({
        "id": data.get("id"),
        "summary": summary,
        "preview": preview,
        "note": "Modified-file previews truncated to first 2; call promotion-gate /promotions/{id}/diff for full diffs.",
    })


@tool
async def approve_promotion(promotion_id: int, note: str = "") -> str:
    """APPROVE a pending promotion — this executes the actual file copy to the live target.

    HIGH-risk operation. Files in the source tree are copied to the target tree
    (e.g. ~/portfolio-site/built-different/). Once applied, the record is frozen
    and there is NO automatic rollback — recovery requires manual git restore or
    a fresh promotion overwriting the new files. Always call get_promotion_diff
    first so you know exactly what will change. The note is recorded in the audit
    trail.
    """
    data = await _promotion_post(
        f"/promotions/{int(promotion_id)}/approve",
        {"approver": "rob", "note": note or ""},
    )
    return json.dumps(data)


@tool
async def reject_promotion(promotion_id: int, note: str = "") -> str:
    """REJECT a pending promotion — marks it rejected. No file copy happens.

    Use this when a proposal is wrong, premature, or unwanted. The record is
    frozen after rejection. The note is recorded in the audit trail and the
    requesting agent can read it (eventually) to learn why.
    """
    data = await _promotion_post(
        f"/promotions/{int(promotion_id)}/reject",
        {"rejector": "rob", "note": note or ""},
    )
    return json.dumps(data)


@tool
async def switch_personality(name: str) -> str:
    """Switch BOB's personality at runtime. Rebuilds the agent with the new
    personality. Available personalities: sardonic, redneck, neutral, terse.
    Use GET /personality/status to see all available options.

    This takes effect on the NEXT message — the current response still uses
    the old personality.
    """
    from app.main import switch_personality_impl
    try:
        result = await switch_personality_impl(name, source="tool")
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# All tools BOB has access to — wrapped with firewall gate
_TOOLS = [
    create_task,
    send_message,
    check_tasks,
    check_agents,
    check_stats,
    poll_messages,
    view_thread,
    remember,
    recall,
    recall_all,
    notify_rob,
    check_email,
    list_scheduled_jobs,
    pause_scheduled_job,
    resume_scheduled_job,
    check_voice_usage,
    check_system_health,
    check_server_resources,
    email_mark_read,
    email_archive,
    email_add_label,
    email_list_labels,
    propose_memory,
    review_pending_proposals,
    approve_proposal,
    reject_proposal,
    check_paused_tasks,
    dismiss_paused_task,
    delegate_task,
    add_scheduled_job,
    remove_scheduled_job,
    trigger_job_now,
    generate_daily_briefing,
    analyze_photo,
    list_recent_photos,
    get_weather,
    search_web,
    list_pending_promotions,
    get_promotion_details,
    get_promotion_diff,
    approve_promotion,
    reject_promotion,
    switch_personality,
]

ALL_TOOLS = [_firewall_wrap(t) for t in _TOOLS + [check_confirmation]]


def wrap_mcp_tool(tool_fn):
    """Wrap an MCP-fetched tool with the BOB firewall.

    MCP tools come from external servers via langchain-mcp-adapters. They're
    StructuredTool instances with the same .coroutine / .func interface as
    native LangChain tools, so _firewall_wrap works on them directly.

    We register MCP tools in the firewall TOOL_REGISTRY at MEDIUM risk by
    default (write, recoverable, logged prominently). Operators can promote
    specific MCP tools to HIGH risk by editing TOOL_REGISTRY in firewall.py
    or by setting an env var (future enhancement).

    Read-only MCP tools could in principle be marked LOW, but we default to
    MEDIUM because we can't introspect side effects from the MCP schema alone.
    """
    from app.firewall import TOOL_REGISTRY, RiskLevel

    name = getattr(tool_fn, "name", None)
    if not name:
        raise ValueError("MCP tool has no .name attribute")

    if name not in TOOL_REGISTRY:
        TOOL_REGISTRY[name] = RiskLevel.MEDIUM
        logger.info(f"Registered MCP tool '{name}' with MEDIUM risk")

    return _firewall_wrap(tool_fn)
