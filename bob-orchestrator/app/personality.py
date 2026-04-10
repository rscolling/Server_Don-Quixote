"""Personality config layer.

BOB's personality is load-bearing — sardonic, push-back-prone, conditionally
loyal. But not every operator wants that. Some need a neutral assistant that
doesn't push back, some want their own custom voice entirely.

This module loads a personality file from disk based on the BOB_PERSONALITY
env var and returns its contents to be injected into the system prompt.

Personalities live in `bob_context/personalities/<name>.md`. The directory
ships with three:
  - sardonic   (default — the canonical BOB)
  - neutral    (no personality, stripped to facts)
  - terse      (sardonic but minimal — for voice / chat where length matters)

Operators can drop in their own `<name>.md` and reference it via the env var.

The personality file format is just a markdown document. Whatever is in the
file gets prepended to the system prompt. The "00_" prefix ensures it loads
first in the existing graph.py context loader.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("bob.personality")


PERSONALITY_NAME = os.getenv("BOB_PERSONALITY", "sardonic").lower().strip()
PERSONALITIES_DIR = os.getenv(
    "BOB_PERSONALITIES_DIR",
    "/app/bob_context/personalities",
)

# Fallback content if no personality file is found at all. Generic, neutral.
FALLBACK_PERSONALITY = """\
# Operational Brain

You are an AI orchestrator. Your job is to help the operator manage a
multi-agent system. Be direct, accurate, and honest about uncertainty.
Push back on requests that are likely to fail. Complete tasks first;
editorialize after if needed.
"""


def get_personality_text() -> tuple[str, str]:
    """Load the active personality file. Returns (name_used, text).

    Resolution order:
    1. {PERSONALITIES_DIR}/{PERSONALITY_NAME}.md
    2. /app/bob_context/00_personality.md (legacy default location)
    3. The hardcoded FALLBACK_PERSONALITY constant above
    """
    # Step 1: try the configured personalities directory
    candidate = Path(PERSONALITIES_DIR) / f"{PERSONALITY_NAME}.md"
    if candidate.exists():
        try:
            text = candidate.read_text(encoding="utf-8")
            logger.info(f"Loaded personality '{PERSONALITY_NAME}' from {candidate}")
            return PERSONALITY_NAME, text
        except Exception as e:
            logger.warning(f"Failed to read personality file {candidate}: {e}")

    # Step 2: legacy file at the old location
    legacy_path = Path("/app/bob_context/00_personality.md")
    if legacy_path.exists():
        try:
            text = legacy_path.read_text(encoding="utf-8")
            logger.info(f"Loaded legacy personality from {legacy_path}")
            return "legacy", text
        except Exception as e:
            logger.warning(f"Failed to read legacy personality: {e}")

    # Step 3: hardcoded fallback
    logger.warning(
        f"No personality file found for '{PERSONALITY_NAME}' "
        f"(checked {PERSONALITIES_DIR} and legacy location). Using fallback."
    )
    return "fallback", FALLBACK_PERSONALITY


def list_available_personalities() -> list[dict]:
    """List all personalities available in the personalities directory.

    Returns list of dicts with name, path, size, and a one-line preview.
    Used by the /personality/status endpoint.
    """
    result = []
    pdir = Path(PERSONALITIES_DIR)
    if not pdir.exists():
        return result
    try:
        for path in sorted(pdir.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")
                # First non-empty line, stripped of markdown header markup
                preview = ""
                for line in content.splitlines():
                    line = line.strip().lstrip("#").strip()
                    if line:
                        preview = line[:120]
                        break
                result.append({
                    "name": path.stem,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "preview": preview,
                    "active": path.stem == PERSONALITY_NAME,
                })
            except Exception as e:
                logger.warning(f"Failed to read personality {path}: {e}")
    except Exception as e:
        logger.error(f"Failed to list personalities: {e}")
    return result


def status() -> dict:
    """Return personality status for the /health and /personality endpoints."""
    name, text = get_personality_text()
    return {
        "active": PERSONALITY_NAME,
        "loaded_from": name,
        "personalities_dir": PERSONALITIES_DIR,
        "loaded_size_bytes": len(text.encode("utf-8")),
        "available": list_available_personalities(),
    }
