"""Retry decorator with exponential backoff and jitter.

Wraps async functions with automatic retry for transient failures.
Works alongside circuit_breaker.py — retry handles individual calls,
circuit breaker handles persistent service-level failures.
"""

import asyncio
import functools
import logging
import random
from typing import Any, Callable

logger = logging.getLogger("bob.retry")


RETRY_CONFIGS = {
    "anthropic": {
        "max_attempts": 4,
        "base_delay": 2.0,
        "max_delay": 30.0,
        "backoff_factor": 2.0,
        "retryable_codes": [429, 500, 502, 503, 529],
        "retryable_errors": ["timeout", "connection_error", "rate_limit", "overloaded"],
    },
    "elevenlabs": {
        "max_attempts": 3,
        "base_delay": 1.0,
        "max_delay": 15.0,
        "backoff_factor": 2.0,
        "retryable_codes": [429, 500, 502, 503],
        "retryable_errors": ["timeout", "connection_error"],
    },
    "default": {
        "max_attempts": 3,
        "base_delay": 1.0,
        "max_delay": 20.0,
        "backoff_factor": 2.0,
        "retryable_codes": [429, 500, 502, 503],
        "retryable_errors": ["timeout", "connection_error"],
    },
}


class RetryExhaustedError(Exception):
    """All retry attempts failed."""

    def __init__(self, service: str, attempts: int, last_error: Exception,
                 task_id: str | None = None):
        self.service = service
        self.attempts = attempts
        self.last_error = last_error
        self.task_id = task_id
        super().__init__(
            f"Retry exhausted for {service} after {attempts} attempts: {last_error}"
        )


def _is_retryable(exc: Exception, config: dict) -> bool:
    """Check if an exception is retryable based on config."""
    error_str = str(exc).lower()
    if any(r in error_str for r in config["retryable_errors"]):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code and status_code in config["retryable_codes"]:
        return True
    return False


def with_retry(service: str = "default", task_id: str | None = None):
    """Decorator that wraps an async function with retry + exponential backoff.

    Usage:
        @with_retry(service="anthropic")
        async def call_claude(prompt):
            ...
    """
    config = RETRY_CONFIGS.get(service, RETRY_CONFIGS["default"])

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_error = None
            delay = config["base_delay"]

            for attempt in range(1, config["max_attempts"] + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc

                    if not _is_retryable(exc, config):
                        raise

                    if attempt >= config["max_attempts"]:
                        break

                    # Add jitter (+-10%)
                    jittered_delay = delay * (0.9 + random.random() * 0.2)
                    logger.warning(
                        f"[RETRY] service={service} task={task_id} "
                        f"attempt={attempt}/{config['max_attempts']} "
                        f"delay={jittered_delay:.1f}s error={str(exc)[:100]}"
                    )
                    await asyncio.sleep(jittered_delay)
                    delay = min(delay * config["backoff_factor"], config["max_delay"])

            raise RetryExhaustedError(
                service=service,
                attempts=config["max_attempts"],
                last_error=last_error,
                task_id=task_id,
            )

        return wrapper
    return decorator
