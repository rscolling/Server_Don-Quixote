import asyncio
import json
import os
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import DB_PATH
from app.database import (
    get_stats, list_messages, list_tasks, list_agents,
    list_topics,
)

router = APIRouter()
_start_time = time.time()

# WebSocket connection manager
_connections: set[WebSocket] = set()


async def broadcast_update():
    """Push current state to all connected WebSocket clients."""
    global _connections
    if not _connections:
        return
    data = json.dumps({
        "type": "update",
        "health": {
            "status": "ok",
            "uptime_seconds": int(time.time() - _start_time),
            "db_size_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
            "version": "2.0.0",
        },
        "stats": await get_stats(),
        "messages": await list_messages(limit=50),
        "tasks": await list_tasks(limit=100),
        "agents": await list_agents(),
        "topics": await list_topics(),
    })
    dead = set()
    for ws in _connections:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _connections -= dead


@router.get("/health")
async def health():
    db_size = 0
    if os.path.exists(DB_PATH):
        db_size = os.path.getsize(DB_PATH)
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _start_time),
        "db_size_bytes": db_size,
        "version": "2.0.0",
    }


@router.get("/stats")
async def stats():
    return await get_stats()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _connections.add(ws)
    try:
        # Send initial state immediately
        await broadcast_update()
        # Keep alive — push updates every 3 seconds
        while True:
            await asyncio.sleep(3)
            if ws in _connections:
                await broadcast_update()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _connections.discard(ws)
