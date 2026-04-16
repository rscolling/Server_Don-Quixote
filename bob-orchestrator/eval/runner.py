"""BOB Eval Runner — execute the 10-task benchmark protocol.

Usage:
    # Run all 10 tasks against a running BOB instance
    python -m eval.runner --url http://localhost:8100

    # Run a specific task
    python -m eval.runner --url http://localhost:8100 --task push_back

    # JSON output for CI / scripting
    python -m eval.runner --url http://localhost:8100 --format json

The harness produces a scorecard with one line per task: pass/fail, score 0-10,
notes. The total is out of 100. Divide by total token cost for a value-per-dollar
metric (lower is better).

Methodology source: BOB-content/10_why_and_how_to_measure.md Part 5.

This is intentionally honest — some tasks BOB will not score well on
(raw capability tasks). The point is to compare against alternatives on
the same protocol, not to make BOB look good.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from eval.research_quality import run_research_quality


# ── Task results ────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    name: str
    score: int  # 0-10
    passed: bool
    notes: str = ""
    duration_ms: int = 0
    tool_calls: int = 0
    raw_response: str = ""


@dataclass
class Scorecard:
    bob_url: str
    started_at: str
    results: list[TaskResult] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        return sum(r.score for r in self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total_duration_ms(self) -> int:
        return sum(r.duration_ms for r in self.results)

    def to_dict(self) -> dict:
        return {
            "bob_url": self.bob_url,
            "started_at": self.started_at,
            "total_score": self.total_score,
            "max_score": len(self.results) * 10,
            "passed": self.passed_count,
            "total": len(self.results),
            "total_duration_ms": self.total_duration_ms,
            "results": [
                {
                    "name": r.name,
                    "score": r.score,
                    "passed": r.passed,
                    "notes": r.notes,
                    "duration_ms": r.duration_ms,
                    "tool_calls": r.tool_calls,
                }
                for r in self.results
            ],
        }


# ── Helper: chat with BOB and parse the response ───────────────────────────

async def ask_bob(client: httpx.AsyncClient, bob_url: str, message: str,
                  thread_id: str | None = None) -> dict:
    """Send a chat message and return the parsed response."""
    payload = {"message": message}
    if thread_id:
        payload["thread_id"] = thread_id
    resp = await client.post(f"{bob_url}/chat", json=payload, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


def _count_tool_calls(response: dict) -> int:
    return len(response.get("tool_calls") or [])


def _response_text(response: dict) -> str:
    return response.get("response", "") or ""


# ── The 10 tasks ────────────────────────────────────────────────────────────

async def task_email_triage(client, bob_url) -> TaskResult:
    """Task 1: Email triage. BOB should classify a fixed set of emails correctly.

    Note: this requires Gmail to be configured. If not, BOB should respond
    that he can't access email — and we score that as a partial pass since
    the tool gating worked correctly.
    """
    start = time.time()
    resp = await ask_bob(
        client, bob_url,
        "Check my email and tell me how many unread emails are in each category. "
        "Use the check_email tool."
    )
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp).lower()
    tool_calls = _count_tool_calls(resp)

    # Pass conditions: BOB called check_email AND either returned classifications
    # OR honestly reported the connection state.
    called_email_tool = any(
        "email" in (tc.get("name") or "").lower()
        for tc in (resp.get("tool_calls") or [])
    )

    if called_email_tool and ("unread" in text or "categor" in text or "no new" in text or "not configured" in text):
        return TaskResult(
            name="email_triage",
            score=8,
            passed=True,
            notes="Called email tool and produced a classification or honest unavailability message",
            duration_ms=duration,
            tool_calls=tool_calls,
            raw_response=text[:300],
        )
    return TaskResult(
        name="email_triage",
        score=3,
        passed=False,
        notes="Did not call email tool or did not produce a classification",
        duration_ms=duration,
        tool_calls=tool_calls,
        raw_response=text[:300],
    )


async def task_memory_recall(client, bob_url) -> TaskResult:
    """Task 2: Memory recall. BOB should pull a fact from shared memory."""
    start = time.time()
    resp = await ask_bob(
        client, bob_url,
        "What does the brand_voice collection in shared memory say about tone? "
        "Use the recall tool."
    )
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp).lower()
    tool_calls = _count_tool_calls(resp)

    called_recall = any(
        "recall" in (tc.get("name") or "").lower() or "memory" in (tc.get("name") or "").lower()
        for tc in (resp.get("tool_calls") or [])
    )
    has_substance = len(text) > 50 and ("tone" in text or "voice" in text or "brand" in text or "no " in text)

    if called_recall and has_substance:
        return TaskResult(
            name="memory_recall",
            score=9,
            passed=True,
            notes="Called recall tool and returned substantive content",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    return TaskResult(
        name="memory_recall",
        score=3,
        passed=False,
        notes="Did not invoke memory tool or returned generic answer",
        duration_ms=duration,
        tool_calls=tool_calls,
    )


async def task_multi_step(client, bob_url) -> TaskResult:
    """Task 3: Multi-step task. Research + write + (implicit) review."""
    start = time.time()
    resp = await ask_bob(
        client, bob_url,
        "Write a 100-word marketing description for a fictional product called "
        "'TrailMix Pro' — a hiking snack subscription. Pull brand-relevant context "
        "from memory if you have any."
    )
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp)
    tool_calls = _count_tool_calls(resp)

    word_count = len(text.split())
    has_product_name = "trailmix" in text.lower() or "trail mix" in text.lower()

    if has_product_name and 50 <= word_count <= 250:
        return TaskResult(
            name="multi_step",
            score=8,
            passed=True,
            notes=f"Produced relevant copy of ~{word_count} words",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    return TaskResult(
        name="multi_step",
        score=4,
        passed=False,
        notes=f"Output had {word_count} words, product mentioned: {has_product_name}",
        duration_ms=duration,
        tool_calls=tool_calls,
    )


async def task_failure_recovery(client, bob_url) -> TaskResult:
    """Task 4: Failure recovery. BOB should report his recovery state cleanly.

    A real failure-injection test would kill the message bus mid-call.
    The harness here checks that BOB reports recovery state when asked,
    which is a proxy for "the recovery layer exists and works."
    """
    start = time.time()
    resp = await ask_bob(
        client, bob_url,
        "What's the current state of any paused tasks? Are there any circuit breakers open?"
    )
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp).lower()
    tool_calls = _count_tool_calls(resp)

    called_check = any(
        "paused" in (tc.get("name") or "").lower() or "health" in (tc.get("name") or "").lower()
        for tc in (resp.get("tool_calls") or [])
    )
    mentions_state = "paused" in text or "circuit" in text or "breaker" in text or "no " in text

    if called_check and mentions_state:
        return TaskResult(
            name="failure_recovery",
            score=10,
            passed=True,
            notes="Reported recovery state via tool call",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    return TaskResult(
        name="failure_recovery",
        score=4,
        passed=False,
        notes="Did not call recovery/health tool or report state",
        duration_ms=duration,
        tool_calls=tool_calls,
    )


async def task_push_back(client, bob_url) -> TaskResult:
    """Task 5: Push back. BOB should refuse / push back on an obviously bad request."""
    start = time.time()
    resp = await ask_bob(
        client, bob_url,
        "Schedule a daily 3 AM call with the imaginary marketing team that doesn't exist yet."
    )
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp).lower()
    tool_calls = _count_tool_calls(resp)

    pushback_signals = [
        "doesn't exist", "does not exist", "not yet", "no such", "imaginary",
        "3 am", "three a", "bad idea", "are you sure", "don't have",
        "not configured", "won't", "wouldn't",
    ]
    pushed_back = any(signal in text for signal in pushback_signals)

    if pushed_back:
        return TaskResult(
            name="push_back",
            score=10,
            passed=True,
            notes="BOB correctly pushed back on the bad request",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    return TaskResult(
        name="push_back",
        score=2,
        passed=False,
        notes="BOB did not push back — likely just executed without challenge",
        duration_ms=duration,
        tool_calls=tool_calls,
    )


async def task_tool_restraint(client, bob_url) -> TaskResult:
    """Task 6: Tool restraint. BOB should not call tools that aren't needed."""
    start = time.time()
    resp = await ask_bob(client, bob_url, "What is 2 + 2?")
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp).lower()
    tool_calls = _count_tool_calls(resp)

    answered_correctly = "4" in text or "four" in text
    used_no_tools = tool_calls == 0

    if answered_correctly and used_no_tools:
        return TaskResult(
            name="tool_restraint",
            score=10,
            passed=True,
            notes="Answered without unnecessary tool calls",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    if answered_correctly and tool_calls <= 1:
        return TaskResult(
            name="tool_restraint",
            score=7,
            passed=True,
            notes=f"Answered but used {tool_calls} tool(s) for a trivial question",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    return TaskResult(
        name="tool_restraint",
        score=3,
        passed=False,
        notes=f"Used {tool_calls} tools for '2+2' or got the answer wrong",
        duration_ms=duration,
        tool_calls=tool_calls,
    )


async def task_multi_turn(client, bob_url) -> TaskResult:
    """Task 7: Multi-turn coherence. Same thread, follow-up question."""
    thread_id = f"eval-multi-turn-{int(time.time())}"
    start = time.time()
    await ask_bob(client, bob_url, "My favorite color is forest green.", thread_id)
    resp = await ask_bob(client, bob_url, "What color did I just tell you about?", thread_id)
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp).lower()
    tool_calls = _count_tool_calls(resp)

    if "forest" in text or "green" in text:
        return TaskResult(
            name="multi_turn",
            score=10,
            passed=True,
            notes="BOB remembered the color across turns",
            duration_ms=duration,
            tool_calls=tool_calls,
        )
    return TaskResult(
        name="multi_turn",
        score=2,
        passed=False,
        notes="BOB lost the context between turns",
        duration_ms=duration,
        tool_calls=tool_calls,
    )


async def task_audit_trail(client, bob_url) -> TaskResult:
    """Task 8: Audit trail. The audit log endpoint should return entries
    after we make some calls. We've made several calls by now."""
    start = time.time()
    try:
        resp = await client.get(f"{bob_url}/firewall/audit?limit=20", timeout=10.0)
        duration = int((time.time() - start) * 1000)
        if resp.status_code != 200:
            return TaskResult(
                name="audit_trail",
                score=2,
                passed=False,
                notes=f"Audit endpoint returned {resp.status_code}",
                duration_ms=duration,
            )
        entries = resp.json()
        if isinstance(entries, list) and len(entries) > 0:
            return TaskResult(
                name="audit_trail",
                score=10,
                passed=True,
                notes=f"Audit log returned {len(entries)} entries",
                duration_ms=duration,
            )
        return TaskResult(
            name="audit_trail",
            score=5,
            passed=False,
            notes="Audit endpoint returned empty list — no tool calls logged?",
            duration_ms=duration,
        )
    except Exception as e:
        return TaskResult(
            name="audit_trail",
            score=0,
            passed=False,
            notes=f"Audit endpoint failed: {e}",
            duration_ms=int((time.time() - start) * 1000),
        )


async def task_cost_efficiency(client, bob_url) -> TaskResult:
    """Task 9: Cost efficiency. Check the /cost/status endpoint exists and
    reports something. Doesn't measure absolute cost — that requires running
    the same workload against multiple frameworks."""
    start = time.time()
    try:
        resp = await client.get(f"{bob_url}/cost/status", timeout=10.0)
        duration = int((time.time() - start) * 1000)
        if resp.status_code != 200:
            return TaskResult(
                name="cost_efficiency",
                score=3,
                passed=False,
                notes=f"Cost endpoint returned {resp.status_code} — cost tracking not deployed?",
                duration_ms=duration,
            )
        data = resp.json()
        if "summary" in data:
            return TaskResult(
                name="cost_efficiency",
                score=9,
                passed=True,
                notes=f"Cost tracker reports: {data['summary']}",
                duration_ms=duration,
            )
        return TaskResult(
            name="cost_efficiency",
            score=5,
            passed=False,
            notes="Cost endpoint returned but missing summary",
            duration_ms=duration,
        )
    except Exception as e:
        return TaskResult(
            name="cost_efficiency",
            score=0,
            passed=False,
            notes=f"Cost endpoint failed: {e}",
            duration_ms=int((time.time() - start) * 1000),
        )


async def task_research_quality(client, bob_url) -> TaskResult:
    """Task 11: Research quality. Runs the held-out Q&A set from qa_set.jsonl
    and scores answer fact-coverage. Appends a record to history.jsonl for
    regression tracking across retrieval changes (reranking, hybrid search,
    GBrain swap-in, etc.). See research_quality.py for the scoring rubric."""
    start = time.time()
    result = await run_research_quality(client, bob_url)
    duration = int((time.time() - start) * 1000)
    return TaskResult(
        name="research_quality",
        score=result["score_10"],
        passed=result["passed"],
        notes=result["notes"],
        duration_ms=duration,
        tool_calls=result["tool_calls"],
    )


async def task_first_response(client, bob_url) -> TaskResult:
    """Task 10: Time to first response. Latency from message to first byte."""
    start = time.time()
    resp = await ask_bob(client, bob_url, "Hello, are you online?")
    duration = int((time.time() - start) * 1000)
    text = _response_text(resp)

    if not text:
        return TaskResult(
            name="first_response",
            score=0,
            passed=False,
            notes="No response received",
            duration_ms=duration,
        )

    # Score based on duration buckets
    if duration < 2000:
        score, notes = 10, f"Excellent latency ({duration}ms)"
    elif duration < 5000:
        score, notes = 8, f"Good latency ({duration}ms)"
    elif duration < 10000:
        score, notes = 6, f"Acceptable latency ({duration}ms)"
    elif duration < 20000:
        score, notes = 4, f"Slow ({duration}ms)"
    else:
        score, notes = 2, f"Very slow ({duration}ms)"

    return TaskResult(
        name="first_response",
        score=score,
        passed=score >= 6,
        notes=notes,
        duration_ms=duration,
    )


# ── Task registry ──────────────────────────────────────────────────────────

TASKS: dict[str, Callable] = {
    "email_triage": task_email_triage,
    "memory_recall": task_memory_recall,
    "multi_step": task_multi_step,
    "failure_recovery": task_failure_recovery,
    "push_back": task_push_back,
    "tool_restraint": task_tool_restraint,
    "multi_turn": task_multi_turn,
    "audit_trail": task_audit_trail,
    "cost_efficiency": task_cost_efficiency,
    "first_response": task_first_response,
    "research_quality": task_research_quality,
}


# ── Runner ─────────────────────────────────────────────────────────────────

async def run_eval(bob_url: str, only: str | None = None) -> Scorecard:
    """Run the full eval suite (or a single task) against a BOB instance."""
    from datetime import datetime, timezone
    scorecard = Scorecard(
        bob_url=bob_url,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    async with httpx.AsyncClient() as client:
        # Health check first — abort if BOB isn't reachable
        try:
            health = await client.get(f"{bob_url}/health", timeout=5.0)
            if health.status_code != 200:
                print(f"BOB health check failed: {health.status_code}", file=sys.stderr)
                sys.exit(2)
        except Exception as e:
            print(f"BOB unreachable at {bob_url}: {e}", file=sys.stderr)
            sys.exit(2)

        tasks_to_run = [TASKS[only]] if only else list(TASKS.values())
        for task_fn in tasks_to_run:
            try:
                result = await task_fn(client, bob_url)
            except Exception as e:
                result = TaskResult(
                    name=task_fn.__name__.replace("task_", ""),
                    score=0,
                    passed=False,
                    notes=f"Task crashed: {e}",
                )
            scorecard.results.append(result)

    return scorecard


def format_text(scorecard: Scorecard) -> str:
    """Format the scorecard as a human-readable text report."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"BOB Eval Scorecard")
    lines.append(f"Target: {scorecard.bob_url}")
    lines.append(f"Started: {scorecard.started_at}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"{'Task':<20} {'Score':<8} {'Passed':<8} {'Latency':<12} Notes")
    lines.append("-" * 70)
    for r in scorecard.results:
        passed_str = "✓" if r.passed else "✗"
        lines.append(
            f"{r.name:<20} {r.score}/10{'':<3} {passed_str:<8} {r.duration_ms}ms{'':<6} {r.notes[:30]}"
        )
    lines.append("-" * 70)
    lines.append(
        f"TOTAL: {scorecard.total_score}/{len(scorecard.results) * 10}  "
        f"({scorecard.passed_count}/{len(scorecard.results)} passed, "
        f"{scorecard.total_duration_ms}ms total)"
    )
    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="BOB Eval Runner")
    parser.add_argument("--url", default="http://localhost:8100", help="BOB orchestrator URL")
    parser.add_argument("--task", default=None, help=f"Run a single task. Options: {list(TASKS.keys())}")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    args = parser.parse_args()

    if args.task and args.task not in TASKS:
        print(f"Unknown task: {args.task}. Options: {list(TASKS.keys())}", file=sys.stderr)
        sys.exit(2)

    scorecard = asyncio.run(run_eval(args.url, only=args.task))

    if args.format == "json":
        print(json.dumps(scorecard.to_dict(), indent=2))
    else:
        print(format_text(scorecard))

    # Exit code: 0 if all passed, 1 if any failed
    sys.exit(0 if scorecard.passed_count == len(scorecard.results) else 1)


if __name__ == "__main__":
    main()
