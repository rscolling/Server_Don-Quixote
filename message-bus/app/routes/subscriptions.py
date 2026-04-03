from fastapi import APIRouter, Query
from app.models import SubscriptionCreate, Subscription
from app.database import subscribe, unsubscribe, list_subscriptions, list_topics

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("", response_model=Subscription, status_code=201)
async def create_subscription(body: SubscriptionCreate):
    return await subscribe(body.agent, body.topic)


@router.delete("")
async def delete_subscription(
    agent: str = Query(..., description="Agent shorthand"),
    topic: str = Query(..., description="Topic to unsubscribe from"),
):
    await unsubscribe(agent, topic)
    return {"agent": agent, "topic": topic, "status": "unsubscribed"}


@router.get("", response_model=list[Subscription])
async def get_subscriptions(
    agent: str | None = None,
    topic: str | None = None,
):
    return await list_subscriptions(agent=agent, topic=topic)


@router.get("/topics")
async def get_topics():
    return await list_topics()
