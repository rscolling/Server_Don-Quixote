from fastapi import APIRouter
from app.models import Agent
from app.database import list_all_capabilities, find_agents_by_capability

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("")
async def get_all_capabilities():
    return await list_all_capabilities()


@router.get("/{name}/agents", response_model=list[Agent])
async def get_agents_with_capability(name: str):
    return await find_agents_by_capability(name)
