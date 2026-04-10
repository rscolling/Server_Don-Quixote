"""A2A (Agent-to-Agent) protocol adapter.

Google's A2A protocol is the emerging standard for agent-to-agent
communication, complementary to MCP. Where MCP standardizes "agent → tool"
calls, A2A standardizes "agent → agent" calls. The two are designed to
work together: an agent uses MCP to access tools and A2A to delegate to
peer agents.

This module gives BOB two A2A capabilities:

1. **A2A server** — BOB exposes himself as an A2A-compliant agent so other
   agents (other BOB instances, CrewAI, AutoGen, anything that speaks A2A)
   can call him. Endpoints follow the A2A spec: agent card discovery,
   message send, status check.

2. **A2A client** — BOB can call other A2A agents the same way he calls
   MCP tools. Useful for federation: a manager-BOB on AWS delegates to
   worker-BOBs on home servers, or BOB delegates a research task to a
   specialized A2A research agent on someone else's infrastructure.

A2A spec reference: https://google-a2a.github.io/A2A/

This implementation is a **minimal subset** of A2A — enough to do the
federation use case, not a full conformant implementation. The roadmap
calls for "A2A protocol support" but explicitly notes "minimal subset"
is the right scope for this session. A future maintainer can expand this
to a full implementation when the spec stabilizes.

Endpoints exposed:
    GET  /a2a/.well-known/agent.json   → Agent card (A2A discovery)
    POST /a2a/message                  → Send a task to BOB
    GET  /a2a/task/{task_id}           → Check task status

Configuration:
    A2A_SERVER_ENABLED      Default: true
    A2A_PEERS               Comma-separated list of peer A2A endpoint URLs
    A2A_AUTH_TOKEN          Optional bearer token for outbound A2A calls
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("bob.a2a")


# ── Configuration ──────────────────────────────────────────────────────────

A2A_SERVER_ENABLED = os.getenv("A2A_SERVER_ENABLED", "true").lower() == "true"
A2A_AUTH_TOKEN = os.getenv("A2A_AUTH_TOKEN", "")
A2A_PEERS = [
    p.strip() for p in os.getenv("A2A_PEERS", "").split(",") if p.strip()
]
A2A_REQUEST_TIMEOUT = float(os.getenv("A2A_REQUEST_TIMEOUT", "60.0"))


# ── Agent card (A2A discovery) ─────────────────────────────────────────────

def agent_card(public_url: str = "") -> dict:
    """Return BOB's A2A agent card.

    The agent card is the discovery document — peers fetch it from
    /.well-known/agent.json to learn what BOB can do, what auth he requires,
    and how to talk to him.
    """
    return {
        "schemaVersion": "0.1",
        "name": "BOB",
        "description": (
            "Bound Operational Brain — a sardonic, self-hosted multi-agent "
            "AI orchestrator. Can delegate work to a debate arena, query "
            "shared memory, generate operational briefings, and coordinate "
            "specialist agents. Push-back-prone by design."
        ),
        "version": "1.0.0",
        "url": public_url or "http://localhost:8100",
        "capabilities": {
            "streaming": False,  # Synchronous responses for now
            "pushNotifications": True,  # Via ntfy
            "stateTransitionHistory": True,  # Via audit log
        },
        "authentication": {
            "schemes": ["bearer"] if A2A_AUTH_TOKEN else ["none"],
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "delegate",
                "name": "Delegate to Debate Arena",
                "description": (
                    "Hand a content/marketing task to BOB's debate arena. "
                    "PM routes through RA → CE → QA. Returns the QA-approved "
                    "deliverable."
                ),
                "tags": ["delegation", "content", "marketing", "research"],
            },
            {
                "id": "query_memory",
                "name": "Query Shared Memory",
                "description": (
                    "Search BOB's vector memory across brand voice, decisions, "
                    "research, product specs, and project context."
                ),
                "tags": ["memory", "recall", "knowledge"],
            },
            {
                "id": "system_health",
                "name": "Infrastructure Health",
                "description": (
                    "Report BOB's infrastructure status — message bus, ChromaDB, "
                    "circuit breakers, voice usage, paused tasks."
                ),
                "tags": ["health", "monitoring", "diagnostics"],
            },
            {
                "id": "generate_briefing",
                "name": "Daily Operational Briefing",
                "description": (
                    "Compile a complete operational briefing covering server "
                    "health, email status, voice usage, task activity, schedule, "
                    "and recovery state."
                ),
                "tags": ["briefing", "report", "daily"],
            },
        ],
    }


# ── A2A task tracking ──────────────────────────────────────────────────────

@dataclass
class A2ATask:
    task_id: str
    skill: str
    input_text: str
    status: str = "submitted"  # submitted | working | completed | failed
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    output_text: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "taskId": self.task_id,
            "skill": self.skill,
            "status": self.status,
            "createdAt": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "completedAt": (
                datetime.fromtimestamp(self.completed_at, tz=timezone.utc).isoformat()
                if self.completed_at else None
            ),
            "input": {"text": self.input_text},
            "output": {"text": self.output_text} if self.output_text else None,
            "error": self.error or None,
        }


_tasks: dict[str, A2ATask] = {}


def _new_task_id() -> str:
    return f"a2a-{uuid.uuid4().hex[:12]}"


# ── A2A server-side: handle incoming messages ─────────────────────────────

async def handle_message(skill: str, input_text: str,
                         auth_token: str | None = None) -> A2ATask:
    """Handle an incoming A2A message and dispatch to the right BOB capability.

    Args:
        skill: The skill ID from the agent card (delegate, query_memory, etc.)
        input_text: The message from the calling agent
        auth_token: The bearer token if the request had one

    Returns the A2ATask with status, output, etc.
    """
    # Auth check
    if A2A_AUTH_TOKEN and auth_token != A2A_AUTH_TOKEN:
        task = A2ATask(
            task_id=_new_task_id(),
            skill=skill,
            input_text=input_text,
            status="failed",
            error="unauthorized",
        )
        task.completed_at = time.time()
        _tasks[task.task_id] = task
        return task

    task = A2ATask(
        task_id=_new_task_id(),
        skill=skill,
        input_text=input_text,
        status="working",
    )
    _tasks[task.task_id] = task

    try:
        if skill == "delegate":
            from app.briefing import generate_brief, format_brief_as_text
            from app import bus_client

            brief = generate_brief(
                title=input_text[:100],
                description=input_text,
                team="",
                priority="normal",
            )
            brief_text = format_brief_as_text(brief)
            result = await bus_client.create_task(
                title=input_text[:100],
                description=brief_text,
                priority="normal",
                metadata={"brief": brief, "source": "a2a"},
            )
            task.output_text = json.dumps(result)

        elif skill == "query_memory":
            from app import memory
            # Default to project_context — caller can specify collection in input
            collection = "project_context"
            query_text = input_text
            # Allow "collection:foo query text" syntax
            if ":" in input_text.split()[0]:
                first, rest = input_text.split(" ", 1) if " " in input_text else (input_text, "")
                if first.endswith(":"):
                    collection = first[:-1]
                    query_text = rest
            results = memory.query(collection, query_text, n_results=5)
            task.output_text = json.dumps(results)

        elif skill == "system_health":
            import httpx as _httpx
            services = {
                "message_bus": os.getenv("MESSAGE_BUS_URL", "http://message-bus:8585") + "/stats",
                "chromadb": os.getenv("CHROMADB_URL", "http://chromadb:8000") + "/api/v1/heartbeat",
            }
            results = {}
            async with _httpx.AsyncClient(timeout=5.0) as client:
                for name, url in services.items():
                    try:
                        resp = await client.get(url)
                        results[name] = "ok" if resp.status_code < 400 else "degraded"
                    except Exception:
                        results[name] = "down"
            task.output_text = json.dumps(results)

        elif skill == "generate_briefing":
            from app.daily_report import compose_daily_report
            task.output_text = await compose_daily_report()

        else:
            task.status = "failed"
            task.error = f"unknown skill: {skill}"
            task.completed_at = time.time()
            return task

        task.status = "completed"
        task.completed_at = time.time()
        return task

    except Exception as e:
        logger.exception(f"A2A skill '{skill}' failed")
        task.status = "failed"
        task.error = str(e)
        task.completed_at = time.time()
        return task


def get_task(task_id: str) -> A2ATask | None:
    """Look up a task by ID."""
    return _tasks.get(task_id)


def list_recent_tasks(limit: int = 20) -> list[dict]:
    """List the most recent A2A tasks."""
    sorted_tasks = sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)
    return [t.to_dict() for t in sorted_tasks[:limit]]


# ── A2A client-side: call peer agents ──────────────────────────────────────

async def fetch_peer_agent_card(peer_url: str) -> dict:
    """Fetch the agent card from a peer A2A endpoint to discover its capabilities."""
    card_url = peer_url.rstrip("/") + "/.well-known/agent.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(card_url)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch agent card from {peer_url}: {e}")
        return {"error": str(e)}


async def call_peer(peer_url: str, skill: str, input_text: str,
                     auth_token: str | None = None) -> dict:
    """Send a message to a peer A2A agent and return the result.

    Args:
        peer_url: Base URL of the peer agent (e.g., 'http://other-bob:8100')
        skill: Skill ID from the peer's agent card
        input_text: Message to send
        auth_token: Optional bearer token for the peer

    Returns the peer's task response (status, output, error).
    """
    message_url = peer_url.rstrip("/") + "/a2a/message"
    payload = {"skill": skill, "input": {"text": input_text}}
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        async with httpx.AsyncClient(timeout=A2A_REQUEST_TIMEOUT) as client:
            resp = await client.post(message_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"A2A call to {peer_url} failed: {e}")
        return {"status": "failed", "error": str(e), "peer": peer_url}


async def discover_peers() -> dict:
    """Fetch agent cards from all configured peers. Returns a dict keyed by URL."""
    if not A2A_PEERS:
        return {}
    results = {}
    for peer in A2A_PEERS:
        results[peer] = await fetch_peer_agent_card(peer)
    return results


def status() -> dict:
    """Return A2A status for /a2a/status endpoint."""
    return {
        "server_enabled": A2A_SERVER_ENABLED,
        "auth_required": bool(A2A_AUTH_TOKEN),
        "configured_peers": A2A_PEERS,
        "active_tasks": len([t for t in _tasks.values() if t.status == "working"]),
        "total_tasks": len(_tasks),
    }
