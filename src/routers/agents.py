"""
Agent listing endpoints - vacancies with agent-specific stats.

Both endpoints return the same AgentVacancyResponse shape, with
agent-specific data in self-describing AgentStatItem lists.
"""
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException
import asyncpg

from src.models.vacancy import (
    NavigationCountsResponse,
    RecruiterSummary,
    ClientSummary,
    AgentStatItem,
    AgentVacancyChannels,
    AgentVacancyResponse,
    AgentDashboardStatsResponse,
)
from src.auth.dependencies import AuthContext, require_workspace
from src.repositories.agent_vacancy_repo import AgentVacancyRepository
from src.repositories.workspace_agent_availability_repo import WorkspaceAgentAvailabilityRepository
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Agents"])


async def get_agent_vacancy_repo() -> AgentVacancyRepository:
    """Dependency to get AgentVacancyRepository."""
    pool = await get_db_pool()
    return AgentVacancyRepository(pool)


async def get_availability_repo() -> WorkspaceAgentAvailabilityRepository:
    """Dependency to get WorkspaceAgentAvailabilityRepository."""
    pool = await get_db_pool()
    return WorkspaceAgentAvailabilityRepository(pool)


async def require_agent_available(
    workspace_id: uuid.UUID, agent_type: str, repo: WorkspaceAgentAvailabilityRepository
):
    """Raise 403 if agent type is not available for workspace."""
    if not await repo.is_agent_available(workspace_id, agent_type):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{agent_type}' is not available for this workspace",
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_recruiter(row: asyncpg.Record) -> Optional[RecruiterSummary]:
    if row.get("recruiter_id") and row.get("r_id"):
        return RecruiterSummary(
            id=str(row["r_id"]),
            name=row["r_name"],
            email=row.get("r_email"),
            phone=row.get("r_phone"),
            team=row.get("r_team"),
            role=row.get("r_role"),
            avatar_url=row.get("r_avatar_url"),
        )
    return None


def _build_client(row: asyncpg.Record) -> Optional[ClientSummary]:
    if row.get("client_id") and row.get("c_id"):
        return ClientSummary(
            id=str(row["c_id"]),
            name=row["c_name"],
            location=row.get("c_location"),
            industry=row.get("c_industry"),
            logo=row.get("c_logo"),
        )
    return None


# ---------------------------------------------------------------------------
# Agent-specific vacancy builders
# ---------------------------------------------------------------------------


def _build_prescreening_vacancy(row: asyncpg.Record) -> AgentVacancyResponse:
    """Build AgentVacancyResponse with prescreening stats."""
    return AgentVacancyResponse(
        id=str(row["id"]),
        title=row["title"],
        company=row["company"],
        location=row.get("location"),
        status=row["status"],
        created_at=row["created_at"],
        agent_status=row["agent_status"],
        stats=[
            AgentStatItem(key="candidates_count", label="Kandidaten", value=row["candidates_count"]),
            AgentStatItem(key="completed_count", label="Afgerond", value=row["completed_count"]),
            AgentStatItem(key="qualified_count", label="Gekwalificeerd", value=row["qualified_count"]),
        ],
        channels=AgentVacancyChannels(
            voice=row["voice_enabled"],
            whatsapp=row["whatsapp_enabled"],
            cv=row["cv_enabled"],
        ),
        last_activity_at=row.get("last_activity_at"),
        recruiter=_build_recruiter(row),
        client=_build_client(row),
    )


def _build_preonboarding_vacancy(row: asyncpg.Record) -> AgentVacancyResponse:
    """Build AgentVacancyResponse with document collection stats."""
    return AgentVacancyResponse(
        id=str(row["id"]),
        title=row["title"],
        company=row["company"],
        location=row.get("location"),
        status=row["status"],
        created_at=row["created_at"],
        agent_status=row["agent_status"],
        stats=[
            AgentStatItem(key="active", label="Actief", value=row["dc_active"]),
            AgentStatItem(key="completed", label="Afgerond", value=row["dc_completed"]),
            AgentStatItem(key="needs_review", label="Review", value=row["dc_needs_review"]),
        ],
        last_activity_at=row.get("last_activity_at"),
        recruiter=_build_recruiter(row),
        client=_build_client(row),
    )


# ---------------------------------------------------------------------------
# Navigation counts
# ---------------------------------------------------------------------------


@router.get("/counts", response_model=NavigationCountsResponse)
async def get_navigation_counts(
    ctx: AuthContext = Depends(require_workspace),
):
    """
    Get lightweight counts for navigation sidebar.
    Reads from denormalized ats.navigation_counts table (kept in sync by DB triggers).
    """
    pool = await get_db_pool()

    row = await pool.fetchrow("""
        SELECT * FROM ats.navigation_counts
        WHERE workspace_id = $1
    """, ctx.workspace_id)

    if not row:
        return NavigationCountsResponse(
            prescreening={"active": 0, "stuck": 0},
            preonboarding={"active": 0, "stuck": 0},
            activities={"active": 0, "stuck": 0},
            vacancies={"active": 0, "archived": 0},
            candidates={"total": 0, "archived": 0},
        )

    return NavigationCountsResponse(
        prescreening={
            "active": row["prescreening_active"],
            "stuck": row["prescreening_stuck"],
        },
        preonboarding={
            "active": row["preonboarding_active"],
            "stuck": row["preonboarding_stuck"],
        },
        activities={
            "active": row["activities_active"],
            "stuck": row["activities_stuck"],
        },
        vacancies={
            "active": row["vacancies_active"],
            "archived": row["vacancies_archived"],
        },
        candidates={
            "total": row["candidates_total"],
            "archived": row["candidates_archived"],
        },
    )


# ---------------------------------------------------------------------------
# Vacancy list endpoints
# ---------------------------------------------------------------------------


@router.get("/prescreening/vacancies")
async def list_prescreening_vacancies(
    archived: bool = Query(False, description="If true, return archived vacancies instead of active ones"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_workspace),
    repo: AgentVacancyRepository = Depends(get_agent_vacancy_repo),
    avail_repo: WorkspaceAgentAvailabilityRepository = Depends(get_availability_repo),
):
    """
    List vacancies with prescreening agent status and stats.

    Use `?archived=true` to get closed/filled/archived vacancies.

    Each vacancy includes an `agent_status` field:
    - **new**: No pre-screening record (questions not generated yet)
    - **generating**: Questions are being generated
    - **generated**: Has pre-screening record but not published
    - **published**: Pre-screening is published
    - **archived**: Vacancy or agent archived
    """
    await require_agent_available(ctx.workspace_id, "prescreening", avail_repo)
    rows, total = await repo.list_prescreening_vacancies(workspace_id=ctx.workspace_id, archived=archived, limit=limit, offset=offset)
    vacancies = [_build_prescreening_vacancy(row) for row in rows]

    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/preonboarding/vacancies")
async def list_preonboarding_vacancies(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_workspace),
    repo: AgentVacancyRepository = Depends(get_agent_vacancy_repo),
    avail_repo: WorkspaceAgentAvailabilityRepository = Depends(get_availability_repo),
):
    """
    List all non-archived vacancies with document collection agent status and stats.

    Each vacancy includes an `agent_status` field:
    - **new**: Document collection agent not registered
    - **generated**: Document collection agent registered
    """
    await require_agent_available(ctx.workspace_id, "document_collection", avail_repo)
    rows, total = await repo.list_preonboarding_vacancies(workspace_id=ctx.workspace_id, limit=limit, offset=offset)
    vacancies = [_build_preonboarding_vacancy(row) for row in rows]

    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Dashboard stats endpoints
# ---------------------------------------------------------------------------


@router.get("/prescreening/stats", response_model=AgentDashboardStatsResponse)
async def get_prescreening_stats(
    ctx: AuthContext = Depends(require_workspace),
    repo: AgentVacancyRepository = Depends(get_agent_vacancy_repo),
    avail_repo: WorkspaceAgentAvailabilityRepository = Depends(get_availability_repo),
):
    """Aggregate dashboard stats for the pre-screening overview page."""
    await require_agent_available(ctx.workspace_id, "prescreening", avail_repo)
    row = await repo.get_prescreening_dashboard_stats(workspace_id=ctx.workspace_id)

    total = row["total"]
    completed = row["completed_count"]
    qualified = row["qualified_count"]
    completion_rate = int(completed / total * 100) if total > 0 else 0
    qualification_rate = int(qualified / completed * 100) if completed > 0 else 0

    return AgentDashboardStatsResponse(
        metrics=[
            AgentStatItem(
                key="total_this_week", label="Pre-screenings", value=row["this_week"],
                description="Deze week", variant="blue", icon="users",
            ),
            AgentStatItem(
                key="completion_rate", label="Afrondingspercentage", value=completion_rate,
                suffix="%", variant="dark", icon="check-circle",
            ),
            AgentStatItem(
                key="qualified_count", label="Gekwalificeerd", value=qualified,
                description="Kandidaten", variant="lime", icon="user-check",
            ),
            AgentStatItem(
                key="channels", label="Kanalen", value=0,
                description=f"voice: {row['voice_count']}, whatsapp: {row['whatsapp_count']}",
                variant="dark", icon="phone",
            ),
        ]
    )


@router.get("/preonboarding/stats", response_model=AgentDashboardStatsResponse)
async def get_preonboarding_stats(
    ctx: AuthContext = Depends(require_workspace),
    repo: AgentVacancyRepository = Depends(get_agent_vacancy_repo),
    avail_repo: WorkspaceAgentAvailabilityRepository = Depends(get_availability_repo),
):
    """Aggregate dashboard stats for the document collection overview page."""
    await require_agent_available(ctx.workspace_id, "document_collection", avail_repo)
    row = await repo.get_preonboarding_dashboard_stats(workspace_id=ctx.workspace_id)

    total = row["total"]
    completed = row["completed"]
    completion_rate = int(completed / total * 100) if total > 0 else 0

    return AgentDashboardStatsResponse(
        metrics=[
            AgentStatItem(
                key="active_collections", label="Actieve collecties", value=row["active"],
                description="Lopend", variant="blue", icon="file-text",
            ),
            AgentStatItem(
                key="completion_rate", label="Afrondingspercentage", value=completion_rate,
                suffix="%", variant="dark", icon="check-circle-2",
            ),
            AgentStatItem(
                key="completed", label="Volledig verzameld", value=completed,
                description="Afgerond", variant="lime", icon="file-check",
            ),
            AgentStatItem(
                key="needs_review", label="Review nodig", value=row["needs_review"],
                description="Wacht op verificatie", variant="pink", icon="alert-circle",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Agent availability
# ---------------------------------------------------------------------------


@router.get("/availability")
async def get_agent_availability(
    ctx: AuthContext = Depends(require_workspace),
    avail_repo: WorkspaceAgentAvailabilityRepository = Depends(get_availability_repo),
):
    """Get available agent types for the current workspace."""
    agents = await avail_repo.get_available_agents(ctx.workspace_id)
    return {"available_agents": agents}
