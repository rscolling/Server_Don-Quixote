import os

DB_PATH = os.environ.get("DB_PATH", "/app/data/messagebus.db")
AGENT_SHARE_PATH = os.environ.get("AGENT_SHARE_PATH", "/agent-share")
PORT = int(os.environ.get("PORT", "8585"))
