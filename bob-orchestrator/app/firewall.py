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
    "check_email": RiskLevel.LOW,
    "check_voice_usage": RiskLevel.LOW,
    "check_system_health": RiskLevel.LOW,
    "check_server_resources": RiskLevel.LOW,
    "email_mark_read": RiskLevel.MEDIUM,
    "email_archive": RiskLevel.MEDIUM,
    "email_add_label": RiskLevel.MEDIUM,
    "email_list_labels": RiskLevel.LOW,
    "add_scheduled_job": RiskLevel.MEDIUM,
    "remove_scheduled_job": RiskLevel.MEDIUM,
    "trigger_job_now": RiskLevel.MEDIUM,
    "generate_daily_briefing": RiskLevel.LOW,
    "check_paused_tasks": RiskLevel.LOW,
    "dismiss_paused_task": RiskLevel.MEDIUM,
    "delegate_task": RiskLevel.MEDIUM,
    "propose_memory": RiskLevel.MEDIUM,
    "review_pending_proposals": RiskLevel.LOW,
    "approve_proposal": RiskLevel.MEDIUM,
    "reject_proposal": RiskLevel.MEDIUM,
    "check_confirmation": RiskLevel.LOW,
    "list_scheduled_jobs": RiskLevel.LOW,
    "pause_scheduled_job": RiskLevel.MEDIUM,
    "resume_scheduled_job": RiskLevel.MEDIUM,

    # HIGH-risk tools — require Rob's confirmation before execution
    # Uncomment as BOB gains these capabilities:
    # "publish_changes": RiskLevel.HIGH,
    # "rollback_changes": RiskLevel.HIGH,
    # "approve_review": RiskLevel.HIGH,
    # "reject_review": RiskLevel.HIGH,
}


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
    # Clean expired and remove old entries
    stale = []
    for cid, conf in list(_pending.items()):
        if conf.is_expired and conf.status == "pending":
            conf.status = "expired"
        # Remove entries older than 2x timeout (cleanup)
        if time.time() - conf.queued_at > conf.timeout_seconds * 2:
            stale.append(cid)
    for cid in stale:
        del _pending[cid]
    return [c for c in _pending.values() if c.status == "pending"]


# ── Audit log ────────────────────────────────────────────────────────────────

from app.config import AUDIT_LOG_PATH
AUDIT_LOG_MAX_SIZE = int(os.getenv("AUDIT_LOG_MAX_SIZE_MB", "10")) * 1024 * 1024  # 10MB default
AUDIT_LOG_ROTATE_COUNT = 3  # Keep 3 rotated logs


def _rotate_audit_log():
    """Rotate audit log if it exceeds max size."""
    try:
        log_path = Path(AUDIT_LOG_PATH)
        if not log_path.exists():
            return
        if log_path.stat().st_size < AUDIT_LOG_MAX_SIZE:
            return

        # Rotate: .jsonl.2 → .jsonl.3, .jsonl.1 → .jsonl.2, .jsonl → .jsonl.1
        for i in range(AUDIT_LOG_ROTATE_COUNT, 0, -1):
            old = Path(f"{AUDIT_LOG_PATH}.{i}")
            new = Path(f"{AUDIT_LOG_PATH}.{i + 1}")
            if old.exists():
                if i == AUDIT_LOG_ROTATE_COUNT:
                    old.unlink()  # Delete oldest
                else:
                    old.rename(new)

        log_path.rename(Path(f"{AUDIT_LOG_PATH}.1"))
        logger.info("Audit log rotated")
    except Exception as e:
        logger.error(f"Audit log rotation failed: {e}")


def write_audit(event: str, tool: str, risk: str, details: dict | None = None):
    """Append one JSON line to the audit log. Auto-rotates at max size."""
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
        _rotate_audit_log()
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
