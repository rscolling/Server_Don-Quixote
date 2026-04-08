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
    "analyze_photo": RiskLevel.MEDIUM,
    "list_recent_photos": RiskLevel.LOW,
    "upload_photo": RiskLevel.MEDIUM,
    "get_weather": RiskLevel.LOW,
    "search_web": RiskLevel.LOW,
    # Promotion gate tools (added 2026-04-08)
    "list_pending_promotions": RiskLevel.LOW,
    "get_promotion_details": RiskLevel.LOW,
    "get_promotion_diff": RiskLevel.LOW,
    "approve_promotion": RiskLevel.HIGH,
    "reject_promotion": RiskLevel.MEDIUM,

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




def find_approved_confirmation(tool_name: str, params: dict):
    """Return an approved (non-expired) confirmation matching this exact (tool, params).

    Used by the HIGH-risk gate to honor a prior approval instead of queueing a fresh
    confirmation on every retry. Match is by tool name + canonical-JSON of params.
    Once consumed, the entry is marked 'consumed' so it cannot be replayed.
    """
    try:
        target_key = json.dumps(params, sort_keys=True, default=str)
    except Exception:
        target_key = str(params)
    for conf in list(_pending.values()):
        if conf.tool_name != tool_name:
            continue
        if conf.status != 'approved':
            continue
        if conf.is_expired:
            continue
        try:
            existing_key = json.dumps(conf.params, sort_keys=True, default=str)
        except Exception:
            existing_key = str(conf.params)
        if existing_key == target_key:
            return conf
    return None


def consume_confirmation(conf):
    """Mark an approved confirmation as consumed so it can't be replayed."""
    conf.status = 'consumed'

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


# Keys whose values must NEVER be written to the audit log
_SECRET_PARAM_KEYS = {
    "api_key", "apikey", "token", "secret", "password", "passwd",
    "credential", "credentials", "auth", "authorization",
    "private_key", "client_secret", "access_token",
}


def _sanitize_params(params: dict | None) -> dict | None:
    """Strip secret-shaped keys before audit logging."""
    if not params:
        return params
    safe = {}
    for k, v in params.items():
        if any(s in k.lower() for s in _SECRET_PARAM_KEYS):
            safe[k] = "[REDACTED]"
        elif isinstance(v, dict):
            safe[k] = _sanitize_params(v)
        elif isinstance(v, str) and len(v) > 2000:
            # Truncate very long strings to keep the audit log manageable
            safe[k] = v[:2000] + f"...[truncated {len(v)} bytes]"
        else:
            safe[k] = v
    return safe


def write_audit(event: str, tool: str, risk: str, details: dict | None = None,
                params: dict | None = None):
    """Append one JSON line to the audit log. Auto-rotates at max size.

    Args:
        event:   The decision (allow, allow_medium, deny_injection, etc.)
        tool:    The tool name
        risk:    The risk level
        details: Free-form structured info (loop signal, confirmation id, etc.)
        params:  The actual parameters the tool was called with. Stored
                 sanitized (secrets redacted, long values truncated) so the
                 replay tool can deterministically re-run a past call.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "tool": tool,
        "risk": risk,
        "audit_id": str(uuid.uuid4())[:8],
    }
    if details:
        entry["details"] = details
    if params is not None:
        entry["params"] = _sanitize_params(params)
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
    DENY_LOOP = "deny_loop"


@dataclass
class FirewallResult:
    decision: FirewallDecision
    tool_name: str
    risk: RiskLevel | None
    reason: str = ""
    confirmation_id: str | None = None
    loop_signal: dict | None = None


def gate(tool_name: str, params: dict, thread_id: str = "default") -> FirewallResult:
    """
    Main firewall gate. Call before executing any tool.

    Returns FirewallResult. Only execute if decision == ALLOW.
    For PENDING, notify Rob and wait for confirmation.
    For DENY_LOOP, the loop detector tripped — abort the run.
    """
    risk = TOOL_REGISTRY.get(tool_name)

    # Unknown tools default to MEDIUM (log but allow — BOB's internal tools)
    if risk is None:
        risk = RiskLevel.MEDIUM

    # Scan for injection
    injection = scan_for_injection(params)
    if injection:
        write_audit("deny_injection", tool_name, risk.value,
                    {"pattern": injection}, params=params)
        logger.warning(f"INJECTION BLOCKED: {tool_name} — {injection}")
        return FirewallResult(
            decision=FirewallDecision.DENY_INJECTION,
            tool_name=tool_name,
            risk=risk,
            reason=f"Prompt injection detected: {injection}",
        )

    # Loop detection — deterministic, not vibes-based
    try:
        from app import loop_detector
        args_signature = json.dumps(params, sort_keys=True, default=str)[:500]
        loop_signal = loop_detector.record_tool_call(thread_id, tool_name, args_signature)
        if loop_signal:
            write_audit("deny_loop", tool_name, risk.value, loop_signal, params=params)
            logger.error(f"LOOP DETECTED: {tool_name} — {loop_signal['details']}")
            return FirewallResult(
                decision=FirewallDecision.DENY_LOOP,
                tool_name=tool_name,
                risk=risk,
                reason=loop_signal["details"],
                loop_signal=loop_signal,
            )
    except Exception as e:
        logger.warning(f"Loop detector error (non-fatal): {e}")

    # LOW — execute, log quietly (params recorded for replay)
    if risk == RiskLevel.LOW:
        write_audit("allow", tool_name, risk.value, params=params)
        return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)

    # MEDIUM — execute, log prominently (params recorded for replay)
    if risk == RiskLevel.MEDIUM:
        write_audit("allow_medium", tool_name, risk.value,
                    {"params_keys": list(params.keys())}, params=params)
        logger.info(f"MEDIUM tool executed: {tool_name}")
        return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)

    # HIGH — queue for confirmation, unless an approved confirmation already exists
    if risk == RiskLevel.HIGH:
        prior = find_approved_confirmation(tool_name, params)
        if prior is not None:
            consume_confirmation(prior)
            write_audit('allow_confirmed', tool_name, risk.value, {
                'confirmation_id': prior.confirmation_id,
                'consumed': True,
            }, params=params)
            logger.warning(f'HIGH tool executed via prior confirmation: {tool_name} '
                           f'(confirmation_id={prior.confirmation_id})')
            return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)
        conf = queue_confirmation(tool_name, params)
        write_audit("pending_confirmation", tool_name, risk.value, {
            "confirmation_id": conf.confirmation_id,
            "timeout_seconds": conf.timeout_seconds,
        }, params=params)
        logger.warning(f"HIGH tool queued: {tool_name} — confirmation_id={conf.confirmation_id}")
        return FirewallResult(
            decision=FirewallDecision.PENDING,
            tool_name=tool_name,
            risk=risk,
            confirmation_id=conf.confirmation_id,
            reason=f"HIGH risk. Confirmation required within {conf.timeout_seconds}s. ID: {conf.confirmation_id}",
        )

    return FirewallResult(decision=FirewallDecision.ALLOW, tool_name=tool_name, risk=risk)
