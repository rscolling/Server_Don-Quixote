"""BOB orchestrator — FastAPI wrapper around the LangGraph agent."""

import asyncio
import json
import os
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.graph import build_graph, build_tiered_graphs, get_langfuse_handler
from app.memory import init_collections
from app.config import (
    CHECKPOINT_DB_PATH,
    CORS_ORIGINS,
    validate_config,
    MCP_CLIENT_ENABLED,
    MCP_CLIENT_CONFIG_PATH,
    MCP_CLIENT_FETCH_TIMEOUT,
    MCP_SERVER_ENABLED,
    MCP_SERVER_PORT,
    MCP_SERVER_TRANSPORT,
)
from app import bus_client

from app.logging_config import setup_logging
setup_logging()
logger = logging.getLogger("bob")

_start_time = time.time()
_graph = None
_tiered_graphs = None
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
    global _graph, _tiered_graphs
    logger.info("BOB is waking up...")

    # Validate config
    config_errors = validate_config()
    if config_errors:
        for err in config_errors:
            logger.error(f"Config error: {err}")
        raise RuntimeError(f"BOB cannot start: {', '.join(config_errors)}")

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

    # Fetch MCP tools from external servers (must happen BEFORE building the graph)
    mcp_tools = []
    if MCP_CLIENT_ENABLED:
        try:
            from app.mcp_client import init_mcp_client
            mcp_tools = await init_mcp_client(
                MCP_CLIENT_CONFIG_PATH,
                fetch_timeout=MCP_CLIENT_FETCH_TIMEOUT,
            )
            if mcp_tools:
                logger.info(f"MCP client loaded {len(mcp_tools)} external tools")
        except Exception as e:
            logger.warning(f"MCP client init failed: {e}")
    else:
        logger.info("MCP client disabled (MCP_CLIENT_ENABLED=false)")

    # Build the graph with persistent checkpointer + any MCP tools
    from app.config import BOB_ROUTING_ENABLED
    try:
        import aiosqlite
        conn = await aiosqlite.connect(CHECKPOINT_DB_PATH)
        checkpointer = AsyncSqliteSaver(conn)
    except Exception as e:
        logger.warning(f"Persistent checkpointer failed ({e}), falling back to in-memory")
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    if BOB_ROUTING_ENABLED:
        _tiered_graphs = build_tiered_graphs(checkpointer=checkpointer, extra_tools=mcp_tools)
        _graph = _tiered_graphs["heavy"]  # fallback for non-chat endpoints
        logger.info(f"Tiered routing enabled: {list(_tiered_graphs.keys())} graphs built. BOB is online.")
    else:
        _graph = build_graph(checkpointer=checkpointer, extra_tools=mcp_tools)
        logger.info("Single-model mode (routing disabled). BOB is online.")

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

    # Start recovery monitor (auto-resumes paused tasks)
    try:
        from app.recovery import recovery_monitor_loop
        from app.recovery import set_notify_callback as set_recovery_notify

        set_recovery_notify(_ntfy_send)
        asyncio.create_task(recovery_monitor_loop())
        logger.info("Recovery monitor started")
    except Exception as e:
        logger.warning(f"Recovery monitor not started: {e}")

    # Start MCP server (expose BOB's capabilities to other AI clients)
    if MCP_SERVER_ENABLED:
        try:
            from app.mcp_server import start_mcp_server
            await start_mcp_server(port=MCP_SERVER_PORT, transport=MCP_SERVER_TRANSPORT)
        except Exception as e:
            logger.warning(f"MCP server not started: {e}")
    else:
        logger.info("MCP server disabled (MCP_SERVER_ENABLED=false)")

    yield

    logger.info("BOB is shutting down.")

    # Cleanup MCP client + server
    try:
        from app.mcp_client import close_mcp_client
        await close_mcp_client()
    except Exception as e:
        logger.warning(f"MCP client cleanup error: {e}")
    try:
        from app.mcp_server import stop_mcp_server
        await stop_mcp_server()
    except Exception as e:
        logger.warning(f"MCP server cleanup error: {e}")


app = FastAPI(title="BOB — Bound Operational Brain", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

# Dashboard API proxy (must come before static mount)
from app.dashboard_api import router as dashboard_api_router
app.include_router(dashboard_api_router)

# Dashboard static files (React SPA)
import os as _os
_dashboard_dir = "/app/dashboard/dist"
if _os.path.isdir(_dashboard_dir):
    from fastapi.staticfiles import StaticFiles
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
    logger.info(f"Dashboard mounted at /dashboard from {_dashboard_dir}")


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    tool_calls: list[dict] | None = None
    model_tier: str | None = None
    model_used: str | None = None


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
    try:
        from app.cost_tracker import status_summary
        result["cost"] = status_summary()
    except Exception:
        pass
    try:
        from app.loop_detector import all_threads_summary
        result["loop_detector"] = all_threads_summary()
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

    # Cost budget guard — abort before BOB even calls the LLM if over budget.
    # Identifies the user from the request (real auth integration to come;
    # for now we use the client IP as a coarse user identifier on /chat).
    try:
        from app.cost_tracker import check_budget
        user_identifier = client_ip
        budget_check = check_budget(user_identifier)
        if not budget_check["allowed"]:
            raise HTTPException(
                status_code=429,
                detail=f"Budget guard: {budget_check['reason']}",
                headers={
                    "X-Budget-Daily-Spend": str(budget_check["daily_spend"]),
                    "X-Budget-Daily-Limit": str(budget_check["daily_budget"]),
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        # Cost tracker should never block BOB if it has internal errors —
        # log and continue. Production hardening means failing OPEN on
        # this kind of advisory check, not closed.
        logger.warning(f"Cost tracker error (non-fatal): {e}")

    thread_id = req.thread_id
    if not thread_id:
        _thread_counter += 1
        thread_id = f"chat-{_thread_counter}-{int(time.time())}"

    # Identify user via pluggable auth backend
    try:
        from app.auth import identify_user
        user = await identify_user(request)
    except Exception as e:
        logger.warning(f"Auth identification error (non-fatal): {e}")
        from app.auth import GUEST
        user = GUEST

    # Track user session
    try:
        from app.user_sessions import open_session, update_session
        open_session(
            session_id=thread_id,
            endpoint="chat",
            user_email=user.email or client_ip,
            user_name=user.display_name or client_ip,
            user_role=user.role.value,
            client_ip=client_ip,
            latitude=req.latitude,
            longitude=req.longitude,
        )
        update_session(thread_id, increment_messages=True,
                       latitude=req.latitude, longitude=req.longitude)
    except Exception as e:
        logger.warning(f"Session tracking error (non-fatal): {e}")

    config = {"configurable": {"thread_id": thread_id}}

    # Attach Langfuse tracing if available
    langfuse = get_langfuse_handler()
    if langfuse:
        config["callbacks"] = [langfuse]

    # ── Route to the right tier ──────────────────────────────────────────
    tier_used = None
    model_used = None

    if _tiered_graphs:
        from app.router import classify, get_tier_model, Tier
        from app.config import BOB_LLM_PROVIDER, BOB_LLM_API_KEY, BOB_MODEL_LIGHT, BOB_MODEL_HEAVY

        decision = await classify(req.message, BOB_LLM_PROVIDER, BOB_LLM_API_KEY)
        tier_used = decision.tier.value
        model_used = get_tier_model(
            decision.tier, BOB_LLM_PROVIDER,
            BOB_MODEL_LIGHT if decision.tier == Tier.LIGHT else BOB_MODEL_HEAVY,
        )
        graph = _tiered_graphs[tier_used]
        logger.info(f"[{thread_id}] Routed to {tier_used} ({model_used}): {decision.reason}")
    else:
        graph = _graph

    # Inject browser geolocation into the message if provided
    user_message = req.message
    if req.latitude is not None and req.longitude is not None:
        location_note = f"[USER_LOCATION: lat={req.latitude}, lon={req.longitude}]\n"
        user_message = location_note + user_message

    try:
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": user_message}]},
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
        model_tier=tier_used,
        model_used=model_used,
    )


# ── Router status ─────────────────────────────────────────────────────────

@app.get("/router/status")
async def router_status():
    """Show routing configuration and tier-to-model mapping."""
    from app.config import BOB_ROUTING_ENABLED, BOB_LLM_PROVIDER, BOB_MODEL_LIGHT, BOB_MODEL_HEAVY

    result = {"enabled": BOB_ROUTING_ENABLED}
    if BOB_ROUTING_ENABLED:
        from app.router import Tier, get_tier_model
        result["provider"] = BOB_LLM_PROVIDER
        result["tiers"] = {
            tier.value: get_tier_model(
                tier, BOB_LLM_PROVIDER,
                BOB_MODEL_LIGHT if tier == Tier.LIGHT else BOB_MODEL_HEAVY,
            )
            for tier in Tier
        }
    return result


# ── Memory proposal endpoints ──────────────────────────────────────────────

@app.get("/proposals/pending")
async def proposals_pending():
    """List pending memory proposals."""
    from app.memory_proposals import get_pending
    return {"proposals": get_pending()}


@app.post("/proposals/{proposal_id}/approve")
async def proposal_approve(proposal_id: str, note: str = ""):
    """Approve a memory proposal via API."""
    from app.memory_proposals import approve
    result = approve(proposal_id, reviewed_by="Rob (API)", note=note)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/proposals/{proposal_id}/reject")
async def proposal_reject(proposal_id: str, note: str = ""):
    """Reject a memory proposal via API."""
    from app.memory_proposals import reject
    result = reject(proposal_id, reviewed_by="Rob (API)", note=note)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/proposals/history")
async def proposals_history(limit: int = 20):
    """Recent proposal history."""
    from app.memory_proposals import get_history
    return {"proposals": get_history(limit)}


# ── A2A protocol endpoints (Agent-to-Agent federation) ─────────────────────

@app.get("/a2a/.well-known/agent.json")
async def a2a_agent_card_endpoint(request: Request):
    """A2A discovery endpoint. Peer agents fetch this to learn what BOB can do."""
    from app.a2a import agent_card
    # Build the public URL from the request so peers know how to reach us
    public_url = str(request.base_url).rstrip("/")
    return agent_card(public_url=public_url)


@app.post("/a2a/message")
async def a2a_message_endpoint(payload: dict, request: Request):
    """Receive an A2A message from a peer agent and dispatch to a BOB skill."""
    from app.a2a import handle_message
    skill = payload.get("skill", "")
    input_obj = payload.get("input", {}) or {}
    input_text = input_obj.get("text", "") if isinstance(input_obj, dict) else str(input_obj)
    if not skill or not input_text:
        raise HTTPException(status_code=400, detail="payload must include 'skill' and 'input.text'")

    # Optional bearer auth
    auth_header = request.headers.get("authorization", "")
    auth_token = None
    if auth_header.lower().startswith("bearer "):
        auth_token = auth_header[7:].strip()

    task = await handle_message(skill, input_text, auth_token=auth_token)
    return task.to_dict()


@app.get("/a2a/task/{task_id}")
async def a2a_task_status(task_id: str):
    """Look up a previously-submitted A2A task by ID."""
    from app.a2a import get_task
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return task.to_dict()


@app.get("/a2a/status")
async def a2a_status_endpoint():
    """A2A configuration and recent task summary."""
    from app.a2a import status, list_recent_tasks
    return {
        "config": status(),
        "recent_tasks": list_recent_tasks(limit=10),
    }


@app.get("/a2a/peers")
async def a2a_peers_endpoint():
    """Discover the agent cards of all configured A2A peers."""
    from app.a2a import discover_peers
    return await discover_peers()


# ── Replay endpoints (deterministic audit log replay) ──────────────────────

@app.get("/replay/audit/{audit_id}")
async def replay_audit_entry(audit_id: str, include_writes: bool = False,
                              dry_run: bool = True):
    """Replay a single audit log entry by its short ID.

    Default is dry_run=True (returns what the replay WOULD do without
    invoking the tool). Pass dry_run=false to actually execute.
    Default is include_writes=False — write tools (create_task, send_message,
    notify_rob, etc.) are skipped to avoid duplicating side effects.
    """
    from app.replay import replay_by_id
    return await replay_by_id(audit_id, include_writes=include_writes, dry_run=dry_run)


@app.get("/replay/recent")
async def replay_recent_endpoint(tool: str = "", limit: int = 10,
                                  include_writes: bool = False, dry_run: bool = True):
    """Replay the most recent N audit entries.

    Args:
        tool: Filter to a specific tool name (e.g., 'check_email')
        limit: Number of entries to replay (default 10)
        include_writes: Allow replay of write tools (default false)
        dry_run: Don't actually invoke tools (default true)
    """
    from app.replay import replay_recent
    return await replay_recent(
        tool_filter=tool or None,
        limit=limit,
        include_writes=include_writes,
        dry_run=dry_run,
    )


# ── Personality endpoints ──────────────────────────────────────────────────

@app.get("/personality/status")
async def personality_status_endpoint():
    """Show which personality variant BOB is using and what other variants
    are available. Set BOB_PERSONALITY env var and restart to switch.
    """
    from app.personality import status
    return status()


# ── Memory export / import endpoints ───────────────────────────────────────

@app.get("/memory/export")
async def memory_export(collections: str = ""):
    """Export memory as JSON. Optional `collections` query param is a
    comma-separated list of collection names; default exports all.

    The output can be saved and later imported into another BOB instance
    via POST /memory/import. The format is portable across vector DB
    implementations because it includes only text and metadata, not
    embeddings.
    """
    from app.memory import export_all
    target = [c.strip() for c in collections.split(",") if c.strip()] if collections else None
    return export_all(target)


@app.post("/memory/import")
async def memory_import(data: dict, mode: str = "merge"):
    """Import a previously-exported memory dump.

    Modes:
        - merge (default): upsert each entry, existing IDs get overwritten
        - replace: wipe each target collection first, then import (destructive)

    Pass the export dict in the request body. To import a file from disk,
    use the orchestrator container shell:
        docker exec atg-bob python -c "from app.memory import import_from_file; print(import_from_file('/app/data/snapshot.json'))"
    """
    from app.memory import import_all
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode must be 'merge' or 'replace'")
    return import_all(data, mode=mode)


# ── Cost tracking endpoints ────────────────────────────────────────────────

@app.get("/cost/status")
async def cost_status():
    """Current cost spend, budget remaining, and breakdown by user/model."""
    from app.cost_tracker import status_summary, get_breakdown
    return {
        "summary": status_summary(),
        "last_7_days": get_breakdown(days=7),
    }


@app.get("/cost/check/{user}")
async def cost_check_user(user: str):
    """Check if a specific user is within their budget."""
    from app.cost_tracker import check_budget
    return check_budget(user)


# ── Photo intake (smartphone vision) ──────────────────────────────────────
# These endpoints are intended to be reached via the voice service proxy
# (which handles auth). LAN-internal — do not expose to the public CF tunnel.

@app.post("/photos/upload")
async def photos_upload(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    mode: str = Form("analyze"),
    user: str = Form("anonymous"),
):
    """Upload a photo, run vision, return the analysis. Photo is held in
    a temp dir and auto-purges in PHOTO_TEMP_TTL_SECONDS unless the caller
    POSTs to /photos/remember/{photo_id}.
    """
    from app import photo_intake
    from app.cost_tracker import check_budget, check_vision_budget
    from app.firewall import gate, FirewallDecision

    # Firewall + budget guards
    fw = gate("upload_photo", {"prompt": prompt[:500], "mode": mode}, thread_id=f"photo:{user}")
    if fw.decision in (FirewallDecision.DENY_INJECTION, FirewallDecision.DENY_LOOP):
        raise HTTPException(status_code=403, detail=f"firewall: {fw.reason}")

    budget = check_budget(user)
    if not budget["allowed"]:
        raise HTTPException(status_code=429, detail=budget["reason"])
    vbudget = check_vision_budget(user)
    if not vbudget["allowed"]:
        raise HTTPException(status_code=429, detail=vbudget["reason"])

    image_bytes = await file.read()
    mimetype = (file.content_type or "image/jpeg").lower()

    try:
        result = await photo_intake.process_photo(
            image_bytes=image_bytes,
            mimetype=mimetype,
            user=user,
            prompt=prompt,
            mode=mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("photo upload failed")
        raise HTTPException(status_code=500, detail=str(e))

    return result


@app.post("/photos/remember/{photo_id}")
async def photos_remember(photo_id: str, user: str = Form("anonymous")):
    """Persist a temp photo so BOB can recall it later."""
    from app import photo_intake
    result = photo_intake.remember_photo(photo_id, user)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "not found"))
    return result


@app.get("/photos/recent")
async def photos_recent(user: str = "", limit: int = 10):
    """List recent persisted photos. Without ?user= returns across all users."""
    from app import photo_intake
    return {"photos": photo_intake.list_recent(user=user or None, limit=limit)}


@app.get("/photos/{photo_id}")
async def photos_get(photo_id: str):
    """Get the metadata + analysis for a single photo."""
    from app import photo_intake
    rec = photo_intake.get_photo_record(photo_id)
    if not rec:
        raise HTTPException(status_code=404, detail="photo not found")
    rec.pop("path", None)  # don't leak filesystem path
    return rec


# ── LLM provider introspection ─────────────────────────────────────────────

@app.get("/llm/status")
async def llm_status():
    """Show which LLM provider BOB is using and which providers are available.

    Useful for the dashboard, debugging "why isn't BOB responding," and
    confirming you actually swapped providers when you thought you did.
    """
    from app.llm import list_providers
    from app.config import (BOB_LLM_PROVIDER, BOB_MODEL, BOB_LLM_MAX_TOKENS,
                            BOB_LLM_BASE_URL)

    return {
        "active": {
            "provider": BOB_LLM_PROVIDER,
            "model": BOB_MODEL or "(provider default)",
            "max_tokens": BOB_LLM_MAX_TOKENS,
            "base_url": BOB_LLM_BASE_URL or "(provider default)",
        },
        "providers": list_providers(),
    }


# ── MCP introspection endpoints ────────────────────────────────────────────

@app.get("/mcp/status")
async def mcp_status():
    """Show the status of MCP integration — both client and server.

    Useful for the dashboard and for debugging which MCP tools BOB has access
    to and which capabilities he's exposing to other clients.
    """
    result = {
        "client": {
            "enabled": MCP_CLIENT_ENABLED,
            "config_path": MCP_CLIENT_CONFIG_PATH,
            "loaded_tools": [],
        },
        "server": {
            "enabled": MCP_SERVER_ENABLED,
            "port": MCP_SERVER_PORT,
            "transport": MCP_SERVER_TRANSPORT,
        },
    }

    if MCP_CLIENT_ENABLED:
        try:
            from app.mcp_client import get_loaded_tool_names
            result["client"]["loaded_tools"] = get_loaded_tool_names()
            result["client"]["tool_count"] = len(result["client"]["loaded_tools"])
        except Exception as e:
            result["client"]["error"] = str(e)

    return result


@app.get("/mcp/tools")
async def mcp_tools_list():
    """List all MCP tools currently available to BOB, with their source server."""
    if not MCP_CLIENT_ENABLED:
        return {"tools": [], "note": "MCP client disabled"}
    try:
        from app.mcp_client import get_loaded_tools
        tools = get_loaded_tools()
        return {
            "tools": [
                {
                    "name": getattr(t, "name", "?"),
                    "description": getattr(t, "description", "")[:200],
                }
                for t in tools
            ],
            "count": len(tools),
        }
    except Exception as e:
        return {"tools": [], "error": str(e)}


# ── Recovery endpoints ─────────────────────────────────────────────────────

@app.get("/recovery/paused")
async def get_paused_tasks():
    """List all tasks paused waiting for service recovery."""
    from app.recovery import get_paused_tasks as _get_paused
    return {"paused_tasks": _get_paused()}


@app.post("/recovery/dismiss/{task_id}")
async def dismiss_paused(task_id: str):
    """Manually dismiss a paused task."""
    from app.recovery import remove_paused_task
    removed = remove_paused_task(task_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "dismissed", "task_id": task_id}


@app.get("/auth/status")
async def auth_status():
    """Show auth backend configuration and supported identity providers."""
    from app.auth import status as _auth_status
    return _auth_status()


@app.get("/auth/me")
async def auth_me(request: Request):
    """Return the identity of the current caller. Useful for testing auth."""
    from app.auth import identify_user
    user = await identify_user(request)
    return user.to_dict()


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

    paused = []
    try:
        from app.recovery import get_paused_tasks as _get_paused
        paused = _get_paused()
    except Exception:
        pass

    return {
        "bob": {
            "status": "online" if _graph else "starting",
            "uptime_seconds": int(time.time() - _start_time),
            "bus_queue_depth": bus_client.get_queue_depth(),
            "paused_tasks": len(paused),
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
