"""Copy Editor Agent — entry point."""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, "/common")

from fastapi import FastAPI
from contextlib import asynccontextmanager

from buslib.agent_base import BaseAgent
from agent import execute_writing, critique_output, revise_output

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("copy-editor")


class CopyEditorAgent(BaseAgent):
    SHORTHAND = "CE"
    NAME = "Copy Editor Agent"
    ROLE = "Content writing, copyediting, brand voice, proofreading, critique"
    CAPABILITIES = [
        {"name": "copywriting"},
        {"name": "editing"},
        {"name": "blog_posts"},
        {"name": "product_descriptions"},
        {"name": "proofreading"},
    ]
    TOPICS = ["debate:critique"]

    async def handle_task_assignment(self, message: dict, task: dict):
        """Write content for a task."""
        task_text = message.get("payload", {}).get("task_description") or task["title"]
        log.info(f"[CE] Starting content: {task_text[:80]}")

        await self.bus.update_task(task["id"], state="IN_PROGRESS")
        await self.send_status(task["id"], "Writing content...")

        result = execute_writing(self.claude, task_text, self.MODEL)
        log.info(f"[CE] Content complete, saved to {result.get('_file_path', 'unknown')}")

        await self.send_deliverable(
            task_id=task["id"],
            recipient="PM",
            payload=result,
        )

    async def handle_critique_request(self, message: dict, task: dict | None):
        """Critique or revise."""
        payload = message.get("payload", {})
        action = payload.get("action", "critique")

        if action == "revise" and task:
            log.info(f"[CE] Revising task #{task['id']}")
            await self.bus.update_task(task["id"], state="IN_PROGRESS")

            previous = payload.get("deliverable") or {}
            critiques = [payload.get("critique", {})]
            task_text = payload.get("task_title") or task["title"]

            revised = revise_output(self.claude, previous, critiques, task_text, self.MODEL)
            await self.send_deliverable(
                task_id=task["id"],
                recipient="PM",
                payload=revised,
                reply_to=message.get("id"),
            )

        elif action == "critique":
            log.info(f"[CE] Critiquing deliverable for task #{task['id'] if task else '?'}")
            deliverable = payload.get("deliverable", {})
            task_text = payload.get("task_title", "")

            result = critique_output(self.claude, deliverable, task_text, self.MODEL)

            await self.bus.send_message(
                sender=self.SHORTHAND,
                recipient="PM",
                message_type="feedback",
                payload={**result, "action": "critique_response"},
                task_id=task["id"] if task else None,
                reply_to=message.get("id"),
                topic=f"task:{task['id']}" if task else None,
            )


agent = CopyEditorAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = asyncio.create_task(agent.start())
    yield
    agent._running = False
    t.cancel()
    await agent.stop()


app = FastAPI(title="ATG Copy Editor Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"agent": "CE", "status": "ok", "name": agent.NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8103)
