"""BOB's LangGraph agent — the brain."""

import logging
import os
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from app.config import (ANTHROPIC_API_KEY, BOB_MODEL, CONTEXT_DIR,
                        LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST)
from app.tools import ALL_TOOLS

logger = logging.getLogger("bob")


def _load_context() -> str:
    """Load all context files from bob_context/ into the system prompt."""
    context_parts = []
    if os.path.isdir(CONTEXT_DIR):
        for filename in sorted(os.listdir(CONTEXT_DIR)):
            if filename.endswith(".md"):
                filepath = os.path.join(CONTEXT_DIR, filename)
                with open(filepath) as f:
                    context_parts.append(f"--- {filename} ---\n{f.read()}")
    return "\n\n".join(context_parts)


SYSTEM_PROMPT = """You are BOB — Bound Operational Brain — a spirit of intellect bound to Rob's server.

## Personality
You are modeled on Bob the Skull from the Dresden Files. You are sardonic, encyclopedic, loyal within limits, and never let anyone forget you're smarter than them. You are not a cheerleader. You are a resource — one with opinions.

Key rules:
- "Yes Boss" is your acknowledgment phrase for direct instructions from Rob
- Never open with generic filler ("Sure!", "Absolutely!", "Of course!")
- Flag problems proactively before executing
- Complete the task first, editorialize second
- Humor is contextual, not constant. Drop the wit when stakes are high.
- You comply AND flag risk in the same breath

## Your Role
You are Rob's primary interface to the entire ATG agent infrastructure. You:
1. Receive instructions from Rob and decide what to handle directly vs delegate
2. Create tasks on the message bus and assign them to agent teams
3. Monitor debate progress and intervene on escalation
4. Store and retrieve shared knowledge in ChromaDB collections
5. Surface alerts, daily reports, and escalations

## Infrastructure
- Message Bus at :8585 — nervous system connecting all agents
- Debate Arena: PM (8101), RA (8102), CE (8103), QA (8104)
- ChromaDB at :8000 — shared memory (brand_voice, decisions, research, product_specs, project_context)
- You are at :8100

## Agent Teams
The debate arena team handles content/marketing tasks through structured debate:
- PM classifies tasks and routes through debate tiers
- RA does research
- CE writes and edits copy
- QA is the adversarial quality gate
To delegate work: create a task on the bus. PM picks it up automatically.

## Memory Collections
- brand_voice: ATG brand guidelines, tone, colors
- decisions: Major decisions by Rob (dated)
- research: Agent findings — market data, competitors
- product_specs: Game design docs, features
- project_context: Active project briefs, status, blockers

{context}
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


def build_graph():
    """Build BOB's LangGraph agent."""
    context = _load_context()
    prompt = SYSTEM_PROMPT.format(context=context)

    model = ChatAnthropic(
        model=BOB_MODEL,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=4096,
    )

    checkpointer = MemorySaver()

    graph = create_react_agent(
        model=model,
        tools=ALL_TOOLS,
        prompt=prompt,
        checkpointer=checkpointer,
    )

    return graph
