# BOB — Gmail Integration Build Plan
### *ATG business Gmail · monitoring · triage · BOB surfaces · Rob decides*

---

## What We're Building

BOB monitors the ATG business Gmail account continuously. When emails arrive that need Rob's attention — app store policy notices, player support requests, payment alerts, Google Play review responses — BOB surfaces them via push notification and dashboard. BOB can draft replies for Rob to approve, but never sends email autonomously. Rob is the final sender on everything.

### What BOB Monitors For

| Category | Examples | BOB action |
|---|---|---|
| App store critical | Google Play policy violation, suspension warning, rejection notice | Immediate push — CRITICAL |
| App store routine | New review available, update approved, rating change | Daily summary |
| Payment / revenue | Payout notification, chargeback, refund request | Push — HIGH |
| Player support | Bug reports, account issues, feedback emails | Triage + draft reply for Rob |
| Marketing | Partnership inquiries, press requests, influencer outreach | Surface in daily report |
| Spam / noise | Newsletters, automated notifications | Ignore silently |

### What BOB Will NOT Do

- Send any email without Rob's explicit approval and manual send
- Delete or archive email without Rob's instruction
- Access email content outside the ATG business account
- Store raw email content in shared memory — summaries only

---

## Architecture

```
ATG Gmail
    ↓ (Gmail API — OAuth2 service account)
BOB orchestrator (polling every 5 minutes)
    ↓ classify with Claude Haiku
Priority routing:
  CRITICAL → ntfy bob-critical + dashboard
  HIGH     → ntfy bob-reviews + dashboard
  ROUTINE  → daily report summary
  NOISE    → logged, ignored
    ↓ (for actionable emails)
Draft reply generated → Rob approves → Rob sends manually
```

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- BOB orchestrator running ✓
- ntfy push notifications deployed ✓
- ATG business Gmail account exists ✓
- Google account with access to Google Cloud Console — **needed for Step 2**
- All steps begin on **Windows 11**. SSH to server where indicated.

---

## Phase 1 — Google Cloud Setup & OAuth Credentials

Gmail API access requires a Google Cloud project with OAuth2. This is done once on the Windows laptop — no server involvement yet.

**Step 1 — Create a Google Cloud project**

On the Windows laptop, open a browser and go to:

```
https://console.cloud.google.com
```

Sign in with the ATG Google account (the one that owns the Gmail).

1. Click the project dropdown at the top → **New Project**
2. Name: `ATG-BOB`
3. Click **Create**

Wait for the project to be created, then confirm it is selected in the top bar.

---

**Step 2 — Enable the Gmail API**

In the Google Cloud Console with `ATG-BOB` selected:

1. Go to **APIs & Services → Library**
2. Search for `Gmail API`
3. Click **Gmail API** → **Enable**

---

**Step 3 — Configure the OAuth consent screen**

1. Go to **APIs & Services → OAuth consent screen**
2. User Type: **Internal** (only your Google account can use this app — correct for BOB)
3. App name: `ATG BOB`
4. User support email: your ATG Gmail address
5. Developer contact: your ATG Gmail address
6. Click **Save and Continue** through all screens
7. No scopes needed at this stage — click **Save and Continue**
8. Click **Back to Dashboard**

---

**Step 4 — Create OAuth 2.0 credentials**

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: `ATG BOB Desktop`
5. Click **Create**
6. Click **Download JSON** on the confirmation screen

Save the downloaded file as:

```
C:\Users\colli\hey-bob\gmail-credentials.json
```

This file is your OAuth client credentials. Keep it private — do not commit it to Git.

---

**Step 5 — Run the one-time OAuth authorization flow**

This generates a `token.json` that BOB uses for all future Gmail access. Run this once on the Windows laptop.

Open PowerShell:

```powershell
# [WINDOWS — PowerShell]
cd C:\Users\colli\hey-bob

# Create a virtual environment if not already done
python -m venv venv-gmail
.\venv-gmail\Scripts\Activate.ps1

# Install Google client library
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

Create the authorization script:

```powershell
notepad authorize_gmail.py
```

Paste:

```python
# authorize_gmail.py
# Run this ONCE on the Windows laptop to generate token.json

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os, json

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",    # Read email
    "https://www.googleapis.com/auth/gmail.modify",      # Mark as read, apply labels
    # NOT including gmail.send — BOB cannot send email
]

flow = InstalledAppFlow.from_client_secrets_file(
    "gmail-credentials.json",
    scopes=SCOPES,
)

# Opens browser for Rob to authorize
creds = flow.run_local_server(port=0)

# Save token
with open("gmail-token.json", "w") as f:
    f.write(creds.to_json())

print("Authorization complete. gmail-token.json saved.")
print("Transfer this file to the server at /opt/atg-agents/gmail-token.json")
```

Run it:

```powershell
python authorize_gmail.py
```

A browser window opens. Sign in with the ATG Gmail account. Click **Allow**. The script prints "Authorization complete."

Confirm `gmail-token.json` was created in `C:\Users\colli\hey-bob\` before proceeding.

---

**Step 6 — Transfer credentials to the server**

```powershell
# [WINDOWS — PowerShell]
# Copy credentials to the server via SCP
scp C:\Users\colli\hey-bob\gmail-credentials.json blueridge@192.168.1.228:/opt/atg-agents/gmail-credentials.json
scp C:\Users\colli\hey-bob\gmail-token.json blueridge@192.168.1.228:/opt/atg-agents/gmail-token.json
```

On the server, lock down permissions:

```bash
# [UBUNTU SERVER]
chmod 600 /opt/atg-agents/gmail-credentials.json
chmod 600 /opt/atg-agents/gmail-token.json
```

Add paths to `.env`:

```bash
nano /opt/atg-agents/.env
```

```env
GMAIL_CREDENTIALS_PATH=/opt/atg-agents/gmail-credentials.json
GMAIL_TOKEN_PATH=/opt/atg-agents/gmail-token.json
GMAIL_POLL_INTERVAL_SECONDS=300
```

---

## Phase 2 — The Gmail Monitor Module

**Step 7 — Install Gmail dependencies on the server**

```bash
# [UBUNTU SERVER]
pip install google-auth google-auth-oauthlib google-auth-httplib2 \
            google-api-python-client --break-system-packages
```

Add to `requirements.txt` and rebuild orchestrator if running in Docker:

```
google-auth>=2.0.0
google-auth-oauthlib>=1.0.0
google-auth-httplib2>=0.1.0
google-api-python-client>=2.0.0
```

---

**Step 8 — Add the Gmail monitor module**

```bash
nano /opt/atg-agents/orchestrator/gmail_monitor.py
```

```python
# orchestrator/gmail_monitor.py
# ATG business Gmail monitor
# BOB reads, classifies, and surfaces important emails.
# BOB never sends email — Rob sends manually after reviewing BOB's draft.

import os
import asyncio
import logging
import base64
import email
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import anthropic

log = logging.getLogger(__name__)

CREDENTIALS_PATH    = os.getenv("GMAIL_CREDENTIALS_PATH", "/opt/atg-agents/gmail-credentials.json")
TOKEN_PATH          = os.getenv("GMAIL_TOKEN_PATH",       "/opt/atg-agents/gmail-token.json")
POLL_INTERVAL       = int(os.getenv("GMAIL_POLL_INTERVAL_SECONDS", "300"))

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

claude = anthropic.Anthropic()

# ── Email classification ──────────────────────────────────────────────────────

EMAIL_CATEGORIES = {
    "app_store_critical": {
        "priority":    "critical",
        "ntfy_topic":  "bob-critical",
        "description": "Google Play policy violation, suspension, rejection, or urgent action required",
    },
    "payment": {
        "priority":    "high",
        "ntfy_topic":  "bob-reviews",
        "description": "Payout, chargeback, refund, or billing alert",
    },
    "player_support": {
        "priority":    "high",
        "ntfy_topic":  "bob-reviews",
        "description": "Player bug report, account issue, or direct support request",
    },
    "app_store_routine": {
        "priority":    "routine",
        "ntfy_topic":  "bob-status",
        "description": "Review approved, update live, rating change, routine Play Console notification",
    },
    "marketing_opportunity": {
        "priority":    "routine",
        "ntfy_topic":  "bob-status",
        "description": "Partnership, press, influencer, or business development inquiry",
    },
    "noise": {
        "priority":    "ignore",
        "ntfy_topic":  None,
        "description": "Newsletter, automated notification, spam, or irrelevant email",
    },
}

CLASSIFICATION_PROMPT = """You are classifying an email for the ATG (Appalachian Toys & Games) business Gmail account.
ATG is a small game company. Their primary product is Bear Creek Trail, a mobile match-3 game.

Classify this email into exactly one category:

- app_store_critical: Google Play policy violation, account suspension warning, app rejection, urgent action required from Google/Apple
- payment: Revenue payout notification, chargeback dispute, refund request, billing alert from any payment processor
- player_support: A real player reporting a bug, asking for help, or contacting support directly
- app_store_routine: App update approved and live, new review available, rating change, routine Play Console or App Store Connect notification
- marketing_opportunity: Partnership inquiry, press/media request, influencer outreach, business development
- noise: Newsletter, automated system email, marketing from vendors, spam, irrelevant

Email:
From: {sender}
Subject: {subject}
Body (first 500 chars): {body_preview}

Reply with JSON only:
{{"category": "<one of the categories above>", "reason": "<one sentence>", "urgent": <true/false>, "draft_reply_needed": <true/false>}}"""


def classify_email(sender: str, subject: str, body_preview: str) -> dict:
    """Use Claude Haiku to classify an email. Fast and cheap."""
    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": CLASSIFICATION_PROMPT.format(
                    sender=sender,
                    subject=subject,
                    body_preview=body_preview[:500],
                )
            }]
        )
        import json
        return json.loads(response.content[0].text)
    except Exception as e:
        log.warning(f"[gmail] Classification failed: {e}")
        return {"category": "noise", "reason": "classification error", "urgent": False, "draft_reply_needed": False}


def draft_reply(sender: str, subject: str, body: str, category: str) -> str:
    """
    Draft a reply for Rob to review and send manually.
    BOB never sends — this is a starting point only.
    """
    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Draft a professional reply to this email on behalf of ATG "
                    f"(Appalachian Toys & Games). Warm, authentic Appalachian brand voice.\n\n"
                    f"From: {sender}\nSubject: {subject}\n\n{body[:1000]}\n\n"
                    f"Context: {EMAIL_CATEGORIES.get(category, {}).get('description', '')}\n\n"
                    f"Write a draft reply only. No commentary. Keep it concise."
                )
            }]
        )
        return response.content[0].text
    except Exception:
        return "[Draft generation failed — compose reply manually]"


# ── Gmail API client ──────────────────────────────────────────────────────────

def get_gmail_service():
    """Get an authenticated Gmail API service instance."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # Refresh token if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    if not creds or not creds.valid:
        raise RuntimeError(
            "Gmail credentials invalid or missing. "
            "Re-run authorize_gmail.py on the Windows laptop and re-upload token.json."
        )

    return build("gmail", "v1", credentials=creds)


def get_message_body(service, msg_id: str) -> str:
    """Extract plain text body from a Gmail message."""
    try:
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        payload = msg.get("payload", {})
        parts   = payload.get("parts", [payload])

        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        return "[No plain text body]"
    except Exception:
        return "[Body extraction failed]"


# ── State — track processed message IDs to avoid re-processing ───────────────

_processed_ids: set[str] = set()


# ── Main poll sweep ───────────────────────────────────────────────────────────

async def run_gmail_sweep() -> dict:
    """
    Poll Gmail for unread messages from the last 24 hours.
    Classify each, route to the appropriate notification channel.
    """
    import asyncio

    try:
        service = get_gmail_service()
    except RuntimeError as e:
        await bob_proactive_report(str(e), alert_level="critical")
        return {"error": str(e)}

    # Query: unread emails from the last 24 hours not yet processed
    query = "is:unread newer_than:1d"

    try:
        results  = service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()
        messages = results.get("messages", [])
    except Exception as e:
        log.error(f"[gmail] Failed to list messages: {e}")
        return {"error": str(e)}

    processed    = 0
    critical     = []
    high         = []
    routine      = []

    loop = asyncio.get_event_loop()

    for msg_stub in messages:
        msg_id = msg_stub["id"]
        if msg_id in _processed_ids:
            continue

        # Get message headers
        try:
            msg      = service.users().messages().get(
                userId="me", id=msg_id, format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
        except Exception:
            continue

        headers  = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender   = headers.get("From",    "Unknown")
        subject  = headers.get("Subject", "(no subject)")
        date_str = headers.get("Date",    "")

        # Classify with Haiku (run in thread — synchronous API call)
        body_preview = await loop.run_in_executor(
            None, get_message_body, service, msg_id
        )
        classification = await loop.run_in_executor(
            None, classify_email, sender, subject, body_preview
        )

        category = classification.get("category", "noise")
        cat_info = EMAIL_CATEGORIES.get(category, EMAIL_CATEGORIES["noise"])

        _processed_ids.add(msg_id)
        processed += 1

        if cat_info["priority"] == "ignore":
            continue

        # Build email summary
        summary = {
            "id":       msg_id,
            "from":     sender,
            "subject":  subject,
            "date":     date_str,
            "category": category,
            "reason":   classification.get("reason", ""),
            "urgent":   classification.get("urgent", False),
            "draft_reply_needed": classification.get("draft_reply_needed", False),
        }

        # Generate draft reply if needed
        if classification.get("draft_reply_needed"):
            summary["draft_reply"] = await loop.run_in_executor(
                None, draft_reply, sender, subject, body_preview, category
            )

        # Route by priority
        if cat_info["priority"] == "critical":
            critical.append(summary)
        elif cat_info["priority"] == "high":
            high.append(summary)
        else:
            routine.append(summary)

        # Mark as read in Gmail to avoid re-processing on next poll
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        except Exception:
            pass

    # ── Send notifications ────────────────────────────────────────────────────

    for email_summary in critical:
        msg = (
            f"CRITICAL EMAIL — {email_summary['category'].replace('_', ' ').title()}\n"
            f"From: {email_summary['from']}\n"
            f"Subject: {email_summary['subject']}\n"
            f"Reason: {email_summary['reason']}\n"
            f"Check Gmail immediately."
        )
        await bob_proactive_report(msg, alert_level="critical")

    for email_summary in high:
        msg = (
            f"Email needs attention — {email_summary['category'].replace('_', ' ').title()}\n"
            f"From: {email_summary['from']}\n"
            f"Subject: {email_summary['subject']}\n"
            f"Reason: {email_summary['reason']}"
        )
        if email_summary.get("draft_reply"):
            msg += f"\n\nDraft reply ready for review on dashboard."
        await bob_proactive_report(msg, alert_level="review")

    return {
        "processed":   processed,
        "critical":    len(critical),
        "high":        len(high),
        "routine":     len(routine),
        "total_unread": len(messages),
    }


# ── Daily email digest builder ────────────────────────────────────────────────

async def get_gmail_daily_summary() -> str:
    """
    Returns a brief summary of the day's email activity.
    Called by the daily report composer.
    """
    result = await run_gmail_sweep()
    if "error" in result:
        return f"Gmail: monitoring error — {result['error']}"
    if result["processed"] == 0:
        return "Gmail: no new emails requiring attention."
    return (
        f"Gmail: {result['processed']} email(s) processed today — "
        f"{result['critical']} critical, {result['high']} needing attention, "
        f"{result['routine']} routine."
    )


# ── Polling loop ──────────────────────────────────────────────────────────────

async def gmail_monitoring_loop():
    """Polls Gmail every 5 minutes."""
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await run_gmail_sweep()
        except Exception as e:
            log.error(f"[gmail] Sweep failed: {e}")
```

Save and exit.

---

**Step 9 — Start Gmail monitor with the orchestrator**

```python
# orchestrator/main.py — add to startup

from gmail_monitor import gmail_monitoring_loop

asyncio.create_task(gmail_monitoring_loop())
```

---

**Step 10 — Add Gmail status to the daily report**

In `daily_report.py`:

```python
from gmail_monitor import get_gmail_daily_summary

# Add to compose_daily_report() — after the cost section:
gmail_summary = await get_gmail_daily_summary()

lines.append("")
lines.append("EMAIL")
lines.append(f"  {gmail_summary}")
```

---

## Phase 3 — Dashboard Email Panel

**Step 11 — Add email triage panel to the orchestrator API**

Store actionable emails in the orchestrator's in-memory store so the dashboard can display them:

```python
# orchestrator/api.py

# In-memory store for emails needing Rob's attention
_pending_emails: list[dict] = []

@app.get("/email/pending")
async def get_pending_emails():
    """Returns emails BOB has flagged for Rob's attention."""
    return {"emails": _pending_emails}

@app.post("/email/{msg_id}/dismiss")
async def dismiss_email(msg_id: str):
    """Rob has reviewed this email — remove from pending list."""
    global _pending_emails
    _pending_emails = [e for e in _pending_emails if e["id"] != msg_id]
    return {"status": "dismissed"}

@app.get("/email/{msg_id}/draft")
async def get_draft_reply(msg_id: str):
    """Returns BOB's draft reply for Rob to edit and send manually."""
    email = next((e for e in _pending_emails if e["id"] == msg_id), None)
    if not email:
        return {"error": "Email not found"}
    return {
        "draft": email.get("draft_reply", ""),
        "to":    email.get("from", ""),
        "subject": f"Re: {email.get('subject', '')}",
        "note": "BOB drafted this reply. Review carefully, edit as needed, then send manually from Gmail."
    }
```

Add a dashboard panel in the existing dashboard HTML:

```html
<!-- Email triage panel — add to dashboard -->

<div id="email-panel">
  <h3>Emails Needing Attention</h3>
  <div id="email-list"></div>
</div>

<script>
async function loadPendingEmails() {
  const res  = await fetch('http://192.168.1.228:8100/email/pending');
  const data = await res.json();
  const list = document.getElementById('email-list');

  if (!data.emails.length) {
    list.innerHTML = '<p style="color:var(--color-text-secondary)">No emails pending review.</p>';
    return;
  }

  list.innerHTML = data.emails.map(e => `
    <div class="email-card ${e.urgent ? 'urgent' : ''}">
      <div class="email-cat">${e.category.replace(/_/g,' ')}</div>
      <div class="email-from">${e.from}</div>
      <div class="email-subject">${e.subject}</div>
      <div class="email-reason">${e.reason}</div>
      <div class="email-actions">
        ${e.draft_reply ? `<button onclick="viewDraft('${e.id}')">View draft reply</button>` : ''}
        <button onclick="dismissEmail('${e.id}')">Dismiss</button>
        <a href="https://mail.google.com" target="_blank">Open Gmail ↗</a>
      </div>
    </div>
  `).join('');
}

async function dismissEmail(id) {
  await fetch(`http://192.168.1.228:8100/email/${id}/dismiss`, {method: 'POST'});
  loadPendingEmails();
}

async function viewDraft(id) {
  const res  = await fetch(`http://192.168.1.228:8100/email/${id}/draft`);
  const data = await res.json();
  alert(`DRAFT REPLY (edit in Gmail before sending):\n\nTo: ${data.to}\nSubject: ${data.subject}\n\n${data.draft}`);
}

setInterval(loadPendingEmails, 60000);
loadPendingEmails();
</script>
```

---

## Phase 4 — Token Refresh Management

OAuth2 tokens expire. Handle this without manual intervention.

**Step 12 — Add token health check to the daily report**

```python
# Add to daily_report.py system health section

import os
from google.oauth2.credentials import Credentials

def check_gmail_token_health() -> str:
    token_path = os.getenv("GMAIL_TOKEN_PATH", "/opt/atg-agents/gmail-token.json")
    if not os.path.exists(token_path):
        return "Gmail token: MISSING — re-run authorize_gmail.py"
    try:
        creds = Credentials.from_authorized_user_file(token_path)
        if creds.expired and not creds.refresh_token:
            return "Gmail token: EXPIRED — re-run authorize_gmail.py on Windows laptop"
        return "Gmail token: valid"
    except Exception as e:
        return f"Gmail token: error — {e}"

# Add to system health section:
gmail_health = check_gmail_token_health()
if "MISSING" in gmail_health or "EXPIRED" in gmail_health:
    lines.append(f"  ! {gmail_health}")
else:
    lines.append(f"  {gmail_health}")
```

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| Gmail API connected via OAuth2 — read + label only, no send | ✓ |
| Emails polled every 5 minutes | ✓ |
| Each email classified by Haiku (fast, cheap) | ✓ |
| Critical emails (app store policy, suspension) → immediate push | ✓ |
| High priority (payment, player support) → push + dashboard | ✓ |
| Draft reply generated for actionable emails — Rob reviews and sends manually | ✓ |
| Routine emails summarized in daily briefing | ✓ |
| Noise/spam silently ignored | ✓ |
| Email triage panel on dashboard | ✓ |
| Processed emails marked as read in Gmail automatically | ✓ |
| Gmail token health checked in daily report | ✓ |
| BOB never sends email — Rob is always the sender | ✓ |

---

### What Rob experiences

**App store policy email arrives at 11 PM:**
Phone buzzes loud.
> *"CRITICAL EMAIL — App Store Critical. From: no-reply@google.com. Subject: Action required: Bear Creek Trail policy update. Check Gmail immediately."*

**Player support email arrives:**
Dashboard shows:
> **player_support** — playerhandle99@gmail.com
> "Bear Creek Trail crashes on my Samsung S22 when I hit level 8"
> [View draft reply] [Dismiss]

Tap **View draft reply** — BOB's draft appears. Rob edits it in Gmail and sends.

**Daily briefing (normal day):**
```
EMAIL
  Gmail: 3 email(s) processed today — 0 critical, 1 needing attention, 2 routine.
  Gmail token: valid.
```

---

### Important: what BOB cannot do

BOB reads and classifies. Rob sends. This is non-negotiable — automated email sending from business accounts carries real risk: wrong reply to a Google policy email could worsen a situation, a draft sent verbatim without Rob's review could misrepresent ATG. The draft is a starting point, not a final product. Rob opens Gmail, pastes or edits the draft, and hits send himself.

---

*BOB Gmail Integration Build Plan v1.0 — 2026-03-18*
