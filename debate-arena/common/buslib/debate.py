"""Debate Arena — tier configuration, critic assignments, metadata model."""
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
}

PRIMARY_AGENT_MAP: dict[str, str] = {
    "campaign": "CE",
    "content": "CE",
    "visual": "GA",
    "research": "RA",
    "seo": "SA",
    "simple": "RA",
}

_TASK_KEYWORDS: dict[str, list[str]] = {
    "campaign": ["campaign", "launch", "brand", "rebrand", "strategy"],
    "content": ["write", "blog", "article", "post", "newsletter", "email", "copy"],
    "visual": ["thumbnail", "image", "graphic", "design", "visual", "sprite", "background", "banner"],
    "research": ["research", "find out", "market", "trends", "analyze", "competitor"],
    "seo": ["seo", "keyword", "analytics", "ranking", "meta"],
}


def get_tier_for_task(task: str) -> dict:
    """Classify a task and return its debate tier config with task_type."""
    task_lower = task.lower()
    for task_type, keywords in _TASK_KEYWORDS.items():
        if any(kw in task_lower for kw in keywords):
            return {**DEBATE_TIERS[task_type], "task_type": task_type}
    return {**DEBATE_TIERS["simple"], "task_type": "simple"}
