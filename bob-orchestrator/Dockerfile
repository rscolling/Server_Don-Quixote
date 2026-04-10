# BOB — Bound Operational Brain
# Production Dockerfile. See README.md for the build context.

FROM python:3.12-slim

# System dependencies — only what BOB actually needs at runtime.
# curl is used for the healthcheck. Everything else is Python.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies in a separate layer so changes to app/ code
# don't invalidate the pip cache.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code last so source changes only invalidate this layer.
COPY bob_context/ /app/bob_context/
COPY app/ /app/app/

# Dashboard static files (pre-built React SPA)
COPY dashboard/dist/ /app/dashboard/dist/

# Create the data directory and ensure it's writable by the runtime user.
RUN mkdir -p /app/data && chmod 755 /app/data

# Expose the FastAPI orchestrator and the MCP server.
EXPOSE 8100 8108

# Healthcheck pings the /health endpoint. BOB serves it as soon as the
# graph is ready, which is typically <10s after container start.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

# Run uvicorn directly. No supervisor, no multi-process — BOB is one process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
