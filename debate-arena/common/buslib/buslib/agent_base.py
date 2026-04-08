"""Base Agent — poll loop, registration, critique/revise protocol."""
import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

import anthropic

from buslib.client import MessageBusClient

log = logging.getLogger(__name__)


class BaseAgent:
    """Base class for all ATG debate arena agents.

    Subclasses override:
        SHORTHAND, NAME, ROLE, CAPABILITIES, SYSTEM_PROMPT
        handle_task_assignment(message, task)
        handle_critique_request(message, task)  (optional)
    """

    SHORTHAND = "XX"
    NAME = "Base Agent"
    ROLE = ""
    CAPABILITIES: list[dict] = []
    SYSTEM_PROMPT = ""
    MODEL = "claude-sonnet-4-5"
    POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3"))
    TOPICS: list[str] = []

    # Task cache TTL in seconds
    _TASK_CACHE_TTL = 15

    def __init__(self):
        self.bus = MessageBusClient()
        self.claude = anthropic.Anthropic()
        self._last_poll = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._running = True
        self._task_cache = {}  # {task_id: {"data": ..., "time": ...}}
        self._agents_cache = None  # {"data": ..., "time": ...}
        self._AGENTS_CACHE_TTL = 300  # 5 minutes

    async def start(self):
        """Register with bus, subscribe to topics, enter poll loop."""
        log.info(f"[{self.SHORTHAND}] Starting agent: {self.NAME}")

        # Registration — retry until bus is reachable
        for attempt in range(10):
            try:
                await self.bus.register_agent(
                    shorthand=self.SHORTHAND,
                    name=self.NAME,
                    role=self.ROLE,
                )
                log.info(f"[{self.SHORTHAND}] Registered with message bus")
                break
            except Exception as e:
                log.warning(f"[{self.SHORTHAND}] Registration attempt {attempt+1} failed: {e}")
                await asyncio.sleep(3)
        else:
            log.error(f"[{self.SHORTHAND}] Could not register after 10 attempts")

        # Register capabilities separately (non-fatal)
        if self.CAPABILITIES:
            try:
                await self.bus.set_capabilities(self.SHORTHAND, self.CAPABILITIES)
                log.info(f"[{self.SHORTHAND}] Capabilities registered")
            except Exception as e:
                log.warning(f"[{self.SHORTHAND}] Capability registration failed (non-fatal): {e}")

        # Subscribe to topics
        for topic in self.TOPICS:
            try:
                await self.bus.subscribe(self.SHORTHAND, topic)
                log.info(f"[{self.SHORTHAND}] Subscribed to topic: {topic}")
            except Exception as e:
                log.warning(f"[{self.SHORTHAND}] Subscription to {topic} failed: {e}")

        await self.poll_loop()

    async def poll_loop(self):
        """Poll the message bus for new messages."""
        log.info(f"[{self.SHORTHAND}] Entering poll loop (interval={self.POLL_INTERVAL}s)")
        while self._running:
            try:
                result = await self.bus.poll(self.SHORTHAND, self._last_poll)
                messages = result.get("messages", [])
                self._last_poll = result.get("server_time", self._last_poll)

                for msg in messages:
                    try:
                        await self.handle_message(msg)
                    except Exception as e:
                        log.error(f"[{self.SHORTHAND}] Error handling message {msg.get('id')}: {e}")
            except Exception as e:
                log.error(f"[{self.SHORTHAND}] Poll error: {e}")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _get_task_cached(self, task_id: int) -> dict:
        """Get a task with short TTL cache."""
        now = time.time()
        cached = self._task_cache.get(task_id)
        if cached and (now - cached["time"]) < self._TASK_CACHE_TTL:
            return cached["data"]
        task = await self.bus.get_task(task_id)
        self._task_cache[task_id] = {"data": task, "time": now}
        return task

    def _invalidate_task(self, task_id: int):
        """Invalidate cached task after update."""
        self._task_cache.pop(task_id, None)

    async def _get_agents_cached(self) -> list:
        """Get agents list with TTL cache."""
        now = time.time()
        if self._agents_cache and (now - self._agents_cache["time"]) < self._AGENTS_CACHE_TTL:
            return self._agents_cache["data"]
        agents = await self.bus.get_agents()
        self._agents_cache = {"data": agents, "time": now}
        return agents

    async def handle_message(self, message: dict):
        """Dispatch messages by type. Override for custom routing."""
        msg_type = message.get("message_type", "")
        log.info(f"[{self.SHORTHAND}] Received {msg_type} from {message.get('sender')}")

        # Acknowledge receipt
        await self.bus.ack_message(message["id"], self.SHORTHAND, "received")

        if msg_type == "task_assignment":
            task_id = message.get("task_id")
            if task_id:
                task = await self._get_task_cached(task_id)
                await self.handle_task_assignment(message, task)
        elif msg_type == "feedback":
            task_id = message.get("task_id")
            task = await self._get_task_cached(task_id) if task_id else None
            await self.handle_critique_request(message, task)
        elif msg_type == "state_change":
            pass  # Informational, subclass can override

    async def handle_task_assignment(self, message: dict, task: dict):
        """Handle a task assignment. Override in subclass."""
        log.warning(f"[{self.SHORTHAND}] handle_task_assignment not implemented")

    async def handle_critique_request(self, message: dict, task: dict | None):
        """Handle a critique request. Override in subclass."""
        log.warning(f"[{self.SHORTHAND}] handle_critique_request not implemented")

    def call_claude(self, prompt: str, max_tokens: int = 4096,
                    system: str | None = None) -> str:
        """Call Claude API and return response text."""
        response = self.claude.messages.create(
            model=self.MODEL,
            max_tokens=max_tokens,
            system=system or self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def call_claude_json(self, prompt: str, max_tokens: int = 4096,
                         system: str | None = None) -> dict:
        """Call Claude API and parse JSON response."""
        text = self.call_claude(prompt, max_tokens, system)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text, "_parse_error": True}

    async def send_deliverable(self, task_id: int, recipient: str, payload: dict,
                               reply_to: int | None = None):
        """Send a deliverable message and transition task to IN_REVIEW."""
        await self.bus.send_message(
            sender=self.SHORTHAND,
            recipient=recipient,
            message_type="deliverable",
            payload=payload,
            task_id=task_id,
            reply_to=reply_to,
            topic=f"task:{task_id}",
        )
        await self.bus.update_task(task_id, state="IN_REVIEW")
        self._invalidate_task(task_id)

    async def send_status(self, task_id: int, text: str):
        """Send a status update message."""
        await self.bus.send_message(
            sender=self.SHORTHAND,
            recipient="PM",
            message_type="status_update",
            payload={"text": text},
            task_id=task_id,
            topic=f"task:{task_id}",
        )

    async def stop(self):
        self._running = False
        await self.bus.close()
