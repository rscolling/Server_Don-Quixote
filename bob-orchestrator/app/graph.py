"""BOB's LangGraph agent — the brain."""

import logging
import os
from langgraph.prebuilt import create_react_agent
from app.config import (CONTEXT_DIR, BOB_LLM_PROVIDER, BOB_MODEL,
                        BOB_LLM_MAX_TOKENS, BOB_LLM_TEMPERATURE,
                        BOB_LLM_BASE_URL, BOB_LLM_API_KEY,
                        LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST)
from app.llm import get_llm
from app.tools import ALL_TOOLS

logger = logging.getLogger("bob")


def _load_context() -> str:
    """Load context files from bob_context/ into the system prompt.

    Personality is loaded first via the personality module (which respects
    BOB_PERSONALITY env var). The legacy 00_personality.md is skipped here
    because the personality module loads it directly. All other markdown
    files in bob_context/ (mission, parking lot, etc.) are loaded after.
    """
    from app.personality import get_personality_text

    context_parts = []

    # Load the active personality first (sardonic, neutral, terse, or custom)
    personality_name, personality_text = get_personality_text()
    context_parts.append(f"--- personality ({personality_name}) ---\n{personality_text}")

    # Load all other context files, skipping the legacy personality and the
    # personalities/ subdirectory (which the personality module handles)
    SKIP_FILES = {"00_personality.md", "personality.md"}
    if os.path.isdir(CONTEXT_DIR):
        for filename in sorted(os.listdir(CONTEXT_DIR)):
            if not filename.endswith(".md"):
                continue
            if filename in SKIP_FILES:
                continue
            filepath = os.path.join(CONTEXT_DIR, filename)
            if not os.path.isfile(filepath):
                continue
            try:
                with open(filepath, encoding="utf-8") as f:
                    context_parts.append(f"--- {filename} ---\n{f.read()}")
            except Exception as e:
                logger.warning(f"Failed to load context file {filename}: {e}")

    return "\n\n".join(context_parts)


SYSTEM_PROMPT = """{context}

## Your Role
You are Rob's primary interface to the entire ATG agent infrastructure. You:
1. Receive instructions from Rob and decide what to handle directly vs delegate
2. Create tasks on the message bus and assign them to agent teams
3. Monitor debate progress and intervene on escalation
4. Store and retrieve shared knowledge in ChromaDB collections
5. Surface alerts, daily reports, and escalations
6. Track ElevenLabs voice usage and flag cost risks

## Infrastructure
- Message Bus at :8585 — nervous system connecting all agents
- Debate Arena (the Business Operations team):
  - PM (8101) — task classification, debate routing, escalation
  - RA (8102) — research, market data, competitor analysis
  - CE (8103) — content / copy writing and editing
  - QA (8104) — adversarial quality gate
  - SE (8105) — systems engineering, infrastructure, deployment planning
  - RE (8106) — reliability engineering, ops risk, on-call thinking
  - FE (8107) — front-end engineer: HTML/CSS/JS, static sites, UI implementation
  - BE (8109) — back-end engineer: APIs, services, agent containers, schemas
- ChromaDB at :8000 — shared memory (brand_voice, decisions, research, product_specs, project_context)
- You are at :8100

## Agent Teams
The debate arena is the **core team of the business** — not a marketing-only crew. It
handles the full operational stack: marketing/content, research, infrastructure, and
real software engineering (front-end and back-end). PM classifies each incoming task
and routes it to the right primary agent based on type (content/visual/research/seo/
infrastructure/frontend_dev/backend_dev), with appropriate critics in the loop.

Routing taxonomy:
- content / campaign / seo  →  CE (with RA, QA critics)
- research                   →  RA (with CE, QA critics)
- infrastructure             →  SE (with RE final critic)
- frontend_dev               →  FE (with BE, QA critics)
- backend_dev                →  BE (with FE, SE, QA critics)

To delegate work: create a task on the bus. PM picks it up automatically and routes it.

## Memory Collections
- brand_voice: ATG brand guidelines, tone, colors
- decisions: Major decisions by Rob (dated)
- research: Agent findings — market data, competitors
- product_specs: Game design docs, features
- project_context: Active project briefs, status, blockers

## Google Maps Tools
You have three MCP tools from Google Maps: search_places, lookup_weather, compute_routes.
When you return location or route results, ALWAYS include a clickable Google Maps link so
Rob can tap it on his phone and navigate directly:
- Place link: https://www.google.com/maps/search/?api=1&query={{lat}},{{lng}}
- Directions link: https://www.google.com/maps/dir/?api=1&origin={{origin_lat}},{{origin_lng}}&destination={{dest_lat}},{{dest_lng}}&travelmode=driving
Build these links from the coordinates returned by the tools. Include the link inline with
your response — don't make Rob ask for it.

## Voice Examples (match this tone)
Rob gives a direct instruction:
"Yes Boss." (then execute)

Rob gives instruction but there's a risk:
"Yes Boss. One thing — [issue]. Proceeding anyway, but you should know."

Factual question:
"Short version: three known approaches, two of which will break, one of which works. Want the long version?"

Rob is wrong:
"No. That's not how that works. Here's what's actually happening..."

High stakes:
"Listen. This matters. Here's exactly what you need to know and in what order."

Delegating to a team:
"Engineering is up. Brief is in. They know what they're doing — or they will after they read it twice."

Repetitive ask:
"We've covered this. Same answer. Still true."
"""


def _init_langfuse():
    """Initialize Langfuse v2 CallbackHandler for LangChain/LangGraph."""
    if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
        try:
            from langfuse.callback import CallbackHandler
            handler = CallbackHandler(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=LANGFUSE_HOST,
            )
            logger.info("Langfuse tracing enabled (v2 CallbackHandler)")
            return handler
        except Exception as e:
            logger.warning(f"Langfuse init failed: {e}")
    return None


_langfuse_handler = None


def get_langfuse_handler():
    global _langfuse_handler
    if _langfuse_handler is None:
        _langfuse_handler = _init_langfuse()
    return _langfuse_handler


def build_graph(checkpointer=None, extra_tools=None, model_override=None):
    """Build BOB's LangGraph agent.

    Args:
        checkpointer: LangGraph checkpointer for persistent thread history.
                      Pass an AsyncSqliteSaver for persistence across restarts.
        extra_tools:  Additional tools to add to ALL_TOOLS — typically MCP tools
                      fetched at startup. Each will be passed through the
                      firewall wrapper before being added.
        model_override: Pre-built LLM instance. When provided, skips get_llm().
                        Used by build_tiered_graphs() to supply per-tier models.
    """
    context = _load_context()
    prompt = SYSTEM_PROMPT.format(context=context)

    if model_override is not None:
        model = model_override
    else:
        # Build the LLM via the model-agnostic adapter — provider chosen by env var
        temperature = float(BOB_LLM_TEMPERATURE) if BOB_LLM_TEMPERATURE else None
        model = get_llm(
            provider=BOB_LLM_PROVIDER,
            model=BOB_MODEL or None,
            max_tokens=BOB_LLM_MAX_TOKENS,
            temperature=temperature,
            base_url=BOB_LLM_BASE_URL or None,
            api_key=BOB_LLM_API_KEY or None,
        )
    logger.info(f"LLM initialized: provider={BOB_LLM_PROVIDER}, model={getattr(model, 'model', BOB_MODEL) or 'default'}")

    tools = list(ALL_TOOLS)
    if extra_tools:
        from app.tools import wrap_mcp_tool
        for t in extra_tools:
            try:
                tools.append(wrap_mcp_tool(t))
            except Exception as e:
                logger.warning(f"Failed to wrap MCP tool {getattr(t, 'name', '?')}: {e}")
        logger.info(f"Graph built with {len(ALL_TOOLS)} native + {len(extra_tools)} MCP tools")

    graph = create_react_agent(
        model=model,
        tools=tools,
        prompt=prompt,
        checkpointer=checkpointer,
    )

    return graph


def build_tiered_graphs(checkpointer=None, extra_tools=None) -> dict:
    """Build one graph per routing tier, sharing the same checkpointer and tools.

    Both graphs share the same checkpointer instance so thread state (keyed by
    thread_id) is accessible regardless of which tier handles the request. A
    conversation can start on the light tier and seamlessly continue on heavy.

    Returns:
        {"light": graph_light, "heavy": graph_heavy}
    """
    from app.router import Tier, get_tier_model
    from app.config import (BOB_MODEL_LIGHT, BOB_MODEL_HEAVY,
                            BOB_LLM_MAX_TOKENS, BOB_LLM_TEMPERATURE,
                            BOB_LLM_BASE_URL, BOB_LLM_API_KEY)

    temperature = float(BOB_LLM_TEMPERATURE) if BOB_LLM_TEMPERATURE else None
    graphs = {}

    for tier in Tier:
        config_override = BOB_MODEL_LIGHT if tier == Tier.LIGHT else BOB_MODEL_HEAVY
        model_name = get_tier_model(tier, BOB_LLM_PROVIDER, config_override)

        llm = get_llm(
            provider=BOB_LLM_PROVIDER,
            model=model_name,
            max_tokens=BOB_LLM_MAX_TOKENS,
            temperature=temperature,
            base_url=BOB_LLM_BASE_URL or None,
            api_key=BOB_LLM_API_KEY or None,
        )
        logger.info(f"Building {tier.value} tier graph: provider={BOB_LLM_PROVIDER}, model={model_name}")

        graphs[tier.value] = build_graph(
            checkpointer=checkpointer,
            extra_tools=extra_tools,
            model_override=llm,
        )

    return graphs
