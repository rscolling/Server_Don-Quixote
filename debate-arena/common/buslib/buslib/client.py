"""Message Bus HTTP client — wraps all bus endpoints."""
import httpx
import os
import logging

log = logging.getLogger(__name__)

BUS_URL = os.environ.get("MESSAGE_BUS_URL", "http://message-bus:8585")


class MessageBusClient:
    """Async HTTP client for the message bus API."""

    def __init__(self, base_url: str = BUS_URL):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def close(self):
        await self._client.aclose()

    # --- Agents ---

    async def register_agent(self, shorthand: str, name: str, role: str = "",
                             capabilities: list[dict] | None = None) -> dict:
        body = {"shorthand": shorthand, "name": name, "role": role}
        if capabilities:
            body["capabilities"] = capabilities
        r = await self._client.post("/agents", json=body)
        r.raise_for_status()
        return r.json()

    async def get_agents(self) -> list[dict]:
        r = await self._client.get("/agents")
        r.raise_for_status()
        return r.json()

    async def set_capabilities(self, shorthand: str, capabilities: list[dict]) -> list[dict]:
        r = await self._client.post(f"/agents/{shorthand}/capabilities", json=capabilities)
        r.raise_for_status()
        return r.json()

    # --- Messages ---

    async def send_message(self, sender: str, recipient: str, message_type: str,
                           payload: dict | None = None, priority: str = "normal",
                           context: dict | None = None, task_id: int | None = None,
                           reply_to: int | None = None, topic: str | None = None) -> dict:
        body = {
            "sender": sender,
            "recipient": recipient,
            "message_type": message_type,
            "priority": priority,
            "payload": payload or {},
            "context": context or {},
        }
        if task_id is not None:
            body["task_id"] = task_id
        if reply_to is not None:
            body["reply_to"] = reply_to
        if topic is not None:
            body["topic"] = topic
        r = await self._client.post("/messages", json=body)
        r.raise_for_status()
        return r.json()

    async def poll(self, agent: str, since: str, limit: int = 100) -> dict:
        r = await self._client.get("/messages/poll", params={
            "agent": agent, "since": since, "limit": limit
        })
        r.raise_for_status()
        return r.json()

    async def get_message(self, msg_id: int) -> dict:
        r = await self._client.get(f"/messages/{msg_id}")
        r.raise_for_status()
        return r.json()

    async def get_thread(self, msg_id: int) -> list[dict]:
        r = await self._client.get(f"/messages/{msg_id}/thread")
        r.raise_for_status()
        return r.json()

    async def ack_message(self, msg_id: int, agent: str, status: str = "received") -> dict:
        r = await self._client.post(f"/messages/{msg_id}/ack", json={
            "agent": agent, "status": status
        })
        r.raise_for_status()
        return r.json()

    # --- Tasks ---

    async def create_task(self, title: str, description: str = "",
                          assignee: str | None = None, priority: str = "normal",
                          metadata: dict | None = None,
                          watchers: list[str] | None = None) -> dict:
        body = {"title": title, "description": description, "priority": priority}
        if assignee:
            body["assignee"] = assignee
        if metadata:
            body["metadata"] = metadata
        if watchers:
            body["watchers"] = watchers
        r = await self._client.post("/tasks", json=body)
        r.raise_for_status()
        return r.json()

    async def get_task(self, task_id: int) -> dict:
        r = await self._client.get(f"/tasks/{task_id}")
        r.raise_for_status()
        return r.json()

    async def update_task(self, task_id: int, state: str | None = None,
                          assignee: str | None = None,
                          metadata: dict | None = None) -> dict:
        body = {}
        if state:
            body["state"] = state
        if assignee:
            body["assignee"] = assignee
        if metadata:
            body["metadata"] = metadata
        r = await self._client.patch(f"/tasks/{task_id}", json=body)
        r.raise_for_status()
        return r.json()

    async def add_watcher(self, task_id: int, agent: str) -> dict:
        r = await self._client.post(f"/tasks/{task_id}/watchers", json={"agent": agent})
        r.raise_for_status()
        return r.json()

    # --- Subscriptions ---

    async def subscribe(self, agent: str, topic: str) -> dict:
        r = await self._client.post("/subscriptions", json={
            "agent": agent, "topic": topic
        })
        r.raise_for_status()
        return r.json()

    # --- Capabilities ---

    async def find_agents_by_capability(self, capability: str) -> list[dict]:
        r = await self._client.get(f"/capabilities/{capability}/agents")
        r.raise_for_status()
        return r.json()

    # --- Health ---

    async def health(self) -> dict:
        r = await self._client.get("/health")
        r.raise_for_status()
        return r.json()
