"""
Monitoring router - provides global activity feed / event log.

Historical view of agent actions, candidate interactions, and recruiter actions.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Query, Depends

from src.auth.dependencies import AuthContext, require_workspace
from src.database import get_db_pool
from src.services import ActivityService
from src.models.common import PaginatedResponse
from src.models.activity import (
    ActorType,
    ActivityEventType,
    ActivityChannel,
    GlobalActivityResponse,
)

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get("", response_model=PaginatedResponse[GlobalActivityResponse])
async def list_activities(
    actor_type: Optional[ActorType] = Query(None, description="Filter by actor type: agent, recruiter, candidate, system"),
    event_type: Optional[list[ActivityEventType]] = Query(None, description="Filter by event type(s)"),
    channel: Optional[ActivityChannel] = Query(None, description="Filter by channel: voice, whatsapp, cv, web"),
    candidate_id: Optional[str] = Query(None, description="Filter by candidate ID"),
    vacancy_id: Optional[str] = Query(None, description="Filter by vacancy ID"),
    since: Optional[str] = Query(None, description="ISO datetime - only return activities created after this timestamp"),
    limit: int = Query(50, ge=1, le=100, description="Number of activities to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    ctx: AuthContext = Depends(require_workspace),
):
    """
    Get all activities across the system for the global activities feed.

    Shows agent actions, candidate interactions, and recruiter actions.
    Results are ordered by most recent first.
    """
    pool = await get_db_pool()
    service = ActivityService(pool)

    # Parse since string to datetime for asyncpg
    since_dt = None
    if since:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

    result = await service.get_all_activities(
        actor_type=actor_type,
        event_types=event_type,
        channel=channel,
        candidate_id=candidate_id,
        vacancy_id=vacancy_id,
        workspace_id=ctx.workspace_id,
        since=since_dt,
        limit=limit,
        offset=offset
    )

    return PaginatedResponse(
        items=result.activities,
        total=result.total,
        limit=limit,
        offset=offset,
    )
