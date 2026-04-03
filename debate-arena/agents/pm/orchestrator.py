"""PM Orchestrator — task classification, debate routing, escalation."""
import json
import logging

from buslib.client import MessageBusClient
from buslib.debate import (
    CRITIC_ASSIGNMENTS, PRIMARY_AGENT_MAP, DebateMetadata,
    get_tier_for_task,
)

log = logging.getLogger(__name__)


class Orchestrator:
    """Manages debate lifecycle through message bus tasks."""

    def __init__(self, bus: MessageBusClient):
        self.bus = bus

    async def classify_and_assign(self, task: dict):
        """Classify a new task, set debate metadata, assign primary agent."""
        title = task["title"]
        description = task.get("description", "")
        task_text = f"{title} {description}".strip()
        tier = get_tier_for_task(task_text)

        task_type = tier["task_type"]
        primary = PRIMARY_AGENT_MAP.get(task_type, "RA")
        critics = CRITIC_ASSIGNMENTS.get(primary, ["QA"])

        # Only include critics that exist as registered agents
        agents = await self.bus.get_agents()
        registered = {a["shorthand"] for a in agents}
        available_critics = [c for c in critics if c in registered]
        if not available_critics and "QA" in registered:
            available_critics = ["QA"]

        meta = DebateMetadata(
            debate_tier=tier["tier"],
            task_type=task_type,
            max_rounds=tier["max_rounds"],
            current_round=0,
            primary_agent=primary,
            critic_agents=available_critics,
            escalation_path=tier.get("escalation_path", []),
        )

        log.info(f"[PM] Task #{task['id']} classified: type={task_type}, "
                 f"tier={tier['tier']}, primary={primary}, critics={available_critics}")

        # Update task with debate metadata and assign
        await self.bus.update_task(
            task["id"],
            state="ASSIGNED",
            assignee=primary,
            metadata={"debate": meta.model_dump()},
        )

        # Add all critics + PM as watchers
        for critic in available_critics:
            await self.bus.add_watcher(task["id"], critic)
        await self.bus.add_watcher(task["id"], "PM")

        # Send task_assignment to primary agent
        await self.bus.send_message(
            sender="PM",
            recipient=primary,
            message_type="task_assignment",
            payload={
                "task_title": title,
                "task_description": description,
                "debate_tier": tier["tier"],
                "task_type": task_type,
            },
            task_id=task["id"],
            topic=f"task:{task['id']}",
        )

    async def handle_deliverable(self, message: dict, task: dict):
        """Route a deliverable to critics for review."""
        meta_raw = task.get("metadata", {}).get("debate", {})
        meta = DebateMetadata(**meta_raw) if meta_raw else None
        if not meta:
            log.warning(f"[PM] Task #{task['id']} has no debate metadata")
            return

        # If no debate, approve directly
        if meta.max_rounds == 0:
            await self.bus.update_task(task["id"], state="ACCEPTED")
            log.info(f"[PM] Task #{task['id']} auto-approved (no_debate tier)")
            return

        # Route to critics
        for critic in meta.critic_agents:
            await self.bus.send_message(
                sender="PM",
                recipient=critic,
                message_type="feedback",
                payload={
                    "action": "critique",
                    "deliverable": message.get("payload", {}),
                    "task_title": task["title"],
                    "round": meta.current_round + 1,
                    "max_rounds": meta.max_rounds,
                },
                task_id=task["id"],
                reply_to=message["id"],
                topic=f"task:{task['id']}",
            )
        log.info(f"[PM] Routed task #{task['id']} to critics: {meta.critic_agents}")

    async def handle_critique(self, message: dict, task: dict):
        """Process a critique response. When all critics responded, decide next step."""
        meta_raw = task.get("metadata", {}).get("debate", {})
        meta = DebateMetadata(**meta_raw) if meta_raw else None
        if not meta:
            return

        payload = message.get("payload", {})
        verdict = payload.get("verdict", "revise")

        log.info(f"[PM] Critique from {message['sender']} on task #{task['id']}: {verdict}")

        if verdict == "approve":
            # Check if all critics approved
            # For now, any single approval triggers QA review
            if meta.debate_tier != "light_review":
                await self._route_to_qa(message, task, meta)
            else:
                await self.bus.update_task(task["id"], state="ACCEPTED")
        elif verdict == "reject" or verdict == "revise":
            meta.current_round += 1
            if meta.current_round >= meta.max_rounds:
                await self._escalate(task, meta)
            else:
                # Send back for revision
                await self.bus.update_task(
                    task["id"],
                    state="REWORK",
                    metadata={"debate": meta.model_dump()},
                )
                await self.bus.send_message(
                    sender="PM",
                    recipient=meta.primary_agent,
                    message_type="feedback",
                    payload={
                        "action": "revise",
                        "critique": payload,
                        "from_critic": message["sender"],
                        "round": meta.current_round,
                    },
                    task_id=task["id"],
                    reply_to=message["id"],
                    topic=f"task:{task['id']}",
                )

    async def _route_to_qa(self, message: dict, task: dict, meta: DebateMetadata):
        """Send deliverable to QA for adversarial review."""
        await self.bus.send_message(
            sender="PM",
            recipient="QA",
            message_type="feedback",
            payload={
                "action": "adversarial_review",
                "deliverable": message.get("payload", {}),
                "task_title": task["title"],
                "round": meta.current_round,
                "primary_agent": meta.primary_agent,
            },
            task_id=task["id"],
            reply_to=message.get("id"),
            topic=f"task:{task['id']}",
        )
        log.info(f"[PM] Routed task #{task['id']} to QA for adversarial review")

    async def handle_qa_verdict(self, message: dict, task: dict):
        """Process QA's final verdict."""
        meta_raw = task.get("metadata", {}).get("debate", {})
        meta = DebateMetadata(**meta_raw) if meta_raw else None
        if not meta:
            return

        payload = message.get("payload", {})
        verdict = payload.get("verdict", "revise")
        score = payload.get("score", 0)

        log.info(f"[PM] QA verdict on task #{task['id']}: {verdict} (score: {score})")

        if verdict == "approve":
            await self.bus.update_task(task["id"], state="ACCEPTED")
        else:
            meta.current_round += 1
            if meta.current_round >= meta.max_rounds:
                await self._escalate(task, meta)
            else:
                await self.bus.update_task(
                    task["id"],
                    state="REWORK",
                    metadata={"debate": meta.model_dump()},
                )
                await self.bus.send_message(
                    sender="PM",
                    recipient=meta.primary_agent,
                    message_type="feedback",
                    payload={
                        "action": "revise",
                        "critique": payload,
                        "from_critic": "QA",
                        "round": meta.current_round,
                    },
                    task_id=task["id"],
                    reply_to=message["id"],
                    topic=f"task:{task['id']}",
                )

    async def _escalate(self, task: dict, meta: DebateMetadata):
        """Handle escalation when max rounds hit."""
        meta.escalation_level += 1
        path = meta.escalation_path
        level = min(meta.escalation_level - 1, len(path) - 1) if path else 0
        escalation_type = path[level] if path else "human"

        log.info(f"[PM] Escalating task #{task['id']}: level={meta.escalation_level}, type={escalation_type}")

        if escalation_type in ("mediator", "orchestrator"):
            # Auto-accept with note
            await self.bus.update_task(
                task["id"],
                state="ACCEPTED",
                metadata={"debate": meta.model_dump()},
            )
            await self.bus.send_message(
                sender="PM",
                recipient="ALL",
                message_type="escalation",
                payload={
                    "reason": f"Max debate rounds ({meta.max_rounds}) reached",
                    "resolution": f"Auto-accepted by {escalation_type}",
                    "escalation_level": meta.escalation_level,
                },
                task_id=task["id"],
                topic=f"task:{task['id']}",
            )
        else:
            # Human review needed
            await self.bus.send_message(
                sender="PM",
                recipient="ALL",
                message_type="escalation",
                payload={
                    "reason": f"Max debate rounds ({meta.max_rounds}) reached, requires human review",
                    "escalation_level": meta.escalation_level,
                },
                task_id=task["id"],
                priority="high",
                topic=f"task:{task['id']}",
            )
