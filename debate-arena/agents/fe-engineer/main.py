"""Front-End Engineer Agent — entry point."""
import asyncio
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
log = logging.getLogger("fe-engineer")


class FrontEndEngineerAgent(BaseAgent):
    SHORTHAND = "FE"
    NAME = "Front-End Engineer Agent"
    ROLE = "Front-end implementation: HTML, CSS, JavaScript, static sites, UI integration"
    CAPABILITIES = [
        {"name": "html_implementation"},
        {"name": "css_styling"},
        {"name": "vanilla_js"},
        {"name": "static_site_build"},
        {"name": "responsive_layout"},
        {"name": "accessibility_pass"},
    ]
    TOPICS = ["debate:critique", "frontend"]

    async def handle_task_assignment(self, message: dict, task: dict):
        task_text = message.get("payload", {}).get("task_description") or task["title"]
        if task.get("description"):
            task_text = f"{task['title']}\n\n{task['description']}"
        log.info(f"[FE] Starting build: {task['title'][:80]}")

        await self.bus.update_task(task["id"], state="IN_PROGRESS")
        await self.send_status(task["id"], "Building front-end deliverables...")

        result = execute_writing(self.claude, task_text, self.MODEL)
        log.info(f"[FE] Build complete: {result.get('_file_path', 'unknown')}")

        await self.send_deliverable(
            task_id=task["id"],
            recipient="PM",
            payload=result,
        )

    async def handle_critique_request(self, message: dict, task: dict | None):
        payload = message.get("payload", {})
        action = payload.get("action", "critique")

        if action == "revise" and task:
            log.info(f"[FE] Revising task #{task['id']}")
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
            log.info(f"[FE] Critiquing deliverable for task #{task['id'] if task else '?'}")
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


agent = FrontEndEngineerAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = asyncio.create_task(agent.start())
    yield
    agent._running = False
    t.cancel()
    await agent.stop()


app = FastAPI(title="ATG Front-End Engineer Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"agent": "FE", "status": "ok", "name": agent.NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8107)
