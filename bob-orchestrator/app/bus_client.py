"""HTTP client for the message bus API — with retry and offline queue."""

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx
from app.config import MESSAGE_BUS_URL

logger = logging.getLogger("bob.bus")

_client = None

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = [1, 3, 8]  # seconds between retries

# Offline queue
QUEUE_DB_PATH = os.getenv("BUS_QUEUE_DB_PATH", "/app/data/bus-queue.db")
QUEUE_DRAIN_INTERVAL = 30  # seconds between drain attempts
_drain_task = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=MESSAGE_BUS_URL, timeout=30.0)
    return _client


# ── Retry wrapper ───────────────────────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    """Check if the error is transient and worth retrying."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


async def _request_with_retry(method: str, path: str, **kwargs) -> httpx.Response:
    """Make an HTTP request with exponential backoff retry.

    Raises the last exception if all retries fail.
    """
    client = get_client()
    last_exc = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == MAX_RETRIES:
                raise
            delay = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else RETRY_BACKOFF[-1]
            logger.warning(f"Bus request {method} {path} failed (attempt {attempt + 1}/{MAX_RETRIES + 1}): {exc}. Retrying in {delay}s...")
            await asyncio.sleep(delay)

    raise last_exc


# ── Offline queue (SQLite) ──────────────────────────────────────────────────

def _init_queue_db():
    """Initialize the offline queue database."""
    os.makedirs(os.path.dirname(QUEUE_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(QUEUE_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            body_json TEXT,
            queued_at TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            last_error TEXT
        )
    """)
    conn.commit()
    conn.close()


def _enqueue(method: str, path: str, body: dict | None):
    """Queue a failed write request for later retry."""
    try:
        _init_queue_db()
        conn = sqlite3.connect(QUEUE_DB_PATH)
        conn.execute(
            "INSERT INTO pending_requests (method, path, body_json, queued_at) VALUES (?, ?, ?, ?)",
            (method, path, json.dumps(body) if body else None, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        logger.info(f"Queued offline: {method} {path}")
    except Exception as e:
        logger.error(f"Failed to enqueue request: {e}")


def get_queue_depth() -> int:
    """Return number of pending requests in the offline queue."""
    try:
        _init_queue_db()
        conn = sqlite3.connect(QUEUE_DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM pending_requests")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1


async def drain_queue():
    """Try to flush all queued requests to the bus. Called periodically."""
    try:
        _init_queue_db()
        conn = sqlite3.connect(QUEUE_DB_PATH)
        rows = conn.execute("SELECT id, method, path, body_json, attempts FROM pending_requests ORDER BY id").fetchall()
        conn.close()

        if not rows:
            return

        logger.info(f"Draining offline queue: {len(rows)} pending requests")
        client = get_client()

        for row_id, method, path, body_json, attempts in rows:
            try:
                kwargs = {}
                if body_json:
                    kwargs["json"] = json.loads(body_json)
                resp = await client.request(method, path, **kwargs)
                resp.raise_for_status()

                # Success — remove from queue
                conn = sqlite3.connect(QUEUE_DB_PATH)
                conn.execute("DELETE FROM pending_requests WHERE id = ?", (row_id,))
                conn.commit()
                conn.close()
                logger.info(f"Drained queued request: {method} {path}")
            except Exception as e:
                # Update attempt count
                conn = sqlite3.connect(QUEUE_DB_PATH)
                conn.execute(
                    "UPDATE pending_requests SET attempts = ?, last_error = ? WHERE id = ?",
                    (attempts + 1, str(e), row_id),
                )
                conn.commit()
                conn.close()
                logger.warning(f"Queue drain failed for {method} {path}: {e}")
                break  # Stop draining — bus is probably still down
    except Exception as e:
        logger.error(f"Queue drain error: {e}")


async def _drain_loop():
    """Background task: periodically drain the offline queue."""
    while True:
        await asyncio.sleep(QUEUE_DRAIN_INTERVAL)
        await drain_queue()


def start_drain_task():
    """Start the background queue drain loop. Call once at startup."""
    global _drain_task
    if _drain_task is None:
        _drain_task = asyncio.create_task(_drain_loop())
        logger.info(f"Bus queue drain started (every {QUEUE_DRAIN_INTERVAL}s)")


# ── Write request helper (retry + queue fallback) ──────────────────────────

async def _write_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make a write request with retry + circuit breaker. If all retries fail, queue for later."""
    from app.circuit_breaker import get_breaker
    breaker = get_breaker("message_bus", failure_threshold=5, cooldown_seconds=60)

    if not breaker.can_execute():
        logger.warning(f"Bus circuit OPEN — queueing {method} {path}")
        _enqueue(method, path, body)
        return {"error": "circuit_open", "detail": f"Message bus circuit breaker open. {breaker.status()['cooldown_remaining']}s until probe."}

    kwargs = {}
    if body:
        kwargs["json"] = body
    try:
        resp = await _request_with_retry(method, path, **kwargs)
        breaker.record_success()
        return resp.json()
    except Exception as e:
        breaker.record_failure(str(e))
        logger.error(f"Bus write failed after retries: {method} {path}: {e}")
        _enqueue(method, path, body)
        return {"error": "queued_offline", "detail": str(e)}


async def _read_request(method: str, path: str, **kwargs) -> dict:
    """Make a read request with retry + circuit breaker. No queueing — reads can't be deferred."""
    from app.circuit_breaker import get_breaker
    breaker = get_breaker("message_bus", failure_threshold=5, cooldown_seconds=60)

    if not breaker.can_execute():
        return {"error": "circuit_open", "detail": "Message bus circuit breaker open"}

    try:
        resp = await _request_with_retry(method, path, **kwargs)
        breaker.record_success()
        return resp.json()
    except Exception as e:
        breaker.record_failure(str(e))
        raise


# ── Public API ──────────────────────────────────────────────────────────────

async def send_message(recipient: str, message_type: str, payload: dict,
                       topic: str | None = None, task_id: str | None = None,
                       reply_to: int | None = None, priority: str = "normal"):
    """Send a message through the bus."""
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
    return await _write_request("POST", "/messages", body)


async def create_task(title: str, description: str, assignee: str | None = None,
                      priority: str = "normal", metadata: dict | None = None):
    """Create a task on the bus."""
    body = {
        "title": title,
        "description": description,
        "priority": priority,
    }
    if assignee:
        body["assignee"] = assignee
    if metadata:
        body["metadata"] = metadata
    return await _write_request("POST", "/tasks", body)


async def update_task(task_id: int, **kwargs):
    """Update a task (state, assignee, metadata, etc.)."""
    return await _write_request("PATCH", f"/tasks/{task_id}", kwargs)


async def get_tasks(state: str | None = None):
    """Get all tasks, optionally filtered by state."""
    params = {}
    if state:
        params["state"] = state
    return await _read_request("GET", "/tasks", params=params)


async def get_task(task_id: int):
    """Get a single task."""
    return await _read_request("GET", f"/tasks/{task_id}")


async def poll_messages(since: str | None = None, limit: int = 50):
    """Poll for messages addressed to BOB."""
    if not since:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    params = {"agent": "BOB", "limit": limit, "since": since}
    return await _read_request("GET", "/messages/poll", params=params)


async def get_stats():
    """Get bus stats."""
    return await _read_request("GET", "/stats")


async def get_agents():
    """Get all registered agents."""
    return await _read_request("GET", "/agents")


async def get_thread(message_id: int):
    """Get a message thread."""
    return await _read_request("GET", f"/messages/{message_id}/thread")


async def register_bob():
    """Register BOB as an agent on the bus."""
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
    return await _write_request("POST", "/agents", body)


async def subscribe(topic: str):
    """Subscribe BOB to a topic."""
    return await _write_request("POST", "/subscriptions", {"agent": "BOB", "topic": topic})
