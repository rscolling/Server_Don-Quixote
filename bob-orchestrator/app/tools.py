"""LangGraph tools — what BOB can do."""

import json
from datetime import datetime, timezone
from langchain_core.tools import tool
from app import bus_client, memory


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
    import httpx
    ntfy_url = os.getenv("NTFY_URL", "http://ntfy:80")
    ntfy_token = os.getenv("NTFY_TOKEN", "")
    headers = {"Title": title, "Priority": priority}
    if ntfy_token:
        headers["Authorization"] = f"Bearer {ntfy_token}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{ntfy_url}/{topic}", content=message, headers=headers)
        resp.raise_for_status()
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
async def check_email() -> str:
    """Check the ATG Gmail inbox for new unread emails. Returns classified email summaries."""
    from app.gmail_monitor import check_inbox
    emails = await check_inbox()
    if not emails:
        return "No new unread emails."
    return json.dumps(emails)


# All tools BOB has access to
ALL_TOOLS = [
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
]
