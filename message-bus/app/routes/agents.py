from fastapi import APIRouter, HTTPException
from app.models import AgentRegister, Agent, CapabilityRegister, Capability
from app.database import (
    upsert_agent, list_agents, get_agent,
    upsert_capabilities, get_agent_capabilities,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=Agent)
async def register_agent(body: AgentRegister):
    agent = await upsert_agent(body.shorthand, body.name, body.role, body.status)
    if body.capabilities:
        await upsert_capabilities(
            body.shorthand,
            [c.model_dump() for c in body.capabilities],
        )
        agent = await get_agent(body.shorthand)
    return agent


@router.get("", response_model=list[Agent])
async def get_agents():
    return await list_agents()


@router.get("/{shorthand}", response_model=Agent)
async def get_agent_by_id(shorthand: str):
    agent = await get_agent(shorthand)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/{shorthand}/capabilities", response_model=list[Capability])
async def set_capabilities(shorthand: str, capabilities: list[CapabilityRegister]):
    agent = await get_agent(shorthand)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await upsert_capabilities(shorthand, [c.model_dump() for c in capabilities])
    return await get_agent_capabilities(shorthand)


@router.get("/{shorthand}/capabilities", response_model=list[Capability])
async def get_capabilities(shorthand: str):
    agent = await get_agent(shorthand)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await get_agent_capabilities(shorthand)
