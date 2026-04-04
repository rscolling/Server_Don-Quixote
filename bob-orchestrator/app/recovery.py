"""Task pause/resume queue with automatic recovery.

When a circuit breaker trips or retries exhaust, tasks are paused here.
A background monitor checks every 30 seconds — when the service recovers,
paused tasks auto-resume from their LangGraph checkpoint.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("bob.recovery")

# Notify callback — set by main.py at startup
_notify_callback = None


def set_notify_callback(callback):
    global _notify_callback
    _notify_callback = callback


@dataclass
class PausedTask:
    task_id: str
    description: str
    pause_reason: str
    resume_after: str  # circuit breaker name that must recover
    paused_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0
    max_retries: int = 3


_paused_tasks: dict[str, PausedTask] = {}


def pause_task(task_id: str, description: str, reason: str,
               resume_after: str = "") -> PausedTask:
    """Pause a task and queue it for automatic resumption."""
    paused = PausedTask(
        task_id=task_id,
        description=description,
        pause_reason=reason,
        resume_after=resume_after,
    )
    _paused_tasks[task_id] = paused
    logger.warning(f"Task paused: {task_id} — {reason} (waiting for: {resume_after})")
    return paused


def get_paused_tasks() -> list[dict]:
    """Return all paused tasks as dicts."""
    return [
        {
            "task_id": t.task_id,
            "description": t.description,
            "pause_reason": t.pause_reason,
            "resume_after": t.resume_after,
            "paused_at": t.paused_at.isoformat(),
            "retry_count": t.retry_count,
            "max_retries": t.max_retries,
        }
        for t in _paused_tasks.values()
    ]


def get_paused_summary() -> str:
    """One-line summary for daily briefing."""
    if not _paused_tasks:
        return "No paused tasks."
    lines = [f"{len(_paused_tasks)} task(s) paused:"]
    for t in _paused_tasks.values():
        lines.append(
            f"  {t.task_id[:12]} — {t.pause_reason} "
            f"(waiting: {t.resume_after}, retries: {t.retry_count}/{t.max_retries})"
        )
    return "\n".join(lines)


def remove_paused_task(task_id: str) -> bool:
    """Manually remove a paused task (e.g., Rob dismisses it)."""
    if task_id in _paused_tasks:
        del _paused_tasks[task_id]
        return True
    return False


async def _resume_task(paused: PausedTask):
    """Attempt to resume a paused task via the message bus."""
    from app import bus_client

    try:
        result = await bus_client.create_task(
            title=f"[Resumed] {paused.description}",
            description=(
                f"Auto-resumed after {paused.resume_after} recovered. "
                f"Original pause reason: {paused.pause_reason}. "
                f"Attempt {paused.retry_count}/{paused.max_retries}."
            ),
            priority="high",
        )
        logger.info(f"Resumed task {paused.task_id}: {result}")
    except Exception as e:
        logger.error(f"Failed to resume task {paused.task_id}: {e}")
        # Re-pause — keep current retry_count so it counts toward max
        _paused_tasks[paused.task_id] = paused


async def recovery_monitor_loop():
    """Background loop — checks paused tasks every 30 seconds.

    When a circuit breaker closes, automatically resumes tasks
    that were waiting for that service.
    """
    from app.circuit_breaker import get_breaker, State

    logger.info("Recovery monitor started")

    while True:
        await asyncio.sleep(30)

        if not _paused_tasks:
            continue

        tasks_to_resume = []

        for task_id, paused in list(_paused_tasks.items()):
            if not paused.resume_after:
                tasks_to_resume.append(task_id)
                continue

            breaker = get_breaker(paused.resume_after)
            if breaker.state == State.CLOSED:
                tasks_to_resume.append(task_id)

        for task_id in tasks_to_resume:
            paused = _paused_tasks.pop(task_id)
            paused.retry_count += 1

            if paused.retry_count > paused.max_retries:
                msg = (
                    f"Task {paused.task_id[:12]} has failed {paused.retry_count} times "
                    f"and cannot be automatically resumed. Manual review required."
                )
                logger.error(msg)
                if _notify_callback:
                    try:
                        await _notify_callback(
                            "bob-critical", "Task Recovery Failed", msg, "urgent"
                        )
                    except Exception:
                        pass
                continue

            msg = (
                f"Resuming task {paused.task_id[:12]} — "
                f"'{paused.resume_after}' recovered. "
                f"Attempt {paused.retry_count}/{paused.max_retries}."
            )
            logger.info(msg)
            if _notify_callback:
                try:
                    await _notify_callback(
                        "bob-status", "Task Resuming", msg, "default"
                    )
                except Exception:
                    pass

            await _resume_task(paused)
