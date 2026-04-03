"""HTTP client for the message bus API."""

import httpx
from app.config import MESSAGE_BUS_URL

_client = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=MESSAGE_BUS_URL, timeout=30.0)
    return _client


async def send_message(recipient: str, message_type: str, payload: dict,
                       topic: str | None = None, task_id: str | None = None,
                       reply_to: int | None = None, priority: str = "normal"):
    """Send a message through the bus."""
    client = get_client()
    body = {
        "sender": "BOB",
        "recipient": recipient,
        "message_type": message_type,
        "payload": payload,
        "priority": priority,
    }
    if topic:
        body["topic"] = topic
    if task_id:
        body["task_id"] = task_id
    if reply_to:
        body["reply_to"] = reply_to
    resp = await client.post("/messages", json=body)
    resp.raise_for_status()
    return resp.json()


async def create_task(title: str, description: str, assignee: str | None = None,
                      priority: str = "normal", metadata: dict | None = None):
    """Create a task on the bus."""
    client = get_client()
    body = {
        "title": title,
        "description": description,
        "priority": priority,
    }
    if assignee:
        body["assignee"] = assignee
    if metadata:
        body["metadata"] = metadata
    resp = await client.post("/tasks", json=body)
    resp.raise_for_status()
    return resp.json()


async def update_task(task_id: int, **kwargs):
    """Update a task (state, assignee, metadata, etc.)."""
    client = get_client()
    resp = await client.patch(f"/tasks/{task_id}", json=kwargs)
    resp.raise_for_status()
    return resp.json()


async def get_tasks(state: str | None = None):
    """Get all tasks, optionally filtered by state."""
    client = get_client()
    params = {}
    if state:
        params["state"] = state
    resp = await client.get("/tasks", params=params)
    resp.raise_for_status()
    return resp.json()


async def get_task(task_id: int):
    """Get a single task."""
    client = get_client()
    resp = await client.get(f"/tasks/{task_id}")
    resp.raise_for_status()
    return resp.json()


async def poll_messages(since: str | None = None, limit: int = 50):
    """Poll for messages addressed to BOB."""
    from datetime import datetime, timedelta, timezone
    client = get_client()
    if not since:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    params = {"agent": "BOB", "limit": limit, "since": since}
    resp = await client.get("/messages/poll", params=params)
    resp.raise_for_status()
    return resp.json()


async def get_stats():
    """Get bus stats."""
    client = get_client()
    resp = await client.get("/stats")
    resp.raise_for_status()
    return resp.json()


async def get_agents():
    """Get all registered agents."""
    client = get_client()
    resp = await client.get("/agents")
    resp.raise_for_status()
    return resp.json()


async def get_thread(message_id: int):
    """Get a message thread."""
    client = get_client()
    resp = await client.get(f"/messages/{message_id}/thread")
    resp.raise_for_status()
    return resp.json()


async def register_bob():
    """Register BOB as an agent on the bus."""
    client = get_client()
    body = {
        "shorthand": "BOB",
        "name": "BOB the Skull",
        "role": "Top-level orchestrator. Rob's primary interface. Activates agent teams, monitors health, handles escalations.",
        "capabilities": [
            {"name": "orchestration"},
            {"name": "escalation_handler"},
            {"name": "health_monitoring"},
            {"name": "daily_reporting"},
            {"name": "task_classification"},
            {"name": "team_management"},
        ]
    }
    resp = await client.post("/agents", json=body)
    resp.raise_for_status()
    return resp.json()


async def subscribe(topic: str):
    """Subscribe BOB to a topic."""
    client = get_client()
    resp = await client.post("/subscriptions", json={"agent": "BOB", "topic": topic})
    resp.raise_for_status()
    return resp.json()
