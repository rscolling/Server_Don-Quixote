"""BOB configuration — all env vars and constants."""

import os

# Core
BOB_PORT = int(os.getenv("BOB_PORT", "8100"))

# ── LLM provider (model-agnostic adapter) ──────────────────────────────────
# Provider: anthropic | openai | ollama
BOB_LLM_PROVIDER = os.getenv("BOB_LLM_PROVIDER", "anthropic").lower()
# Model name (interpreted per provider — see app/llm.py for defaults)
BOB_MODEL = os.getenv("BOB_MODEL", "")  # Empty = use the provider's default model
BOB_LLM_MAX_TOKENS = int(os.getenv("BOB_LLM_MAX_TOKENS", "8192"))
BOB_LLM_TEMPERATURE = os.getenv("BOB_LLM_TEMPERATURE", "")  # Empty = provider default
BOB_LLM_BASE_URL = os.getenv("BOB_LLM_BASE_URL", "")  # Override endpoint (vLLM, LiteLLM, custom Ollama)
BOB_LLM_API_KEY = os.getenv("BOB_LLM_API_KEY", "")  # Generic fallback if provider-specific key not set

# ── Model routing (auto tier selection per request) ───────────────────────
BOB_ROUTING_ENABLED = os.getenv("BOB_ROUTING_ENABLED", "true").lower() == "true"
BOB_MODEL_LIGHT = os.getenv("BOB_MODEL_LIGHT", "")   # Empty = auto per provider
BOB_MODEL_HEAVY = os.getenv("BOB_MODEL_HEAVY", "")   # Empty = auto per provider
BOB_MODEL_DEEP = os.getenv("BOB_MODEL_DEEP", "")     # Deep-research tier (Opus). Empty = auto per provider
BOB_CLASSIFIER_MAX_TOKENS = int(os.getenv("BOB_CLASSIFIER_MAX_TOKENS", "20"))

# Deep-research ($$$ guardrail): daily cap on Opus-class spend.
# Set to 0 to disable the model-specific cap (total daily budget still applies).
DAILY_BUDGET_USD_OPUS = float(os.getenv("DAILY_BUDGET_USD_OPUS", "5.00"))
OPUS_BUDGET_ALERT_FRACTION = float(os.getenv("OPUS_BUDGET_ALERT_FRACTION", "0.80"))

# Provider-specific keys (each takes precedence over BOB_LLM_API_KEY for its provider)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

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

# Personality (sardonic | neutral | terse | <custom>)
BOB_PERSONALITY = os.getenv("BOB_PERSONALITY", "sardonic").lower()
BOB_PERSONALITIES_DIR = os.getenv("BOB_PERSONALITIES_DIR", f"{CONTEXT_DIR}/personalities")

# Bus offline queue
BUS_QUEUE_DB_PATH = os.getenv("BUS_QUEUE_DB_PATH", f"{DATA_DIR}/bus-queue.db")

# Memory proposals
PROPOSALS_DB_PATH = os.getenv("PROPOSALS_DB_PATH", f"{DATA_DIR}/memory-proposals.db")

# Firewall audit log
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", f"{DATA_DIR}/bob-audit.jsonl")

# Photo intake (smartphone vision uploads)
PHOTOS_DIR = os.getenv("PHOTOS_DIR", f"{DATA_DIR}/photos")
PHOTOS_DB_PATH = os.getenv("PHOTOS_DB_PATH", f"{DATA_DIR}/photos.db")
MAX_PHOTO_SIZE_BYTES = int(os.getenv("MAX_PHOTO_SIZE_BYTES", str(20 * 1024 * 1024)))
PHOTO_TEMP_TTL_SECONDS = int(os.getenv("PHOTO_TEMP_TTL_SECONDS", "60"))

# Timeouts (seconds)
SERVICE_TIMEOUT = float(os.getenv("SERVICE_TIMEOUT", "30.0"))
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "5.0"))
EXTERNAL_API_TIMEOUT = float(os.getenv("EXTERNAL_API_TIMEOUT", "10.0"))

# Rate limiting
CHAT_RATE_LIMIT_PER_MIN = int(os.getenv("CHAT_RATE_LIMIT_PER_MIN", "10"))
CHAT_RATE_LIMIT_PER_HOUR = int(os.getenv("CHAT_RATE_LIMIT_PER_HOUR", "60"))

# ── MCP (Model Context Protocol) ────────────────────────────────────────────

# MCP client — fetch tools from external MCP servers
# Path to a JSON file listing MCP servers BOB should connect to as a client.
# See mcp_servers.example.json for the format.
MCP_CLIENT_CONFIG_PATH = os.getenv("MCP_CLIENT_CONFIG_PATH", f"{DATA_DIR}/mcp_servers.json")
MCP_CLIENT_ENABLED = os.getenv("MCP_CLIENT_ENABLED", "true").lower() == "true"
MCP_CLIENT_FETCH_TIMEOUT = float(os.getenv("MCP_CLIENT_FETCH_TIMEOUT", "15.0"))

# MCP server — expose BOB's high-level capabilities as MCP tools
# Other AI clients (Claude Desktop, Cursor, goose, etc.) can call BOB via this.
MCP_SERVER_ENABLED = os.getenv("MCP_SERVER_ENABLED", "true").lower() == "true"
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8108"))  # 8101-8104 reserved for debate arena
MCP_SERVER_AUTH_TOKEN = os.getenv("MCP_SERVER_AUTH_TOKEN", "")  # Bearer token; empty = no auth (CF Tunnel handles outer)
MCP_SERVER_TRANSPORT = os.getenv("MCP_SERVER_TRANSPORT", "sse")  # "sse" or "streamable-http"

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

    # Validate LLM provider config
    provider = BOB_LLM_PROVIDER
    if provider not in ("anthropic", "openai", "ollama"):
        errors.append(
            f"BOB_LLM_PROVIDER='{provider}' is not supported. "
            f"Use one of: anthropic, openai, ollama"
        )
    elif provider == "anthropic":
        if not ANTHROPIC_API_KEY and not BOB_LLM_API_KEY:
            errors.append(
                "ANTHROPIC_API_KEY (or BOB_LLM_API_KEY) is not set "
                "but BOB_LLM_PROVIDER is 'anthropic'"
            )
    elif provider == "openai":
        # OpenAI may use a custom base_url (vLLM, LiteLLM) which doesn't need a real key
        if not OPENAI_API_KEY and not BOB_LLM_API_KEY and not BOB_LLM_BASE_URL:
            errors.append(
                "OPENAI_API_KEY (or BOB_LLM_API_KEY) is not set "
                "but BOB_LLM_PROVIDER is 'openai' and no BOB_LLM_BASE_URL "
                "is configured for a self-hosted OpenAI-compatible endpoint"
            )
    # Ollama needs no API key — it talks to a local daemon

    return errors
