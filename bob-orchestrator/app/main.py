"""BOB orchestrator — FastAPI wrapper around the LangGraph agent."""

import asyncio
import json
import os
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.graph import build_graph, get_langfuse_handler
from app.memory import init_collections
from app.config import CHECKPOINT_DB_PATH
from app import bus_client

logger = logging.getLogger("bob")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

_start_time = time.time()
_graph = None
_thread_counter = 0


async def _ntfy_send(topic: str, title: str, message: str, priority: str = "default"):
    """Send a push notification via ntfy. Shared by Gmail monitor and ElevenLabs monitor."""
    ntfy_url = os.getenv("NTFY_URL", "http://ntfy:80")
    ntfy_token = os.getenv("NTFY_TOKEN", "")
    headers = {"Title": title, "Priority": priority}
    if ntfy_token:
        headers["Authorization"] = f"Bearer {ntfy_token}"
    async with httpx.AsyncClient() as client:
        await client.post(f"{ntfy_url}/{topic}", content=message, headers=headers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    logger.info("BOB is waking up...")

    # Init ChromaDB collections and seed baseline data
    try:
        init_collections()
        from app.memory import seed_collections
        seeded = seed_collections()
        if seeded:
            logger.info(f"ChromaDB initialized — seeded {seeded} baseline documents")
        else:
            logger.info("ChromaDB collections initialized (already seeded)")
    except Exception as e:
        logger.warning(f"ChromaDB not ready yet: {e}")

    # Register on message bus
    try:
        await bus_client.register_bob()
        for topic in ["escalation", "task:completed", "task:failed", "health:alert", "daily:report"]:
            await bus_client.subscribe(topic)
        logger.info("Registered on message bus")
    except Exception as e:
        logger.warning(f"Message bus not ready yet: {e}")

    # Build the graph with persistent checkpointer
    try:
        import aiosqlite
        conn = await aiosqlite.connect(CHECKPOINT_DB_PATH)
        checkpointer = AsyncSqliteSaver(conn)
        _graph = build_graph(checkpointer=checkpointer)
        logger.info(f"LangGraph agent built with persistent threads at {CHECKPOINT_DB_PATH}. BOB is online.")
    except Exception as e:
        logger.warning(f"Persistent checkpointer failed ({e}), falling back to in-memory")
        from langgraph.checkpoint.memory import MemorySaver
        _graph = build_graph(checkpointer=MemorySaver())
        logger.info("LangGraph agent built with in-memory checkpointer. BOB is online.")

    # Start scheduler
    try:
        from app.scheduler import start_scheduler, set_task_callback

        async def _on_scheduled_task(job_id, label, task, priority):
            """When a scheduled task fires, create it on the message bus."""
            try:
                await bus_client.create_task(
                    title=f"[Scheduled] {label}",
                    description=task,
                    priority=priority,
                )
                logger.info(f"Scheduled task created on bus: {label}")
            except Exception as e:
                logger.error(f"Failed to create scheduled task: {e}")

        set_task_callback(_on_scheduled_task)
        start_scheduler()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning(f"Scheduler not started: {e}")

    # Start Gmail monitor background task
    try:
        from app.gmail_monitor import poll_loop

        asyncio.create_task(poll_loop(
            notify_callback=_ntfy_send,
            email_callback=add_pending_email,
        ))
        logger.info("Gmail monitor started")
    except Exception as e:
        logger.warning(f"Gmail monitor not started: {e}")

    # Start message bus offline queue drain loop
    bus_client.start_drain_task()

    # Start ElevenLabs usage monitor
    try:
        from app.elevenlabs_monitor import monitoring_loop, set_notify_callback

        set_notify_callback(_ntfy_send)
        asyncio.create_task(monitoring_loop())
        logger.info("ElevenLabs usage monitor started")
    except Exception as e:
        logger.warning(f"ElevenLabs monitor not started: {e}")

    yield

    logger.info("BOB is shutting down.")


app = FastAPI(title="BOB — Bound Operational Brain", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://appalachiantoysgames.com",
        "https://www.appalachiantoysgames.com",
        "https://voice.appalachiantoysgames.com",
        "https://bob.appalachiantoysgames.com",
        "http://192.168.1.228:8100",   # LAN dashboard
        "http://192.168.1.228:8200",   # LAN dashboard
        "http://localhost:8100",
    ],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    tool_calls: list[dict] | None = None


@app.get("/health")
async def health():
    el_status = None
    try:
        from app.elevenlabs_monitor import get_last_sweep
        el_status = get_last_sweep()
    except Exception:
        pass

    result = {
        "status": "ok",
        "persona": "BOB the Skull",
        "uptime_seconds": int(time.time() - _start_time),
        "graph_ready": _graph is not None,
        "bus_queue_depth": bus_client.get_queue_depth(),
    }
    if el_status:
        result["elevenlabs"] = {
            "tier": el_status["tier"],
            "voice_pct": el_status["voice_pct"],
            "voice_remaining_min": el_status["voice_minutes_remaining"],
            "char_pct": el_status["char_pct"],
        }
    try:
        from app.circuit_breaker import all_status
        breakers = all_status()
        if breakers:
            result["circuit_breakers"] = breakers
    except Exception:
        pass
    return result


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    """Talk to BOB. This is the primary interface."""
    global _thread_counter

    if _graph is None:
        raise HTTPException(status_code=503, detail="BOB is still waking up. Give him a moment.")

    # Rate limiting
    from app.rate_limit import check_rate_limit, get_client_ip
    client_ip = get_client_ip(request)

    # Check per-minute limit
    allowed, info = check_rate_limit(client_ip, "chat")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Try again in {info.get('retry_after', 60)} seconds.",
            headers={"Retry-After": str(info.get("retry_after", 60))},
        )

    # Check per-hour burst limit
    allowed, info = check_rate_limit(client_ip, "chat_burst")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Hourly limit reached. Try again in {info.get('retry_after', 3600)} seconds.",
            headers={"Retry-After": str(info.get("retry_after", 3600))},
        )

    thread_id = req.thread_id
    if not thread_id:
        _thread_counter += 1
        thread_id = f"chat-{_thread_counter}-{int(time.time())}"

    config = {"configurable": {"thread_id": thread_id}}

    # Attach Langfuse tracing if available
    langfuse = get_langfuse_handler()
    if langfuse:
        config["callbacks"] = [langfuse]

    try:
        result = await _graph.ainvoke(
            {"messages": [{"role": "user", "content": req.message}]},
            config=config,
        )
    except Exception as e:
        logger.error(f"Graph error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Extract the final AI message
    messages = result.get("messages", [])
    ai_messages = [m for m in messages if hasattr(m, "type") and m.type == "ai" and m.content]

    if not ai_messages:
        response_text = "I processed that, but I don't have anything to say about it. Which is unusual for me."
    else:
        response_text = ai_messages[-1].content

    # Extract tool calls for transparency
    tool_calls = []
    for m in messages:
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                tool_calls.append({"name": tc.get("name", ""), "args": tc.get("args", {})})

    return ChatResponse(
        response=response_text,
        thread_id=thread_id,
        tool_calls=tool_calls or None,
    )


@app.get("/status")
async def status():
    """Full system status — what BOB sees."""
    try:
        stats = await bus_client.get_stats()
    except Exception:
        stats = {"error": "message bus unreachable"}

    try:
        agents = await bus_client.get_agents()
    except Exception:
        agents = {"error": "message bus unreachable"}

    return {
        "bob": {
            "status": "online" if _graph else "starting",
            "uptime_seconds": int(time.time() - _start_time),
            "bus_queue_depth": bus_client.get_queue_depth(),
        },
        "message_bus": stats,
        "agents": agents,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Email triage endpoints ─────────────────────────────────────────────────

_pending_emails: list[dict] = []


@app.get("/email/pending")
async def get_pending_emails():
    """Emails BOB has flagged for Rob's attention."""
    return {"emails": _pending_emails}


@app.post("/email/{msg_id}/dismiss")
async def dismiss_email(msg_id: str):
    """Rob has reviewed this email — remove from pending."""
    global _pending_emails
    _pending_emails = [e for e in _pending_emails if e.get("id") != msg_id]
    return {"status": "dismissed"}


@app.get("/email/status")
async def email_status():
    """Gmail connection health check."""
    try:
        from app.gmail_monitor import _get_gmail_service
        service = _get_gmail_service()
        if service:
            profile = service.users().getProfile(userId="me").execute()
            return {
                "status": "connected",
                "email": profile.get("emailAddress"),
                "total_messages": profile.get("messagesTotal"),
            }
        return {"status": "disconnected", "error": "No valid credentials"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def add_pending_email(email_summary: dict):
    """Called by the Gmail monitor to surface emails for dashboard."""
    _pending_emails.append(email_summary)
    # Keep only last 50 to prevent unbounded growth
    if len(_pending_emails) > 50:
        _pending_emails.pop(0)


# ── Thread history endpoints ────────────────────────────────────────────────

@app.get("/threads")
async def list_threads(limit: int = 20):
    """List recent conversation threads (most recent first)."""
    if _graph is None:
        raise HTTPException(status_code=503, detail="BOB is still waking up.")
    try:
        import aiosqlite
        async with aiosqlite.connect(CHECKPOINT_DB_PATH) as db:
            cursor = await db.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY rowid DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return {"threads": [row[0] for row in rows]}
    except Exception as e:
        logger.warning(f"Could not list threads: {e}")
        return {"threads": [], "error": str(e)}


# ── Firewall endpoints ──────────────────────────────────────────────────────

from app import firewall


@app.get("/firewall/pending")
async def firewall_pending():
    """List pending HIGH-risk confirmations."""
    pending = firewall.get_pending()
    return [
        {
            "confirmation_id": c.confirmation_id,
            "tool": c.tool_name,
            "params": c.params,
            "seconds_remaining": c.seconds_remaining,
        }
        for c in pending
    ]


@app.post("/firewall/confirm/{confirmation_id}")
async def firewall_confirm(confirmation_id: str):
    """Approve a HIGH-risk tool execution."""
    conf = firewall.confirm(confirmation_id)
    if not conf:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    if conf.status == "expired":
        raise HTTPException(status_code=410, detail="Confirmation expired")
    firewall.write_audit("confirmed", conf.tool_name, "high", {"confirmation_id": confirmation_id})
    return {"status": "approved", "tool": conf.tool_name}


@app.post("/firewall/reject/{confirmation_id}")
async def firewall_reject(confirmation_id: str):
    """Reject a HIGH-risk tool execution."""
    conf = firewall.reject(confirmation_id)
    if not conf:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    firewall.write_audit("rejected", conf.tool_name, "high", {"confirmation_id": confirmation_id})
    return {"status": "rejected", "tool": conf.tool_name}


@app.get("/firewall/audit")
async def firewall_audit(limit: int = 50):
    """Read the last N audit log entries."""
    try:
        with open(firewall.AUDIT_LOG_PATH) as f:
            lines = f.readlines()
        entries = [json.loads(line) for line in lines[-limit:]]
        return entries
    except FileNotFoundError:
        return []
