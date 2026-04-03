from fastapi import APIRouter, HTTPException, Query
from app.models import TaskCreate, TaskUpdate, Task, WatcherAdd, VALID_TRANSITIONS
from app.database import (
    insert_task, get_task, list_tasks, update_task,
    insert_message, add_watcher, remove_watcher, list_watchers,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _notify_watchers(task_id: int, task: dict, old_state: str | None, new_state: str):
    """Send state_change message to all watchers via task topic."""
    await insert_message(
        sender="SYSTEM",
        recipient="ALL",
        message_type="state_change",
        priority=task["priority"],
        payload={
            "task_id": task_id,
            "title": task["title"],
            "old_state": old_state,
            "new_state": new_state,
        },
        context={},
        task_id=task_id,
        topic=f"task:{task_id}",
    )


@router.post("", response_model=Task, status_code=201)
async def create_task(body: TaskCreate):
    task = await insert_task(
        title=body.title,
        description=body.description,
        assignee=body.assignee,
        priority=body.priority.value,
        file_paths=body.file_paths,
        metadata=body.metadata,
        watchers=body.watchers,
    )
    # Auto-generate state_change message via topic
    await _notify_watchers(task["id"], task, None, "CREATED")
    return task


@router.get("", response_model=list[Task])
async def get_tasks(
    state: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await list_tasks(
        state=state, assignee=assignee, priority=priority,
        limit=limit, offset=offset,
    )


@router.get("/{task_id}", response_model=Task)
async def get_task_by_id(task_id: int):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=Task)
async def update_task_state(task_id: int, body: TaskUpdate):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = {}

    if body.state is not None:
        current_state = task["state"]
        new_state = body.state.value
        allowed = VALID_TRANSITIONS.get(current_state, [])
        if new_state not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid transition: {current_state} -> {new_state}. "
                       f"Allowed: {allowed}",
            )
        updates["state"] = new_state

        # Notify all watchers via topic
        await _notify_watchers(task_id, task, current_state, new_state)

    if body.assignee is not None:
        updates["assignee"] = body.assignee
        # Auto-add new assignee as watcher
        await add_watcher(task_id, body.assignee)
    if body.file_paths is not None:
        updates["file_paths"] = body.file_paths
    if body.metadata is not None:
        updates["metadata"] = body.metadata

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = await update_task(task_id, **updates)
    return updated


@router.get("/{task_id}/watchers")
async def get_watchers(task_id: int):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "watchers": await list_watchers(task_id)}


@router.post("/{task_id}/watchers", status_code=201)
async def watch_task(task_id: int, body: WatcherAdd):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await add_watcher(task_id, body.agent)
    return {"task_id": task_id, "agent": body.agent, "status": "watching"}


@router.delete("/{task_id}/watchers/{agent}")
async def unwatch_task(task_id: int, agent: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await remove_watcher(task_id, agent)
    return {"task_id": task_id, "agent": agent, "status": "unwatched"}
