"""BOB configuration — all env vars and constants."""

import os

# Core
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BOB_MODEL = os.getenv("BOB_MODEL", "claude-sonnet-4-20250514")
BOB_PORT = int(os.getenv("BOB_PORT", "8100"))

# Message Bus
MESSAGE_BUS_URL = os.getenv("MESSAGE_BUS_URL", "http://message-bus:8585")

# ChromaDB
CHROMADB_URL = os.getenv("CHROMADB_URL", "http://chromadb:8000")

# Langfuse (optional — graceful if missing)
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")

# Data directory — all SQLite DBs and logs live here
DATA_DIR = os.getenv("BOB_DATA_DIR", "/app/data")

# Checkpointer (persistent conversation history)
CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", f"{DATA_DIR}/bob-threads.db")

# Scheduler
SCHEDULER_DB_PATH = os.getenv("SCHEDULER_DB_PATH", f"sqlite:///{DATA_DIR}/scheduler_jobs.db")
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "America/New_York")
REPORT_HOUR = int(os.getenv("BOB_REPORT_HOUR", "8"))
REPORT_MINUTE = int(os.getenv("BOB_REPORT_MINUTE", "0"))

# Context files
CONTEXT_DIR = os.getenv("BOB_CONTEXT_DIR", "/app/bob_context")

# Bus offline queue
BUS_QUEUE_DB_PATH = os.getenv("BUS_QUEUE_DB_PATH", f"{DATA_DIR}/bus-queue.db")

# Memory proposals
PROPOSALS_DB_PATH = os.getenv("PROPOSALS_DB_PATH", f"{DATA_DIR}/memory-proposals.db")

# Firewall audit log
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", f"{DATA_DIR}/bob-audit.jsonl")

# Timeouts (seconds)
SERVICE_TIMEOUT = float(os.getenv("SERVICE_TIMEOUT", "30.0"))
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "5.0"))
EXTERNAL_API_TIMEOUT = float(os.getenv("EXTERNAL_API_TIMEOUT", "10.0"))

# Rate limiting
CHAT_RATE_LIMIT_PER_MIN = int(os.getenv("CHAT_RATE_LIMIT_PER_MIN", "10"))
CHAT_RATE_LIMIT_PER_HOUR = int(os.getenv("CHAT_RATE_LIMIT_PER_HOUR", "60"))

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", (
    "https://appalachiantoysgames.com,"
    "https://www.appalachiantoysgames.com,"
    "https://voice.appalachiantoysgames.com,"
    "https://bob.appalachiantoysgames.com,"
    "http://192.168.1.228:8100,"
    "http://192.168.1.228:8200,"
    "http://localhost:8100"
)).split(",")


def validate_config():
    """Check required config at startup. Returns list of errors."""
    errors = []
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set")
    return errors
