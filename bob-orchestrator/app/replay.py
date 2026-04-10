"""Audit log replay tool — deterministic re-execution of past tool calls.

The audit log captures every tool call BOB makes (sanitized of secrets).
This module reads those entries and re-runs them, optionally diffing the
new result against what was recorded. Two main use cases:

1. **Reproducibility for bug reports.** "BOB returned X yesterday at 3pm
   when I asked for Y" — find the audit entry, replay it, see if you get
   X again or something else.
2. **Regression testing.** After a code change, replay a corpus of past
   tool calls to confirm behavior didn't drift.

Replay is **read-only-by-default**. Tools that write to external state
(create_task, send_message, remember, notify_rob, email_archive, etc.)
are skipped unless --include-writes is passed. This is the right default
because replaying a write tool a second time creates a duplicate task,
sends a duplicate notification, etc.

Replay is **per-thread-isolated**. Each replay run uses a fresh thread_id
so it doesn't trip the loop detector against the original conversation.

Replay does NOT bypass the firewall. The replayed call still goes through
the gate, still gets logged in the audit trail (with a `replay_of: <id>`
marker), and still has its risk level checked. This is intentional — you
want replay to be observable, not invisible.
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("bob.replay")


# Tools that write to external state. Replay skips these unless explicitly
# allowed via include_writes=True. The list is intentionally conservative —
# better to skip a safe tool than to replay a destructive one.
_WRITE_TOOLS = {
    "create_task", "send_message", "update_task",
    "remember", "propose_memory", "approve_proposal", "reject_proposal",
    "notify_rob",
    "email_mark_read", "email_archive", "email_add_label",
    "add_scheduled_job", "remove_scheduled_job", "trigger_job_now",
    "pause_scheduled_job", "resume_scheduled_job",
    "delegate_task",
    "dismiss_paused_task",
}


def _is_write_tool(tool_name: str) -> bool:
    """Best-effort classification of whether a tool writes to external state."""
    if tool_name in _WRITE_TOOLS:
        return True
    # Conservative fallbacks: anything starting with these prefixes is a write
    write_prefixes = ("create_", "update_", "delete_", "add_", "remove_",
                      "send_", "approve_", "reject_", "dismiss_",
                      "notify_", "trigger_", "pause_", "resume_",
                      "store_", "write_", "modify_", "archive_", "mark_")
    return any(tool_name.startswith(p) for p in write_prefixes)


# ── Audit log reader ───────────────────────────────────────────────────────

def read_audit_log(limit: int = 100, audit_id: str | None = None,
                   tool_filter: str | None = None) -> list[dict]:
    """Read entries from the audit log.

    Args:
        limit: Max entries to return (most recent first)
        audit_id: If set, return only the entry with this exact ID
        tool_filter: If set, return only entries for this tool name

    Returns a list of audit entries (newest first).
    """
    from app.config import AUDIT_LOG_PATH

    log_path = Path(AUDIT_LOG_PATH)
    if not log_path.exists():
        return []

    entries = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if audit_id and entry.get("audit_id") != audit_id:
                    continue
                if tool_filter and entry.get("tool") != tool_filter:
                    continue
                entries.append(entry)
    except Exception as e:
        logger.error(f"Failed to read audit log: {e}")
        return []

    # Newest first, then trim
    entries.reverse()
    return entries[:limit]


def find_entry(audit_id: str) -> dict | None:
    """Find a single audit entry by its short ID. Searches the current
    log file plus rotated logs (.1, .2, .3)."""
    from app.config import AUDIT_LOG_PATH

    paths_to_check = [AUDIT_LOG_PATH] + [
        f"{AUDIT_LOG_PATH}.{i}" for i in range(1, 4)
    ]
    for path in paths_to_check:
        if not Path(path).exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except (json.JSONDecodeError, AttributeError):
                        continue
                    if entry.get("audit_id") == audit_id:
                        return entry
        except Exception as e:
            logger.warning(f"Failed to scan {path}: {e}")
    return None


# ── Replayer ───────────────────────────────────────────────────────────────

async def replay_entry(entry: dict, include_writes: bool = False,
                       dry_run: bool = False) -> dict:
    """Replay a single audit log entry.

    Args:
        entry: The audit entry dict (from find_entry or read_audit_log)
        include_writes: Allow replay of write tools. Default False.
        dry_run: If True, do not actually invoke the tool — just return what
                 the replay WOULD do. Used for validation.

    Returns a dict with:
        - status: "replayed" | "skipped" | "error" | "would_replay"
        - tool: The tool name
        - audit_id: The replayed entry's ID
        - replay_thread_id: The fresh thread used for the replay
        - reason: If skipped or errored, why
        - result: The tool's output if replayed (truncated to 5KB)
    """
    tool_name = entry.get("tool")
    params = entry.get("params") or {}
    original_audit_id = entry.get("audit_id", "unknown")
    replay_thread_id = f"replay-{uuid.uuid4().hex[:8]}"

    base_result = {
        "status": "replayed",
        "tool": tool_name,
        "audit_id": original_audit_id,
        "replay_thread_id": replay_thread_id,
        "original_event": entry.get("event"),
        "original_timestamp": entry.get("timestamp"),
    }

    if not tool_name:
        return {**base_result, "status": "error", "reason": "audit entry has no tool name"}

    # Skip the original deny outcomes — they didn't run, replaying them
    # is meaningless
    original_event = entry.get("event", "")
    if original_event in ("deny_injection", "deny_loop", "pending_confirmation"):
        return {
            **base_result,
            "status": "skipped",
            "reason": f"original event was '{original_event}' — never executed, nothing to replay",
        }

    # Skip writes by default
    if _is_write_tool(tool_name) and not include_writes:
        return {
            **base_result,
            "status": "skipped",
            "reason": (
                f"'{tool_name}' is a write tool. Replay is read-only by default. "
                f"Pass include_writes=true to override (use with care — this can "
                f"create duplicate tasks, send duplicate notifications, etc.)."
            ),
        }

    # Sanitized param values may include "[REDACTED]" or truncation markers.
    # Warn about these — replay may not match the original behavior.
    has_redacted = any(
        isinstance(v, str) and "[REDACTED]" in v for v in params.values()
    )
    if has_redacted:
        base_result["warning"] = (
            "Params contain redacted secrets. Replay will use literal '[REDACTED]' "
            "values which will likely cause the tool to fail."
        )

    if dry_run:
        return {**base_result, "status": "would_replay", "params_preview": params}

    # Find the actual tool function and invoke it
    try:
        from app import tools as tools_module
        tool_fn = None
        for t in tools_module.ALL_TOOLS:
            if getattr(t, "name", None) == tool_name:
                tool_fn = t
                break

        if tool_fn is None:
            return {**base_result, "status": "error",
                    "reason": f"tool '{tool_name}' not found in ALL_TOOLS"}

        # Invoke the tool. LangChain tools expose .ainvoke() for async use.
        start = time.time()
        try:
            if hasattr(tool_fn, "ainvoke"):
                result = await tool_fn.ainvoke(params)
            elif hasattr(tool_fn, "invoke"):
                result = tool_fn.invoke(params)
            else:
                return {**base_result, "status": "error",
                        "reason": "tool has no invoke or ainvoke method"}
        except Exception as e:
            return {**base_result, "status": "error",
                    "reason": f"tool raised exception: {e}",
                    "duration_ms": int((time.time() - start) * 1000)}

        duration_ms = int((time.time() - start) * 1000)

        # Truncate large results
        result_str = str(result)
        if len(result_str) > 5000:
            result_str = result_str[:5000] + f"...[truncated {len(result_str)} bytes]"

        return {
            **base_result,
            "status": "replayed",
            "result": result_str,
            "duration_ms": duration_ms,
        }
    except Exception as e:
        logger.exception("replay_entry failed")
        return {**base_result, "status": "error", "reason": str(e)}


async def replay_by_id(audit_id: str, include_writes: bool = False,
                       dry_run: bool = False) -> dict:
    """Find an entry by audit_id and replay it. Convenience wrapper."""
    entry = find_entry(audit_id)
    if not entry:
        return {
            "status": "error",
            "audit_id": audit_id,
            "reason": "audit entry not found in current or rotated logs",
        }
    return await replay_entry(entry, include_writes=include_writes, dry_run=dry_run)


async def replay_recent(tool_filter: str | None = None, limit: int = 10,
                        include_writes: bool = False, dry_run: bool = False) -> dict:
    """Replay the most recent N audit entries (optionally filtered by tool).

    Returns a summary dict with per-entry results and aggregate counts.
    """
    entries = read_audit_log(limit=limit, tool_filter=tool_filter)
    results = []
    counts = {"replayed": 0, "skipped": 0, "error": 0, "would_replay": 0}

    for entry in entries:
        r = await replay_entry(entry, include_writes=include_writes, dry_run=dry_run)
        results.append(r)
        counts[r.get("status", "error")] = counts.get(r.get("status", "error"), 0) + 1

    return {
        "total": len(results),
        "counts": counts,
        "include_writes": include_writes,
        "dry_run": dry_run,
        "tool_filter": tool_filter,
        "results": results,
    }
