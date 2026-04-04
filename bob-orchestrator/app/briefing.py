"""Auto-generated team briefings for delegated tasks.

When BOB creates a task for an agent team, this module generates a
structured brief with objective, constraints, deliverables, brand
context, and relevant memory. PM picks up the brief and routes work.
"""

import json
import logging
from datetime import datetime, timezone

from app import memory

logger = logging.getLogger("bob.briefing")


def generate_brief(
    title: str,
    description: str,
    team: str = "",
    priority: str = "normal",
    deadline: str = "",
    constraints: list[str] | None = None,
    deliverables: list[str] | None = None,
) -> dict:
    """Generate a structured team brief for a task.

    Pulls relevant context from ChromaDB collections to give the team
    everything they need to start work without asking BOB follow-up questions.

    Returns a dict suitable for inclusion as task metadata.
    """
    brief = {
        "title": title,
        "objective": description,
        "team": team,
        "priority": priority,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "BOB",
    }

    if deadline:
        brief["deadline"] = deadline

    if constraints:
        brief["constraints"] = constraints

    if deliverables:
        brief["deliverables"] = deliverables

    # Pull relevant context from shared memory
    context = _gather_context(title, description)
    if context:
        brief["context"] = context

    # Add brand voice guidelines (always included)
    brand = _get_brand_guidelines()
    if brand:
        brief["brand_guidelines"] = brand

    # Add standing orders
    brief["standing_orders"] = [
        "Revenue from Bear Creek Trail is the primary objective.",
        "ATG brand voice: warm, authentic, Appalachian. Never corporate.",
        "Complete the task first, debate quality second.",
        "Escalate to BOB if blocked or if scope needs to change.",
        "Rob approves all major decisions — recommend, don't decide.",
    ]

    logger.info(f"Generated brief for '{title}' (team: {team}, priority: {priority})")
    return brief


def format_brief_as_text(brief: dict) -> str:
    """Format a brief dict as readable text for the task description."""
    lines = []
    lines.append(f"# Team Brief: {brief['title']}")
    lines.append("")
    lines.append(f"**Objective:** {brief['objective']}")
    lines.append(f"**Priority:** {brief['priority']}")
    lines.append(f"**Team:** {brief.get('team', 'unassigned')}")

    if brief.get("deadline"):
        lines.append(f"**Deadline:** {brief['deadline']}")

    lines.append(f"**Created:** {brief['created_at']}")
    lines.append("")

    if brief.get("constraints"):
        lines.append("## Constraints")
        for c in brief["constraints"]:
            lines.append(f"- {c}")
        lines.append("")

    if brief.get("deliverables"):
        lines.append("## Deliverables")
        for d in brief["deliverables"]:
            lines.append(f"- {d}")
        lines.append("")

    if brief.get("brand_guidelines"):
        lines.append("## Brand Guidelines")
        lines.append(brief["brand_guidelines"])
        lines.append("")

    if brief.get("context"):
        lines.append("## Relevant Context")
        for ctx in brief["context"]:
            lines.append(f"**[{ctx['collection']}]** {ctx['text'][:300]}")
            lines.append("")

    if brief.get("standing_orders"):
        lines.append("## Standing Orders")
        for order in brief["standing_orders"]:
            lines.append(f"- {order}")
        lines.append("")

    return "\n".join(lines)


def _gather_context(title: str, description: str) -> list[dict]:
    """Search relevant ChromaDB collections for context related to the task."""
    query = f"{title} {description}"
    context = []

    for collection in ["decisions", "research", "product_specs", "project_context"]:
        try:
            results = memory.query(collection, query, n_results=2)
            for doc in results:
                if doc.get("distance", 999) < 1.5:  # Only include reasonably relevant hits
                    context.append({
                        "collection": collection,
                        "id": doc["id"],
                        "text": doc["text"],
                    })
        except Exception:
            pass

    return context


def _get_brand_guidelines() -> str:
    """Get ATG brand voice summary from ChromaDB."""
    try:
        results = memory.query("brand_voice", "ATG brand tone voice guidelines", n_results=2)
        if results:
            return " ".join(doc["text"] for doc in results[:2])
    except Exception:
        pass
    return ""
