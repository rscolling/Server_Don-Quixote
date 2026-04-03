import json
import aiosqlite
from datetime import datetime, timezone
from app.config import DB_PATH

_db: aiosqlite.Connection | None = None
_on_change_callback = None


def set_on_change(callback):
    """Register a callback to be called after any mutation."""
    global _on_change_callback
    _on_change_callback = callback


async def _notify_change():
    if _on_change_callback:
        await _on_change_callback()

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender       TEXT NOT NULL,
    recipient    TEXT NOT NULL,
    message_type TEXT NOT NULL,
    priority     TEXT NOT NULL DEFAULT 'normal',
    payload      TEXT NOT NULL DEFAULT '{}',
    context      TEXT NOT NULL DEFAULT '{}',
    task_id      INTEGER,
    timestamp    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_recipient_ts ON messages(recipient, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_task_id ON messages(task_id);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    assignee    TEXT,
    state       TEXT NOT NULL DEFAULT 'CREATED',
    priority    TEXT NOT NULL DEFAULT 'normal',
    file_paths  TEXT DEFAULT '[]',
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);

CREATE TABLE IF NOT EXISTS agents (
    shorthand     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT DEFAULT '',
    status        TEXT DEFAULT 'active',
    registered_at TEXT NOT NULL,
    last_seen     TEXT
);
"""

# Idempotent migrations for peer-to-peer features (Phases 1-4)
MIGRATIONS = """
-- Phase 1: Threading
ALTER TABLE messages ADD COLUMN reply_to INTEGER DEFAULT NULL;
ALTER TABLE messages ADD COLUMN thread_id INTEGER DEFAULT NULL;

-- Phase 3: Topics
ALTER TABLE messages ADD COLUMN topic TEXT DEFAULT NULL;
"""

MIGRATION_TABLES = """
-- Phase 1: Acknowledgments
CREATE TABLE IF NOT EXISTS acks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    agent      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'received',
    acked_at   TEXT NOT NULL,
    UNIQUE(message_id, agent)
);
CREATE INDEX IF NOT EXISTS idx_acks_message ON acks(message_id);
CREATE INDEX IF NOT EXISTS idx_acks_agent ON acks(agent);

-- Phase 2: Capabilities
CREATE TABLE IF NOT EXISTS capabilities (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    agent    TEXT NOT NULL,
    name     TEXT NOT NULL,
    version  TEXT DEFAULT '1.0',
    metadata TEXT DEFAULT '{}',
    UNIQUE(agent, name)
);
CREATE INDEX IF NOT EXISTS idx_capabilities_name ON capabilities(name);

-- Phase 3: Subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT NOT NULL,
    topic      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(agent, topic)
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_topic ON subscriptions(topic);
CREATE INDEX IF NOT EXISTS idx_subscriptions_agent ON subscriptions(agent);

-- Phase 4: Task watchers
CREATE TABLE IF NOT EXISTS task_watchers (
    task_id INTEGER NOT NULL,
    agent   TEXT NOT NULL,
    PRIMARY KEY (task_id, agent)
);
CREATE INDEX IF NOT EXISTS idx_watchers_task ON task_watchers(task_id);
CREATE INDEX IF NOT EXISTS idx_watchers_agent ON task_watchers(agent);

-- Phase 1: Thread index
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);

-- Phase 3: Topic index
CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(topic);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    cols = await cursor.fetchall()
    return any(c[1] == column for c in cols)


async def _run_migrations(db: aiosqlite.Connection):
    """Run ALTER TABLE migrations idempotently."""
    migrations = [
        ("messages", "reply_to", "ALTER TABLE messages ADD COLUMN reply_to INTEGER DEFAULT NULL"),
        ("messages", "thread_id", "ALTER TABLE messages ADD COLUMN thread_id INTEGER DEFAULT NULL"),
        ("messages", "topic", "ALTER TABLE messages ADD COLUMN topic TEXT DEFAULT NULL"),
    ]
    for table, column, sql in migrations:
        if not await _column_exists(db, table, column):
            await db.execute(sql)
    await db.commit()


async def init_db():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.executescript(SCHEMA)
    await _db.commit()
    # Run column migrations idempotently
    await _run_migrations(_db)
    # Create new tables and indexes
    await _db.executescript(MIGRATION_TABLES)
    await _db.commit()


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized"
    return _db


# --- Message queries ---

async def insert_message(sender: str, recipient: str, message_type: str,
                         priority: str, payload: dict, context: dict,
                         task_id: int | None = None,
                         reply_to: int | None = None,
                         topic: str | None = None) -> dict:
    db = get_db()
    ts = now_iso()

    # Resolve threading
    thread_id = None
    if reply_to is not None:
        parent = await get_message(reply_to)
        if parent:
            thread_id = parent.get("thread_id") or parent["id"]

    cursor = await db.execute(
        """INSERT INTO messages (sender, recipient, message_type, priority,
           payload, context, task_id, timestamp, reply_to, thread_id, topic)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sender, recipient, message_type, priority,
         json.dumps(payload), json.dumps(context), task_id, ts,
         reply_to, thread_id, topic)
    )
    # Update agent last_seen in same transaction
    await db.execute(
        "UPDATE agents SET last_seen = ? WHERE shorthand = ?", (ts, sender)
    )
    await db.commit()
    result = await get_message(cursor.lastrowid)
    await _notify_change()
    return result


async def get_message(msg_id: int) -> dict | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
    row = await cursor.fetchone()
    return _row_to_message(row) if row else None


async def list_messages(sender: str | None = None, recipient: str | None = None,
                        message_type: str | None = None, since: str | None = None,
                        task_id: int | None = None, topic: str | None = None,
                        thread_id: int | None = None,
                        limit: int = 50, offset: int = 0) -> list[dict]:
    db = get_db()
    conditions = []
    params = []
    if sender:
        conditions.append("sender = ?")
        params.append(sender)
    if recipient:
        conditions.append("recipient = ?")
        params.append(recipient)
    if message_type:
        conditions.append("message_type = ?")
        params.append(message_type)
    if since:
        conditions.append("timestamp > ?")
        params.append(since)
    if task_id is not None:
        conditions.append("task_id = ?")
        params.append(task_id)
    if topic:
        conditions.append("topic = ?")
        params.append(topic)
    if thread_id is not None:
        conditions.append("thread_id = ?")
        params.append(thread_id)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM messages{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [_row_to_message(r) for r in rows]


async def poll_messages(agent: str, since: str, limit: int = 100) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        """SELECT * FROM messages
           WHERE ((recipient = ? OR recipient = 'ALL')
                  OR topic IN (SELECT topic FROM subscriptions WHERE agent = ?))
             AND timestamp > ?
           ORDER BY timestamp ASC
           LIMIT ?""",
        (agent, agent, since, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_message(r) for r in rows]


async def get_thread(thread_id: int) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        """SELECT * FROM messages
           WHERE thread_id = ? OR id = ?
           ORDER BY timestamp ASC""",
        (thread_id, thread_id)
    )
    rows = await cursor.fetchall()
    return [_row_to_message(r) for r in rows]


def _row_to_message(row) -> dict:
    return {
        "id": row["id"],
        "sender": row["sender"],
        "recipient": row["recipient"],
        "message_type": row["message_type"],
        "priority": row["priority"],
        "payload": json.loads(row["payload"]),
        "context": json.loads(row["context"]),
        "task_id": row["task_id"],
        "timestamp": row["timestamp"],
        "reply_to": row["reply_to"],
        "thread_id": row["thread_id"],
        "topic": row["topic"],
    }


# --- Ack queries ---

async def insert_ack(message_id: int, agent: str, status: str) -> dict:
    db = get_db()
    ts = now_iso()
    await db.execute(
        """INSERT INTO acks (message_id, agent, status, acked_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(message_id, agent) DO UPDATE SET
             status = excluded.status,
             acked_at = excluded.acked_at""",
        (message_id, agent, status, ts)
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM acks WHERE message_id = ? AND agent = ?",
        (message_id, agent)
    )
    row = await cursor.fetchone()
    await _notify_change()
    return _row_to_ack(row)


async def get_acks(message_id: int) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM acks WHERE message_id = ? ORDER BY acked_at",
        (message_id,)
    )
    rows = await cursor.fetchall()
    return [_row_to_ack(r) for r in rows]


def _row_to_ack(row) -> dict:
    return {
        "id": row["id"],
        "message_id": row["message_id"],
        "agent": row["agent"],
        "status": row["status"],
        "acked_at": row["acked_at"],
    }


# --- Task queries ---

async def insert_task(title: str, description: str, assignee: str | None,
                      priority: str, file_paths: list[str],
                      metadata: dict, watchers: list[str] | None = None) -> dict:
    db = get_db()
    ts = now_iso()
    cursor = await db.execute(
        """INSERT INTO tasks (title, description, assignee, state, priority, file_paths, metadata, created_at, updated_at)
           VALUES (?, ?, ?, 'CREATED', ?, ?, ?, ?, ?)""",
        (title, description, assignee, priority,
         json.dumps(file_paths), json.dumps(metadata), ts, ts)
    )
    await db.commit()
    task_id = cursor.lastrowid

    # Add watchers — always include assignee and ORCH
    watcher_set = set(watchers or [])
    if assignee:
        watcher_set.add(assignee)
    watcher_set.add("ORCH")
    for agent in watcher_set:
        await add_watcher(task_id, agent)

    result = await get_task(task_id)
    await _notify_change()
    return result


async def get_task(task_id: int) -> dict | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    task = _row_to_task(row)
    task["watchers"] = await list_watchers(task_id)
    return task


async def list_tasks(state: str | None = None, assignee: str | None = None,
                     priority: str | None = None, limit: int = 50,
                     offset: int = 0) -> list[dict]:
    db = get_db()
    conditions = []
    params = []
    if state:
        conditions.append("state = ?")
        params.append(state)
    if assignee:
        conditions.append("assignee = ?")
        params.append(assignee)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM tasks{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    tasks = []
    for r in rows:
        task = _row_to_task(r)
        task["watchers"] = await list_watchers(task["id"])
        tasks.append(task)
    return tasks


async def update_task(task_id: int, **kwargs) -> dict | None:
    db = get_db()
    sets = []
    params = []
    for key, val in kwargs.items():
        if val is not None:
            if key in ("file_paths", "metadata"):
                sets.append(f"{key} = ?")
                params.append(json.dumps(val))
            else:
                sets.append(f"{key} = ?")
                params.append(val)
    sets.append("updated_at = ?")
    params.append(now_iso())
    params.append(task_id)

    await db.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
    )
    await db.commit()
    result = await get_task(task_id)
    await _notify_change()
    return result


def _row_to_task(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "assignee": row["assignee"],
        "state": row["state"],
        "priority": row["priority"],
        "file_paths": json.loads(row["file_paths"]),
        "metadata": json.loads(row["metadata"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# --- Watcher queries ---

async def add_watcher(task_id: int, agent: str):
    db = get_db()
    await db.execute(
        """INSERT INTO task_watchers (task_id, agent) VALUES (?, ?)
           ON CONFLICT DO NOTHING""",
        (task_id, agent)
    )
    await db.commit()


async def remove_watcher(task_id: int, agent: str):
    db = get_db()
    await db.execute(
        "DELETE FROM task_watchers WHERE task_id = ? AND agent = ?",
        (task_id, agent)
    )
    await db.commit()


async def list_watchers(task_id: int) -> list[str]:
    db = get_db()
    cursor = await db.execute(
        "SELECT agent FROM task_watchers WHERE task_id = ? ORDER BY agent",
        (task_id,)
    )
    rows = await cursor.fetchall()
    return [r["agent"] for r in rows]


# --- Agent queries ---

async def upsert_agent(shorthand: str, name: str, role: str,
                       status: str) -> dict:
    db = get_db()
    ts = now_iso()
    await db.execute(
        """INSERT INTO agents (shorthand, name, role, status, registered_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(shorthand) DO UPDATE SET
             name = excluded.name,
             role = excluded.role,
             status = excluded.status""",
        (shorthand, name, role, status, ts)
    )
    await db.commit()
    result = await get_agent(shorthand)
    await _notify_change()
    return result


async def get_agent(shorthand: str) -> dict | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM agents WHERE shorthand = ?", (shorthand,))
    row = await cursor.fetchone()
    if not row:
        return None
    agent = _row_to_agent(row)
    agent["capabilities"] = await get_agent_capabilities(shorthand)
    return agent


async def list_agents() -> list[dict]:
    db = get_db()
    cursor = await db.execute("SELECT * FROM agents ORDER BY shorthand")
    rows = await cursor.fetchall()
    agents = []
    for r in rows:
        agent = _row_to_agent(r)
        agent["capabilities"] = await get_agent_capabilities(agent["shorthand"])
        agents.append(agent)
    return agents


def _row_to_agent(row) -> dict:
    last_seen = row["last_seen"]
    is_active = False
    if last_seen:
        try:
            seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            is_active = (datetime.now(timezone.utc) - seen_dt).total_seconds() < 300
        except ValueError:
            pass
    return {
        "shorthand": row["shorthand"],
        "name": row["name"],
        "role": row["role"],
        "status": row["status"],
        "registered_at": row["registered_at"],
        "last_seen": last_seen,
        "is_active": is_active,
    }


# --- Capability queries ---

async def upsert_capabilities(agent: str, capabilities: list[dict]):
    db = get_db()
    await db.execute("DELETE FROM capabilities WHERE agent = ?", (agent,))
    for cap in capabilities:
        await db.execute(
            """INSERT INTO capabilities (agent, name, version, metadata)
               VALUES (?, ?, ?, ?)""",
            (agent, cap["name"], cap.get("version", "1.0"),
             json.dumps(cap.get("metadata", {})))
        )
    await db.commit()
    await _notify_change()


async def get_agent_capabilities(agent: str) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM capabilities WHERE agent = ? ORDER BY name",
        (agent,)
    )
    rows = await cursor.fetchall()
    return [_row_to_capability(r) for r in rows]


async def list_all_capabilities() -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        """SELECT DISTINCT name, GROUP_CONCAT(agent) as agents
           FROM capabilities GROUP BY name ORDER BY name"""
    )
    rows = await cursor.fetchall()
    return [{"name": r["name"], "agents": r["agents"].split(",")} for r in rows]


async def find_agents_by_capability(capability_name: str) -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        """SELECT a.* FROM agents a
           INNER JOIN capabilities c ON a.shorthand = c.agent
           WHERE c.name = ?
           ORDER BY a.shorthand""",
        (capability_name,)
    )
    rows = await cursor.fetchall()
    agents = []
    for r in rows:
        agent = _row_to_agent(r)
        agent["capabilities"] = await get_agent_capabilities(agent["shorthand"])
        agents.append(agent)
    return agents


def _row_to_capability(row) -> dict:
    return {
        "id": row["id"],
        "agent": row["agent"],
        "name": row["name"],
        "version": row["version"],
        "metadata": json.loads(row["metadata"]),
    }


# --- Subscription queries ---

async def subscribe(agent: str, topic: str) -> dict:
    db = get_db()
    ts = now_iso()
    await db.execute(
        """INSERT INTO subscriptions (agent, topic, created_at)
           VALUES (?, ?, ?)
           ON CONFLICT(agent, topic) DO NOTHING""",
        (agent, topic, ts)
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM subscriptions WHERE agent = ? AND topic = ?",
        (agent, topic)
    )
    row = await cursor.fetchone()
    await _notify_change()
    return _row_to_subscription(row)


async def unsubscribe(agent: str, topic: str):
    db = get_db()
    await db.execute(
        "DELETE FROM subscriptions WHERE agent = ? AND topic = ?",
        (agent, topic)
    )
    await db.commit()
    await _notify_change()


async def list_subscriptions(agent: str | None = None,
                              topic: str | None = None) -> list[dict]:
    db = get_db()
    conditions = []
    params = []
    if agent:
        conditions.append("agent = ?")
        params.append(agent)
    if topic:
        conditions.append("topic = ?")
        params.append(topic)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    cursor = await db.execute(
        f"SELECT * FROM subscriptions{where} ORDER BY created_at", params
    )
    rows = await cursor.fetchall()
    return [_row_to_subscription(r) for r in rows]


async def list_topics() -> list[dict]:
    db = get_db()
    cursor = await db.execute(
        """SELECT topic, COUNT(*) as subscriber_count,
                  GROUP_CONCAT(agent) as subscribers
           FROM subscriptions GROUP BY topic ORDER BY topic"""
    )
    rows = await cursor.fetchall()
    return [
        {
            "topic": r["topic"],
            "subscriber_count": r["subscriber_count"],
            "subscribers": r["subscribers"].split(","),
        }
        for r in rows
    ]


def _row_to_subscription(row) -> dict:
    return {
        "id": row["id"],
        "agent": row["agent"],
        "topic": row["topic"],
        "created_at": row["created_at"],
    }


# --- Stats queries ---

async def get_stats() -> dict:
    db = get_db()

    cursor = await db.execute("SELECT COUNT(*) as total FROM messages")
    msg_total = (await cursor.fetchone())["total"]

    cursor = await db.execute(
        "SELECT message_type, COUNT(*) as count FROM messages GROUP BY message_type"
    )
    msg_by_type = {r["message_type"]: r["count"] for r in await cursor.fetchall()}

    cursor = await db.execute("SELECT COUNT(*) as total FROM tasks")
    task_total = (await cursor.fetchone())["total"]

    cursor = await db.execute(
        "SELECT state, COUNT(*) as count FROM tasks GROUP BY state"
    )
    tasks_by_state = {r["state"]: r["count"] for r in await cursor.fetchall()}

    agents = await list_agents()
    active_count = sum(1 for a in agents if a["is_active"])

    cursor = await db.execute("SELECT COUNT(*) as total FROM subscriptions")
    sub_total = (await cursor.fetchone())["total"]

    cursor = await db.execute("SELECT COUNT(DISTINCT topic) as total FROM subscriptions")
    topic_total = (await cursor.fetchone())["total"]

    return {
        "messages": {"total": msg_total, "by_type": msg_by_type},
        "tasks": {"total": task_total, "by_state": tasks_by_state},
        "agents": {"total": len(agents), "active": active_count},
        "subscriptions": {"total": sub_total, "topics": topic_total},
    }
