"""Loop detection — deterministic, not vibes-based.

Per Cogent's 2026 multi-agent failure playbook: "You cannot ask an agent if
it is in a loop; you must prove it mathematically." This module provides
three deterministic detectors that BOB can call from the firewall layer:

1. **Repeated tool call detector** — same tool name + same arguments called
   N times within a window. The most common loop pattern.

2. **Tool sequence cycle detector** — A→B→A→B→A→B style repeating
   subsequence. Catches loops where the agent thinks it's making progress
   but is actually toggling between two states.

3. **Token burn budget** — cumulative tokens in a single agent run exceeds
   a hard cap. The blunt-force detector for "this run has gone off the rails
   no matter why."

When any detector trips, it returns a loop signal. The caller (firewall or
graph node) decides what to do: warn, throttle, abort, or escalate to Rob.

Per-thread state. Each conversation thread gets its own counters so a
long-running orchestration session doesn't trigger false positives from
unrelated past activity.
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger("bob.loop_detector")


# ── Configuration ──────────────────────────────────────────────────────────

# A repeated tool call is suspicious if it appears this many times in the window
REPEATED_CALL_THRESHOLD = 5
REPEATED_CALL_WINDOW_SECONDS = 60

# Tool sequence cycle: a sub-pattern of length N that repeats this many times
CYCLE_MIN_LENGTH = 2  # Smallest cycle to detect (A→B→A→B)
CYCLE_MAX_LENGTH = 5  # Largest cycle to detect (A→B→C→D→E→A→B→C→D→E)
CYCLE_REPETITIONS = 3  # How many times the cycle must repeat to trip

# Token budget per single agent run (one conversation turn)
TOKEN_BUDGET_PER_RUN = 50000

# How many recent tool calls to remember per thread (sliding window)
HISTORY_SIZE = 50


# ── Per-thread state ───────────────────────────────────────────────────────

@dataclass
class ThreadState:
    """Loop detection state for a single conversation thread."""
    thread_id: str
    tool_history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    tokens_used: int = 0
    started_at: float = field(default_factory=time.time)
    trips: list = field(default_factory=list)  # Audit trail of detected loops


# Global registry: thread_id → ThreadState
_threads: dict[str, ThreadState] = {}


def _get_state(thread_id: str) -> ThreadState:
    """Get or create the loop-detection state for a thread."""
    if thread_id not in _threads:
        _threads[thread_id] = ThreadState(thread_id=thread_id)
    return _threads[thread_id]


def reset_thread(thread_id: str) -> None:
    """Reset loop detection state for a thread. Call this between
    independent agent runs (e.g., after a successful task completion)
    to avoid carrying state across unrelated work."""
    if thread_id in _threads:
        del _threads[thread_id]


# ── Detector 1: Repeated tool call ─────────────────────────────────────────

def record_tool_call(thread_id: str, tool_name: str, args_signature: str) -> dict | None:
    """Record a tool call and check if it's part of a loop pattern.

    Args:
        thread_id: The conversation thread this call belongs to
        tool_name: Name of the tool being called
        args_signature: A stable string representation of the args (e.g.,
                        json.dumps(args, sort_keys=True))

    Returns:
        None if no loop detected.
        dict with {"loop_type": "...", "details": "..."} if a loop is detected.
    """
    state = _get_state(thread_id)
    now = time.time()

    # Add to history
    entry = (now, tool_name, args_signature)
    state.tool_history.append(entry)

    # Detector 1: Same tool + same args called too many times in the window
    cutoff = now - REPEATED_CALL_WINDOW_SECONDS
    recent_matching = sum(
        1 for ts, name, sig in state.tool_history
        if ts >= cutoff and name == tool_name and sig == args_signature
    )

    if recent_matching >= REPEATED_CALL_THRESHOLD:
        signal = {
            "loop_type": "repeated_tool_call",
            "tool": tool_name,
            "count": recent_matching,
            "window_seconds": REPEATED_CALL_WINDOW_SECONDS,
            "thread_id": thread_id,
            "details": (
                f"Tool '{tool_name}' called with identical args {recent_matching} "
                f"times in {REPEATED_CALL_WINDOW_SECONDS}s. Threshold is "
                f"{REPEATED_CALL_THRESHOLD}."
            ),
        }
        state.trips.append({"type": "repeated_call", "ts": now, "tool": tool_name})
        logger.warning(f"Loop detected (repeated): {signal['details']}")
        return signal

    # Detector 2: Cycle in the recent tool sequence
    cycle_signal = _detect_cycle(state, thread_id)
    if cycle_signal:
        return cycle_signal

    return None


# ── Detector 2: Tool sequence cycle ────────────────────────────────────────

def _detect_cycle(state: ThreadState, thread_id: str) -> dict | None:
    """Look for repeating subsequences in the tool history.

    Algorithm: for each possible cycle length L from CYCLE_MIN_LENGTH to
    CYCLE_MAX_LENGTH, check if the most recent L*REPETITIONS calls form
    a repeating pattern of length L.

    Example with L=2 and REPETITIONS=3, cycle detected:
        [A, B, A, B, A, B] — last 6 calls are 3 reps of [A, B]
    """
    if len(state.tool_history) < CYCLE_MIN_LENGTH * CYCLE_REPETITIONS:
        return None

    # Use only tool names for cycle detection (not args), so we catch loops
    # where the agent calls the same sequence with different parameters
    names = [name for _, name, _ in state.tool_history]

    for cycle_len in range(CYCLE_MIN_LENGTH, CYCLE_MAX_LENGTH + 1):
        needed = cycle_len * CYCLE_REPETITIONS
        if len(names) < needed:
            continue

        # Take the most recent `needed` calls
        recent = names[-needed:]

        # Split into chunks of cycle_len and check if all chunks are identical
        chunks = [recent[i:i + cycle_len] for i in range(0, needed, cycle_len)]
        if all(chunk == chunks[0] for chunk in chunks):
            signal = {
                "loop_type": "tool_sequence_cycle",
                "cycle_length": cycle_len,
                "repetitions": CYCLE_REPETITIONS,
                "pattern": chunks[0],
                "thread_id": thread_id,
                "details": (
                    f"Detected {CYCLE_REPETITIONS}x repetition of "
                    f"{cycle_len}-tool cycle: {chunks[0]}"
                ),
            }
            state.trips.append({
                "type": "cycle",
                "ts": time.time(),
                "pattern": chunks[0],
            })
            logger.warning(f"Loop detected (cycle): {signal['details']}")
            return signal

    return None


# ── Detector 3: Token burn budget ──────────────────────────────────────────

def record_tokens(thread_id: str, tokens: int) -> dict | None:
    """Record tokens used by an LLM call. Trip if the cumulative budget
    for this thread exceeds the per-run cap.

    Args:
        thread_id: Conversation thread
        tokens: Number of tokens consumed by this call (input + output)

    Returns:
        None if under budget.
        dict signal if over budget.
    """
    state = _get_state(thread_id)
    state.tokens_used += tokens

    if state.tokens_used > TOKEN_BUDGET_PER_RUN:
        signal = {
            "loop_type": "token_burn_budget",
            "tokens_used": state.tokens_used,
            "budget": TOKEN_BUDGET_PER_RUN,
            "thread_id": thread_id,
            "duration_seconds": int(time.time() - state.started_at),
            "details": (
                f"Thread {thread_id} burned {state.tokens_used} tokens "
                f"(budget: {TOKEN_BUDGET_PER_RUN}). Likely runaway loop."
            ),
        }
        state.trips.append({
            "type": "token_burn",
            "ts": time.time(),
            "tokens": state.tokens_used,
        })
        logger.error(f"Loop detected (token budget): {signal['details']}")
        return signal

    return None


# ── Inspection ─────────────────────────────────────────────────────────────

def get_thread_state(thread_id: str) -> dict | None:
    """Return the current loop-detection state for a thread, for diagnostics."""
    state = _threads.get(thread_id)
    if not state:
        return None
    return {
        "thread_id": thread_id,
        "tool_calls_in_history": len(state.tool_history),
        "tokens_used": state.tokens_used,
        "duration_seconds": int(time.time() - state.started_at),
        "trips": state.trips,
    }


def all_threads_summary() -> dict:
    """Return a summary of all tracked threads. Used by the /health endpoint."""
    return {
        "tracked_threads": len(_threads),
        "threads_with_trips": sum(1 for s in _threads.values() if s.trips),
        "total_trips": sum(len(s.trips) for s in _threads.values()),
    }
