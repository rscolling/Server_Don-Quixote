"""Webhook firewall — pre-execution security gate for BOB's tools.

Risk levels:
  LOW    — execute immediately, log quietly
  MEDIUM — execute immediately, log prominently
  HIGH   — block, notify Rob, require confirmation within 2 minutes

Adapted from bob-webhook-firewall-plan.md for the LangGraph architecture.
"""

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger("bob.firewall")

# ── Risk levels ──────────────────────────────────────────────────────────────

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Tool risk registry ───────────────────────────────────────────────────────
# Maps BOB's tool names to risk levels

TOOL_REGISTRY = {
    # LOW — read-only, no side effects
    "check_tasks": RiskLevel.LOW,
    "check_agents": RiskLevel.LOW,
    "check_stats": RiskLevel.LOW,
    "poll_messages": RiskLevel.LOW,
    "view_thread": RiskLevel.LOW,
    "recall": RiskLevel.LOW,
    "recall_all": RiskLevel.LOW,

    # MEDIUM — write, recoverable
    "create_task": RiskLevel.MEDIUM,
    "send_message": RiskLevel.MEDIUM,
    "remember": RiskLevel.MEDIUM,
    "notify_rob": RiskLevel.MEDIUM,
}

# HIGH-risk tools can be added here as BOB gains more capabilities:
# "publish_changes": RiskLevel.HIGH,
# "rollback_changes": RiskLevel.HIGH,
# "approve_review": RiskLevel.HIGH,
# "reject_review": RiskLevel.HIGH,


# ── Prompt injection scanner ─────────────────────────────────────────────────

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+a",
    r"system\s*:\s*",
    r"<\s*script\s*>",
    r"javascript\s*:",
    r"\{\{.*\}\}",           # template injection
    r"__import__\s*\(",      # Python code injection
    r"os\.system\s*\(",
    r"subprocess\.",
    r"eval\s*\(",
    r"exec\s*\(",
]

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def scan_for_injection(params: dict) -> str | None:
    """Scan all string values in params for injection patterns. Returns matched pattern or None."""
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        for pattern in _compiled_patterns:
            match = pattern.search(value)
            if match:
                return f"Pattern '{pattern.pattern}' matched in param '{key}': '{match.group()}'"
    return None


# ── Pending confirmations (HIGH risk) ────────────────────────────────────────

@dataclass
class PendingConfirmation:
    confirmation_id: str
    tool_name: str
    params: dict
    queued_at: float = field(default_factory=time.time)
    timeout_seconds: int = 120
    status: str = "pending"  # pending | approved | rejected | expired

    @property
    def expires_at(self) -> float:
        return self.queued_at + self.timeout_seconds

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))


_pending: dict[str, PendingConfirmation] = {}


def queue_confirmation(tool_name: str, params: dict) -> PendingConfirmation:
    conf = PendingConfirmation(
        confirmation_id=str(uuid.uuid4())[:8],
        tool_name=tool_name,
        params=params,
    )
    _pending[conf.confirmation_id] = conf
    return conf


def confirm(confirmation_id: str) -> PendingConfirmation | None:
    conf = _pending.get(confirmation_id)
    if conf and not conf.is_expired:
        conf.status = "approved"
        return conf
    if conf and conf.is_expired:
        conf.status = "expired"
    return conf


def reject(confirmation_id: str) -> PendingConfirmation | None:
    conf = _pending.get(confirmation_id)
    if conf:
        conf.status = "rejected"
    return conf


def get_pending() -> list[PendingConfirmation]:
    # Clean expired
    for cid, conf in list(_pending.items()):
        if conf.is_expired and conf.status == "pending":
            conf.status = "expired"
    return [c for c in _pending.values() if c.status == "pending"]


# ── Audit log ────────────────────────────────────────────────────────────────

AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "/app/data/bob-audit.jsonl")


def write_audit(event: str, tool: str, risk: str, details: dict | None = None):
    """Append one JSON line to the immutable audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "tool": tool,
        "risk": risk,
        "audit_id": str(uuid.uuid4())[:8],
    }
    if details:
        entry["details"] = details
    try:
        Path(AUDIT_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Audit log write failed: {e}")


# ── Main firewall gate ───────────────────────────────────────────────────────

class FirewallDecision(Enum):
    ALLOW = "allow"
    PENDING = "pending"
    DENY_INJECTION = "deny_injection"


@dataclass
class FirewallResult:
    decision: FirewallDecision
    tool_name: str
    risk: RiskLevel | None
    reason: str = ""
    confirmation_id: str | None = None


def gate(tool_name: str, params: dict) -> FirewallResult:
    """
    Main firewall gate. Call before executing any tool.

    Returns FirewallResult. Only execute if decision == ALLOW.
    For PENDING, notify Rob and wait for confirmation.
    """
    risk = TOOL_REGISTRY.get(tool_name)

    # Unknown tools default to MEDIUM (log but allow — BOB's internal tools)
    if risk is None:
        risk = RiskLevel.MEDIUM

    # Scan for injection
    injection = scan_for_injection(params)
    if injection:
        write_audit("deny_injection", tool_name, risk.value, {"pattern": injection})
        logger.warning(f"INJECTION BLOCKED: {tool_name} — {injection}")
        return FirewallResult(
            decision=FirewallDecision.DENY_INJECTION,
            tool_name=tool_name,
            risk=risk,
            reason=f"Prompt injection detected: {injection}",
        )

    # LOW — execute, log quietly
    if risk == RiskLevel.LOW:
        write_audit("allow", tool_name, risk.value)
        return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)

    # MEDIUM — execute, log prominently
    if risk == RiskLevel.MEDIUM:
        write_audit("allow_medium", tool_name, risk.value, {"params_keys": list(params.keys())})
        logger.info(f"MEDIUM tool executed: {tool_name}")
        return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)

    # HIGH — queue for confirmation
    if risk == RiskLevel.HIGH:
        conf = queue_confirmation(tool_name, params)
        write_audit("pending_confirmation", tool_name, risk.value, {
            "confirmation_id": conf.confirmation_id,
            "timeout_seconds": conf.timeout_seconds,
        })
        logger.warning(f"HIGH tool queued: {tool_name} — confirmation_id={conf.confirmation_id}")
        return FirewallResult(
            decision=FirewallDecision.PENDING,
            tool_name=tool_name,
            risk=risk,
            confirmation_id=conf.confirmation_id,
            reason=f"HIGH risk. Confirmation required within {conf.timeout_seconds}s. ID: {conf.confirmation_id}",
        )

    return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)
