"""Lightweight circuit breaker for external service calls.

Tracks failure counts per service. After consecutive failures hit the
threshold, the circuit opens and calls fail fast for a cooldown period.
After cooldown, one probe call is allowed — if it succeeds, the circuit
closes and normal operation resumes.

States: CLOSED (normal) → OPEN (failing fast) → HALF_OPEN (probing)
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("bob.circuit")


class State(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing fast
    HALF_OPEN = "half_open"  # Probing with one call


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5      # Consecutive failures before opening
    cooldown_seconds: int = 60      # Time before probing after opening
    failure_count: int = 0
    state: State = State.CLOSED
    last_failure_time: float = 0.0
    last_error: str = ""

    def record_success(self):
        """Call was successful — reset."""
        if self.state != State.CLOSED:
            logger.info(f"Circuit {self.name}: recovered → CLOSED")
        self.failure_count = 0
        self.state = State.CLOSED
        self.last_error = ""

    def record_failure(self, error: str = ""):
        """Call failed — increment counter, maybe open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.last_error = error

        if self.failure_count >= self.failure_threshold:
            if self.state != State.OPEN:
                logger.warning(
                    f"Circuit {self.name}: OPEN after {self.failure_count} failures. "
                    f"Cooldown {self.cooldown_seconds}s. Last error: {error}"
                )
            self.state = State.OPEN

    def can_execute(self) -> bool:
        """Check if a call should be attempted."""
        if self.state == State.CLOSED:
            return True

        if self.state == State.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.cooldown_seconds:
                self.state = State.HALF_OPEN
                logger.info(f"Circuit {self.name}: HALF_OPEN — probing")
                return True
            return False

        if self.state == State.HALF_OPEN:
            return True

        return True

    def status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
            "cooldown_remaining": max(0, int(
                self.cooldown_seconds - (time.time() - self.last_failure_time)
            )) if self.state == State.OPEN else 0,
        }


# ── Global registry ─────────────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, failure_threshold: int = 5, cooldown_seconds: int = 60) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
    return _breakers[name]


def all_status() -> list[dict]:
    """Return status of all circuit breakers."""
    return [b.status() for b in _breakers.values()]
