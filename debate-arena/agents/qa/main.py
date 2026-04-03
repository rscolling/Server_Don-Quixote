"""QA Agent — entry point."""
import asyncio
import json
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
log = logging.getLogger("qa")


class QAAgent(BaseAgent):
    SHORTHAND = "QA"
    NAME = "Quality Assurance Agent"
    ROLE = "Adversarial review, brand consistency, quality gate"
    CAPABILITIES = [
        {"name": "adversarial_review"},
        {"name": "brand_consistency"},
        {"name": "quality_assurance"},
        {"name": "fact_checking"},
    ]
    TOPICS = ["debate:qa"]

    async def handle_critique_request(self, message: dict, task: dict | None):
        """Run adversarial review on a deliverable."""
        payload = message.get("payload", {})
        action = payload.get("action", "critique")

        if action in ("adversarial_review", "critique"):
            deliverable = payload.get("deliverable", {})
            task_text = payload.get("task_title", task["title"] if task else "")
            primary = payload.get("primary_agent", "unknown")

            log.info(f"[QA] Adversarial review for task #{task['id'] if task else '?'} by {primary}")

            result = adversarial_review(self.claude, deliverable, task_text, primary, self.MODEL)
            log.info(f"[QA] Verdict: {result.get('verdict')} (score: {result.get('score', '?')})")

            await self.bus.send_message(
                sender=self.SHORTHAND,
                recipient="PM",
                message_type="feedback",
                payload={**result, "action": "adversarial_review"},
                task_id=task["id"] if task else None,
                reply_to=message.get("id"),
                topic=f"task:{task['id']}" if task else None,
            )


agent = QAAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = asyncio.create_task(agent.start())
    yield
    agent._running = False
    t.cancel()
    await agent.stop()


app = FastAPI(title="ATG QA Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"agent": "QA", "status": "ok", "name": agent.NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8104)
