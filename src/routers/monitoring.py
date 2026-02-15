"""
Monitoring router - provides global activity feed / event log.

Historical view of agent actions, candidate interactions, and recruiter actions.
"""
from typing import Optional
from fastapi import APIRouter, Query

from src.database import get_db_pool
from src.services import ActivityService
from src.models.activity import (
    ActorType,
    ActivityEventType,
    ActivityChannel,
    GlobalActivitiesResponse,
)

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get("", response_model=GlobalActivitiesResponse)
async def list_activities(
    actor_type: Optional[ActorType] = Query(None, description="Filter by actor type: agent, recruiter, candidate, system"),
    event_type: Optional[list[ActivityEventType]] = Query(None, description="Filter by event type(s)"),
    channel: Optional[ActivityChannel] = Query(None, description="Filter by channel: voice, whatsapp, cv, web"),
    limit: int = Query(50, ge=1, le=100, description="Number of activities to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Get all activities across the system for the global activities feed.

    Shows agent actions, candidate interactions, and recruiter actions.
    Results are ordered by most recent first.
    """
    pool = await get_db_pool()
    service = ActivityService(pool)

    return await service.get_all_activities(
        actor_type=actor_type,
        event_types=event_type,
        channel=channel,
        limit=limit,
        offset=offset
    )
