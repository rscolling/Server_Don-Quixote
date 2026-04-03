from fastapi import APIRouter, HTTPException, Query
from app.models import MessageCreate, Message, AckCreate, Ack
from app.database import (
    insert_message, get_message, list_messages, poll_messages,
    get_thread, insert_ack, get_acks, now_iso,
)

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("", response_model=Message, status_code=201)
async def send_message(body: MessageCreate):
    if body.reply_to is not None:
        parent = await get_message(body.reply_to)
        if not parent:
            raise HTTPException(status_code=422, detail=f"reply_to message {body.reply_to} not found")

    msg = await insert_message(
        sender=body.sender,
        recipient=body.recipient,
        message_type=body.message_type.value,
        priority=body.priority.value,
        payload=body.payload,
        context=body.context,
        task_id=body.task_id,
        reply_to=body.reply_to,
        topic=body.topic,
    )
    return msg


@router.get("/poll")
async def poll(
    agent: str = Query(..., description="Agent shorthand to poll for"),
    since: str = Query(..., description="ISO-8601 timestamp, return messages after this"),
    limit: int = Query(100, ge=1, le=500, description="Max messages to return"),
):
    messages = await poll_messages(agent, since, limit=limit)
    return {"messages": messages, "server_time": now_iso()}


@router.get("", response_model=list[Message])
async def get_messages(
    sender: str | None = None,
    recipient: str | None = None,
    message_type: str | None = None,
    since: str | None = None,
    task_id: int | None = None,
    topic: str | None = None,
    thread_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await list_messages(
        sender=sender, recipient=recipient, message_type=message_type,
        since=since, task_id=task_id, topic=topic, thread_id=thread_id,
        limit=limit, offset=offset,
    )


@router.get("/{msg_id}", response_model=Message)
async def get_message_by_id(msg_id: int):
    msg = await get_message(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.get("/{msg_id}/thread", response_model=list[Message])
async def get_message_thread(msg_id: int):
    msg = await get_message(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    tid = msg.get("thread_id") or msg["id"]
    return await get_thread(tid)


@router.post("/{msg_id}/ack", response_model=Ack)
async def acknowledge_message(msg_id: int, body: AckCreate):
    msg = await get_message(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    return await insert_ack(msg_id, body.agent, body.status.value)


@router.get("/{msg_id}/acks", response_model=list[Ack])
async def get_message_acks(msg_id: int):
    msg = await get_message(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    return await get_acks(msg_id)
