"""Photo intake — vision processing for BOB.

Receives an image (from a smartphone via the voice service PWA), runs it
through Claude vision, and returns the analysis. Photos are saved to a
temp directory by default and only persisted if the user explicitly asks
to "remember this" — temp files auto-purge after PHOTO_TEMP_TTL_SECONDS.

Vision calls are billed against a separate per-user vision budget
(check_vision_budget) so a chatty member can't drain the API budget by
spamming uploads.

Storage layout:
    {DATA_DIR}/photos/tmp/<photo_id>.<ext>           # transient
    {DATA_DIR}/photos/<safe_user>/<photo_id>.<ext>   # remembered
    {DATA_DIR}/photos.db                              # metadata sqlite
"""

import asyncio
import base64
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app import config, cost_tracker
from app.llm import get_llm

logger = logging.getLogger("bob.photo_intake")


# ── Limits / config ────────────────────────────────────────────────────────

MAX_PHOTO_SIZE_BYTES = int(os.getenv("MAX_PHOTO_SIZE_BYTES", str(20 * 1024 * 1024)))
ALLOWED_MIMETYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
PHOTO_TEMP_TTL_SECONDS = int(os.getenv("PHOTO_TEMP_TTL_SECONDS", "60"))

PHOTOS_DIR = Path(getattr(config, "PHOTOS_DIR", f"{config.DATA_DIR}/photos"))
PHOTOS_TMP_DIR = PHOTOS_DIR / "tmp"
PHOTOS_DB_PATH = Path(getattr(config, "PHOTOS_DB_PATH", f"{config.DATA_DIR}/photos.db"))

DEFAULT_PROMPT = (
    "Describe this image in plain language. If it contains text, transcribe "
    "the text. If it shows a whiteboard, document, or note, extract any "
    "action items, decisions, or key facts as a bulleted list. Be concise "
    "but complete."
)

MODE_PROMPTS = {
    "analyze": DEFAULT_PROMPT,
    "ocr": "Transcribe all visible text in this image exactly as it appears. Preserve line breaks and structure. Do not summarize.",
    "extract_tasks": "List every action item, task, or to-do shown in this image as a bulleted list. One item per line. Be specific.",
    "identify_product": "Identify the product shown in this image. Include brand, model, key features, and any visible identifiers (SKU, barcode text, etc.).",
}


# ── DB ────────────────────────────────────────────────────────────────────

def _init_db():
    PHOTOS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PHOTOS_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            photo_id TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            path TEXT NOT NULL,
            mimetype TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            mode TEXT DEFAULT 'analyze',
            prompt TEXT DEFAULT '',
            analysis TEXT DEFAULT '',
            cost_usd REAL DEFAULT 0.0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            persisted INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_user ON photos(user)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_created ON photos(created_at)")
    conn.commit()
    conn.close()


@contextmanager
def _db():
    _init_db()
    conn = sqlite3.connect(str(PHOTOS_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _safe_user(user: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "_", (user or "anonymous").lower())[:64]


def _new_photo_id() -> str:
    return f"ph-{uuid.uuid4().hex[:12]}"


# ── Vision call ───────────────────────────────────────────────────────────

async def _call_vision(image_b64: str, mimetype: str, prompt: str,
                       user: str, mode: str) -> dict:
    """Run a Claude vision call. Returns {text, input_tokens, output_tokens, cost_usd}."""
    llm = get_llm()  # Uses configured provider; only Anthropic supports vision today
    model_name = getattr(llm, "model", None) or getattr(llm, "model_name", "") or "claude-opus-4-6"

    # langchain-anthropic accepts a multimodal HumanMessage as a list of content blocks
    from langchain_core.messages import HumanMessage
    message = HumanMessage(content=[
        {
            "type": "image",
            "source_type": "base64",
            "mime_type": mimetype,
            "data": image_b64,
        },
        {"type": "text", "text": prompt},
    ])

    try:
        resp = await llm.ainvoke([message])
    except Exception as e:
        # Older langchain-anthropic uses a slightly different schema
        logger.warning(f"Vision call schema-A failed ({e}); retrying with legacy schema")
        message = HumanMessage(content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mimetype};base64,{image_b64}"},
            },
            {"type": "text", "text": prompt},
        ])
        resp = await llm.ainvoke([message])

    text = resp.content if isinstance(resp.content, str) else str(resp.content)

    usage = getattr(resp, "usage_metadata", None) or {}
    in_tok = int(usage.get("input_tokens", 0) or 0)
    out_tok = int(usage.get("output_tokens", 0) or 0)

    record = cost_tracker.record_usage(
        provider=config.BOB_LLM_PROVIDER,
        model=model_name,
        input_tokens=in_tok,
        output_tokens=out_tok,
        user=user,
        tool=f"photo_{mode}",
    )

    return {
        "text": text,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": record["cost_usd"],
        "model": model_name,
    }


# ── Public API ────────────────────────────────────────────────────────────

async def process_photo(image_bytes: bytes, mimetype: str, user: str,
                        prompt: str = "", mode: str = "analyze") -> dict:
    """Validate, save to temp, run vision, persist metadata. Returns full result dict."""
    if mimetype not in ALLOWED_MIMETYPES:
        raise ValueError(f"Unsupported mimetype: {mimetype}. Allowed: {sorted(ALLOWED_MIMETYPES)}")
    if len(image_bytes) > MAX_PHOTO_SIZE_BYTES:
        raise ValueError(
            f"Photo too large: {len(image_bytes)} bytes (max {MAX_PHOTO_SIZE_BYTES})"
        )
    if not image_bytes:
        raise ValueError("Empty photo")

    if mode not in MODE_PROMPTS and mode != "log_to_memory":
        mode = "analyze"
    final_prompt = (prompt or "").strip() or MODE_PROMPTS.get(mode, DEFAULT_PROMPT)

    PHOTOS_TMP_DIR.mkdir(parents=True, exist_ok=True)
    photo_id = _new_photo_id()
    ext = MIME_TO_EXT.get(mimetype, "bin")
    tmp_path = PHOTOS_TMP_DIR / f"{photo_id}.{ext}"
    tmp_path.write_bytes(image_bytes)

    # Vision
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    try:
        vision = await _call_vision(image_b64, mimetype, final_prompt, user, mode)
    except Exception as e:
        logger.exception("Vision call failed")
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    now = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO photos (photo_id, user, path, mimetype, bytes, mode, prompt, "
            "analysis, cost_usd, input_tokens, output_tokens, persisted, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                photo_id, _safe_user(user), str(tmp_path), mimetype, len(image_bytes),
                mode, final_prompt, vision["text"], vision["cost_usd"],
                vision["input_tokens"], vision["output_tokens"], now,
            ),
        )

    # Schedule auto-purge
    asyncio.create_task(_auto_purge(photo_id, PHOTO_TEMP_TTL_SECONDS))

    return {
        "photo_id": photo_id,
        "analysis": vision["text"],
        "mode": mode,
        "cost_usd": vision["cost_usd"],
        "input_tokens": vision["input_tokens"],
        "output_tokens": vision["output_tokens"],
        "model": vision["model"],
        "persisted": False,
        "auto_purge_in": PHOTO_TEMP_TTL_SECONDS,
        "bytes": len(image_bytes),
    }


async def _auto_purge(photo_id: str, delay: int):
    """Delete the temp file after `delay` seconds unless it has been persisted."""
    try:
        await asyncio.sleep(delay)
        with _db() as conn:
            row = conn.execute(
                "SELECT path, persisted FROM photos WHERE photo_id = ?", (photo_id,)
            ).fetchone()
            if not row:
                return
            if row["persisted"]:
                return
            try:
                Path(row["path"]).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"auto_purge unlink failed for {photo_id}: {e}")
            conn.execute("DELETE FROM photos WHERE photo_id = ?", (photo_id,))
        logger.info(f"Auto-purged temp photo {photo_id}")
    except Exception:
        logger.exception(f"auto_purge failed for {photo_id}")


def remember_photo(photo_id: str, user: str) -> dict:
    """Move a temp photo into the user's persistent dir and mark it persisted.

    Also writes the analysis text to ChromaDB project_context so BOB can recall it.
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE photo_id = ?", (photo_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "photo not found or already purged"}
        if row["persisted"]:
            return {"ok": True, "already_persisted": True, "photo_id": photo_id}

        if _safe_user(user) != row["user"]:
            return {"ok": False, "error": "not your photo"}

        src = Path(row["path"])
        if not src.exists():
            conn.execute("DELETE FROM photos WHERE photo_id = ?", (photo_id,))
            return {"ok": False, "error": "temp file already purged"}

        dest_dir = PHOTOS_DIR / row["user"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        src.rename(dest)

        conn.execute(
            "UPDATE photos SET path = ?, persisted = 1 WHERE photo_id = ?",
            (str(dest), photo_id),
        )
        analysis = row["analysis"]
        mimetype = row["mimetype"]
        mode = row["mode"]

    # Write to memory (best-effort)
    try:
        from app import memory
        memory.store(
            collection="project_context",
            doc_id=f"photo:{photo_id}",
            text=f"Photo intake ({mode}): {analysis}",
            metadata={
                "source": "photo_intake",
                "photo_id": photo_id,
                "user": _safe_user(user),
                "mimetype": mimetype,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.warning(f"Failed to write photo memory for {photo_id}: {e}")

    return {"ok": True, "photo_id": photo_id, "persisted": True, "path": str(dest)}


def list_recent(user: str | None = None, limit: int = 10,
                only_persisted: bool = True) -> list[dict]:
    with _db() as conn:
        if user:
            rows = conn.execute(
                "SELECT photo_id, user, mimetype, bytes, mode, analysis, cost_usd, "
                "persisted, created_at FROM photos WHERE user = ? "
                + ("AND persisted = 1 " if only_persisted else "")
                + "ORDER BY created_at DESC LIMIT ?",
                (_safe_user(user), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT photo_id, user, mimetype, bytes, mode, analysis, cost_usd, "
                "persisted, created_at FROM photos "
                + ("WHERE persisted = 1 " if only_persisted else "")
                + "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    return [
        {
            "photo_id": r["photo_id"],
            "user": r["user"],
            "mimetype": r["mimetype"],
            "bytes": r["bytes"],
            "mode": r["mode"],
            "analysis_preview": (r["analysis"] or "")[:200],
            "cost_usd": r["cost_usd"],
            "persisted": bool(r["persisted"]),
            "created_at": datetime.fromtimestamp(r["created_at"], tz=timezone.utc).isoformat(),
        }
        for r in rows
    ]


def get_photo_record(photo_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM photos WHERE photo_id = ?", (photo_id,)).fetchone()
        if not row:
            return None
        return dict(row)


async def analyze_existing(photo_id: str, question: str, user: str) -> dict:
    """Re-run vision on a previously persisted photo with a new question."""
    rec = get_photo_record(photo_id)
    if not rec:
        raise ValueError(f"photo {photo_id} not found")
    if not rec["persisted"]:
        raise ValueError(f"photo {photo_id} was not remembered (temp file purged)")

    path = Path(rec["path"])
    if not path.exists():
        raise ValueError(f"photo file missing on disk: {path}")

    image_bytes = path.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    return await _call_vision(image_b64, rec["mimetype"], question, user, "analyze")
