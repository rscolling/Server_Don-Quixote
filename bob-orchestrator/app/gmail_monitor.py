"""Gmail monitor — BOB watches ATG inbox and triages emails.

Polls every 5 minutes. Classifies emails by category.
Surfaces critical/high items via ntfy. Logs everything.
Never sends email — BOB reads, Rob sends.
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger("bob.gmail")

TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "/app/gmail_token.json")
CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "/app/gmail_credentials.json")
POLL_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL", "300"))  # 5 minutes
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Track last seen message to avoid re-processing
_last_history_id = None
_processed_ids: set[str] = set()


def _get_gmail_service():
    """Build authenticated Gmail API service."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            logger.info("Gmail token refreshed")
        else:
            logger.error("Gmail token invalid and no refresh token. Re-run OAuth flow.")
            return None

    return build("gmail", "v1", credentials=creds)


def _get_message_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Recurse into multipart
        if part.get("parts"):
            result = _get_message_body(part)
            if result:
                return result
    return ""


def _extract_headers(headers: list[dict]) -> dict:
    """Extract common headers into a dict."""
    result = {}
    for h in headers:
        name = h.get("name", "").lower()
        if name in ("from", "to", "subject", "date"):
            result[name] = h.get("value", "")
    return result


# Email categories and their priority
CATEGORIES = {
    "app_store_critical": {"priority": "urgent", "topic": "bob-critical",
                           "keywords": ["policy violation", "suspension", "terminated", "rejected", "removal"]},
    "payment": {"priority": "high", "topic": "bob-reviews",
                "keywords": ["payout", "payment", "chargeback", "refund", "revenue", "earnings"]},
    "player_support": {"priority": "default", "topic": "bob-status",
                       "keywords": ["bug report", "account issue", "help", "support", "not working"]},
    "app_store_routine": {"priority": "low", "topic": None,
                          "keywords": ["review", "rating", "update approved", "published"]},
    "marketing": {"priority": "low", "topic": None,
                  "keywords": ["partnership", "press", "influencer", "collaboration", "sponsor"]},
}


def classify_email(subject: str, sender: str, body_preview: str) -> tuple[str, str]:
    """Simple keyword-based classification. Returns (category, priority)."""
    text = f"{subject} {sender} {body_preview}".lower()

    for category, config in CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword in text:
                return category, config["priority"]

    return "routine", "low"


async def check_inbox() -> list[dict]:
    """Check for new unread emails. Returns list of classified email summaries."""
    service = _get_gmail_service()
    if not service:
        return []

    try:
        results = service.users().messages().list(
            userId="me",
            q="is:unread",
            maxResults=10,
        ).execute()
    except Exception as e:
        logger.error(f"Gmail API error: {e}")
        return []

    messages = results.get("messages", [])
    new_emails = []

    for msg_meta in messages:
        msg_id = msg_meta["id"]
        if msg_id in _processed_ids:
            continue

        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
        except Exception as e:
            logger.error(f"Failed to fetch message {msg_id}: {e}")
            continue

        headers = _extract_headers(msg.get("payload", {}).get("headers", []))
        body = _get_message_body(msg.get("payload", {}))
        body_preview = body[:500] if body else ""

        category, priority = classify_email(
            headers.get("subject", ""),
            headers.get("from", ""),
            body_preview,
        )

        email_summary = {
            "id": msg_id,
            "from": headers.get("from", "unknown"),
            "subject": headers.get("subject", "(no subject)"),
            "date": headers.get("date", ""),
            "category": category,
            "priority": priority,
            "preview": body_preview[:200],
        }

        new_emails.append(email_summary)
        _processed_ids.add(msg_id)

    return new_emails


async def poll_loop(notify_callback=None):
    """Background loop — check inbox every POLL_INTERVAL seconds."""
    logger.info(f"Gmail monitor started. Polling every {POLL_INTERVAL}s")

    while True:
        try:
            new_emails = await check_inbox()
            for email in new_emails:
                logger.info(f"New email: [{email['category']}] {email['subject']} from {email['from']}")

                # Notify for critical/high priority
                if notify_callback and email["priority"] in ("urgent", "high"):
                    topic_map = {cat: cfg["topic"] for cat, cfg in CATEGORIES.items() if cfg["topic"]}
                    topic = topic_map.get(email["category"], "bob-status")
                    await notify_callback(
                        topic=topic,
                        title=f"Email: {email['subject'][:50]}",
                        message=f"From: {email['from']}\nCategory: {email['category']}\n{email['preview'][:100]}",
                        priority=email["priority"],
                    )
        except Exception as e:
            logger.error(f"Gmail poll error: {e}")

        await asyncio.sleep(POLL_INTERVAL)
