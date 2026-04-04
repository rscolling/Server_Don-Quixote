"""LangGraph tools — what BOB can do."""

import asyncio
import json
import functools
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
]

ALL_TOOLS = [_firewall_wrap(t) for t in _TOOLS + [check_confirmation]]
