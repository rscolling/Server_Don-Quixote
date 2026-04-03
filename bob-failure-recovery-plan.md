# BOB — Failure Recovery & Circuit Breakers Build Plan
### *LangGraph checkpointing · retry logic · circuit breakers · graceful degradation*

---

## What We're Building

Right now, if an agent crashes mid-debate, an API call times out, or a Docker container dies during a task — the work stops silently. No retry. No recovery. No notification to Rob. The task is just gone.

This plan adds three layers of protection:

1. **LangGraph checkpointing** — debate state is saved after every round. A crashed task can resume from where it stopped, not from scratch.
2. **Retry logic with exponential backoff** — transient failures (API timeouts, rate limits, network blips) are retried automatically before escalating.
3. **Circuit breakers** — repeated failures on a specific agent or service trip a breaker, stop the bleeding, and tell BOB what broke and why.

All three layers report to BOB. Rob only gets involved when automatic recovery fails.

---

## Prerequisites

Before starting, confirm these are running:
- Ubuntu server with Docker + Docker Compose ✓
- BOB orchestrator at `:8100` ✓
- LangGraph installed in the orchestrator container ✓
- ChromaDB running ✓
- Observability plan Phases 1–2 complete (Langfuse instrumented) — recommended but not required

All steps begin on **Windows 11**. SSH to server where indicated.

---

## Phase 1 — LangGraph State Checkpointing

LangGraph has built-in checkpointing. It saves the full graph state after every node execution. If a graph run crashes at round 3 of a 5-round debate, it can be resumed from round 3 — not restarted from round 1.

By default, checkpointing is off. We turn it on and point it at a persistent SQLite database so state survives container restarts.

---

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Install LangGraph checkpointing dependencies**

```bash
# [UBUNTU SERVER]
# In the orchestrator container or its requirements.txt
pip install langgraph-checkpoint-sqlite --break-system-packages
```

If orchestrator runs in Docker, add to `requirements.txt` and rebuild:

```
langgraph-checkpoint-sqlite>=0.1.0
```

```bash
docker compose up -d --build orchestrator
```

---

**Step 3 — Create the checkpoints directory**

```bash
# [UBUNTU SERVER]
mkdir -p /opt/atg-agents/checkpoints
chmod 755 /opt/atg-agents/checkpoints
```

Mount it into the orchestrator container in `docker-compose.yml`:

```yaml
  orchestrator:
    # ... existing config ...
    volumes:
      - /opt/atg-agents/checkpoints:/app/checkpoints
      - /opt/atg-agents/shared:/app/shared
      # ... other volumes
```

Rebuild after editing compose:

```bash
docker compose up -d --build orchestrator
```

---

**Step 4 — Enable checkpointing in the LangGraph orchestrator**

```python
# orchestrator/checkpointing.py

import os
from langgraph.checkpoint.sqlite import SqliteSaver

CHECKPOINT_DB = os.getenv(
    "CHECKPOINT_DB_PATH",
    "/app/checkpoints/langgraph_state.db"
)

def get_checkpointer() -> SqliteSaver:
    """
    Returns a persistent SQLite checkpointer.
    One shared instance — all graphs use the same DB.
    """
    return SqliteSaver.from_conn_string(CHECKPOINT_DB)

# Single shared instance
checkpointer = get_checkpointer()
```

---

**Step 5 — Wire checkpointing into every graph**

In the orchestrator, every LangGraph graph compilation must include the checkpointer:

```python
# orchestrator/debate_graph.py

from checkpointing import checkpointer
from langgraph.graph import StateGraph

def build_debate_graph(team: str) -> any:
    """
    Build and compile a debate graph for the given team.
    Checkpointing is enabled — state is saved after every node.
    """
    graph = StateGraph(DebateState)

    # Add all nodes
    graph.add_node("debate_start",      debate_start_node)
    graph.add_node("round_start",       round_start_node)
    graph.add_node("agent_contribution",agent_contribution_node)
    graph.add_node("round_end",         round_end_node)
    graph.add_node("qa_decision",       qa_decision_node)
    graph.add_node("debate_end",        debate_end_node)

    # Add edges
    graph.set_entry_point("debate_start")
    graph.add_edge("debate_start",   "round_start")
    graph.add_edge("round_start",    "agent_contribution")
    graph.add_edge("agent_contribution", "round_end")
    graph.add_conditional_edges(
        "round_end",
        should_continue_debate,
        {
            "continue": "round_start",
            "qa":       "qa_decision",
            "end":      "debate_end",
        }
    )
    graph.add_edge("qa_decision", "debate_end")
    graph.set_finish_point("debate_end")

    # CRITICAL: compile with checkpointer
    return graph.compile(checkpointer=checkpointer)
```

---

**Step 6 — Use thread IDs for resumable tasks**

Every task invocation needs a unique `thread_id`. LangGraph uses this to identify which checkpoint to load on resume:

```python
# orchestrator/task_runner.py

import uuid
from debate_graph import build_debate_graph

async def run_debate_task(task_id: str, team: str, brief: dict) -> dict:
    """
    Runs a debate task. Automatically resumes from checkpoint if one exists
    for this task_id.
    """
    graph = build_debate_graph(team)

    # thread_id = task_id — consistent so the same task always resumes
    # from the same checkpoint
    config = {
        "configurable": {
            "thread_id": task_id,
        },
        "callbacks": [langfuse_handler],
        "metadata": {
            "team":         team,
            "task_id":      task_id,
            "debate_tier":  brief.get("tier", 2),
            "triggered_by": "BOB",
        }
    }

    try:
        result = await graph.ainvoke(
            input={"task_id": task_id, "brief": brief, "team": team},
            config=config,
        )
        return {"status": "completed", "result": result}

    except Exception as e:
        # Checkpoint was saved up to the last completed node.
        # Task can be resumed by calling run_debate_task again
        # with the same task_id.
        return {
            "status":  "failed",
            "task_id": task_id,
            "error":   str(e),
            "resumable": True,
        }
```

---

**Step 7 — Add a resume endpoint to the orchestrator API**

```python
# orchestrator/api.py

@app.post("/task/{task_id}/resume")
async def resume_task(task_id: str):
    """
    BOB calls this to resume a checkpointed task that failed mid-run.
    LangGraph loads the saved state and continues from the last completed node.
    """
    # Look up the original task brief from the task registry
    task = await get_task_from_registry(task_id)
    if not task:
        return {"error": f"Task {task_id} not found in registry"}

    result = await run_debate_task(
        task_id=task_id,
        team=task["team"],
        brief=task["brief"],
    )
    return result


@app.get("/task/{task_id}/checkpoint")
async def get_checkpoint_status(task_id: str):
    """
    Returns the saved state for a task — which round it reached,
    which node it was in when it stopped, and whether it's resumable.
    """
    from checkpointing import checkpointer

    state = checkpointer.get({"configurable": {"thread_id": task_id}})
    if not state:
        return {"has_checkpoint": False}

    return {
        "has_checkpoint":   True,
        "last_node":        state.next[0] if state.next else "completed",
        "rounds_completed": state.values.get("rounds_completed", 0),
        "resumable":        True,
    }
```

---

**Step 8 — Verify checkpointing works**

```bash
# [UBUNTU SERVER]
# Confirm the SQLite DB is being created
ls -la /opt/atg-agents/checkpoints/
# Should show: langgraph_state.db

# Check its size after running a task
du -sh /opt/atg-agents/checkpoints/langgraph_state.db
```

---

## Phase 2 — Retry Logic with Exponential Backoff

Not every failure needs human intervention. API timeouts, rate limit 429s, and brief network blips should be retried automatically. This phase adds a retry layer that sits between the agent and its API calls — transparent to the agent, invisible to Rob unless retries are exhausted.

---

**Step 9 — Add the retry module**

```python
# orchestrator/retry.py

import os
import asyncio
import time
import functools
from typing import Callable, Any

# ── Retry configuration ──────────────────────────────────────────────────────

RETRY_CONFIG = {
    # Anthropic API — rate limits and transient errors
    "anthropic": {
        "max_attempts":   4,
        "base_delay_s":   2.0,    # First retry after 2s
        "max_delay_s":    30.0,   # Cap at 30s
        "backoff_factor": 2.0,    # 2s → 4s → 8s → 16s (capped at 30s)
        "retryable_codes": [429, 500, 502, 503, 529],
        "retryable_errors": ["timeout", "connection_error", "rate_limit"],
    },
    # ElevenLabs voice API
    "elevenlabs": {
        "max_attempts":   3,
        "base_delay_s":   1.0,
        "max_delay_s":    15.0,
        "backoff_factor": 2.0,
        "retryable_codes": [429, 500, 502, 503],
        "retryable_errors": ["timeout", "connection_error"],
    },
    # Stability AI image generation
    "stability": {
        "max_attempts":   3,
        "base_delay_s":   5.0,    # Image gen is slow — longer initial delay
        "max_delay_s":    60.0,
        "backoff_factor": 2.0,
        "retryable_codes": [429, 500, 502, 503],
        "retryable_errors": ["timeout", "connection_error"],
    },
    # General default
    "default": {
        "max_attempts":   3,
        "base_delay_s":   1.0,
        "max_delay_s":    20.0,
        "backoff_factor": 2.0,
        "retryable_codes": [429, 500, 502, 503],
        "retryable_errors": ["timeout", "connection_error"],
    },
}

# ── Retry decorator ──────────────────────────────────────────────────────────

def with_retry(service: str = "default", task_id: str = None):
    """
    Decorator that wraps any async function with retry + exponential backoff.

    Usage:
        @with_retry(service="anthropic", task_id=task_id)
        async def call_claude(prompt: str) -> str:
            ...
    """
    config = RETRY_CONFIG.get(service, RETRY_CONFIG["default"])

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            attempt = 0
            last_error = None
            delay = config["base_delay_s"]

            while attempt < config["max_attempts"]:
                try:
                    return await func(*args, **kwargs)

                except Exception as e:
                    last_error = e
                    attempt += 1
                    error_str = str(e).lower()

                    # Check if this error is retryable
                    is_retryable = any(
                        r in error_str
                        for r in config["retryable_errors"]
                    )

                    # Check HTTP status codes if present
                    status_code = getattr(e, "status_code", None)
                    if status_code and status_code in config["retryable_codes"]:
                        is_retryable = True

                    if not is_retryable:
                        # Non-retryable error — fail immediately
                        raise

                    if attempt >= config["max_attempts"]:
                        # Exhausted retries
                        break

                    # Log the retry attempt
                    _log_retry(service, task_id, attempt, config["max_attempts"],
                               delay, str(e))

                    await asyncio.sleep(delay)

                    # Exponential backoff with jitter
                    delay = min(
                        delay * config["backoff_factor"],
                        config["max_delay_s"]
                    )
                    # Add ±10% jitter to avoid thundering herd
                    import random
                    delay *= (0.9 + random.random() * 0.2)

            # All retries exhausted — raise the last error
            raise RetryExhaustedError(
                service=service,
                attempts=attempt,
                last_error=last_error,
                task_id=task_id,
            )

        return wrapper
    return decorator


# ── Retry-aware Claude call ──────────────────────────────────────────────────

def make_retrying_claude_call(task_id: str):
    """
    Returns a Claude messages.create function wrapped with retry logic.
    Usage: claude_call = make_retrying_claude_call(task_id)
    """
    import anthropic
    client = anthropic.Anthropic()

    @with_retry(service="anthropic", task_id=task_id)
    async def retrying_create(**kwargs):
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(**kwargs)
        )

    return retrying_create


# ── Custom exception ─────────────────────────────────────────────────────────

class RetryExhaustedError(Exception):
    def __init__(self, service: str, attempts: int,
                 last_error: Exception, task_id: str = None):
        self.service    = service
        self.attempts   = attempts
        self.last_error = last_error
        self.task_id    = task_id
        super().__init__(
            f"Retry exhausted for {service} after {attempts} attempts. "
            f"Last error: {last_error}"
        )


# ── Internal logging ─────────────────────────────────────────────────────────

def _log_retry(service: str, task_id: str, attempt: int,
               max_attempts: int, next_delay: float, error: str):
    """Log retry events — visible in container logs and Langfuse."""
    import logging
    logging.warning(
        f"[RETRY] service={service} task={task_id} "
        f"attempt={attempt}/{max_attempts} "
        f"next_delay={next_delay:.1f}s "
        f"error={error[:100]}"
    )
```

---

**Step 10 — Apply retry to all agent API calls**

In each agent's Claude call, wrap with the retry decorator:

```python
# orchestrator/agents/base_agent.py

from retry import make_retrying_claude_call, RetryExhaustedError

class BaseAgent:
    def __init__(self, agent_id: str, task_id: str):
        self.agent_id  = agent_id
        self.task_id   = task_id
        self.claude    = make_retrying_claude_call(task_id)

    async def call_claude(self, system: str, messages: list,
                          model: str = "claude-sonnet-4-5") -> str:
        try:
            response = await self.claude(
                model=model,
                max_tokens=2000,
                system=system,
                messages=messages,
            )
            return response.content[0].text

        except RetryExhaustedError as e:
            # Retries exhausted — this agent has failed permanently on this call
            # Let the circuit breaker handle it
            raise AgentCallFailedError(
                agent_id=self.agent_id,
                task_id=self.task_id,
                reason=str(e),
            )
```

---

## Phase 3 — Circuit Breakers

Retry logic handles transient failures. Circuit breakers handle persistent ones. If the Anthropic API is returning errors on every call, retrying indefinitely wastes time and money. A circuit breaker detects the pattern, trips open, and stops attempts — then tests periodically to see if the service has recovered.

Three states: **Closed** (normal operation), **Open** (failing — requests blocked), **Half-Open** (testing recovery).

---

**Step 11 — Add the circuit breaker module**

```python
# orchestrator/circuit_breaker.py

import asyncio
import time
from enum import Enum
from dataclasses import dataclass, field

class BreakerState(Enum):
    CLOSED    = "closed"      # Normal — requests pass through
    OPEN      = "open"        # Failing — requests blocked
    HALF_OPEN = "half_open"   # Testing — one request allowed through

@dataclass
class CircuitBreaker:
    """
    One circuit breaker per external service or agent.
    """
    name: str

    # Thresholds
    failure_threshold:  int   = 3      # Trip after this many consecutive failures
    recovery_timeout_s: float = 60.0   # Wait this long before testing recovery
    success_threshold:  int   = 2      # Require this many successes to close again

    # State
    state:               BreakerState = field(default=BreakerState.CLOSED, init=False)
    failure_count:       int          = field(default=0, init=False)
    success_count:       int          = field(default=0, init=False)
    last_failure_time:   float        = field(default=0.0, init=False)
    last_state_change:   float        = field(default_factory=time.time, init=False)

    def is_open(self) -> bool:
        if self.state == BreakerState.OPEN:
            # Check if recovery timeout has elapsed
            if time.time() - self.last_failure_time >= self.recovery_timeout_s:
                self._transition_to(BreakerState.HALF_OPEN)
                return False    # Allow one test request through
            return True         # Still open — block request
        return False

    def record_success(self):
        if self.state == BreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._transition_to(BreakerState.CLOSED)
        elif self.state == BreakerState.CLOSED:
            self.failure_count = 0  # Reset on success

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == BreakerState.HALF_OPEN:
            # Recovery test failed — go back to open
            self._transition_to(BreakerState.OPEN)
        elif (self.state == BreakerState.CLOSED and
              self.failure_count >= self.failure_threshold):
            self._transition_to(BreakerState.OPEN)

    def _transition_to(self, new_state: BreakerState):
        old_state = self.state
        self.state = new_state
        self.last_state_change = time.time()

        if new_state == BreakerState.CLOSED:
            self.failure_count = 0
            self.success_count = 0

        elif new_state == BreakerState.HALF_OPEN:
            self.success_count = 0

        # Notify BOB of state changes
        asyncio.create_task(
            _notify_bob_breaker_change(self.name, old_state, new_state)
        )


# ── Breaker registry ─────────────────────────────────────────────────────────
# One breaker per service and per agent type

_breakers: dict[str, CircuitBreaker] = {}

def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _breakers[name]

def get_all_breaker_statuses() -> dict:
    """Returns current state of all circuit breakers — for BOB's status report."""
    return {
        name: {
            "state":         breaker.state.value,
            "failures":      breaker.failure_count,
            "last_failure":  breaker.last_failure_time,
        }
        for name, breaker in _breakers.items()
    }


# ── Context manager for protected calls ──────────────────────────────────────

class CircuitBreakerOpen(Exception):
    def __init__(self, breaker_name: str):
        self.breaker_name = breaker_name
        super().__init__(
            f"Circuit breaker '{breaker_name}' is OPEN. "
            f"Service is unavailable. Requests blocked."
        )


async def call_with_breaker(breaker_name: str, coro, **breaker_kwargs):
    """
    Execute a coroutine protected by a circuit breaker.

    Usage:
        result = await call_with_breaker(
            "anthropic_api",
            claude_client.messages.create(...),
            failure_threshold=3,
            recovery_timeout_s=60,
        )
    """
    breaker = get_breaker(breaker_name, **breaker_kwargs)

    if breaker.is_open():
        raise CircuitBreakerOpen(breaker_name)

    try:
        result = await coro
        breaker.record_success()
        return result

    except Exception as e:
        breaker.record_failure()
        raise


# ── BOB notification on breaker state change ─────────────────────────────────

async def _notify_bob_breaker_change(
    name: str,
    old_state: BreakerState,
    new_state: BreakerState
):
    if new_state == BreakerState.OPEN:
        await bob_proactive_report(
            f"Circuit breaker TRIPPED — {name}\n"
            f"Service is failing consistently. Requests are now blocked "
            f"to prevent cascade failures.\n"
            f"Recovery test in 60 seconds.\n"
            f"Affected tasks have been paused and will resume automatically "
            f"if the service recovers."
        )
    elif new_state == BreakerState.CLOSED and old_state != BreakerState.CLOSED:
        await bob_proactive_report(
            f"Circuit breaker RECOVERED — {name}\n"
            f"Service is responding normally. Paused tasks are resuming."
        )
```

---

**Step 12 — Register breakers for all external services and agent types**

```python
# orchestrator/main.py — on startup

from circuit_breaker import get_breaker

# External service breakers
get_breaker("anthropic_api",  failure_threshold=3, recovery_timeout_s=60)
get_breaker("elevenlabs",     failure_threshold=3, recovery_timeout_s=30)
get_breaker("stability_ai",   failure_threshold=3, recovery_timeout_s=120)
get_breaker("unsplash",       failure_threshold=5, recovery_timeout_s=30)

# Per-team breakers — trip if the entire team is failing
get_breaker("team_marketing",   failure_threshold=3, recovery_timeout_s=120)
get_breaker("team_engineering", failure_threshold=3, recovery_timeout_s=120)
get_breaker("team_research",    failure_threshold=3, recovery_timeout_s=120)
```

---

**Step 13 — Combine retry + circuit breaker in agent calls**

The full protection stack: circuit breaker check → retry with backoff → circuit breaker record:

```python
# orchestrator/agents/base_agent.py  (updated)

from circuit_breaker import call_with_breaker, CircuitBreakerOpen
from retry import make_retrying_claude_call, RetryExhaustedError

class BaseAgent:
    async def call_claude(self, system: str, messages: list,
                          model: str = "claude-sonnet-4-5") -> str:
        try:
            # Circuit breaker wraps the retry-wrapped call
            response = await call_with_breaker(
                breaker_name="anthropic_api",
                coro=self.claude(          # self.claude already has retry logic
                    model=model,
                    max_tokens=2000,
                    system=system,
                    messages=messages,
                ),
                failure_threshold=3,
                recovery_timeout_s=60,
            )
            return response.content[0].text

        except CircuitBreakerOpen as e:
            # Breaker is open — don't even try. Pause the task.
            await bob_proactive_report(
                f"Agent {self.agent_id} call blocked — {e.breaker_name} "
                f"circuit breaker is open. Task {self.task_id} paused."
            )
            raise

        except RetryExhaustedError as e:
            # Retries failed — record against the circuit breaker
            # (The breaker may trip on the next failure)
            raise
```

---

## Phase 4 — Graceful Degradation

When a circuit breaker trips, tasks should pause cleanly — not crash. This phase adds a task pause/resume queue and BOB's recovery behavior.

---

**Step 14 — Add the task pause queue**

```python
# orchestrator/recovery.py

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class PausedTask:
    task_id:        str
    team:           str
    brief:          dict
    paused_at:      datetime = field(default_factory=datetime.utcnow)
    pause_reason:   str      = ""
    resume_after:   str      = ""  # Which breaker/service must recover first
    retry_count:    int      = 0
    max_retries:    int      = 3


_paused_tasks: dict[str, PausedTask] = {}


def pause_task(task_id: str, team: str, brief: dict,
               reason: str, resume_after: str):
    """Pause a task and queue it for automatic resumption."""
    _paused_tasks[task_id] = PausedTask(
        task_id=task_id,
        team=team,
        brief=brief,
        pause_reason=reason,
        resume_after=resume_after,
    )


async def recovery_monitor_loop():
    """
    Checks paused tasks every 30 seconds.
    When a circuit breaker closes, automatically resumes tasks
    that were paused waiting for that service.
    """
    from circuit_breaker import _breakers, BreakerState
    from task_runner import run_debate_task

    while True:
        await asyncio.sleep(30)

        tasks_to_resume = []

        for task_id, paused in list(_paused_tasks.items()):
            breaker_name = paused.resume_after

            if not breaker_name:
                tasks_to_resume.append(task_id)
                continue

            breaker = _breakers.get(breaker_name)
            if not breaker or breaker.state == BreakerState.CLOSED:
                tasks_to_resume.append(task_id)

        for task_id in tasks_to_resume:
            paused = _paused_tasks.pop(task_id)

            if paused.retry_count >= paused.max_retries:
                await bob_proactive_report(
                    f"Task {task_id} ({paused.team}) has failed {paused.retry_count} times "
                    f"and cannot be automatically resumed. "
                    f"Manual review required at http://192.168.1.228:8200"
                )
                continue

            paused.retry_count += 1
            await bob_proactive_report(
                f"Resuming paused task {task_id} ({paused.team}) — "
                f"service '{paused.resume_after}' has recovered. "
                f"Attempt {paused.retry_count}/{paused.max_retries}."
            )

            # Resume from LangGraph checkpoint
            asyncio.create_task(
                run_debate_task(
                    task_id=task_id,
                    team=paused.team,
                    brief=paused.brief,
                )
            )


def get_paused_task_summary() -> str:
    if not _paused_tasks:
        return "No paused tasks."
    lines = [f"{len(_paused_tasks)} task(s) paused:"]
    for t in _paused_tasks.values():
        lines.append(
            f"  [{t.team}] {t.task_id[:8]} — paused {t.paused_at.strftime('%H:%M')} "
            f"waiting for: {t.resume_after}"
        )
    return "\n".join(lines)
```

---

**Step 15 — Start the recovery monitor with the orchestrator**

```python
# orchestrator/main.py — add to startup

from recovery import recovery_monitor_loop

asyncio.create_task(recovery_monitor_loop())
```

---

## Phase 5 — Add Recovery Status to BOB

**Step 16 — Wire recovery status into BOB's status report**

```python
# orchestrator/bob.py

from circuit_breaker import get_all_breaker_statuses
from recovery import get_paused_task_summary

def bob_full_status_report() -> str:
    lines = []

    # Breaker status — only report non-closed breakers
    breakers = get_all_breaker_statuses()
    open_breakers = {
        name: b for name, b in breakers.items()
        if b["state"] != "closed"
    }
    if open_breakers:
        lines.append("CIRCUIT BREAKERS — issues detected:")
        for name, b in open_breakers.items():
            lines.append(f"  [{b['state'].upper()}] {name} — {b['failures']} failures")
    else:
        lines.append("Circuit breakers: all closed (normal).")

    # Paused tasks
    lines.append(get_paused_task_summary())

    return "\n".join(lines)
```

**Step 17 — Add breaker status to the daily report**

In `daily_report.py`, add to the system health section:

```python
from circuit_breaker import get_all_breaker_statuses

breakers = get_all_breaker_statuses()
open_breakers = [
    f"{name} ({b['state']})"
    for name, b in breakers.items()
    if b["state"] != "closed"
]

if open_breakers:
    lines.append(f"  ! Circuit breakers open: {', '.join(open_breakers)}")
else:
    lines.append("  Circuit breakers: all normal.")
```

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| LangGraph state saved after every debate node | ✓ |
| Failed tasks resume from last checkpoint — not from scratch | ✓ |
| Resume endpoint at `POST /task/{id}/resume` | ✓ |
| Transient API errors retried automatically (up to 4 attempts) | ✓ |
| Exponential backoff with jitter — no thundering herd | ✓ |
| Non-retryable errors fail immediately — no wasted attempts | ✓ |
| Circuit breakers on all external services and team endpoints | ✓ |
| Breaker trips after 3 consecutive failures | ✓ |
| BOB notified immediately when breaker trips or recovers | ✓ |
| Paused tasks auto-resume when service recovers | ✓ |
| Tasks abandoned after 3 failed resume attempts — escalated to Rob | ✓ |
| Breaker status in BOB status report | ✓ |
| Breaker status in daily morning briefing | ✓ |

---

### Nightly schedule — updated with recovery

| Time | Task |
|---|---|
| Continuous | Recovery monitor checks paused tasks every 30 seconds |
| Continuous | Circuit breakers self-test recovery every 60 seconds |
| 1:00 AM | Langfuse database backup |
| 2:00 AM | Langfuse trace prune |
| 3:00 AM | Retention sweep |
| 8:00 AM | BOB daily briefing (includes breaker + paused task status) |

---

### What BOB says when things go wrong

**Breaker trips:**
> *"Circuit breaker TRIPPED — anthropic_api. Service is failing consistently. Requests are now blocked to prevent cascade failures. Recovery test in 60 seconds. Affected tasks have been paused and will resume automatically if the service recovers."*

**Automatic recovery:**
> *"Circuit breaker RECOVERED — anthropic_api. Service is responding normally. Paused tasks are resuming."*

**Task resumed from checkpoint:**
> *"Resuming paused task a3f2b1c8 (marketing) — service 'anthropic_api' has recovered. Attempt 1/3. Continuing from round 3 of 5."*

**Task cannot be auto-recovered:**
> *"Task a3f2b1c8 (marketing) has failed 3 times and cannot be automatically resumed. Manual review required at http://192.168.1.228:8200"*

---

*BOB Failure Recovery & Circuit Breakers Build Plan v1.0 — 2026-03-18*
*Next build: Webhook Tool Security — Pre-Execution Firewall*
