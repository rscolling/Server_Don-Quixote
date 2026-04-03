"""BOB orchestrator — FastAPI wrapper around the LangGraph agent."""

import asyncio
import json
import os
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.graph import build_graph, get_langfuse_handler
from app.memory import init_collections
from app import bus_client

logger = logging.getLogger("bob")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

_start_time = time.time()
_graph = None
_thread_counter = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    logger.info("BOB is waking up...")

    # Init ChromaDB collections
    try:
        init_collections()
        logger.info("ChromaDB collections initialized")
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

    # Build the graph
    _graph = build_graph()
    logger.info("LangGraph agent built. BOB is online.")

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
        from app.tools import notify_rob

        async def _notify(topic, title, message, priority="default"):
            import httpx
            ntfy_url = os.getenv("NTFY_URL", "http://ntfy:80")
            ntfy_token = os.getenv("NTFY_TOKEN", "")
            headers = {"Title": title, "Priority": priority}
            if ntfy_token:
                headers["Authorization"] = f"Bearer {ntfy_token}"
            async with httpx.AsyncClient() as client:
                await client.post(f"{ntfy_url}/{topic}", content=message, headers=headers)

        asyncio.create_task(poll_loop(notify_callback=_notify))
        logger.info("Gmail monitor started")
    except Exception as e:
        logger.warning(f"Gmail monitor not started: {e}")

    yield

    logger.info("BOB is shutting down.")


app = FastAPI(title="BOB — Bound Operational Brain", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
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
    return {
        "status": "ok",
        "persona": "BOB the Skull",
        "uptime_seconds": int(time.time() - _start_time),
        "graph_ready": _graph is not None,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Talk to BOB. This is the primary interface."""
    global _thread_counter

    if _graph is None:
        raise HTTPException(status_code=503, detail="BOB is still waking up. Give him a moment.")

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
        },
        "message_bus": stats,
        "agents": agents,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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
