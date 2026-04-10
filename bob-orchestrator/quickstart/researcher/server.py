"""Researcher specialist agent — quickstart example.

A minimal FastMCP server that exposes a single tool: research(topic).
BOB consumes this via his MCP client.

The researcher uses Claude (any tool-calling model would work) to answer
research questions and return structured findings. It demonstrates the
specialist-agent pattern: a small focused service that does one thing well
and exposes it via MCP.

Run standalone:
    python server.py

Or via docker compose (see ../docker-compose.yml).
"""

import logging
import os
from datetime import datetime, timezone

import anthropic
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("researcher")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RESEARCHER_MODEL = os.getenv("RESEARCHER_MODEL", "claude-haiku-4-5")
PORT = int(os.getenv("RESEARCHER_PORT", "9001"))

if not ANTHROPIC_API_KEY:
    logger.warning("ANTHROPIC_API_KEY not set — research tool will fail at runtime")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

mcp = FastMCP("researcher", instructions=(
    "A specialist agent that does focused research. Call the 'research' tool "
    "with a topic and optional depth. Returns structured findings: summary, "
    "key facts, and follow-up questions."
))


SYSTEM_PROMPT = """You are a focused research specialist agent. Your job is to take a research \
topic and produce a structured, accurate response. You are NOT a general assistant — you only \
do research.

For every research request, return:
1. A 2-3 sentence summary of the topic
2. 4-6 key facts (each one short, verifiable, attributed if possible)
3. 2-3 follow-up questions a thoughtful person would ask next

Keep responses concise. Avoid speculation. If you don't know something, say so. If the topic is \
too broad, suggest a narrower scope.

Format your response as plain text with clear section headers."""


@mcp.tool()
def research(topic: str, depth: str = "standard") -> str:
    """Research a topic and return structured findings.

    Args:
        topic: The subject to research (e.g., "Cloudflare Zero Trust pricing tiers")
        depth: 'quick' (2-3 facts), 'standard' (4-6 facts), or 'deep' (8-12 facts)
    """
    if not claude:
        return "Researcher agent not configured: ANTHROPIC_API_KEY missing"

    fact_count = {"quick": "2-3", "standard": "4-6", "deep": "8-12"}.get(depth, "4-6")
    user_message = (
        f"Research this topic: {topic}\n\n"
        f"Return {fact_count} key facts. Focus on what someone making a decision "
        f"about this topic would actually need to know."
    )

    try:
        response = claude.messages.create(
            model=RESEARCHER_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text
        logger.info(f"Researched '{topic}' (depth={depth}, len={len(text)})")
        return f"# Research: {topic}\n\n{text}\n\n_Researched at {datetime.now(timezone.utc).isoformat()} by researcher agent_"
    except Exception as e:
        logger.error(f"Research failed: {e}")
        return f"Research failed: {e}"


@mcp.tool()
def list_research_capabilities() -> str:
    """List what kinds of research this agent is good at."""
    return (
        "I do focused research on: technology, products, companies, "
        "frameworks, APIs, pricing, market analysis, technical concepts, "
        "and historical context. I'm not great at: real-time news, "
        "personal advice, anything requiring web browsing (I work from "
        "the model's training data only), or anything outside the "
        "language model's knowledge cutoff."
    )


@mcp.resource("researcher://about")
def about() -> str:
    """About this researcher agent."""
    return (
        "Researcher Agent — quickstart example specialist for BOB.\n\n"
        f"Model: {RESEARCHER_MODEL}\n"
        f"Port: {PORT}\n"
        "Transport: SSE\n\n"
        "Tools: research, list_research_capabilities\n"
        "Purpose: Demonstrates the BOB specialist pattern via MCP."
    )


if __name__ == "__main__":
    # FastMCP settings for SSE transport
    if hasattr(mcp, "settings"):
        try:
            mcp.settings.host = "0.0.0.0"
            mcp.settings.port = PORT
        except Exception:
            pass

    logger.info(f"Researcher agent starting on port {PORT} (model: {RESEARCHER_MODEL})")
    mcp.run(transport="sse")
