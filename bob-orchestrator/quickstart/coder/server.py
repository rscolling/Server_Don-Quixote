"""Coder specialist agent — quickstart example.

A minimal FastMCP server that exposes two tools:
  - write_code(spec, language)
  - review_code(code, language)

BOB consumes these via his MCP client. The coder uses Claude (any
tool-calling model would work) and is intentionally focused — it doesn't
try to be a general assistant. It writes code and reviews code. That's it.

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
logger = logging.getLogger("coder")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CODER_MODEL = os.getenv("CODER_MODEL", "claude-sonnet-4-5")
PORT = int(os.getenv("CODER_PORT", "9002"))

if not ANTHROPIC_API_KEY:
    logger.warning("ANTHROPIC_API_KEY not set — coder tools will fail at runtime")

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

mcp = FastMCP("coder", instructions=(
    "A specialist agent that writes and reviews code. Call 'write_code' with "
    "a spec and a language to get a working implementation. Call 'review_code' "
    "with existing code and a language to get a structured review."
))


WRITE_SYSTEM_PROMPT = """You are a focused coding specialist agent. Your job is to take a spec \
and produce working code. You are NOT a general assistant — you only write code.

Rules:
1. Return ONLY code in the requested language. No prose explanations before or after.
2. The code must be self-contained and runnable as-is. No "fill in the blanks."
3. Include necessary imports.
4. Use clear variable names. No clever one-liners that obscure intent.
5. If the spec is ambiguous, make a reasonable choice and proceed. Don't ask clarifying questions.
6. Add brief inline comments only where the logic isn't self-evident.
7. If the spec requires external dependencies, use the most common idiomatic library.

Output format: a single code block with the language hint. Nothing else."""


REVIEW_SYSTEM_PROMPT = """You are a focused code reviewer. Your job is to take existing code and \
produce a structured review. You are NOT a general assistant — you only review code.

For every review, return:
1. A 1-sentence summary of what the code does
2. Strengths (2-4 bullet points)
3. Issues (ordered by severity: critical, important, minor)
4. Specific suggestions (concrete, actionable)
5. An overall rating: ship_it, needs_work, or rewrite

Be direct. No flattery. If the code is bad, say so. If it's good, say so."""


@mcp.tool()
def write_code(spec: str, language: str = "python") -> str:
    """Write code from a natural-language specification.

    Args:
        spec: What the code should do (e.g., "a function that takes a list of
              integers and returns the median, handling empty list and even-length")
        language: Target language (python, javascript, typescript, go, rust, bash, sql)
    """
    if not claude:
        return "Coder agent not configured: ANTHROPIC_API_KEY missing"

    try:
        response = claude.messages.create(
            model=CODER_MODEL,
            max_tokens=4096,
            system=WRITE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Language: {language}\n\nSpec: {spec}"}],
        )
        text = response.content[0].text
        logger.info(f"Wrote {language} code (spec_len={len(spec)}, code_len={len(text)})")
        return text
    except Exception as e:
        logger.error(f"write_code failed: {e}")
        return f"write_code failed: {e}"


@mcp.tool()
def review_code(code: str, language: str = "python") -> str:
    """Review existing code and return a structured assessment.

    Args:
        code: The code to review
        language: The language the code is in
    """
    if not claude:
        return "Coder agent not configured: ANTHROPIC_API_KEY missing"

    try:
        response = claude.messages.create(
            model=CODER_MODEL,
            max_tokens=2000,
            system=REVIEW_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Language: {language}\n\nCode:\n```{language}\n{code}\n```",
            }],
        )
        text = response.content[0].text
        logger.info(f"Reviewed {language} code (code_len={len(code)}, review_len={len(text)})")
        return f"# Code Review ({language})\n\n{text}\n\n_Reviewed at {datetime.now(timezone.utc).isoformat()} by coder agent_"
    except Exception as e:
        logger.error(f"review_code failed: {e}")
        return f"review_code failed: {e}"


@mcp.tool()
def list_supported_languages() -> str:
    """List the languages this coder agent is best at."""
    return (
        "I'm strongest in: Python, JavaScript, TypeScript, Go, Rust, Bash, "
        "SQL, HTML/CSS, and YAML/TOML/JSON config. I'll attempt other "
        "languages but the quality drops for niche ones (Forth, COBOL, "
        "APL, etc.). I do not write GPU shaders, smart contracts, or "
        "anything safety-critical."
    )


@mcp.resource("coder://about")
def about() -> str:
    """About this coder agent."""
    return (
        "Coder Agent — quickstart example specialist for BOB.\n\n"
        f"Model: {CODER_MODEL}\n"
        f"Port: {PORT}\n"
        "Transport: SSE\n\n"
        "Tools: write_code, review_code, list_supported_languages\n"
        "Purpose: Demonstrates the BOB specialist pattern via MCP."
    )


if __name__ == "__main__":
    if hasattr(mcp, "settings"):
        try:
            mcp.settings.host = "0.0.0.0"
            mcp.settings.port = PORT
        except Exception:
            pass

    logger.info(f"Coder agent starting on port {PORT} (model: {CODER_MODEL})")
    mcp.run(transport="sse")
