"""Shared memory proposal workflow.

Agent teams propose writes to ChromaDB. BOB reviews before committing.
Prevents bad data, duplicates, and conflicting information from entering
the shared knowledge base.

Flow:
  Agent proposes → queued as pending → BOB reviews → approve/reject → commit or discard
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("bob.proposals")

from app.config import PROPOSALS_DB_PATH as PROPOSALS_DB


def _init_db():
    """Create proposals table if it doesn't exist."""
    os.makedirs(os.path.dirname(PROPOSALS_DB), exist_ok=True)
    conn = sqlite3.connect(PROPOSALS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            text TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            proposed_by TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            reviewed_by TEXT DEFAULT '',
            review_note TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            reviewed_at TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def propose(
    collection: str,
    doc_id: str,
    text: str,
    metadata: dict | None = None,
    proposed_by: str = "",
    reason: str = "",
) -> dict:
    """Submit a proposal to write to shared memory.

    Returns the proposal with its ID for tracking.
    """
    _init_db()
    proposal_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(PROPOSALS_DB)
    conn.execute(
        "INSERT INTO proposals (id, collection, doc_id, text, metadata_json, "
        "proposed_by, reason, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (proposal_id, collection, doc_id, text,
         json.dumps(metadata or {}), proposed_by, reason, now),
    )
    conn.commit()
    conn.close()

    logger.info(f"Memory proposal created: {proposal_id} → {collection}/{doc_id} by {proposed_by}")
    return {
        "proposal_id": proposal_id,
        "collection": collection,
        "doc_id": doc_id,
        "status": "pending",
        "proposed_by": proposed_by,
    }


def get_pending() -> list[dict]:
    """Get all pending proposals awaiting review."""
    _init_db()
    conn = sqlite3.connect(PROPOSALS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM proposals WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_proposal(proposal_id: str) -> dict | None:
    """Get a single proposal by ID."""
    _init_db()
    conn = sqlite3.connect(PROPOSALS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def approve(proposal_id: str, reviewed_by: str = "BOB", note: str = "") -> dict:
    """Approve a proposal — commit to ChromaDB.

    Returns the result of the write.
    """
    from app import memory

    _init_db()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"error": "Proposal not found", "proposal_id": proposal_id}

    if proposal["status"] != "pending":
        return {"error": f"Proposal already {proposal['status']}", "proposal_id": proposal_id}

    now = datetime.now(timezone.utc).isoformat()
    metadata = json.loads(proposal["metadata_json"])
    metadata["proposed_by"] = proposal["proposed_by"]
    metadata["approved_by"] = reviewed_by
    metadata["approved_at"] = now

    try:
        memory.store(
            collection=proposal["collection"],
            doc_id=proposal["doc_id"],
            text=proposal["text"],
            metadata=metadata,
        )
    except Exception as e:
        logger.error(f"Failed to commit proposal {proposal_id}: {e}")
        return {"error": f"Commit failed: {e}", "proposal_id": proposal_id}

    conn = sqlite3.connect(PROPOSALS_DB)
    conn.execute(
        "UPDATE proposals SET status = 'approved', reviewed_by = ?, "
        "review_note = ?, reviewed_at = ? WHERE id = ?",
        (reviewed_by, note, now, proposal_id),
    )
    conn.commit()
    conn.close()

    logger.info(f"Proposal {proposal_id} approved → {proposal['collection']}/{proposal['doc_id']}")
    return {
        "status": "approved",
        "proposal_id": proposal_id,
        "collection": proposal["collection"],
        "doc_id": proposal["doc_id"],
    }


def reject(proposal_id: str, reviewed_by: str = "BOB", note: str = "") -> dict:
    """Reject a proposal — data is not written."""
    _init_db()
    proposal = get_proposal(proposal_id)
    if not proposal:
        return {"error": "Proposal not found", "proposal_id": proposal_id}

    if proposal["status"] != "pending":
        return {"error": f"Proposal already {proposal['status']}", "proposal_id": proposal_id}

    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(PROPOSALS_DB)
    conn.execute(
        "UPDATE proposals SET status = 'rejected', reviewed_by = ?, "
        "review_note = ?, reviewed_at = ? WHERE id = ?",
        (reviewed_by, note, now, proposal_id),
    )
    conn.commit()
    conn.close()

    logger.info(f"Proposal {proposal_id} rejected: {note}")
    return {
        "status": "rejected",
        "proposal_id": proposal_id,
        "note": note,
    }


def get_history(limit: int = 20) -> list[dict]:
    """Get recent proposal history (all statuses)."""
    _init_db()
    conn = sqlite3.connect(PROPOSALS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
