"""Reliability Engineer Agent — entry point."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/common")

from fastapi import FastAPI
from contextlib import asynccontextmanager

from buslib.agent_base import BaseAgent
from agent import adversarial_review

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("reliability-engineer")


class ReliabilityEngineerAgent(BaseAgent):
    SHORTHAND = "RE"
    NAME = "Reliability Engineer Agent"
    ROLE = "Adversarial review of engineering work — resource grounding, failure modes, one-way doors, operational burden"
    CAPABILITIES = [
        {"name": "adversarial_engineering_review"},
        {"name": "failure_mode_analysis"},
        {"name": "resource_grounding_check"},
        {"name": "security_review"},
    ]
    TOPICS = ["debate:critique", "debate:engineering_review"]

    async def handle_critique_request(self, message: dict, task: dict | None):
        payload = message.get("payload", {})
        action = payload.get("action", "critique")

        # RE handles both the round-by-round critique AND the final adversarial gate
        if action in ("critique", "adversarial_review"):
            deliverable = payload.get("deliverable", {})
            task_text = payload.get("task_title", task["title"] if task else "")
            primary = payload.get("primary_agent", "unknown")

            log.info(f"[RE] Engineering review for task #{task['id'] if task else '?'} by {primary} (action={action})")

            result = adversarial_review(self.claude, deliverable, task_text, primary, self.MODEL)
            log.info(f"[RE] Verdict: {result.get('verdict')} (score: {result.get('score', '?')})")

            # Tag the response so PM can route it correctly. We use the same
            # 'adversarial_review' action as QA so PM treats RE as a final-stage critic.
            await self.bus.send_message(
                sender=self.SHORTHAND,
                recipient="PM",
                message_type="feedback",
                payload={**result, "action": "adversarial_review"},
                task_id=task["id"] if task else None,
                reply_to=message.get("id"),
                topic=f"task:{task['id']}" if task else None,
            )


agent = ReliabilityEngineerAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = asyncio.create_task(agent.start())
    yield
    agent._running = False
    t.cancel()
    await agent.stop()


app = FastAPI(title="ATG Reliability Engineer Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"agent": "RE", "status": "ok", "name": agent.NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8106)
