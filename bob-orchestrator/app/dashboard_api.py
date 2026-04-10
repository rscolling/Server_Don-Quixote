"""Dashboard API proxy — routes browser requests to internal services.

The React dashboard SPA talks only to BOB at :8100. This router proxies
requests to the message bus (:8585) and local BOB endpoints, keeping the
bus off the public network and avoiding CORS issues.
"""

import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
import httpx

from app.config import MESSAGE_BUS_URL

logger = logging.getLogger("bob.dashboard")

router = APIRouter(prefix="/dashboard/api", tags=["dashboard"])

BUS_TIMEOUT = 10.0


async def _proxy_get(path: str, params: dict) -> JSONResponse:
    clean = {k: v for k, v in params.items() if v is not None}
    async with httpx.AsyncClient(base_url=MESSAGE_BUS_URL, timeout=BUS_TIMEOUT) as c:
        resp = await c.get(path, params=clean)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)


async def _proxy_patch(path: str, body: dict) -> JSONResponse:
    async with httpx.AsyncClient(base_url=MESSAGE_BUS_URL, timeout=BUS_TIMEOUT) as c:
        resp = await c.patch(path, json=body)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)


# ── Bus proxy endpoints ──────────────────────────────────────────────────

@router.get("/tasks")
async def proxy_tasks(
    state: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    limit: int = 200,
    offset: int = 0,
):
    return await _proxy_get("/tasks", {
        "state": state, "assignee": assignee, "priority": priority,
        "limit": limit, "offset": offset,
    })


@router.get("/tasks/{task_id}")
async def proxy_task_detail(task_id: int):
    return await _proxy_get(f"/tasks/{task_id}", {})


@router.patch("/tasks/{task_id}")
async def proxy_task_update(task_id: int, request: Request):
    body = await request.json()
    return await _proxy_patch(f"/tasks/{task_id}", body)


@router.get("/messages")
async def proxy_messages(
    sender: str | None = None,
    recipient: str | None = None,
    message_type: str | None = None,
    task_id: int | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    return await _proxy_get("/messages", {
        "sender": sender, "recipient": recipient, "message_type": message_type,
        "task_id": task_id, "since": since, "limit": limit, "offset": offset,
    })


@router.get("/agents")
async def proxy_agents():
    return await _proxy_get("/agents", {})


@router.get("/stats")
async def proxy_stats():
    return await _proxy_get("/stats", {})


# ── Local BOB endpoints (no proxy needed, just re-expose) ────────────────

@router.get("/health")
async def dashboard_health():
    from app.main import health
    return await health()


@router.get("/cost")
async def dashboard_cost():
    from app.cost_tracker import (
        get_breakdown, get_daily_spend, get_monthly_spend,
        DAILY_BUDGET_USD_TOTAL, MONTHLY_BUDGET_USD_TOTAL,
    )
    breakdown = get_breakdown(days=7)
    breakdown["daily_spend"] = round(get_daily_spend(), 4)
    breakdown["daily_budget"] = DAILY_BUDGET_USD_TOTAL
    breakdown["monthly_spend"] = round(get_monthly_spend(), 4)
    breakdown["monthly_budget"] = MONTHLY_BUDGET_USD_TOTAL
    return breakdown


@router.get("/router")
async def dashboard_router():
    from app.config import BOB_ROUTING_ENABLED, BOB_LLM_PROVIDER, BOB_MODEL_LIGHT, BOB_MODEL_HEAVY
    result: dict = {"enabled": BOB_ROUTING_ENABLED}
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


# ── Session tracking endpoints ────────────────────────────────────────────

@router.get("/sessions/active")
async def sessions_active():
    from app.user_sessions import get_active_sessions
    return get_active_sessions()


@router.get("/sessions/all")
async def sessions_all(limit: int = 100):
    from app.user_sessions import get_all_sessions
    return get_all_sessions(limit=limit)


@router.get("/sessions/users")
async def sessions_users():
    from app.user_sessions import get_unique_users
    return get_unique_users()


@router.get("/sessions/user/{user_email}")
async def sessions_by_user(user_email: str):
    from app.user_sessions import get_user_sessions
    return get_user_sessions(user_email)


# ── Idea Parking Lot ─────────────────────────────────────────────────────

@router.get("/ideas")
async def get_ideas():
    """Parse IDEA_PARKING_LOT.md into structured data."""
    import re
    from app.config import CONTEXT_DIR

    path = f"{CONTEXT_DIR}/IDEA_PARKING_LOT.md"
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return {"ideas": [], "archive": [], "error": "IDEA_PARKING_LOT.md not found"}

    ideas = []
    # Remove code fences (template block) before parsing
    content_clean = re.sub(r"```[\s\S]*?```", "", content)
    # Split on ### IDEA — markers
    blocks = re.split(r"(?=^### IDEA —)", content_clean, flags=re.MULTILINE)
    for block in blocks:
        if not block.startswith("### IDEA"):
            continue
        # Skip the template
        if "[Short title]" in block:
            continue
        idea: dict = {}
        # Title
        title_match = re.match(r"### IDEA — (.+)", block)
        idea["title"] = title_match.group(1).strip() if title_match else "Untitled"

        # Fields
        for field, key in [
            (r"\*\*Added:\*\*\s*(.+)", "added"),
            (r"\*\*Source:\*\*\s*(.+)", "source"),
            (r"\*\*Status:\*\*\s*(.+)", "status"),
        ]:
            m = re.search(field, block)
            idea[key] = m.group(1).strip() if m else ""

        # Sections
        for section, key in [
            (r"\*\*The idea:\*\*\n([\s\S]*?)(?=\n\*\*|$)", "description"),
            (r"\*\*Why it might be worth doing:\*\*\n([\s\S]*?)(?=\n\*\*|$)", "rationale"),
            (r"\*\*What it would need:\*\*\n([\s\S]*?)(?=\n\*\*|$)", "requirements"),
            (r"\*\*Open questions:\*\*\n([\s\S]*?)(?=\n\*\*|$)", "questions"),
            (r"\*\*BOB notes:\*\*\n([\s\S]*?)(?=\n---|$)", "bob_notes"),
        ]:
            m = re.search(section, block)
            idea[key] = m.group(1).strip() if m else ""

        ideas.append(idea)

    # Archive table
    archive = []
    archive_match = re.search(
        r"\| Idea \| Activated \| Became \|\n\|.*\|\n([\s\S]*?)(?=\n---|\Z)", content
    )
    if archive_match:
        for row in archive_match.group(1).strip().split("\n"):
            cols = [c.strip() for c in row.split("|") if c.strip()]
            if len(cols) >= 3:
                archive.append({"idea": cols[0], "activated": cols[1], "became": cols[2]})

    return {"ideas": ideas, "archive": archive}


# ── Session tracking API (called by voice service) ───────────────────────

from pydantic import BaseModel as _BM

class SessionOpenRequest(_BM):
    session_id: str
    endpoint: str = "voice"
    user_email: str | None = None
    user_name: str | None = None
    user_role: str = "unknown"
    client_ip: str | None = None
    latitude: float | None = None
    longitude: float | None = None

class SessionUpdateRequest(_BM):
    session_id: str
    latitude: float | None = None
    longitude: float | None = None
    increment_messages: bool = False

class SessionCloseRequest(_BM):
    session_id: str


@router.post("/sessions/open")
async def session_open(req: SessionOpenRequest):
    from app.user_sessions import open_session
    return open_session(**req.model_dump())


@router.post("/sessions/update")
async def session_update(req: SessionUpdateRequest):
    from app.user_sessions import update_session
    return update_session(**req.model_dump())


@router.post("/sessions/close")
async def session_close(req: SessionCloseRequest):
    from app.user_sessions import close_session
    return close_session(req.session_id)


# ── WebSocket proxy to message bus ────────────────────────────────────────

@router.websocket("/ws")
async def ws_proxy(browser_ws: WebSocket):
    """Bidirectional WebSocket proxy: browser <-> message bus."""
    await browser_ws.accept()

    bus_url = MESSAGE_BUS_URL.replace("http://", "ws://").replace("https://", "wss://")
    bus_ws_url = f"{bus_url}/ws"

    try:
        import websockets
        async with websockets.connect(bus_ws_url) as bus_ws:
            async def bus_to_browser():
                try:
                    async for msg in bus_ws:
                        await browser_ws.send_text(msg if isinstance(msg, str) else msg.decode())
                except Exception:
                    pass

            async def browser_to_bus():
                try:
                    while True:
                        data = await browser_ws.receive_text()
                        await bus_ws.send(data)
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            await asyncio.gather(bus_to_browser(), browser_to_bus())
    except Exception as e:
        logger.warning(f"Dashboard WS proxy error: {e}")
    finally:
        try:
            await browser_ws.close()
        except Exception:
            pass
