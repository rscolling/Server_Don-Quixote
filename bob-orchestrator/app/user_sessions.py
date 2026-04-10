"""User session tracking for the dashboard.

Tracks active and historical sessions across voice and chat endpoints.
Sessions are stored in SQLite for persistence across restarts.
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone

from app.config import DATA_DIR

logger = logging.getLogger("bob.sessions")

SESSIONS_DB_PATH = f"{DATA_DIR}/user-sessions.db"


def _db():
    conn = sqlite3.connect(SESSIONS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_email TEXT,
                user_name TEXT,
                user_role TEXT DEFAULT 'unknown',
                endpoint TEXT NOT NULL,
                client_ip TEXT,
                latitude REAL,
                longitude REAL,
                connected_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL,
                disconnected_at TEXT,
                message_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_email ON sessions(user_email)
        """)
    logger.info(f"Session tracking DB initialized at {SESSIONS_DB_PATH}")


# Initialize on import
try:
    _init_db()
except Exception as e:
    logger.warning(f"Session DB init failed: {e}")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def open_session(
    session_id: str,
    endpoint: str,
    user_email: str | None = None,
    user_name: str | None = None,
    user_role: str = "unknown",
    client_ip: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    """Record a new session opening."""
    now = _now_iso()
    try:
        with _db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sessions
                (session_id, user_email, user_name, user_role, endpoint,
                 client_ip, latitude, longitude, connected_at, last_activity_at,
                 message_count, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
            """, (session_id, user_email, user_name, user_role, endpoint,
                  client_ip, latitude, longitude, now, now))
        logger.info(f"Session opened: {session_id} ({user_email or client_ip}, {endpoint})")
        return {"session_id": session_id, "status": "opened"}
    except Exception as e:
        logger.error(f"Failed to open session: {e}")
        return {"error": str(e)}


def update_session(
    session_id: str,
    latitude: float | None = None,
    longitude: float | None = None,
    increment_messages: bool = False,
) -> dict:
    """Update session activity (location, message count)."""
    try:
        with _db() as conn:
            sets = ["last_activity_at = ?"]
            params: list = [_now_iso()]

            if latitude is not None and longitude is not None:
                sets.append("latitude = ?")
                sets.append("longitude = ?")
                params.extend([latitude, longitude])

            if increment_messages:
                sets.append("message_count = message_count + 1")

            params.append(session_id)
            conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?",
                params,
            )
        return {"session_id": session_id, "status": "updated"}
    except Exception as e:
        logger.error(f"Failed to update session: {e}")
        return {"error": str(e)}


def close_session(session_id: str) -> dict:
    """Mark a session as closed."""
    try:
        with _db() as conn:
            conn.execute("""
                UPDATE sessions SET is_active = 0, disconnected_at = ?
                WHERE session_id = ?
            """, (_now_iso(), session_id))
        logger.info(f"Session closed: {session_id}")
        return {"session_id": session_id, "status": "closed"}
    except Exception as e:
        logger.error(f"Failed to close session: {e}")
        return {"error": str(e)}


def get_active_sessions() -> list[dict]:
    """Return all currently active sessions."""
    try:
        # Also mark stale sessions (no activity in 10 minutes) as inactive
        cutoff = datetime.fromtimestamp(
            time.time() - 600, tz=timezone.utc
        ).isoformat()
        with _db() as conn:
            conn.execute("""
                UPDATE sessions SET is_active = 0, disconnected_at = ?
                WHERE is_active = 1 AND last_activity_at < ?
            """, (_now_iso(), cutoff))

            rows = conn.execute("""
                SELECT * FROM sessions WHERE is_active = 1
                ORDER BY last_activity_at DESC
            """).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get active sessions: {e}")
        return []


def get_all_sessions(limit: int = 100) -> list[dict]:
    """Return recent sessions (active and historical)."""
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions
                ORDER BY connected_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get sessions: {e}")
        return []


def get_user_sessions(user_email: str, limit: int = 50) -> list[dict]:
    """Return sessions for a specific user."""
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions WHERE user_email = ?
                ORDER BY connected_at DESC LIMIT ?
            """, (user_email, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get user sessions: {e}")
        return []


def get_unique_users() -> list[dict]:
    """Return unique users with their latest session info."""
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT
                    user_email,
                    user_name,
                    user_role,
                    MAX(connected_at) as last_seen,
                    SUM(message_count) as total_messages,
                    COUNT(*) as session_count,
                    MAX(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as is_online,
                    (SELECT latitude FROM sessions s2
                     WHERE s2.user_email = s1.user_email
                     ORDER BY last_activity_at DESC LIMIT 1) as last_latitude,
                    (SELECT longitude FROM sessions s2
                     WHERE s2.user_email = s1.user_email
                     ORDER BY last_activity_at DESC LIMIT 1) as last_longitude,
                    (SELECT endpoint FROM sessions s2
                     WHERE s2.user_email = s1.user_email
                     ORDER BY last_activity_at DESC LIMIT 1) as last_endpoint
                FROM sessions s1
                WHERE user_email IS NOT NULL
                GROUP BY user_email
                ORDER BY last_seen DESC
            """).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to get unique users: {e}")
        return []
