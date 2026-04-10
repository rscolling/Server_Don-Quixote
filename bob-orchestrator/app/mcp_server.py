"""MCP server — expose BOB's high-level capabilities as MCP tools.

Other AI clients (Claude Desktop, Cursor, goose, another BOB instance, etc.)
can call this server to invoke BOB's debate arena, query shared memory,
check infrastructure health, generate briefings, and delegate work.

Auth: optional bearer token via MCP_SERVER_AUTH_TOKEN. When BOB is exposed
through the Cloudflare Tunnel, the outer auth is handled by Cloudflare
Zero Trust — the bearer token is for direct in-network calls only.

Transport: Server-Sent Events (SSE) by default, runs on its own port
(MCP_SERVER_PORT, default 8101) so it doesn't share the FastAPI app.
"""

import asyncio
import json
import logging

logger = logging.getLogger("bob.mcp_server")

_server_task = None
_mcp_app = None


def build_mcp_server():
    """Construct the FastMCP server with BOB's exposed tools.

    Returns the FastMCP instance, ready to run.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.error("mcp package not installed — cannot start MCP server")
        return None

    mcp = FastMCP("BOB", instructions=(
        "BOB — Bound Operational Brain. A self-hosted multi-agent AI orchestrator. "
        "Use these tools to delegate work to BOB's debate arena, query his shared "
        "memory, check infrastructure health, or generate operational briefings. "
        "BOB is sardonic, push-back-prone, and built for solo-founder operations."
    ))

    # ── Tool 1: Delegate work to BOB's debate arena ────────────────────────

    @mcp.tool()
    async def delegate_to_bob_team(
        title: str,
        description: str,
        team: str = "",
        priority: str = "normal",
        deadline: str = "",
    ) -> str:
        """Delegate a task to BOB's agent team. BOB will auto-generate a structured
        brief with brand context, route through the debate arena (PM → RA → CE → QA),
        and return the task ID for tracking.

        Args:
            title: Short task title
            description: Detailed task description
            team: Optional team shorthand (PM, Marketing, Engineering, Research)
            priority: low, normal, high, or urgent
            deadline: Optional date string like '2026-04-15'
        """
        from app.briefing import generate_brief, format_brief_as_text
        from app import bus_client

        brief = generate_brief(
            title=title,
            description=description,
            team=team,
            priority=priority,
            deadline=deadline,
        )
        brief_text = format_brief_as_text(brief)

        result = await bus_client.create_task(
            title=title,
            description=brief_text,
            assignee=team or None,
            priority=priority,
            metadata={"brief": brief, "source": "mcp"},
        )
        return json.dumps({
            "status": "delegated",
            "task": result,
            "brief_summary": (
                f"Brief generated with {len(brief.get('context', []))} context items, "
                f"brand guidelines included."
            ),
        })

    # ── Tool 2: Query BOB's shared memory ──────────────────────────────────

    @mcp.tool()
    def recall_bob_memory(collection: str, query: str, n_results: int = 5) -> str:
        """Search BOB's shared memory for relevant information.

        Args:
            collection: One of brand_voice, decisions, research, product_specs, project_context
            query: Natural language search query
            n_results: Max number of results to return (default 5)
        """
        from app import memory
        try:
            results = memory.query(collection, query, n_results)
            return json.dumps(results)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Tool 3: List BOB's available memory collections ────────────────────

    @mcp.tool()
    def list_bob_memory_collections() -> str:
        """List all shared memory collections BOB maintains, with descriptions."""
        from app.memory import COLLECTIONS
        return json.dumps(COLLECTIONS)

    # ── Tool 4: System health ──────────────────────────────────────────────

    @mcp.tool()
    async def check_bob_system_health() -> str:
        """Check the health of all BOB infrastructure services.

        Returns status for message bus, ChromaDB, Langfuse, ntfy, ElevenLabs API,
        plus the bus offline queue depth and overall status.
        """
        import os
        import httpx

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
                    results[name] = {"status": "ok" if resp.status_code < 400 else "degraded",
                                     "code": resp.status_code}
                except httpx.ConnectError:
                    results[name] = {"status": "down", "error": "connection refused"}
                except httpx.TimeoutException:
                    results[name] = {"status": "down", "error": "timeout"}
                except Exception as e:
                    results[name] = {"status": "unknown", "error": str(e)}

        from app.bus_client import get_queue_depth
        results["bus_offline_queue"] = get_queue_depth()

        down = [k for k, v in results.items() if isinstance(v, dict) and v.get("status") == "down"]
        results["overall"] = "degraded" if down else "healthy"
        return json.dumps(results)

    # ── Tool 5: Generate daily briefing ────────────────────────────────────

    @mcp.tool()
    async def generate_bob_briefing() -> str:
        """Generate BOB's daily operational briefing — system health, email status,
        voice usage, task activity, scheduler queue, recovery state. Returns
        markdown text suitable for human reading or further LLM analysis."""
        from app.daily_report import compose_daily_report
        return await compose_daily_report()

    # ── Tool 6: List paused tasks ──────────────────────────────────────────

    @mcp.tool()
    def list_bob_paused_tasks() -> str:
        """List tasks BOB has paused waiting for service recovery. Useful for
        diagnostic agents that want to know what's stuck."""
        from app.recovery import get_paused_tasks
        tasks = get_paused_tasks()
        return json.dumps({"paused_tasks": tasks, "count": len(tasks)})

    # ── Tool 7: Scheduler operations ───────────────────────────────────────

    @mcp.tool()
    def list_bob_scheduled_jobs() -> str:
        """List all of BOB's recurring scheduled jobs with their next run time.
        Useful for clients that want to inspect or coordinate around BOB's schedule."""
        from app.scheduler import list_jobs
        return json.dumps(list_jobs())

    @mcp.tool()
    def add_bob_scheduled_job(
        job_id: str,
        label: str,
        task: str,
        cron_json: str,
        priority: str = "normal",
    ) -> str:
        """Add a new recurring scheduled job to BOB's schedule.

        Args:
            job_id: Unique identifier for the job
            label: Human-readable label
            task: The task description that fires when the job runs
            cron_json: JSON string with APScheduler cron fields, e.g.
                       '{"day_of_week": "mon", "hour": 9, "minute": 0}'
            priority: low, normal, high, or urgent
        """
        from app.scheduler import add_job
        try:
            cron = json.loads(cron_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid cron_json: {e}"})
        return json.dumps(add_job(job_id, label, task, cron, priority))

    @mcp.tool()
    def trigger_bob_job(job_id: str) -> str:
        """Run a scheduled job immediately without waiting for its next scheduled time."""
        from app.scheduler import run_job_now
        return json.dumps(run_job_now(job_id))

    # ── Tool 8: Memory write proposal ──────────────────────────────────────

    @mcp.tool()
    def propose_bob_memory(
        collection: str,
        doc_id: str,
        text: str,
        proposed_by: str = "external_mcp_client",
        reason: str = "",
        metadata_json: str = "{}",
    ) -> str:
        """Propose a write to BOB's shared memory. The proposal is queued for
        BOB's review — it does NOT commit until BOB approves it. This is the
        only way external clients can add to BOB's knowledge base.

        Args:
            collection: brand_voice, decisions, research, product_specs, project_context
            doc_id: Unique identifier for the memory entry
            text: The content to store
            proposed_by: Who/what is proposing the write (for audit trail)
            reason: Why this should be stored (helps BOB review)
            metadata_json: JSON-encoded metadata dict
        """
        from app.memory_proposals import propose
        try:
            metadata = json.loads(metadata_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid metadata_json: {e}"})
        result = propose(
            collection=collection,
            doc_id=doc_id,
            text=text,
            metadata=metadata,
            proposed_by=proposed_by,
            reason=reason,
        )
        return json.dumps(result)

    # ── Tool 9: Email triage (read-only — BOB never sends from MCP) ────────

    @mcp.tool()
    async def check_bob_email() -> str:
        """Check BOB's connected Gmail inbox for new unread emails. Returns
        classified summaries. BOB does NOT send email via this tool — drafts
        only, manual send by Rob. This is read-only triage.
        """
        from app.gmail_monitor import check_inbox
        emails = await check_inbox()
        if not emails:
            return json.dumps({"emails": [], "message": "No new unread emails."})
        return json.dumps({"emails": emails, "count": len(emails)})

    @mcp.tool()
    def email_status() -> str:
        """Check the health of BOB's Gmail connection. Returns connected/disconnected,
        the email address, total message count."""
        try:
            from app.gmail_monitor import _get_gmail_service
            service = _get_gmail_service()
            if not service:
                return json.dumps({"status": "disconnected", "error": "No valid credentials"})
            profile = service.users().getProfile(userId="me").execute()
            return json.dumps({
                "status": "connected",
                "email": profile.get("emailAddress"),
                "total_messages": profile.get("messagesTotal"),
            })
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    # ── Tool 10: Voice usage telemetry ─────────────────────────────────────

    @mcp.tool()
    async def check_bob_voice_usage() -> str:
        """Check ElevenLabs voice usage for the current billing period.
        Useful for clients that want to know if BOB is approaching voice limits."""
        from app.elevenlabs_monitor import run_usage_sweep
        result = await run_usage_sweep()
        return json.dumps(result)

    # ── Tool 11: Server resources ──────────────────────────────────────────

    @mcp.tool()
    def check_bob_server_resources() -> str:
        """Check the host server's CPU, memory, and disk usage. Useful for
        diagnostic clients that want to know if BOB's host is under load."""
        import psutil
        cpu_pct = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return json.dumps({
            "cpu_percent": cpu_pct,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024**3), 1),
            "memory_total_gb": round(mem.total / (1024**3), 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024**3), 1),
            "disk_total_gb": round(disk.total / (1024**3), 1),
        })

    # ── Tool 12: Memory export ─────────────────────────────────────────────

    @mcp.tool()
    def export_bob_memory(collections: str = "") -> str:
        """Export BOB's shared memory as a portable JSON dict.

        Args:
            collections: Comma-separated list of collection names. Empty = all.

        Returns the export as a JSON string. Useful for federation between
        BOB instances, backups, or migrating to another vector DB.
        """
        from app.memory import export_all
        target = [c.strip() for c in collections.split(",") if c.strip()] if collections else None
        data = export_all(target)
        return json.dumps(data)

    # ── Resource: BOB's mission and context ────────────────────────────────

    @mcp.resource("bob://mission")
    def bob_mission() -> str:
        """BOB's current mission and active project context."""
        import os
        from app.config import CONTEXT_DIR
        mission_path = os.path.join(CONTEXT_DIR, "MISSION.md")
        try:
            with open(mission_path) as f:
                return f.read()
        except FileNotFoundError:
            return "Mission file not available."

    @mcp.resource("bob://personality")
    def bob_personality() -> str:
        """BOB's personality definition — useful for clients that want to
        match BOB's voice when generating responses on his behalf."""
        import os
        from app.config import CONTEXT_DIR
        for fname in ("00_personality.md", "personality.md"):
            path = os.path.join(CONTEXT_DIR, fname)
            if os.path.exists(path):
                with open(path) as f:
                    return f.read()
        return "Personality file not available."

    return mcp


async def start_mcp_server(port: int, transport: str = "sse"):
    """Start the MCP server in the background.

    Args:
        port: Port to listen on
        transport: 'sse' or 'streamable-http'
    """
    global _server_task, _mcp_app

    mcp = build_mcp_server()
    if mcp is None:
        logger.warning("MCP server not started — mcp package missing")
        return

    _mcp_app = mcp

    # FastMCP exposes either run_sse_async() or run_streamable_http_async()
    # depending on version. We try both.
    try:
        if transport == "streamable-http":
            run_method = getattr(mcp, "run_streamable_http_async", None)
        else:
            run_method = getattr(mcp, "run_sse_async", None)

        if run_method is None:
            # Fall back to mcp.run(transport=...) for newer SDK versions
            run_method = lambda: mcp.run(transport=transport)

        # Most FastMCP versions accept host/port via the underlying uvicorn settings.
        # We set them on the FastMCP instance before starting.
        if hasattr(mcp, "settings"):
            try:
                mcp.settings.host = "0.0.0.0"
                mcp.settings.port = port
            except Exception:
                pass

        async def _run():
            try:
                if asyncio.iscoroutinefunction(run_method):
                    await run_method()
                else:
                    await asyncio.get_event_loop().run_in_executor(None, run_method)
            except Exception as e:
                logger.error(f"MCP server crashed: {e}")

        _server_task = asyncio.create_task(_run())
        logger.info(f"MCP server started on port {port} (transport: {transport})")
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")


async def stop_mcp_server():
    """Stop the MCP server background task."""
    global _server_task
    if _server_task is None:
        return
    _server_task.cancel()
    try:
        await _server_task
    except (asyncio.CancelledError, Exception):
        pass
    _server_task = None
    logger.info("MCP server stopped")
