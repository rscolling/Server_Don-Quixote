"""Request router — picks light or heavy model tier per message.

Two-phase classification:
1. Fast heuristic (regex + keyword matching) — ~0ms, handles ~80% of traffic
2. Optional LLM fallback (Haiku call) — ~200ms, handles ambiguous cases

Tiers:
- LIGHT: simple greetings, status checks, yes/no questions, recall/lookup
- HEAVY: multi-step reasoning, tool-needing requests, creative tasks, analysis
"""

import logging
import re
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("bob.router")


class Tier(str, Enum):
    LIGHT = "light"
    HEAVY = "heavy"


@dataclass
class RoutingDecision:
    tier: Tier
    reason: str        # Human-readable explanation for logs
    method: str        # "heuristic" or "classifier"
    confidence: float  # 0.0–1.0


# ── Provider-specific default models per tier ──────────────────────────────
TIER_DEFAULTS = {
    "light": {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai": "gpt-4o-mini",
        "ollama": "qwen2.5:14b",
    },
    "heavy": {
        "anthropic": "claude-sonnet-4-20250514",
        "openai": "gpt-4o",
        "ollama": "qwen2.5:32b",
    },
}


def get_tier_model(tier: Tier, provider: str, config_override: str = "") -> str:
    """Resolve a tier to a concrete model name."""
    if config_override:
        return config_override
    return TIER_DEFAULTS[tier.value].get(provider, TIER_DEFAULTS[tier.value]["anthropic"])


# ── Heuristic classifier (Phase 1) ────────────────────────────────────────

# Patterns that strongly indicate LIGHT tier
_LIGHT_PATTERNS = [
    re.compile(r"^\s*(hi|hello|hey|yo|sup|morning|evening|good\s+(morning|afternoon|evening))\b", re.I),
    re.compile(r"^\s*(thanks|thank you|thx|cheers|bye|goodbye|later|peace)\b", re.I),
    re.compile(r"^\s*(yes|no|yep|nope|ok|okay|sure|fine|got it|understood)\s*[.!?]?\s*$", re.I),
    re.compile(r"^\s*what\s+time\b", re.I),
    re.compile(r"^\s*(how\s+are\s+you|what'?s?\s+up|how'?s?\s+it\s+going)", re.I),
    re.compile(r"^\s*(status|health|uptime)\s*\??\s*$", re.I),
]

# Keywords/phrases that strongly indicate HEAVY tier (tool use or complex reasoning)
_HEAVY_KEYWORDS = [
    # Tool-triggering intents
    "search", "look up", "find", "google", "web search",
    "email", "check email", "send email", "inbox", "gmail",
    "photo", "upload", "image", "picture", "analyze photo",
    "weather", "forecast",
    "create task", "delegate", "assign", "send to",
    "schedule", "remind me", "set a reminder", "cron",
    "notify", "alert", "push notification",
    "remember this", "store", "save to memory",
    "briefing", "daily report", "generate report",
    "promote", "promotion", "approve", "reject",
    "deploy", "server", "infrastructure",
    # Complex reasoning indicators
    "compare", "analyze", "explain why", "pros and cons",
    "write", "draft", "compose", "create content",
    "plan", "strategy", "roadmap", "design",
    "debug", "troubleshoot", "investigate",
    "summarize", "break down", "step by step",
    "calculate", "estimate", "how much",
    "what should", "what would", "recommend",
    "research", "deep dive",
]

# Compile heavy keywords into a single regex for speed
_HEAVY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in _HEAVY_KEYWORDS) + r")\b",
    re.I,
)


def _heuristic_classify(message: str) -> RoutingDecision | None:
    """Fast regex/keyword classification. Returns None if ambiguous."""
    text = message.strip()

    # Very short messages (under 15 chars) matching light patterns
    if len(text) < 15:
        for pat in _LIGHT_PATTERNS:
            if pat.search(text):
                return RoutingDecision(Tier.LIGHT, "short greeting/ack", "heuristic", 0.95)

    # Check for explicit light patterns
    for pat in _LIGHT_PATTERNS:
        if pat.match(text):
            return RoutingDecision(Tier.LIGHT, "greeting/simple pattern", "heuristic", 0.90)

    # Check for heavy keywords
    matches = _HEAVY_PATTERN.findall(text)
    if matches:
        return RoutingDecision(Tier.HEAVY, f"tool/complex keyword: {matches[0]}", "heuristic", 0.85)

    # Question mark with more than ~40 chars suggests a substantive question
    if "?" in text and len(text) > 40:
        return RoutingDecision(Tier.HEAVY, "substantive question (length + ?)", "heuristic", 0.65)

    # Multi-sentence messages (3+ sentences) lean heavy
    sentence_count = len([s for s in re.split(r'[.!?]+', text.strip()) if s.strip()])
    if sentence_count >= 3:
        return RoutingDecision(Tier.HEAVY, f"multi-sentence ({sentence_count})", "heuristic", 0.70)

    # Ambiguous — return None to trigger LLM fallback
    return None


# ── LLM classifier (Phase 2 — fallback) ───────────────────────────────────

_CLASSIFIER_PROMPT = """Classify this user message as LIGHT or HEAVY.

LIGHT: greetings, simple factual questions, yes/no, status checks, acknowledgments, small talk.
HEAVY: needs tools (email, search, photos, tasks, scheduling), multi-step reasoning, content creation, analysis, planning, debugging.

Respond with exactly one word: LIGHT or HEAVY

Message: {message}"""


async def _llm_classify(message: str, provider: str, api_key: str = "") -> RoutingDecision:
    """Use a cheap Haiku/mini call to classify ambiguous messages."""
    from app.llm import get_llm
    from app.config import BOB_CLASSIFIER_MAX_TOKENS, BOB_LLM_BASE_URL, BOB_LLM_API_KEY

    light_model = get_tier_model(Tier.LIGHT, provider)
    try:
        llm = get_llm(
            provider=provider,
            model=light_model,
            max_tokens=BOB_CLASSIFIER_MAX_TOKENS,
            temperature=0.0,
            base_url=BOB_LLM_BASE_URL or None,
            api_key=api_key or BOB_LLM_API_KEY or None,
        )
        resp = await llm.ainvoke(_CLASSIFIER_PROMPT.format(message=message[:500]))
        answer = resp.content.strip().upper() if hasattr(resp, "content") else "HEAVY"

        if "LIGHT" in answer:
            return RoutingDecision(Tier.LIGHT, "LLM classified as light", "classifier", 0.80)
        else:
            return RoutingDecision(Tier.HEAVY, "LLM classified as heavy", "classifier", 0.80)
    except Exception as e:
        logger.warning(f"LLM classifier failed ({e}), defaulting to HEAVY")
        return RoutingDecision(Tier.HEAVY, f"classifier error, defaulting heavy: {e}", "classifier", 0.50)


# ── Public API ─────────────────────────────────────────────────────────────

async def classify(message: str, provider: str, api_key: str = "") -> RoutingDecision:
    """Classify a message into a routing tier.

    Phase 1: heuristic (instant, free).
    Phase 2: LLM fallback if heuristic is ambiguous.
    """
    decision = _heuristic_classify(message)
    if decision is not None:
        logger.info(f"Router: {decision.tier.value} (heuristic, {decision.reason})")
        return decision

    decision = await _llm_classify(message, provider, api_key)
    logger.info(f"Router: {decision.tier.value} (classifier, {decision.reason})")
    return decision
