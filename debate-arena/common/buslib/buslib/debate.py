"""Debate Arena — tier configuration, critic assignments, metadata model."""
import re
from pydantic import BaseModel, Field


class DebateMetadata(BaseModel):
    """Stored in task.metadata to track debate state."""
    debate_tier: str = "no_debate"
    task_type: str = "simple"
    max_rounds: int = 0
    current_round: int = 0
    primary_agent: str = ""
    critic_agents: list[str] = Field(default_factory=list)
    escalation_path: list[str] = Field(default_factory=list)
    escalation_level: int = 0
    draft_message_id: int | None = None
    final_critic: str = "QA"


DEBATE_TIERS = {
    "campaign": {
        "tier": "full_tension",
        "max_rounds": 5,
        "description": "Full creative tension — all layers active",
        "mesh_enabled": True,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["mediator", "orchestrator", "human"],
        "example_tasks": ["social media campaign", "product launch", "brand refresh"],
    },
    "content": {
        "tier": "full_tension",
        "max_rounds": 4,
        "description": "Full tension for content",
        "mesh_enabled": True,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["mediator", "orchestrator", "human"],
        "example_tasks": ["blog post", "article", "newsletter", "email campaign"],
    },
    "visual": {
        "tier": "critique_revise",
        "max_rounds": 3,
        "description": "Critique cycle for visual work",
        "mesh_enabled": False,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["orchestrator", "human"],
        "example_tasks": ["thumbnail", "banner", "social graphic", "sprite"],
    },
    "research": {
        "tier": "critique_revise",
        "max_rounds": 3,
        "description": "Critique cycle for research",
        "mesh_enabled": False,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["orchestrator", "human"],
        "example_tasks": ["market research", "competitor analysis", "trend report"],
    },
    "seo": {
        "tier": "light_review",
        "max_rounds": 2,
        "description": "Light review for SEO work",
        "mesh_enabled": False,
        "critique_enabled": True,
        "adversarial_qa": False,
        "escalation_path": ["orchestrator"],
        "example_tasks": ["keyword optimization", "meta tags", "page audit"],
    },
    "infrastructure": {
        "tier": "critique_revise",
        "max_rounds": 3,
        "description": "Infrastructure / architecture review with QA risk gate",
        "mesh_enabled": False,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["orchestrator", "human"],
        "example_tasks": ["deployment plan", "resource modeling", "architecture review"],
    },
    "frontend_dev": {
        "tier": "critique_revise",
        "max_rounds": 3,
        "description": "Front-end build with critique cycle",
        "mesh_enabled": False,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["orchestrator", "human"],
        "example_tasks": ["build a landing page", "new website page", "UI fix"],
    },
    "backend_dev": {
        "tier": "critique_revise",
        "max_rounds": 3,
        "description": "Back-end build with critique cycle",
        "mesh_enabled": False,
        "critique_enabled": True,
        "adversarial_qa": True,
        "escalation_path": ["orchestrator", "human"],
        "example_tasks": ["new API endpoint", "new agent container", "schema change"],
    },
    "simple": {
        "tier": "no_debate",
        "max_rounds": 0,
        "description": "No debate — single agent responds directly",
        "mesh_enabled": False,
        "critique_enabled": False,
        "adversarial_qa": False,
        "escalation_path": [],
        "example_tasks": ["font recommendation", "color lookup", "file conversion"],
    },
}

CRITIC_ASSIGNMENTS: dict[str, list[str]] = {
    "RA": ["CE", "QA"],
    "GA": ["CE", "QA"],
    "CE": ["RA", "QA"],
    "SM": ["CE", "GA", "QA"],
    "SA": ["CE"],
    "WD": ["GA", "QA"],
    "SE": ["RE"],
    "FE": ["BE", "RE"],
    "BE": ["FE", "SE", "RE"],
}

FINAL_CRITIC_BY_TYPE: dict[str, str] = {
    "infrastructure": "RE",
    "frontend_dev": "RE",
    "backend_dev": "RE",
    "campaign": "QA",
    "content": "QA",
    "visual": "QA",
    "research": "QA",
    "seo": "QA",
    "simple": "QA",
}

PRIMARY_AGENT_MAP: dict[str, str] = {
    "campaign": "CE",
    "content": "CE",
    "visual": "GA",
    "research": "RA",
    "seo": "SA",
    "simple": "RA",
    "infrastructure": "SE",
    "frontend_dev": "FE",
    "backend_dev": "BE",
}

_TASK_KEYWORDS: dict[str, list[str]] = {
    # Order matters: get_tier_for_task returns the FIRST type whose keyword
    # matches. Put infrastructure FIRST so words like 'docker', 'compose',
    # 'cloudflared', 'ingress' route to SE before any incidental match on
    # 'service'/'api'/'endpoint' diverts to backend_dev.
    "infrastructure": ["infrastructure", "deploy", "deployment", "architecture", "scaling", "server", "docker", "kubernetes", "k8s", "on-prem", "aws", "agent team", "engineering team", "resource", "capacity", "sql", "database choice", "compose", "cloudflared", "ingress", "socket", "tunnel", "audit", "capacity check"],
    "frontend_dev": ["frontend", "front-end", "front end", "html", "css", "javascript", "js", "ui", "website page", "landing page", "web page", "static site", "responsive", "layout", "styling"],
    "backend_dev": ["backend", "back-end", "back end", "api", "endpoint", "route", "schema", "migration", "agent container", "build agent", "new agent", "service", "fastapi", "langgraph"],
    "campaign": ["campaign", "launch", "brand", "rebrand", "strategy"],
    "content": ["write", "blog", "article", "post", "newsletter", "email", "copy"],
    "visual": ["thumbnail", "image", "graphic", "design", "visual", "sprite", "background", "banner"],
    "research": ["research", "find out", "market", "trends", "analyze", "competitor"],
    "seo": ["seo", "keyword", "analytics", "ranking", "meta"],
}


def get_tier_for_task(task: str) -> dict:
    """Classify a task and return its debate tier config with task_type.

    Strips BOB-injected boilerplate (Mission Context, Brand Guidelines, etc.) before
    matching keywords, so generic words like "deployment" or "server" in the
    studio mission don't poison classification of customer-facing content.
    Uses word-boundary matching so "server" doesn't match "observer".
    """
    # Strip everything from the first boilerplate marker onwards
    classify_text = task
    for marker in ("## Brand Guidelines", "## Mission Context", "## Studio Mission", "**Created:**"):
        idx = classify_text.find(marker)
        if idx > 0:
            classify_text = classify_text[:idx]
    task_lower = classify_text.lower()
    for task_type, keywords in _TASK_KEYWORDS.items():
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", task_lower):
                return {**DEBATE_TIERS[task_type], "task_type": task_type}
    return {**DEBATE_TIERS["simple"], "task_type": "simple"}
