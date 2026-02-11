"""
Agent listing endpoints - vacancies grouped by agent status.
"""
import logging
from typing import Literal
from fastapi import APIRouter, Query, Depends
import asyncpg

from src.models.vacancy import (
    VacancyResponse,
    ChannelsResponse,
    AgentStatusResponse,
    AgentsResponse,
    RecruiterSummary,
    ClientSummary,
)
from src.repositories.agent_vacancy_repo import AgentVacancyRepository
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Agents"])


async def get_agent_vacancy_repo() -> AgentVacancyRepository:
    """Dependency to get AgentVacancyRepository."""
    pool = await get_db_pool()
    return AgentVacancyRepository(pool)


def build_vacancy_response(row: asyncpg.Record) -> VacancyResponse:
    """Build VacancyResponse from database row."""
    # Build recruiter info if present
    recruiter = None
    if row.get("recruiter_id") and row.get("r_id"):
        recruiter = RecruiterSummary(
            id=str(row["r_id"]),
            name=row["r_name"],
            email=row.get("r_email"),
            phone=row.get("r_phone"),
            team=row.get("r_team"),
            role=row.get("r_role"),
            avatar_url=row.get("r_avatar_url")
        )

    # Build client info if present
    client = None
    if row.get("client_id") and row.get("c_id"):
        client = ClientSummary(
            id=str(row["c_id"]),
            name=row["c_name"],
            location=row.get("c_location"),
            industry=row.get("c_industry"),
            logo=row.get("c_logo")
        )

    return VacancyResponse(
        id=str(row["id"]),
        title=row["title"],
        company=row["company"],
        location=row.get("location"),
        description=row.get("description"),
        status=row["status"],
        created_at=row["created_at"],
        archived_at=row.get("archived_at"),
        source=row.get("source"),
        source_id=row.get("source_id"),
        has_screening=row["has_screening"],
        is_online=row.get("is_online"),
        channels=ChannelsResponse(
            voice=row.get("voice_enabled") or False,
            whatsapp=row.get("whatsapp_enabled") or False,
            cv=row.get("cv_enabled") or False
        ),
        agents=AgentsResponse(
            prescreening=AgentStatusResponse(
                exists=row["has_screening"],
                status="online" if row.get("is_online") else ("offline" if row["has_screening"] else None)
            ),
            preonboarding=AgentStatusResponse(
                exists=row.get("preonboarding_agent_enabled") or False,
                status=None
            ),
            insights=AgentStatusResponse(
                exists=row.get("insights_agent_enabled") or False,
                status=None
            )
        ),
        recruiter_id=str(row["recruiter_id"]) if row.get("recruiter_id") else None,
        recruiter=recruiter,
        client_id=str(row["client_id"]) if row.get("client_id") else None,
        client=client,
        candidates_count=row["candidates_count"],
        completed_count=row["completed_count"],
        qualified_count=row["qualified_count"],
        last_activity_at=row.get("last_activity_at")
    )


@router.get("/prescreening/vacancies")
async def list_prescreening_vacancies(
    status: Literal["new", "generated", "archived"] = Query(..., description="Agent status filter"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: AgentVacancyRepository = Depends(get_agent_vacancy_repo)
):
    """
    List vacancies by pre-screening agent status.

    Status definitions:
    - **new**: No pre-screening record (questions not generated yet)
    - **generated**: Has pre-screening record (questions exist, can be online/offline)
    - **archived**: Vacancy status is 'closed' or 'filled'
    """
    rows, total = await repo.list_prescreening_vacancies(
        status=status, limit=limit, offset=offset
    )

    vacancies = [build_vacancy_response(row) for row in rows]

    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/preonboarding/vacancies")
async def list_preonboarding_vacancies(
    status: Literal["new", "generated", "archived"] = Query(..., description="Agent status filter"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: AgentVacancyRepository = Depends(get_agent_vacancy_repo)
):
    """
    List vacancies by pre-onboarding agent status.

    Status definitions:
    - **new**: Pre-onboarding agent not enabled
    - **generated**: Pre-onboarding agent enabled
    - **archived**: Vacancy status is 'closed' or 'filled'
    """
    rows, total = await repo.list_preonboarding_vacancies(
        status=status, limit=limit, offset=offset
    )

    vacancies = [build_vacancy_response(row) for row in rows]

    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset
    }
