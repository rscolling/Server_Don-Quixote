"""PM Agent — entry point with FastAPI health endpoint and poll loop."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/common")

from fastapi import FastAPI
from contextlib import asynccontextmanager

from buslib.agent_base import BaseAgent
from buslib.client import MessageBusClient
from orchestrator import Orchestrator

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("pm")


class PMAgent(BaseAgent):
    SHORTHAND = "PM"
    NAME = "Project Manager / Orchestrator"
    ROLE = "Classifies tasks, manages debate rounds, routes work, handles escalation"
    CAPABILITIES = [
        {"name": "task_classification"},
        {"name": "debate_orchestration"},
        {"name": "escalation"},
        {"name": "deployment"},
    ]
    TOPICS = ["task:new", "debate:review_complete", "escalation"]

    def __init__(self):
        super().__init__()
        self.orch = Orchestrator(self.bus, self.claude)

    async def handle_message(self, message: dict):
        msg_type = message.get("message_type", "")
        sender = message.get("sender", "")

        await self.bus.ack_message(message["id"], self.SHORTHAND, "received")

        # New task created (state_change to CREATED)
        if msg_type == "state_change":
            payload = message.get("payload", {})
            new_state = payload.get("new_state")
            old_state = payload.get("old_state")
            task_id = payload.get("task_id")

            if new_state == "CREATED" and old_state is None and task_id:
                task = await self.bus.get_task(task_id)
                # Only classify if PM didn't create it (avoid self-loop)
                if task and (task.get("assignee") is None or task.get("assignee") == self.SHORTHAND):
                    await self.orch.classify_and_assign(task)


        # BOB delegates directly via task_assignment — pick it up
        elif msg_type == "task_assignment":
            payload = message.get("payload", {})
            task_id = payload.get("task_id") or message.get("task_id")
            if task_id:
                task = await self.bus.get_task(task_id)
                if task:
                    await self.orch.classify_and_assign(task)

        # Deliverable from an agent
        elif msg_type == "deliverable" and sender != self.SHORTHAND:
            task_id = message.get("task_id")
            if task_id:
                task = await self.bus.get_task(task_id)
                if task:
                    await self.orch.handle_deliverable(message, task)

        # Critique/feedback from a critic or QA
        elif msg_type == "feedback" and sender != self.SHORTHAND:
            task_id = message.get("task_id")
            payload = message.get("payload", {})
            if task_id:
                task = await self.bus.get_task(task_id)
                if task:
                    if sender in ("QA", "RE") and payload.get("action") == "adversarial_review":
                        await self.orch.handle_qa_verdict(message, task)
                    elif payload.get("verdict"):
                        await self.orch.handle_critique(message, task)


agent = PMAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(agent.start())
    yield
    agent._running = False
    task.cancel()
    await agent.stop()


app = FastAPI(title="ATG PM Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"agent": "PM", "status": "ok", "name": agent.NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8101)
