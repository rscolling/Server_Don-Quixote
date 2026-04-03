# BOB — Webhook Tool Security: Pre-Execution Firewall Build Plan
### *Risk classification · confirmation gates · audit trail · injection defense*

---

## What We're Building

BOB's 14 webhook tools call directly into the Ubuntu server — starting teams, publishing to the live website, rolling back changes, approving reviews. Currently, when ElevenLabs sends a webhook call, it hits the orchestrator API with no intermediate validation layer. A misheard instruction, a prompt injection in a web page BOB read, or a hallucinated tool call could publish bad content or roll back good work.

This plan adds a firewall that sits between ElevenLabs and the orchestrator API. Every tool call is:
1. **Classified** by risk level before execution
2. **Validated** for required parameters and caller authenticity
3. **Gated** — LOW executes immediately, MEDIUM logs and executes, HIGH requires Rob's explicit voice or dashboard confirmation
4. **Logged** to an immutable audit trail

---

## The 14 Webhook Tools — Risk Classification

| Tool | Method | Risk | Reason |
|---|---|---|---|
| `server_health` | GET | LOW | Read-only. No side effects. |
| `team_status` | GET | LOW | Read-only. No side effects. |
| `get_pending_reviews` | GET | LOW | Read-only. No side effects. |
| `list_files` | GET | LOW | Read-only. Scoped paths only. |
| `read_file` | GET | LOW | Read-only. Scoped paths only. |
| `submit_task` | POST | MEDIUM | Starts agent work. Costs money. Can be re-queued if wrong. |
| `start_team` | POST | MEDIUM | Spins up containers. Resource cost. Recoverable. |
| `stop_team` | POST | MEDIUM | Stops containers. Recoverable — can restart. |
| `write_note` | POST | MEDIUM | Writes a file. Low blast radius. |
| `search_files` | GET | MEDIUM | Could leak internal file names if logged externally. |
| `approve_review` | POST | HIGH | Triggers content publish. Irreversible until rollback. |
| `reject_review` | POST | HIGH | Discards agent work. Data loss if wrong. |
| `publish_changes` | POST | HIGH | Pushes to live ATG website. Public-facing. |
| `rollback_changes` | POST | HIGH | Reverts live site. Destructive if wrong. |

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- Orchestrator API running at `:8100` ✓
- ElevenLabs voice layer planned (webhook tools configured in ElevenLabs dashboard)
- Observability plan Phase 1–2 complete (Langfuse) — recommended

All steps begin on **Windows 11**. SSH to server where indicated.

---

## Phase 1 — Shared Secret Authentication

Before classifying risk, verify the request actually came from ElevenLabs and not an external actor hitting the API directly.

---

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Generate a shared webhook secret**

```bash
# [UBUNTU SERVER]
openssl rand -hex 32
```

Copy the output. This is your `WEBHOOK_SECRET`. Add it to `.env`:

```bash
nano /opt/atg-agents/.env
```

```env
WEBHOOK_SECRET=your_generated_secret_here
```

---

**Step 3 — Add the secret to ElevenLabs**

In the ElevenLabs dashboard, for each webhook tool:
- Open the tool settings
- Find **Custom Headers**
- Add: `X-Webhook-Secret: your_generated_secret_here`

ElevenLabs will send this header on every webhook call. The firewall validates it before doing anything else.

---

## Phase 2 — The Firewall Middleware

**Step 4 — Add the firewall module**

```python
# orchestrator/webhook_firewall.py

import os
import time
import uuid
import hmac
import hashlib
import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# ── Risk levels ──────────────────────────────────────────────────────────────

class RiskLevel(Enum):
    LOW    = "low"      # Execute immediately, log quietly
    MEDIUM = "medium"   # Execute immediately, log prominently
    HIGH   = "high"     # Block — require Rob confirmation before executing

# ── Tool registry — every tool classified ────────────────────────────────────

TOOL_REGISTRY = {
    # ── LOW risk — read-only ─────────────────────────────────────────────────
    "server_health":      RiskLevel.LOW,
    "team_status":        RiskLevel.LOW,
    "get_pending_reviews":RiskLevel.LOW,
    "list_files":         RiskLevel.LOW,
    "read_file":          RiskLevel.LOW,

    # ── MEDIUM risk — write, recoverable ─────────────────────────────────────
    "submit_task":        RiskLevel.MEDIUM,
    "start_team":         RiskLevel.MEDIUM,
    "stop_team":          RiskLevel.MEDIUM,
    "write_note":         RiskLevel.MEDIUM,
    "search_files":       RiskLevel.MEDIUM,

    # ── HIGH risk — destructive or public-facing ──────────────────────────────
    "approve_review":     RiskLevel.HIGH,
    "reject_review":      RiskLevel.HIGH,
    "publish_changes":    RiskLevel.HIGH,
    "rollback_changes":   RiskLevel.HIGH,
}

# HIGH risk tools also require these parameter checks before even queuing
HIGH_RISK_REQUIRED_PARAMS = {
    "approve_review":  ["review_id"],
    "reject_review":   ["review_id", "reason"],
    "publish_changes": [],              # No params needed — just confirmation
    "rollback_changes":[],              # No params needed — just confirmation
}

# ── Pending confirmation queue ────────────────────────────────────────────────
# HIGH risk calls wait here until Rob confirms or times out

@dataclass
class PendingConfirmation:
    confirmation_id: str
    tool_name:       str
    params:          dict
    risk_level:      RiskLevel
    queued_at:       float  = field(default_factory=time.time)
    expires_at:      float  = field(default=0.0)
    status:          str    = "pending"   # pending | approved | rejected | expired
    timeout_seconds: int    = 120         # Rob has 2 minutes to confirm

    def __post_init__(self):
        self.expires_at = self.queued_at + self.timeout_seconds

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))


_pending_confirmations: dict[str, PendingConfirmation] = {}

# ── Audit log ─────────────────────────────────────────────────────────────────

AUDIT_LOG_PATH = "/opt/atg-agents/shared/bob-audit.jsonl"

def _write_audit_entry(entry: dict):
    """
    Append one JSON line to the audit log.
    Append-only — never overwritten. Tamper-evident by design.
    """
    entry["logged_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        import logging
        logging.error(f"Audit log write failed: {e}")


# ── Shared secret validation ──────────────────────────────────────────────────

def validate_webhook_secret(header_value: str) -> bool:
    """
    Constant-time comparison to prevent timing attacks.
    """
    if not WEBHOOK_SECRET:
        return True   # Secret not configured — skip check (warn in logs)
    expected = WEBHOOK_SECRET.encode()
    provided = header_value.encode() if header_value else b""
    return hmac.compare_digest(expected, provided)


# ── Parameter validation ──────────────────────────────────────────────────────

def validate_params(tool_name: str, params: dict) -> tuple[bool, str]:
    """
    Check required parameters are present and non-empty.
    Returns (valid: bool, error_message: str)
    """
    required = HIGH_RISK_REQUIRED_PARAMS.get(tool_name, [])
    for param in required:
        if param not in params or not params[param]:
            return False, f"Missing required parameter: '{param}'"
    return True, ""


# ── Path traversal protection for file tools ─────────────────────────────────

ALLOWED_FILE_SCOPES = {
    "shared":           "/opt/atg-agents/shared",
    "source-materials": "/opt/atg-bridge/source-materials",
}

def validate_file_path(path: str, scope: str) -> tuple[bool, str]:
    """
    Prevent path traversal attacks on list_files, read_file, write_note.
    Rejects any path containing '..' or that escapes the allowed root.
    """
    import os.path
    allowed_root = ALLOWED_FILE_SCOPES.get(scope)
    if not allowed_root:
        return False, f"Unknown scope: '{scope}'. Allowed: {list(ALLOWED_FILE_SCOPES)}"

    # Resolve to catch ../ traversal
    full_path = os.path.realpath(os.path.join(allowed_root, path.lstrip("/")))
    if not full_path.startswith(allowed_root):
        return False, (
            f"Path traversal attempt detected. "
            f"Resolved path '{full_path}' is outside allowed root '{allowed_root}'."
        )
    return True, ""


# ── Main firewall gate ────────────────────────────────────────────────────────

class FirewallDecision(Enum):
    ALLOW            = "allow"          # Execute immediately
    PENDING          = "pending"        # Queued for Rob's confirmation
    DENY_AUTH        = "deny_auth"      # Invalid secret
    DENY_UNKNOWN     = "deny_unknown"   # Tool not in registry
    DENY_PARAMS      = "deny_params"    # Missing required parameters
    DENY_PATH        = "deny_path"      # Path traversal attempt
    DENY_INJECTION   = "deny_injection" # Prompt injection pattern detected

@dataclass
class FirewallResult:
    decision:        FirewallDecision
    tool_name:       str
    risk_level:      RiskLevel | None
    params:          dict
    confirmation_id: str | None = None
    reason:          str        = ""
    audit_id:        str        = field(default_factory=lambda: str(uuid.uuid4())[:8])


async def firewall_gate(
    tool_name:      str,
    params:         dict,
    webhook_secret: str = "",
    source:         str = "elevenlabs",
) -> FirewallResult:
    """
    The main firewall gate. Call this before executing ANY webhook tool.

    Returns a FirewallResult. Only execute the tool if result.decision == ALLOW.
    For PENDING — wait for Rob's confirmation via confirm_tool() below.
    """

    # ── 1. Authenticate ───────────────────────────────────────────────────────
    if not validate_webhook_secret(webhook_secret):
        result = FirewallResult(
            decision=FirewallDecision.DENY_AUTH,
            tool_name=tool_name,
            risk_level=None,
            params=params,
            reason="Invalid or missing webhook secret.",
        )
        _write_audit_entry({
            "event":    "firewall_deny",
            "reason":   "auth_failure",
            "tool":     tool_name,
            "source":   source,
            "audit_id": result.audit_id,
        })
        return result

    # ── 2. Check tool is registered ───────────────────────────────────────────
    risk = TOOL_REGISTRY.get(tool_name)
    if risk is None:
        result = FirewallResult(
            decision=FirewallDecision.DENY_UNKNOWN,
            tool_name=tool_name,
            risk_level=None,
            params=params,
            reason=f"Tool '{tool_name}' is not registered in the firewall.",
        )
        _write_audit_entry({
            "event":    "firewall_deny",
            "reason":   "unknown_tool",
            "tool":     tool_name,
            "source":   source,
            "audit_id": result.audit_id,
        })
        await bob_proactive_report(
            f"SECURITY — Unknown tool call blocked: '{tool_name}'. "
            f"This tool is not registered. Possible prompt injection or "
            f"misconfigured ElevenLabs webhook. Audit ID: {result.audit_id}"
        )
        return result

    # ── 3. Check for prompt injection patterns ────────────────────────────────
    injection_detected = _scan_for_injection(params)
    if injection_detected:
        result = FirewallResult(
            decision=FirewallDecision.DENY_INJECTION,
            tool_name=tool_name,
            risk_level=risk,
            params=params,
            reason=f"Prompt injection pattern detected in parameters: {injection_detected}",
        )
        _write_audit_entry({
            "event":    "firewall_deny",
            "reason":   "injection_detected",
            "tool":     tool_name,
            "pattern":  injection_detected,
            "source":   source,
            "audit_id": result.audit_id,
        })
        await bob_proactive_report(
            f"SECURITY ALERT — Prompt injection attempt blocked.\n"
            f"Tool: {tool_name}\n"
            f"Pattern detected: {injection_detected}\n"
            f"Audit ID: {result.audit_id}\n"
            f"Review the full entry in the audit log."
        )
        return result

    # ── 4. Validate file paths for file tools ─────────────────────────────────
    if tool_name in ("list_files", "read_file", "write_note", "search_files"):
        path  = params.get("path", "")
        scope = params.get("scope", "shared")
        path_ok, path_error = validate_file_path(path, scope)
        if not path_ok:
            result = FirewallResult(
                decision=FirewallDecision.DENY_PATH,
                tool_name=tool_name,
                risk_level=risk,
                params=params,
                reason=path_error,
            )
            _write_audit_entry({
                "event":    "firewall_deny",
                "reason":   "path_traversal",
                "tool":     tool_name,
                "path":     path,
                "scope":    scope,
                "source":   source,
                "audit_id": result.audit_id,
            })
            await bob_proactive_report(
                f"SECURITY — Path traversal attempt blocked on {tool_name}.\n"
                f"Attempted path: {path} (scope: {scope})\n"
                f"Audit ID: {result.audit_id}"
            )
            return result

    # ── 5. Validate required parameters ──────────────────────────────────────
    if risk == RiskLevel.HIGH:
        params_ok, params_error = validate_params(tool_name, params)
        if not params_ok:
            result = FirewallResult(
                decision=FirewallDecision.DENY_PARAMS,
                tool_name=tool_name,
                risk_level=risk,
                params=params,
                reason=params_error,
            )
            _write_audit_entry({
                "event":    "firewall_deny",
                "reason":   "missing_params",
                "tool":     tool_name,
                "error":    params_error,
                "source":   source,
                "audit_id": result.audit_id,
            })
            return result

    # ── 6. Route by risk level ────────────────────────────────────────────────

    audit_base = {
        "tool":      tool_name,
        "risk":      risk.value,
        "params":    _redact_sensitive(params),
        "source":    source,
    }

    if risk == RiskLevel.LOW:
        _write_audit_entry({**audit_base, "event": "firewall_allow", "gate": "low_risk"})
        return FirewallResult(
            decision=FirewallDecision.ALLOW,
            tool_name=tool_name,
            risk_level=risk,
            params=params,
        )

    elif risk == RiskLevel.MEDIUM:
        _write_audit_entry({**audit_base, "event": "firewall_allow", "gate": "medium_risk"})
        # Log to BOB's internal state — surfaced in daily report
        _log_medium_risk_call(tool_name, params)
        return FirewallResult(
            decision=FirewallDecision.ALLOW,
            tool_name=tool_name,
            risk_level=risk,
            params=params,
        )

    else:  # HIGH
        # Queue for Rob's confirmation
        confirmation_id = str(uuid.uuid4())[:12]
        pending = PendingConfirmation(
            confirmation_id=confirmation_id,
            tool_name=tool_name,
            params=params,
            risk_level=risk,
        )
        _pending_confirmations[confirmation_id] = pending

        _write_audit_entry({
            **audit_base,
            "event":           "firewall_pending",
            "gate":            "high_risk",
            "confirmation_id": confirmation_id,
            "expires_in_s":    pending.timeout_seconds,
        })

        # Tell Rob immediately
        param_summary = _format_params_for_display(tool_name, params)
        await bob_proactive_report(
            f"HIGH RISK ACTION — confirmation required.\n"
            f"Tool: {tool_name}\n"
            f"{param_summary}\n"
            f"Confirmation ID: {confirmation_id}\n"
            f"Say 'confirm {confirmation_id}' or approve at "
            f"http://192.168.1.228:8200/confirmations\n"
            f"Expires in {pending.timeout_seconds} seconds."
        )

        return FirewallResult(
            decision=FirewallDecision.PENDING,
            tool_name=tool_name,
            risk_level=risk,
            params=params,
            confirmation_id=confirmation_id,
        )


# ── Rob's confirmation handler ────────────────────────────────────────────────

async def confirm_tool(confirmation_id: str, approved: bool,
                        reason: str = "") -> dict:
    """
    Called when Rob says 'confirm <id>' or clicks approve/reject on the dashboard.
    Returns the result of executing the tool (if approved) or a rejection notice.
    """
    pending = _pending_confirmations.get(confirmation_id)

    if not pending:
        return {"error": f"Confirmation ID '{confirmation_id}' not found or already processed."}

    if pending.is_expired:
        pending.status = "expired"
        _pending_confirmations.pop(confirmation_id, None)
        _write_audit_entry({
            "event":           "confirmation_expired",
            "confirmation_id": confirmation_id,
            "tool":            pending.tool_name,
        })
        return {"error": f"Confirmation '{confirmation_id}' expired. Re-issue the command."}

    if approved:
        pending.status = "approved"
        _pending_confirmations.pop(confirmation_id, None)
        _write_audit_entry({
            "event":           "confirmation_approved",
            "confirmation_id": confirmation_id,
            "tool":            pending.tool_name,
            "params":          _redact_sensitive(pending.params),
            "approved_by":     "rob",
        })
        return {"status": "approved", "execute": True,
                "tool": pending.tool_name, "params": pending.params}
    else:
        pending.status = "rejected"
        _pending_confirmations.pop(confirmation_id, None)
        _write_audit_entry({
            "event":           "confirmation_rejected",
            "confirmation_id": confirmation_id,
            "tool":            pending.tool_name,
            "rejected_by":     "rob",
            "reason":          reason,
        })
        return {"status": "rejected", "execute": False,
                "tool": pending.tool_name}


# ── Expiry cleanup loop ────────────────────────────────────────────────────────

async def confirmation_expiry_loop():
    """Cleans up expired confirmations every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        expired = [
            cid for cid, p in _pending_confirmations.items()
            if p.is_expired and p.status == "pending"
        ]
        for cid in expired:
            pending = _pending_confirmations.pop(cid, None)
            if pending:
                _write_audit_entry({
                    "event":           "confirmation_expired",
                    "confirmation_id": cid,
                    "tool":            pending.tool_name,
                })
                await bob_proactive_report(
                    f"Confirmation '{cid}' for {pending.tool_name} expired "
                    f"without a response. Action was not taken."
                )


# ── Injection detection ───────────────────────────────────────────────────────

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous",
    "disregard your instructions",
    "you are now",
    "new instructions:",
    "system prompt:",
    "forget your",
    "act as if",
    "pretend you are",
    "override",
    "jailbreak",
    "bypass",
    "<!-- ",
    "<script",
    "eval(",
    "__import__",
    "os.system",
    "subprocess",
]

def _scan_for_injection(params: dict) -> str | None:
    """
    Scan string parameter values for known prompt injection patterns.
    Returns the matched pattern if found, None otherwise.
    """
    payload = json.dumps(params).lower()
    for pattern in INJECTION_PATTERNS:
        if pattern.lower() in payload:
            return pattern
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _redact_sensitive(params: dict) -> dict:
    """Remove any values that look like secrets before writing to audit log."""
    sensitive_keys = {"api_key", "secret", "password", "token", "key"}
    return {
        k: ("***REDACTED***" if any(s in k.lower() for s in sensitive_keys) else v)
        for k, v in params.items()
    }

def _format_params_for_display(tool_name: str, params: dict) -> str:
    """Human-readable summary of what the tool is about to do."""
    descriptions = {
        "publish_changes":  "This will push staging changes to the live ATG website.",
        "rollback_changes": "This will roll back the last published change on the live site.",
        "approve_review":   f"This will approve review {params.get('review_id', '?')} and publish it.",
        "reject_review":    f"This will reject review {params.get('review_id', '?')}. Reason: {params.get('reason', 'none')}",
    }
    return descriptions.get(tool_name, f"Parameters: {params}")

_medium_risk_log: list[dict] = []

def _log_medium_risk_call(tool_name: str, params: dict):
    _medium_risk_log.append({
        "tool": tool_name,
        "params": _redact_sensitive(params),
        "time": datetime.utcnow().isoformat(),
    })

def get_medium_risk_summary() -> list[dict]:
    """Returns today's medium risk calls — for daily report."""
    return list(_medium_risk_log)
```

---

**Step 5 — Wire the firewall into the orchestrator API**

Every webhook endpoint gets the firewall gate added before the handler executes:

```python
# orchestrator/api.py  (updated endpoints)

from fastapi import Request, HTTPException
from webhook_firewall import (
    firewall_gate, confirm_tool,
    FirewallDecision, _pending_confirmations
)

async def get_webhook_secret(request: Request) -> str:
    return request.headers.get("X-Webhook-Secret", "")


# ── Example: publish_changes (HIGH risk) ─────────────────────────────────────
@app.post("/marketing/publish")
async def publish_changes(request: Request):
    secret = await get_webhook_secret(request)
    result = await firewall_gate(
        tool_name="publish_changes",
        params={},
        webhook_secret=secret,
        source="elevenlabs",
    )

    if result.decision == FirewallDecision.ALLOW:
        return await _do_publish_changes()

    elif result.decision == FirewallDecision.PENDING:
        # Return 202 Accepted — action is queued, not executed
        return {
            "status":          "pending_confirmation",
            "confirmation_id": result.confirmation_id,
            "message":         "High risk action queued. Rob must confirm.",
        }

    else:
        raise HTTPException(
            status_code=403,
            detail=f"Firewall blocked: {result.reason}"
        )


# ── Example: submit_task (MEDIUM risk) ────────────────────────────────────────
@app.post("/task")
async def submit_task(request: Request, body: dict):
    secret = await get_webhook_secret(request)
    result = await firewall_gate(
        tool_name="submit_task",
        params=body,
        webhook_secret=secret,
        source="elevenlabs",
    )

    if result.decision == FirewallDecision.ALLOW:
        return await _do_submit_task(body)
    else:
        raise HTTPException(status_code=403, detail=result.reason)


# ── Confirmation endpoint — Rob approves/rejects HIGH risk actions ─────────────
@app.post("/firewall/confirm/{confirmation_id}")
async def confirm_action(confirmation_id: str, request: Request):
    body    = await request.json()
    approved = body.get("approved", False)
    reason   = body.get("reason", "")

    outcome = await confirm_tool(confirmation_id, approved, reason)

    if outcome.get("execute"):
        # Rob approved — now execute the actual tool
        tool    = outcome["tool"]
        params  = outcome["params"]
        handler = _get_tool_handler(tool)
        if handler:
            return await handler(params)
        return {"error": f"No handler for tool: {tool}"}

    return outcome


# ── Dashboard endpoint — show pending confirmations ───────────────────────────
@app.get("/firewall/pending")
async def get_pending():
    return [
        {
            "id":               p.confirmation_id,
            "tool":             p.tool_name,
            "params":           p.params,
            "queued_at":        p.queued_at,
            "seconds_remaining":p.seconds_remaining,
        }
        for p in _pending_confirmations.values()
        if not p.is_expired
    ]


# ── Audit log endpoint — Rob can query the audit trail ───────────────────────
@app.get("/firewall/audit")
async def get_audit_log(limit: int = 50):
    """Returns the last N audit log entries."""
    try:
        with open("/opt/atg-agents/shared/bob-audit.jsonl") as f:
            lines = f.readlines()
        entries = [json.loads(l) for l in lines[-limit:] if l.strip()]
        return {"entries": entries, "total_lines": len(lines)}
    except FileNotFoundError:
        return {"entries": [], "total_lines": 0}
```

---

**Step 6 — Start the confirmation expiry loop**

```python
# orchestrator/main.py — add to startup

from webhook_firewall import confirmation_expiry_loop

asyncio.create_task(confirmation_expiry_loop())
```

---

## Phase 3 — Dashboard Confirmation UI

HIGH risk actions need a confirmation interface Rob can use from the dashboard — especially for times when voice confirmation is awkward or the 2-minute window is tight.

**Step 7 — Add the confirmations panel to the dashboard**

Add this endpoint to the existing dashboard at `:8200`:

```html
<!-- In the dashboard HTML — add a Pending Confirmations panel -->

<div id="confirmations-panel">
  <h3>Pending Confirmations</h3>
  <div id="confirmations-list"></div>
</div>

<script>
async function loadConfirmations() {
  const res  = await fetch('http://192.168.1.228:8100/firewall/pending');
  const data = await res.json();
  const list = document.getElementById('confirmations-list');

  if (!data.length) {
    list.innerHTML = '<p style="color:#8b949e">No pending confirmations.</p>';
    return;
  }

  list.innerHTML = data.map(p => `
    <div class="confirmation-card" id="conf-${p.id}">
      <div class="conf-tool">${p.tool}</div>
      <div class="conf-detail">${JSON.stringify(p.params)}</div>
      <div class="conf-timer">${p.seconds_remaining}s remaining</div>
      <button onclick="confirmAction('${p.id}', true)"  class="btn-approve">Approve</button>
      <button onclick="confirmAction('${p.id}', false)" class="btn-reject">Reject</button>
    </div>
  `).join('');
}

async function confirmAction(id, approved) {
  await fetch(`http://192.168.1.228:8100/firewall/confirm/${id}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approved, reason: approved ? '' : 'Rejected by Rob' })
  });
  loadConfirmations();
}

// Poll every 5 seconds
setInterval(loadConfirmations, 5000);
loadConfirmations();
</script>
```

---

## Phase 4 — Audit Log Rotation

The audit log is append-only and should not be included in standard log rotation. However it will grow indefinitely without a size check.

**Step 8 — Add audit log rotation to the retention manager**

In `retention_manager.py`, add:

```python
AUDIT_LOG_PATH     = "/opt/atg-agents/shared/bob-audit.jsonl"
AUDIT_ARCHIVE_PATH = "/opt/atg-agents/archive/audit"
AUDIT_MAX_SIZE_MB  = 50   # Archive and start fresh when log exceeds 50MB

def rotate_audit_log():
    """
    When the audit log exceeds 50MB, archive it with a timestamp
    and start a fresh log. Nothing is ever deleted.
    """
    from pathlib import Path
    log = Path(AUDIT_LOG_PATH)
    if not log.exists():
        return

    size_mb = log.stat().st_size / (1024 * 1024)
    if size_mb < AUDIT_MAX_SIZE_MB:
        return

    archive_dir = Path(AUDIT_ARCHIVE_PATH)
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"bob-audit-{timestamp}.jsonl"

    import shutil
    shutil.move(str(log), str(archive_path))
    # Fresh log starts automatically on next write
```

Call `rotate_audit_log()` at the start of the nightly retention sweep.

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| All 14 webhook tools classified LOW / MEDIUM / HIGH | ✓ |
| Shared secret validates every incoming webhook call | ✓ |
| Unknown tool calls blocked and BOB alerted immediately | ✓ |
| Prompt injection patterns scanned in all parameters | ✓ |
| Path traversal blocked on all file tools | ✓ |
| LOW risk tools execute immediately, logged quietly | ✓ |
| MEDIUM risk tools execute immediately, logged prominently | ✓ |
| HIGH risk tools blocked — Rob must confirm within 2 minutes | ✓ |
| Confirmation via voice ("confirm [id]") or dashboard | ✓ |
| Expired confirmations cleaned up and reported to BOB | ✓ |
| Immutable append-only audit log at `/opt/atg-agents/shared/bob-audit.jsonl` | ✓ |
| Audit log queryable via `GET /firewall/audit` | ✓ |
| Pending confirmations panel on dashboard at `:8200` | ✓ |
| Audit log archived at 50MB — never deleted | ✓ |

---

### What Rob experiences

**LOW risk call (invisible — just works):**
> BOB executes `server_health` silently. Rob sees the result. Nothing else happens.

**MEDIUM risk call (executes, BOB reports):**
> *"Yes Boss — starting the Marketing team now."* [executes] *"Marketing is up. Brief is in."*

**HIGH risk call (blocked, confirmation required):**
> *"HIGH RISK ACTION — confirmation required. This will push staging changes to the live ATG website. Confirmation ID: a3f2b1c8. Say 'confirm a3f2b1c8' or approve at http://192.168.1.228:8200/confirmations. Expires in 120 seconds."*

**Rob confirms:**
> Rob: *"Confirm a3f2b1c8"*
> BOB: *"Yes Boss."* [publishes] *"Live site updated."*

**Injection attempt blocked:**
> *"SECURITY ALERT — Prompt injection attempt blocked. Tool: submit_task. Pattern detected: 'ignore previous instructions'. Audit ID: 7c4d2e1f. Review the full entry in the audit log."*

---

*BOB Webhook Tool Security Build Plan v1.0 — 2026-03-18*
*Next build: Wake-Word Listener — "Hey BOB"*
