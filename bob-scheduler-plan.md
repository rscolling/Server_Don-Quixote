# BOB — Recurring Task Scheduler Build Plan
### *APScheduler · BOB owns the schedule · voice and dashboard management*

---

## What We're Building

Currently, recurring tasks like weekly SEO audits are described as PowerShell cron jobs in the operational workflow. That approach bypasses BOB entirely — Rob has to manage cron syntax, the schedule is invisible to BOB, and there is no intelligence about when to fire (for example, not firing an SEO audit while the server is already under load from a full engineering debate).

This plan moves the schedule to BOB. BOB owns the schedule, executes tasks at the right time, checks system health before firing, and lets Rob add, pause, or remove recurring tasks via voice or dashboard — no cron syntax required.

---

## What Gets Scheduled Out of the Box

| Task | Team | Frequency | Tier | Default time |
|---|---|---|---|---|
| Weekly SEO audit | Marketing | Every Monday | 1 (SA + QA only) | 9:00 AM |
| Monthly content calendar | Marketing | 1st of month | 2 | 10:00 AM |
| Weekly competitor check | Research | Every Wednesday | 2 | 9:00 AM |
| Monthly patent scan | Research | 1st of month | 3 | 11:00 AM |
| Weekly app store review analysis | Research | Every Friday | 2 | 9:00 AM |
| Bi-weekly game mechanics review | Engineering | Every other Tuesday | 2 | 10:00 AM |

Rob can add any task from this list or create new ones via voice or dashboard. All schedules are stored in SQLite — they survive restarts, and BOB remembers them across sessions.

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- BOB orchestrator running at `:8100` ✓
- All steps begin on **Windows 11**. SSH to server where indicated.

---

## Phase 1 — Install APScheduler

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Install APScheduler**

```bash
# [UBUNTU SERVER]
pip install apscheduler --break-system-packages
```

If the orchestrator runs in Docker, add to `requirements.txt` and rebuild:

```
apscheduler>=3.10.0
```

```bash
docker compose up -d --build orchestrator
```

Verify install:

```bash
python3 -c "import apscheduler; print('APScheduler:', apscheduler.__version__)"
```

---

## Phase 2 — The Scheduler Module

**Step 3 — Create the scheduler module**

```bash
nano /opt/atg-agents/orchestrator/scheduler.py
```

```python
# orchestrator/scheduler.py
# BOB's recurring task scheduler
# BOB owns the schedule. Rob manages it via voice or dashboard.

import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import (
    EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED
)

log = logging.getLogger(__name__)

SCHEDULER_DB = os.getenv(
    "SCHEDULER_DB_PATH",
    "/app/checkpoints/scheduler_jobs.db"
)

# ── Schedule definitions — the default recurring tasks ───────────────────────
# BOB loads these on first run if no schedule exists yet.
# Rob can modify them via voice or dashboard after initial load.

DEFAULT_SCHEDULES = [
    {
        "job_id":      "weekly_seo_audit",
        "label":       "Weekly SEO audit",
        "team":        "marketing",
        "task":        "Perform weekly SEO audit of www.appalachiantoysgames.com. Check rankings, broken links, page speed, and meta tags. Identify top 3 improvements.",
        "priority":    "standard",
        "tier":        1,
        "trigger":     "cron",
        "cron":        {"day_of_week": "mon", "hour": 9, "minute": 0},
        "enabled":     True,
        "created_by":  "bob_default",
    },
    {
        "job_id":      "monthly_content_calendar",
        "label":       "Monthly content calendar",
        "team":        "marketing",
        "task":        "Create content calendar for the coming month. Include blog posts, social media topics, and product spotlight schedule aligned with ATG brand voice.",
        "priority":    "standard",
        "tier":        2,
        "trigger":     "cron",
        "cron":        {"day": 1, "hour": 10, "minute": 0},
        "enabled":     True,
        "created_by":  "bob_default",
    },
    {
        "job_id":      "weekly_competitor_check",
        "label":       "Weekly competitor check",
        "team":        "research",
        "task":        "Research any new product launches, pricing changes, or marketing campaigns from direct ATG competitors in the handcrafted toys and games space.",
        "priority":    "standard",
        "tier":        2,
        "trigger":     "cron",
        "cron":        {"day_of_week": "wed", "hour": 9, "minute": 0},
        "enabled":     True,
        "created_by":  "bob_default",
    },
    {
        "job_id":      "monthly_patent_scan",
        "label":       "Monthly patent scan",
        "team":        "research",
        "task":        "Scan USPTO and Google Patents for new filings in: wooden puzzle mechanisms, interlocking toy components, Appalachian-themed game designs. Flag anything that overlaps with ATG's current or planned products.",
        "priority":    "standard",
        "tier":        3,
        "trigger":     "cron",
        "cron":        {"day": 1, "hour": 11, "minute": 0},
        "enabled":     True,
        "created_by":  "bob_default",
    },
    {
        "job_id":      "weekly_app_store_reviews",
        "label":       "Weekly app store review analysis",
        "team":        "research",
        "task":        "Analyze recent app store reviews for mobile puzzle games similar to ATG's mobile project. Identify common complaints, praise patterns, and feature requests. Summarize for product and marketing teams.",
        "priority":    "standard",
        "tier":        2,
        "trigger":     "cron",
        "cron":        {"day_of_week": "fri", "hour": 9, "minute": 0},
        "enabled":     True,
        "created_by":  "bob_default",
    },
    {
        "job_id":      "biweekly_game_mechanics_review",
        "label":       "Bi-weekly game mechanics review",
        "team":        "engineering",
        "task":        "Review current mobile game mechanics, difficulty curve, and player progression. Identify balance issues, technical debt, or UX friction points. Produce a prioritized list of improvements.",
        "priority":    "standard",
        "tier":        2,
        "trigger":     "cron",
        "cron":        {"day_of_week": "tue", "week": "*/2", "hour": 10, "minute": 0},
        "enabled":     True,
        "created_by":  "bob_default",
    },
]


# ── Scheduler singleton ───────────────────────────────────────────────────────

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {
            "default": SQLAlchemyJobStore(
                url=f"sqlite:///{SCHEDULER_DB}"
            )
        }
        _scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone="America/New_York",  # Rob's timezone — adjust if needed
        )
    return _scheduler


# ── Job execution function ────────────────────────────────────────────────────

async def _execute_scheduled_task(
    job_id:   str,
    label:    str,
    team:     str,
    task:     str,
    priority: str,
    tier:     int,
):
    """
    Called by APScheduler when a job fires.
    Checks system health, then submits the task to the orchestrator.
    """
    import aiohttp
    from resource_monitor import get_resource_snapshot, should_block_team_start
    from circuit_breaker import _breakers, BreakerState

    log.info(f"[scheduler] Firing scheduled task: {label} ({job_id})")

    # ── Pre-flight checks ─────────────────────────────────────────────────────

    # 1. Check Anthropic API circuit breaker
    anthropic_breaker = _breakers.get("anthropic_api")
    if anthropic_breaker and anthropic_breaker.state != BreakerState.CLOSED:
        msg = (
            f"Scheduled task '{label}' skipped — Anthropic API circuit breaker "
            f"is {anthropic_breaker.state.value}. Will retry next scheduled run."
        )
        log.warning(f"[scheduler] {msg}")
        await bob_proactive_report(msg, alert_level="status")
        return

    # 2. Check server resources
    snap = get_resource_snapshot()
    blocked, reason = should_block_team_start(snap)
    if blocked:
        msg = (
            f"Scheduled task '{label}' skipped — server resources too high "
            f"to start {team} team safely. {reason} Will retry next scheduled run."
        )
        log.warning(f"[scheduler] {msg}")
        await bob_proactive_report(msg, alert_level="status")
        return

    # ── Submit the task ───────────────────────────────────────────────────────

    task_id = str(uuid.uuid4())
    payload = {
        "task_id":    task_id,
        "team":       team,
        "task":       task,
        "priority":   priority,
        "tier":       tier,
        "source":     "scheduler",
        "job_id":     job_id,
        "label":      label,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8100/task",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201, 202):
                    log.info(
                        f"[scheduler] Task submitted: {label} → task_id={task_id}"
                    )
                    await bob_proactive_report(
                        f"Scheduled task started: {label}. "
                        f"Task ID: {task_id[:8]}. "
                        f"Results will appear on the dashboard when complete.",
                        alert_level="status",
                    )
                else:
                    body = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {body}")

    except Exception as e:
        log.error(f"[scheduler] Task submission failed for {label}: {e}")
        await bob_proactive_report(
            f"Scheduled task '{label}' failed to start. Error: {e}",
            alert_level="status",
        )


# ── Public scheduler API ──────────────────────────────────────────────────────

def add_job(
    job_id:    str,
    label:     str,
    team:      str,
    task:      str,
    trigger:   str,
    cron:      dict     = None,
    interval:  dict     = None,
    priority:  str      = "standard",
    tier:      int      = 2,
    enabled:   bool     = True,
    replace:   bool     = False,
) -> dict:
    """
    Add or replace a scheduled job.
    trigger: "cron" | "interval"
    cron: APScheduler CronTrigger kwargs (day_of_week, hour, minute, etc.)
    interval: APScheduler IntervalTrigger kwargs (weeks, days, hours, etc.)
    """
    scheduler = get_scheduler()

    if trigger == "cron":
        trig = CronTrigger(**cron)
    elif trigger == "interval":
        trig = IntervalTrigger(**interval)
    else:
        return {"error": f"Unknown trigger type: {trigger}"}

    kwargs = dict(
        id=job_id,
        func=_execute_scheduled_task,
        trigger=trig,
        kwargs={
            "job_id":   job_id,
            "label":    label,
            "team":     team,
            "task":     task,
            "priority": priority,
            "tier":     tier,
        },
        replace_existing=replace,
        name=label,
    )

    if not enabled:
        # Add job but immediately pause it
        scheduler.add_job(**kwargs)
        scheduler.pause_job(job_id)
    else:
        scheduler.add_job(**kwargs)

    log.info(f"[scheduler] Added job: {job_id} ({label}) — enabled={enabled}")
    return {"job_id": job_id, "label": label, "status": "added"}


def remove_job(job_id: str) -> dict:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
        return {"job_id": job_id, "status": "removed"}
    except Exception as e:
        return {"error": str(e)}


def pause_job(job_id: str) -> dict:
    scheduler = get_scheduler()
    try:
        scheduler.pause_job(job_id)
        return {"job_id": job_id, "status": "paused"}
    except Exception as e:
        return {"error": str(e)}


def resume_job(job_id: str) -> dict:
    scheduler = get_scheduler()
    try:
        scheduler.resume_job(job_id)
        return {"job_id": job_id, "status": "resumed"}
    except Exception as e:
        return {"error": str(e)}


def list_jobs() -> list[dict]:
    """Returns all scheduled jobs with their next run times."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "job_id":    job.id,
            "label":     job.name,
            "enabled":   next_run is not None,
            "next_run":  next_run.isoformat() if next_run else "paused",
            "trigger":   str(job.trigger),
        })
    return sorted(jobs, key=lambda j: j["next_run"] or "zzz")


def get_job_status_summary() -> str:
    """Human-readable schedule summary for BOB's status report."""
    jobs = list_jobs()
    if not jobs:
        return "No scheduled tasks configured."

    active  = [j for j in jobs if j["enabled"]]
    paused  = [j for j in jobs if not j["enabled"]]
    lines   = [f"{len(active)} active scheduled task(s):"]

    for job in active[:5]:
        next_run = job["next_run"]
        if next_run != "paused":
            try:
                dt       = datetime.fromisoformat(next_run)
                readable = dt.strftime("%a %b %-d at %-I:%M %p")
            except Exception:
                readable = next_run
        else:
            readable = "paused"
        lines.append(f"  - {job['label']}: next run {readable}")

    if len(active) > 5:
        lines.append(f"  ...and {len(active) - 5} more")

    if paused:
        lines.append(f"{len(paused)} paused: {', '.join(j['label'] for j in paused)}")

    return "\n".join(lines)


# ── Startup — initialize scheduler and load default jobs ─────────────────────

def initialize_scheduler():
    """
    Start the scheduler and load default jobs if the DB is empty.
    Called at orchestrator startup.
    """
    scheduler = get_scheduler()

    # Attach event listeners for job execution monitoring
    def on_job_executed(event):
        log.info(f"[scheduler] Job executed: {event.job_id}")

    def on_job_error(event):
        log.error(
            f"[scheduler] Job failed: {event.job_id} — {event.exception}"
        )

    def on_job_missed(event):
        log.warning(
            f"[scheduler] Job missed: {event.job_id} — "
            f"scheduled at {event.scheduled_run_time}"
        )

    scheduler.add_listener(on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(on_job_error,    EVENT_JOB_ERROR)
    scheduler.add_listener(on_job_missed,   EVENT_JOB_MISSED)

    scheduler.start()

    # Load defaults only if the scheduler DB has no jobs yet
    existing_jobs = {j.id for j in scheduler.get_jobs()}
    loaded = 0
    for schedule in DEFAULT_SCHEDULES:
        if schedule["job_id"] not in existing_jobs:
            add_job(**{k: v for k, v in schedule.items()
                       if k not in ("created_by",)})
            loaded += 1

    if loaded:
        log.info(f"[scheduler] Loaded {loaded} default scheduled jobs")
    else:
        log.info(
            f"[scheduler] Scheduler started — "
            f"{len(existing_jobs)} existing jobs restored from DB"
        )

    return scheduler
```

Save and exit.

---

## Phase 3 — Wire Scheduler into the Orchestrator

**Step 4 — Initialize at startup**

```python
# orchestrator/main.py — add to startup

from scheduler import initialize_scheduler

# Start the scheduler — restores persisted jobs from SQLite
scheduler = initialize_scheduler()
```

---

**Step 5 — Add scheduler API endpoints**

```python
# orchestrator/api.py

from scheduler import (
    add_job, remove_job, pause_job, resume_job,
    list_jobs, get_job_status_summary
)

# ── List all scheduled tasks ──────────────────────────────────────────────────
@app.get("/schedule")
async def get_schedule():
    return {"jobs": list_jobs()}


# ── Add a new recurring task ──────────────────────────────────────────────────
@app.post("/schedule")
async def create_scheduled_job(request: Request):
    body = await request.json()
    result = add_job(
        job_id   = body.get("job_id",  str(uuid.uuid4())[:12]),
        label    = body["label"],
        team     = body["team"],
        task     = body["task"],
        trigger  = body.get("trigger", "cron"),
        cron     = body.get("cron"),
        interval = body.get("interval"),
        priority = body.get("priority", "standard"),
        tier     = body.get("tier", 2),
        enabled  = body.get("enabled", True),
        replace  = body.get("replace", False),
    )
    return result


# ── Pause a job ───────────────────────────────────────────────────────────────
@app.post("/schedule/{job_id}/pause")
async def pause_scheduled_job(job_id: str):
    return pause_job(job_id)


# ── Resume a paused job ───────────────────────────────────────────────────────
@app.post("/schedule/{job_id}/resume")
async def resume_scheduled_job(job_id: str):
    return resume_job(job_id)


# ── Remove a job ──────────────────────────────────────────────────────────────
@app.delete("/schedule/{job_id}")
async def delete_scheduled_job(job_id: str):
    return remove_job(job_id)


# ── Trigger a job immediately (run now, outside normal schedule) ──────────────
@app.post("/schedule/{job_id}/run-now")
async def run_job_now(job_id: str):
    from scheduler import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if not job:
        return {"error": f"Job '{job_id}' not found"}
    scheduler.modify_job(job_id, next_run_time=datetime.now(timezone.utc))
    return {"job_id": job_id, "status": "triggered"}
```

---

## Phase 4 — BOB Voice Interface for the Scheduler

Rob can manage the schedule by talking to BOB. BOB parses the intent and calls the scheduler API.

**Step 6 — Add scheduler intent handlers to BOB**

```python
# orchestrator/bob.py

from scheduler import (
    add_job, pause_job, resume_job, remove_job,
    list_jobs, get_job_status_summary
)

# ── Intent: "what's scheduled?" / "show me the schedule" ─────────────────────
def handle_schedule_query() -> str:
    return get_job_status_summary()


# ── Intent: "pause the weekly SEO audit" ─────────────────────────────────────
def handle_pause_job(job_id: str = None, label: str = None) -> str:
    if not job_id and label:
        # Find job by label substring match
        jobs  = list_jobs()
        match = next(
            (j for j in jobs if label.lower() in j["label"].lower()), None
        )
        if not match:
            return f"No scheduled task found matching '{label}'."
        job_id = match["job_id"]

    result = pause_job(job_id)
    if "error" in result:
        return f"Could not pause job: {result['error']}"
    return f"Paused: {job_id}. It will not run until resumed."


# ── Intent: "resume the weekly SEO audit" ────────────────────────────────────
def handle_resume_job(job_id: str = None, label: str = None) -> str:
    if not job_id and label:
        jobs  = list_jobs()
        match = next(
            (j for j in jobs if label.lower() in j["label"].lower()), None
        )
        if not match:
            return f"No scheduled task found matching '{label}'."
        job_id = match["job_id"]

    result = resume_job(job_id)
    if "error" in result:
        return f"Could not resume job: {result['error']}"
    return f"Resumed: {job_id}. Next run scheduled."


# ── Intent: "run the SEO audit now" ──────────────────────────────────────────
async def handle_run_job_now(job_id: str = None, label: str = None) -> str:
    if not job_id and label:
        jobs  = list_jobs()
        match = next(
            (j for j in jobs if label.lower() in j["label"].lower()), None
        )
        if not match:
            return f"No scheduled task found matching '{label}'."
        job_id = match["job_id"]

    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://localhost:8100/schedule/{job_id}/run-now"
        ) as resp:
            if resp.status == 200:
                return f"Yes Boss. Triggering '{label or job_id}' now."
            return f"Could not trigger job. HTTP {resp.status}"


# ── Intent: "add a new recurring task" ───────────────────────────────────────
def handle_add_job(
    label:    str,
    team:     str,
    task:     str,
    schedule: str,   # Natural language: "every Monday at 9am", "every 2 weeks"
) -> str:
    """
    BOB parses the natural language schedule and calls add_job().
    Uses Claude Haiku to parse the schedule string into APScheduler args.
    """
    import anthropic, json
    client = anthropic.Anthropic()

    parse_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"Parse this schedule description into APScheduler trigger args.\n"
                f"Schedule: '{schedule}'\n\n"
                f"Reply with JSON only:\n"
                f"{{\"trigger\": \"cron\" or \"interval\", "
                f"\"cron\": {{...APScheduler CronTrigger kwargs...}} or null, "
                f"\"interval\": {{...APScheduler IntervalTrigger kwargs...}} or null}}\n\n"
                f"CronTrigger kwargs: day_of_week (mon/tue/wed/thu/fri/sat/sun), "
                f"day (1-31), hour (0-23), minute (0-59), week (*/2 for biweekly).\n"
                f"IntervalTrigger kwargs: weeks, days, hours, minutes."
            )
        }]
    )

    try:
        parsed = json.loads(parse_response.content[0].text)
        result = add_job(
            job_id   = f"custom_{str(uuid.uuid4())[:8]}",
            label    = label,
            team     = team,
            task     = task,
            trigger  = parsed["trigger"],
            cron     = parsed.get("cron"),
            interval = parsed.get("interval"),
        )
        if "error" in result:
            return f"Could not add schedule: {result['error']}"
        return (
            f"Yes Boss. Added '{label}' — {team} team, "
            f"{schedule}. First run scheduled."
        )
    except Exception as e:
        return f"Could not parse schedule '{schedule}': {e}"
```

---

**Step 7 — Add schedule to daily briefing**

In `daily_report.py`, add to the system health section:

```python
from scheduler import get_job_status_summary

schedule_summary = get_job_status_summary()
lines.append(f"\nSCHEDULE\n{schedule_summary}")
```

---

## Phase 5 — Dashboard Schedule Panel

**Step 8 — Add the schedule panel to the dashboard**

Add to the existing dashboard at `:8200`:

```html
<!-- Schedule management panel — add to dashboard HTML -->

<div id="schedule-panel">
  <h3>Scheduled Tasks</h3>
  <div id="schedule-list"></div>
  <button onclick="sendPrompt('Show me the schedule')">Refresh ↗</button>
</div>

<script>
async function loadSchedule() {
  const res  = await fetch('http://192.168.1.228:8100/schedule');
  const data = await res.json();
  const list = document.getElementById('schedule-list');

  list.innerHTML = data.jobs.map(job => `
    <div class="schedule-card ${job.enabled ? '' : 'paused'}">
      <div class="job-label">${job.label}</div>
      <div class="job-next">
        ${job.enabled
          ? 'Next: ' + new Date(job.next_run).toLocaleString()
          : 'PAUSED'
        }
      </div>
      <div class="job-actions">
        ${job.enabled
          ? `<button onclick="pauseJob('${job.job_id}')">Pause</button>`
          : `<button onclick="resumeJob('${job.job_id}')">Resume</button>`
        }
        <button onclick="runNow('${job.job_id}')">Run now</button>
        <button onclick="deleteJob('${job.job_id}')" class="danger">Remove</button>
      </div>
    </div>
  `).join('');
}

async function pauseJob(id) {
  await fetch(`http://192.168.1.228:8100/schedule/${id}/pause`, {method: 'POST'});
  loadSchedule();
}

async function resumeJob(id) {
  await fetch(`http://192.168.1.228:8100/schedule/${id}/resume`, {method: 'POST'});
  loadSchedule();
}

async function runNow(id) {
  await fetch(`http://192.168.1.228:8100/schedule/${id}/run-now`, {method: 'POST'});
  loadSchedule();
}

async function deleteJob(id) {
  if (!confirm('Remove this scheduled task?')) return;
  await fetch(`http://192.168.1.228:8100/schedule/${id}`, {method: 'DELETE'});
  loadSchedule();
}

// Refresh every 60 seconds
setInterval(loadSchedule, 60000);
loadSchedule();
</script>
```

---

**Step 9 — Verify the scheduler is running**

```bash
# [UBUNTU SERVER]
# Check the scheduler DB was created
ls -la /opt/atg-agents/checkpoints/scheduler_jobs.db

# Query the schedule via the API
curl http://localhost:8100/schedule | python3 -m json.tool
```

You should see all six default scheduled tasks listed with their next run times. Confirm with Rob before considering the build complete.

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| APScheduler running inside orchestrator — no external cron dependency | ✓ |
| Schedule persisted to SQLite — survives server restarts | ✓ |
| 6 default recurring tasks loaded on first run | ✓ |
| Pre-flight checks — skips if circuit breaker open or server under load | ✓ |
| BOB notifies Rob when a scheduled task starts | ✓ |
| BOB notifies Rob if a scheduled task is skipped (with reason) | ✓ |
| Pause / resume / remove tasks via voice ("pause the SEO audit") | ✓ |
| Run a task immediately on demand ("run the competitor check now") | ✓ |
| Add new recurring tasks via voice — natural language schedule parsing | ✓ |
| All schedule management available on dashboard at `:8200` | ✓ |
| Schedule summary in daily morning briefing | ✓ |
| Job missed and job error events logged and alerted | ✓ |

---

### What Rob experiences

**Scheduler fires automatically (Monday 9 AM):**
> *"Scheduled task started: Weekly SEO audit. Task ID: a3f2b1c8. Results will appear on the dashboard when complete."*

**Rob asks about the schedule:**
> Rob: *"Hey BOB, what's scheduled this week?"*
> BOB: *"6 active scheduled tasks. Weekly SEO audit: next Monday at 9 AM. Competitor check: Wednesday at 9 AM. App store reviews: Friday at 9 AM. Monthly tasks fire on the 1st. Everything's running."*

**Rob pauses a task:**
> Rob: *"Pause the patent scan for now."*
> BOB: *"Yes Boss. Monthly patent scan paused. It won't run until you resume it."*

**Rob adds a new task:**
> Rob: *"Add a weekly check on mobile game revenue — research team, every Thursday at 2 PM."*
> BOB: *"Yes Boss. Added 'Weekly mobile game revenue check' — research team, every Thursday at 2:00 PM. First run Thursday."*

**Task skipped due to server load:**
> *"Scheduled task 'Monthly content calendar' skipped — server resources too high to start the marketing team safely. RAM at 89%. Will retry next scheduled run."*

---

*BOB Recurring Task Scheduler Build Plan v1.0 — 2026-03-18*
*All major build plans complete. Ready to execute.*
