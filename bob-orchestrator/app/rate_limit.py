"""Simple in-memory rate limiter — per IP, per endpoint group.

No external dependencies. Sliding window counter.
"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger("bob.ratelimit")


@dataclass
class RateLimit:
    max_requests: int
    window_seconds: int


# Rate limit tiers
LIMITS = {
    "chat": RateLimit(max_requests=10, window_seconds=60),       # 10 req/min — public widget
    "chat_burst": RateLimit(max_requests=60, window_seconds=3600),  # 60 req/hr — prevents sustained abuse
    "api_read": RateLimit(max_requests=60, window_seconds=60),   # 60 req/min — read endpoints
    "api_write": RateLimit(max_requests=30, window_seconds=60),  # 30 req/min — write endpoints
}

# Storage: {(ip, tier): [timestamps]}
_requests: dict[tuple[str, str], list[float]] = defaultdict(list)

# IPs that bypass rate limiting (internal services, Rob's known IPs)
_BYPASS_IPS = {
    "127.0.0.1",
    "172.23.0.1",   # Docker gateway
}


def _cleanup(key: tuple[str, str], window: int):
    """Remove expired timestamps."""
    cutoff = time.time() - window
    _requests[key] = [t for t in _requests[key] if t > cutoff]


def check_rate_limit(ip: str, tier: str) -> tuple[bool, dict]:
    """Check if a request is allowed.

    Returns (allowed, info) where info has remaining/limit/retry_after.
    """
    if ip in _BYPASS_IPS:
        return True, {"remaining": -1, "limit": -1}

    limit = LIMITS.get(tier)
    if not limit:
        return True, {}

    key = (ip, tier)
    _cleanup(key, limit.window_seconds)

    current = len(_requests[key])

    if current >= limit.max_requests:
        retry_after = int(limit.window_seconds - (time.time() - _requests[key][0])) + 1
        logger.warning(f"Rate limited: {ip} on {tier} ({current}/{limit.max_requests})")
        return False, {
            "remaining": 0,
            "limit": limit.max_requests,
            "window": limit.window_seconds,
            "retry_after": max(1, retry_after),
        }

    _requests[key].append(time.time())
    return True, {
        "remaining": limit.max_requests - current - 1,
        "limit": limit.max_requests,
        "window": limit.window_seconds,
    }


def get_client_ip(request) -> str:
    """Extract client IP — respects CF-Connecting-IP and X-Forwarded-For."""
    # Cloudflare sends the real IP
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"
