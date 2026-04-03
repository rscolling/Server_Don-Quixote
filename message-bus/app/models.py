from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TASK_ASSIGNMENT = "task_assignment"
    STATUS_UPDATE = "status_update"
    DELIVERABLE = "deliverable"
    FEEDBACK = "feedback"
    QUESTION = "question"
    ESCALATION = "escalation"
    STATE_CHANGE = "state_change"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskState(str, Enum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    REWORK = "REWORK"
    ACCEPTED = "ACCEPTED"
    CLOSED = "CLOSED"


class AckStatus(str, Enum):
    RECEIVED = "received"
    READ = "read"
    ACTED = "acted"


VALID_TRANSITIONS: dict[str, list[str]] = {
    "CREATED": ["ASSIGNED"],
    "ASSIGNED": ["IN_PROGRESS", "CREATED"],
    "IN_PROGRESS": ["IN_REVIEW"],
    "IN_REVIEW": ["ACCEPTED", "REWORK"],
    "REWORK": ["IN_PROGRESS"],
    "ACCEPTED": ["CLOSED"],
    "CLOSED": [],
}


# --- Request models ---

class MessageCreate(BaseModel):
    sender: str
    recipient: str
    message_type: MessageType
    priority: Priority = Priority.NORMAL
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[int] = None
    reply_to: Optional[int] = None
    topic: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    assignee: Optional[str] = None
    priority: Priority = Priority.NORMAL
    file_paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    watchers: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    state: Optional[TaskState] = None
    assignee: Optional[str] = None
    file_paths: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None


class AgentRegister(BaseModel):
    shorthand: str
    name: str
    role: str = ""
    status: str = "active"
    capabilities: list["CapabilityRegister"] = Field(default_factory=list)


class AckCreate(BaseModel):
    agent: str
    status: AckStatus = AckStatus.RECEIVED


class CapabilityRegister(BaseModel):
    name: str
    version: str = "1.0"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionCreate(BaseModel):
    agent: str
    topic: str


class SubscriptionDelete(BaseModel):
    agent: str
    topic: str


class WatcherAdd(BaseModel):
    agent: str


# --- Response models ---

class Message(BaseModel):
    id: int
    sender: str
    recipient: str
    message_type: str
    priority: str
    payload: dict[str, Any]
    context: dict[str, Any]
    task_id: Optional[int]
    timestamp: str
    reply_to: Optional[int] = None
    thread_id: Optional[int] = None
    topic: Optional[str] = None


class Task(BaseModel):
    id: int
    title: str
    description: str
    assignee: Optional[str]
    state: str
    priority: str
    file_paths: list[str]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    watchers: list[str] = Field(default_factory=list)


class Agent(BaseModel):
    shorthand: str
    name: str
    role: str
    status: str
    registered_at: str
    last_seen: Optional[str]
    is_active: bool = False
    capabilities: list["Capability"] = Field(default_factory=list)


class Ack(BaseModel):
    id: int
    message_id: int
    agent: str
    status: str
    acked_at: str


class Capability(BaseModel):
    id: int
    agent: str
    name: str
    version: str
    metadata: dict[str, Any]


class Subscription(BaseModel):
    id: int
    agent: str
    topic: str
    created_at: str
