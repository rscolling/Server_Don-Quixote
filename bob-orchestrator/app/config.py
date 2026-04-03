"""BOB configuration — all env vars and constants."""

import os

# Core
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
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

# Scheduler
REPORT_HOUR = int(os.getenv("BOB_REPORT_HOUR", "8"))
REPORT_MINUTE = int(os.getenv("BOB_REPORT_MINUTE", "0"))

# Context files
CONTEXT_DIR = os.getenv("BOB_CONTEXT_DIR", "/app/bob_context")
