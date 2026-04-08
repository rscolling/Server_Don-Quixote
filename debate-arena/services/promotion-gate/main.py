"""Promotion Gate — human-approved file promotion from agent proposals to live targets.

FE and BE agents write to /agent-share/workspace/{frontend,backend}/proposals/.
Nothing they write is automatically live. To promote a proposal to a real
target directory (e.g. ~/portfolio-site/), an agent or a human creates a
*pending promotion* via this service. A human reviews, optionally checks the
diff, and approves — only then does the file copy actually happen.

Endpoints
  GET  /health
  POST /promotions             create a pending promotion
  GET  /promotions             list (filter by state, agent, target)
  GET  /promotions/{id}        single promotion detail
  GET  /promotions/{id}/diff   unified diff (source vs current target)
  POST /promotions/{id}/approve  execute the copy, mark applied
  POST /promotions/{id}/reject   mark rejected with note

Safety
  - Source paths MUST be under /agent-share/workspace/{frontend,backend}/proposals/
  - Target paths MUST be under one of the env-configured target roots
  - Both source and target are resolved with `.resolve()` and re-checked against
    their allowlist roots, so symlinks and `..` are caught
  - Source can be a file or a directory (directories copied recursively)
  - Approval is single-shot: once applied or rejected, the record is frozen
  - Every state change is timestamped and logged in the audit table
"""
import json
import logging
import os
import shutil
import sqlite3
import difflib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("promotion-gate")

# === Config ===
DB_PATH = Path(os.environ.get("PROMOTION_DB", "/state/promotions.db"))
SOURCE_ROOTS = [
    Path("/agent-share/workspace/frontend/proposals"),
    Path("/agent-share/workspace/backend/proposals"),
]
# Comma-separated list of allowed target roots, e.g.
# "/promote-targets/portfolio-site"
TARGET_ROOTS_ENV = os.environ.get("PROMOTION_TARGET_ROOTS", "/promote-targets/portfolio-site")
TARGET_ROOTS = [Path(p.strip()) for p in TARGET_ROOTS_ENV.split(",") if p.strip()]

# === ntfy notifications ===
NTFY_URL = os.environ.get("NTFY_URL", "http://ntfy:80")
NTFY_REVIEW_TOPIC = os.environ.get("NTFY_REVIEW_TOPIC", "bob-reviews")
NTFY_AUDIT_TOPIC = os.environ.get("NTFY_AUDIT_TOPIC", "bob-status")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")
NTFY_TIMEOUT = 5.0


def _ntfy_send(topic: str, title: str, message: str, priority: str = "default") -> None:
    """Best-effort POST to the ntfy server. Never raises — logs and continues."""
    import httpx
    headers = {"Title": title, "Priority": priority}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    try:
        with httpx.Client(timeout=NTFY_TIMEOUT) as client:
            client.post(f"{NTFY_URL}/{topic}", content=message, headers=headers)
        log.info(f"ntfy sent to {topic}: {title}")
    except Exception as e:
        log.warning(f"ntfy send failed (topic={topic}): {e}")


def _format_promotion_for_ntfy(rec: dict) -> str:
    return (
        f"#{rec['id']} from {rec['agent']}\n"
        f"src: {rec['source_path']}\n"
        f"tgt: {rec['target_path']}\n"
        f"why: {(rec.get('reason') or '')[:200]}"
    )





# === DB ===
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path  TEXT NOT NULL,
                target_path  TEXT NOT NULL,
                agent        TEXT NOT NULL,
                task_id      INTEGER,
                reason       TEXT,
                state        TEXT NOT NULL DEFAULT 'pending',
                created_at   TEXT NOT NULL,
                resolved_at  TEXT,
                resolved_by  TEXT,
                resolution_note TEXT,
                files_copied_count INTEGER,
                bytes_copied INTEGER
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_state ON promotions(state)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_created ON promotions(created_at)")


_init_db()


# === Path safety ===
def _safe_source(p: str) -> Path:
    if not p:
        raise HTTPException(400, "source_path is required")
    candidate = Path(p).resolve()
    for root in SOURCE_ROOTS:
        try:
            candidate.relative_to(root.resolve())
            if not candidate.exists():
                raise HTTPException(404, f"source does not exist: {p}")
            return candidate
        except ValueError:
            continue
    raise HTTPException(400, f"source must be under one of {[str(r) for r in SOURCE_ROOTS]}")


def _safe_target(p: str) -> Path:
    if not p:
        raise HTTPException(400, "target_path is required")
    candidate = Path(p).resolve()
    for root in TARGET_ROOTS:
        try:
            candidate.relative_to(root.resolve())
            return candidate
        except ValueError:
            continue
    raise HTTPException(400, f"target must be under one of {[str(r) for r in TARGET_ROOTS]}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# === Models ===
class PromotionCreate(BaseModel):
    source_path: str = Field(..., description="Path under /agent-share/workspace/*/proposals/")
    target_path: str = Field(..., description="Path under one of the configured target roots")
    agent: str = Field(..., description="Which agent requested this (FE, BE, or human)")
    task_id: int | None = None
    reason: str | None = Field(None, description="Why this should be promoted")


class ApproveRequest(BaseModel):
    approver: str = Field("rob", description="Who is approving")
    note: str | None = None


class RejectRequest(BaseModel):
    rejector: str = Field("rob", description="Who is rejecting")
    note: str | None = None


# === FastAPI ===
app = FastAPI(title="Promotion Gate")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "promotion-gate",
        "source_roots": [str(r) for r in SOURCE_ROOTS],
        "target_roots": [str(r) for r in TARGET_ROOTS],
        "db": str(DB_PATH),
    }


@app.post("/promotions")
def create_promotion(req: PromotionCreate):
    """Validate paths and create a pending promotion record."""
    src = _safe_source(req.source_path)
    tgt = _safe_target(req.target_path)
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO promotions
               (source_path, target_path, agent, task_id, reason, state, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (str(src), str(tgt), req.agent, req.task_id, req.reason, _now()),
        )
        pid = cur.lastrowid
        c.commit()
    log.info(f"promotion #{pid} created: {src} -> {tgt} by {req.agent}")
    rec = _fetch_one(pid)
    _ntfy_send(
        NTFY_REVIEW_TOPIC,
        title=f"Promotion #{pid} pending review",
        message=_format_promotion_for_ntfy(rec),
        priority="high",
    )
    return rec


@app.get("/promotions")
def list_promotions(state: str | None = None, agent: str | None = None, limit: int = 50):
    sql = "SELECT * FROM promotions"
    clauses = []
    args: list = []
    if state:
        clauses.append("state = ?")
        args.append(state)
    if agent:
        clauses.append("agent = ?")
        args.append(agent)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(sql, args)]
    return {"count": len(rows), "promotions": rows}


def _fetch_one(pid: int) -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM promotions WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, f"promotion {pid} not found")
    return dict(row)


@app.get("/promotions/{pid}")
def get_promotion(pid: int):
    return _fetch_one(pid)


@app.get("/promotions/{pid}/diff")
def promotion_diff(pid: int):
    """Return a unified diff between source and current target.

    For directories, returns per-file diffs for files that differ. Skips
    binary files. New files in source that don't exist in target are listed
    as ADDED. Files removed from source are listed as REMOVED.
    """
    rec = _fetch_one(pid)
    src = Path(rec["source_path"])
    tgt = Path(rec["target_path"])
    if not src.exists():
        raise HTTPException(404, f"source no longer exists: {src}")

    diffs: list[dict] = []

    def _diff_one_file(src_file: Path, tgt_file: Path, rel: str) -> None:
        try:
            src_text = src_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            diffs.append({"path": rel, "kind": "binary_skipped"})
            return
        if not tgt_file.exists():
            diffs.append({
                "path": rel, "kind": "added",
                "lines_added": src_text.count("\n") + 1,
            })
            return
        try:
            tgt_text = tgt_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            diffs.append({"path": rel, "kind": "binary_target_skipped"})
            return
        if src_text == tgt_text:
            diffs.append({"path": rel, "kind": "unchanged"})
            return
        ud = list(difflib.unified_diff(
            tgt_text.splitlines(keepends=False),
            src_text.splitlines(keepends=False),
            fromfile=f"target/{rel}",
            tofile=f"source/{rel}",
            lineterm="",
            n=3,
        ))
        diffs.append({"path": rel, "kind": "modified", "diff": "\n".join(ud)[:8000]})

    if src.is_file():
        _diff_one_file(src, tgt, src.name)
    else:
        # Walk source tree
        for sf in src.rglob("*"):
            if sf.is_dir():
                continue
            rel = str(sf.relative_to(src))
            tf = tgt / rel
            _diff_one_file(sf, tf, rel)
        # Files only in target
        if tgt.exists() and tgt.is_dir():
            for tf in tgt.rglob("*"):
                if tf.is_dir():
                    continue
                rel = str(tf.relative_to(tgt))
                if not (src / rel).exists():
                    diffs.append({"path": rel, "kind": "removed_from_source"})

    summary = {
        "total": len(diffs),
        "added": sum(1 for d in diffs if d["kind"] == "added"),
        "modified": sum(1 for d in diffs if d["kind"] == "modified"),
        "unchanged": sum(1 for d in diffs if d["kind"] == "unchanged"),
        "removed_from_source": sum(1 for d in diffs if d["kind"] == "removed_from_source"),
        "binary_skipped": sum(1 for d in diffs if d["kind"].startswith("binary")),
    }
    return {"id": pid, "summary": summary, "diffs": diffs}


@app.post("/promotions/{pid}/approve")
def approve_promotion(pid: int, req: ApproveRequest):
    """Execute the actual copy. Once applied, the record is frozen."""
    rec = _fetch_one(pid)
    if rec["state"] != "pending":
        raise HTTPException(409, f"promotion {pid} is in state {rec['state']}, not pending")

    src = Path(rec["source_path"])
    tgt = Path(rec["target_path"])
    if not src.exists():
        raise HTTPException(404, f"source no longer exists: {src}")

    files_copied = 0
    bytes_copied = 0
    try:
        if src.is_file():
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
            files_copied = 1
            bytes_copied = src.stat().st_size
        else:
            tgt.mkdir(parents=True, exist_ok=True)
            for sf in src.rglob("*"):
                if sf.is_dir():
                    continue
                rel = sf.relative_to(src)
                tf = tgt / rel
                tf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sf, tf)
                files_copied += 1
                bytes_copied += sf.stat().st_size
    except Exception as e:
        log.exception(f"promotion #{pid} copy failed")
        with _conn() as c:
            c.execute(
                """UPDATE promotions SET state='error', resolved_at=?, resolved_by=?, resolution_note=?
                   WHERE id=?""",
                (_now(), req.approver, f"copy failed: {e}", pid),
            )
            c.commit()
        raise HTTPException(500, f"copy failed: {e}")

    with _conn() as c:
        c.execute(
            """UPDATE promotions
               SET state='applied', resolved_at=?, resolved_by=?, resolution_note=?,
                   files_copied_count=?, bytes_copied=?
               WHERE id=?""",
            (_now(), req.approver, req.note, files_copied, bytes_copied, pid),
        )
        c.commit()
    log.info(f"promotion #{pid} APPLIED by {req.approver}: {files_copied} files, {bytes_copied} bytes")
    rec = _fetch_one(pid)
    _ntfy_send(
        NTFY_AUDIT_TOPIC,
        title=f"Promotion #{pid} APPLIED",
        message=(
            f"approved by {req.approver}\n"
            f"{files_copied} files, {bytes_copied} bytes\n"
            f"-> {rec['target_path']}\n"
            f"note: {(req.note or '')[:200]}"
        ),
        priority="default",
    )
    return rec


@app.post("/promotions/{pid}/reject")
def reject_promotion(pid: int, req: RejectRequest):
    rec = _fetch_one(pid)
    if rec["state"] != "pending":
        raise HTTPException(409, f"promotion {pid} is in state {rec['state']}, not pending")
    with _conn() as c:
        c.execute(
            """UPDATE promotions SET state='rejected', resolved_at=?, resolved_by=?, resolution_note=?
               WHERE id=?""",
            (_now(), req.rejector, req.note, pid),
        )
        c.commit()
    log.info(f"promotion #{pid} REJECTED by {req.rejector}")
    rec = _fetch_one(pid)
    _ntfy_send(
        NTFY_AUDIT_TOPIC,
        title=f"Promotion #{pid} rejected",
        message=(
            f"rejected by {req.rejector}\n"
            f"src: {rec['source_path']}\n"
            f"note: {(req.note or '')[:200]}"
        ),
        priority="low",
    )
    return rec


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8112)
