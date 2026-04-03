"""BOB's recurring task scheduler — APScheduler backed by SQLite.

BOB owns the schedule. Rob manages it via voice or API.
Tasks fire as message bus tasks that the debate arena picks up.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

logger = logging.getLogger("bob.scheduler")

SCHEDULER_DB = os.getenv("SCHEDULER_DB_PATH", "sqlite:////app/data/scheduler_jobs.db")

# ── Default recurring tasks ──────────────────────────────────────────────────

DEFAULT_SCHEDULES = [
    {
        "job_id": "weekly_seo_audit",
        "label": "Weekly SEO audit",
        "task": "Perform weekly SEO audit of www.appalachiantoysgames.com. Check rankings, broken links, page speed, and meta tags. Identify top 3 improvements.",
        "priority": "normal",
        "cron": {"day_of_week": "mon", "hour": 9, "minute": 0},
    },
    {
        "job_id": "monthly_content_calendar",
        "label": "Monthly content calendar",
        "task": "Create content calendar for the coming month. Include blog posts, social media topics, and product spotlight schedule aligned with ATG brand voice.",
        "priority": "normal",
        "cron": {"day": 1, "hour": 10, "minute": 0},
    },
    {
        "job_id": "weekly_competitor_check",
        "label": "Weekly competitor check",
        "task": "Research new product launches, pricing changes, or marketing campaigns from direct ATG competitors in handcrafted toys and games.",
        "priority": "normal",
        "cron": {"day_of_week": "wed", "hour": 9, "minute": 0},
    },
    {
        "job_id": "weekly_app_store_reviews",
        "label": "Weekly app store review analysis",
        "task": "Analyze recent app store reviews for mobile puzzle games similar to Bear Creek Trail. Identify common complaints, praise patterns, and feature requests.",
        "priority": "normal",
        "cron": {"day_of_week": "fri", "hour": 9, "minute": 0},
    },
    {
        "job_id": "daily_briefing",
        "label": "Daily morning briefing",
        "task": "Compile daily briefing: yesterday's completed tasks, costs, pending reviews, system health, and any alerts.",
        "priority": "high",
        "cron": {"hour": 8, "minute": 0},
    },
]

# ── Task execution callback ──────────────────────────────────────────────────

_task_callback = None


def set_task_callback(callback):
    """Set the async callback that fires when a scheduled task triggers.
    Callback signature: async def callback(job_id, label, task_description, priority)
    """
    global _task_callback
    _task_callback = callback


def _execute_scheduled_task(job_id: str, label: str, task: str, priority: str):
    """Sync wrapper — APScheduler calls this, we bridge to async."""
    if _task_callback:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_task_callback(job_id, label, task, priority))
        else:
            loop.run_until_complete(_task_callback(job_id, label, task, priority))
    else:
        logger.warning(f"Scheduled task fired but no callback set: {job_id} — {label}")


# ── Scheduler singleton ─────────────────────────────────────────────────────

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {
            "default": SQLAlchemyJobStore(url=SCHEDULER_DB)
        }
        _scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="America/New_York")

        def _on_event(event):
            if event.exception:
                logger.error(f"Scheduled job {event.job_id} failed: {event.exception}")
            else:
                logger.info(f"Scheduled job {event.job_id} executed successfully")

        _scheduler.add_listener(_on_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    return _scheduler


def start_scheduler():
    """Start the scheduler and seed default jobs if empty."""
    scheduler = get_scheduler()

    # Seed defaults if no jobs exist
    existing = scheduler.get_jobs()
    existing_ids = {j.id for j in existing}

    for sched in DEFAULT_SCHEDULES:
        if sched["job_id"] not in existing_ids:
            scheduler.add_job(
                _execute_scheduled_task,
                trigger=CronTrigger(**sched["cron"]),
                id=sched["job_id"],
                name=sched["label"],
                kwargs={
                    "job_id": sched["job_id"],
                    "label": sched["label"],
                    "task": sched["task"],
                    "priority": sched["priority"],
                },
                replace_existing=True,
            )
            logger.info(f"Seeded default job: {sched['label']}")

    scheduler.start()
    logger.info(f"Scheduler started with {len(scheduler.get_jobs())} jobs")


def stop_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


# ── Management functions ─────────────────────────────────────────────────────

def list_jobs() -> list[dict]:
    """List all scheduled jobs."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "job_id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs


def add_job(job_id: str, label: str, task: str, cron: dict, priority: str = "normal") -> dict:
    """Add a new recurring job."""
    scheduler = get_scheduler()
    scheduler.add_job(
        _execute_scheduled_task,
        trigger=CronTrigger(**cron),
        id=job_id,
        name=label,
        kwargs={"job_id": job_id, "label": label, "task": task, "priority": priority},
        replace_existing=True,
    )
    logger.info(f"Added job: {label} ({job_id})")
    return {"job_id": job_id, "label": label, "status": "added"}


def remove_job(job_id: str) -> dict:
    """Remove a scheduled job."""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Removed job: {job_id}")
        return {"job_id": job_id, "status": "removed"}
    except Exception as e:
        return {"job_id": job_id, "status": "error", "message": str(e)}


def pause_job(job_id: str) -> dict:
    """Pause a scheduled job."""
    scheduler = get_scheduler()
    scheduler.pause_job(job_id)
    return {"job_id": job_id, "status": "paused"}


def resume_job(job_id: str) -> dict:
    """Resume a paused job."""
    scheduler = get_scheduler()
    scheduler.resume_job(job_id)
    return {"job_id": job_id, "status": "resumed"}
