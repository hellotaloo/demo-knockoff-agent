"""
Candidacy router — pipeline tracking for candidates across vacancies.

GET  /candidacies                  — list (scoped to vacancy or workspace)
POST /candidacies                  — add candidate to pipeline
PATCH /candidacies/{id}/stage      — move to a different stage
"""
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.auth.dependencies import AuthContext, require_workspace
from src.database import get_db_pool
from src.exceptions import InvalidTransitionError, NotFoundError
from src.repositories.candidacy_repo import CandidacyRepository
from src.repositories.candidate_repo import CandidateRepository
from src.repositories.vacancy_repo import VacancyRepository
from src.models.candidacy import (
    CandidacyResponse,
    CandidacyCreate,
    CandidacyStage,
    CandidacyCandidateInfo,
    CandidacyVacancyInfo,
    CandidacyVacancyLink,
    CandidacyApplicationSummary,
)
from src.models.placement import PlacementCreate, PlacementResponse
from src.repositories.placement_repo import PlacementRepository
from src.services.candidacy_transition_service import CandidacyStageTransitionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/candidacies", tags=["Candidacies"])


def _build_response(row) -> CandidacyResponse:
    """Map a DB row (with nested columns) to CandidacyResponse."""
    latest_app = None
    if row["app_id"] is not None:
        latest_app = CandidacyApplicationSummary(
            id=str(row["app_id"]),
            channel=row["app_channel"],
            status=row["app_status"] or "active",
            qualified=row["app_qualified"],
            open_questions_score=row["app_score"],
            knockout_passed=row["app_ko_passed"] or 0,
            knockout_total=row["app_ko_total"] or 0,
            completed_at=row["app_completed_at"],
            interview_scheduled_at=row["app_interview_scheduled_at"],
        )

    linked_vacancies = []
    raw_lv = row["linked_vacancies"]
    if raw_lv:
        items = raw_lv if isinstance(raw_lv, list) else __import__("json").loads(raw_lv)
        linked_vacancies = [
            CandidacyVacancyLink(
                candidacy_id=str(lv["candidacy_id"]),
                vacancy_id=str(lv["vacancy_id"]),
                vacancy_title=lv["vacancy_title"],
                stage=CandidacyStage(lv["stage"]),
            )
            for lv in items
        ]

    vacancy = None
    if row["vac_id"] is not None:
        vacancy = CandidacyVacancyInfo(
            id=str(row["vac_id"]),
            title=row["vac_title"],
            company=row["vac_company"],
            is_open_application=row["vac_is_open_application"] or False,
        )

    return CandidacyResponse(
        id=str(row["id"]),
        candidate_id=str(row["candidate_id"]),
        stage=CandidacyStage(row["stage"]),
        source=row["source"],
        stage_updated_at=row["stage_updated_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        candidate=CandidacyCandidateInfo(
            id=str(row["cand_id"]),
            full_name=row["cand_full_name"],
            phone=row["cand_phone"],
            email=row["cand_email"],
        ),
        vacancy=vacancy,
        latest_application=latest_app,
        linked_vacancies=linked_vacancies,
        recruiter_verification=row["recruiter_verification"] or False,
        recruiter_verification_reason=row["recruiter_verification_reason"],
        contract_url=row["contract_url"],
    )


@router.get("", response_model=list[CandidacyResponse])
async def list_candidacies(
    vacancy_id: Optional[uuid.UUID] = Query(None, description="Filter to one vacancy (Kanban view)"),
    candidate_id: Optional[uuid.UUID] = Query(None, description="Filter to one candidate (candidate detail panel)"),
    stage: Optional[CandidacyStage] = Query(None, description="Filter by stage"),
    ctx: AuthContext = Depends(require_workspace),
):
    """
    List candidacies with nested candidate, vacancy, and latest application summary.

    - With vacancy_id: returns the pipeline for a single vacancy (Kanban view).
    - Without vacancy_id: returns all candidacies workspace-wide (global Pipeline view — one card per candidacy).
    """
    pool = await get_db_pool()
    repo = CandidacyRepository(pool)

    rows = await repo.list(
        workspace_id=ctx.workspace_id,
        vacancy_id=vacancy_id,
        candidate_id=candidate_id,
        stage=stage.value if stage else None,
    )

    return [_build_response(row) for row in rows]


@router.post("", response_model=CandidacyResponse, status_code=201)
async def create_candidacy(
    body: CandidacyCreate,
    ctx: AuthContext = Depends(require_workspace),
):
    """
    Add a candidate to a vacancy pipeline (or talent pool if vacancy_id omitted).

    Returns 409 if the candidate already has a candidacy for that vacancy.
    """
    pool = await get_db_pool()
    repo = CandidacyRepository(pool)

    # Validate candidate exists
    candidate_id = uuid.UUID(body.candidate_id)
    candidate_repo = CandidateRepository(pool)
    if not await candidate_repo.get_by_id(candidate_id):
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Validate vacancy exists (if provided)
    vacancy_id: Optional[uuid.UUID] = None
    if body.vacancy_id:
        vacancy_id = uuid.UUID(body.vacancy_id)
        vacancy_repo = VacancyRepository(pool)
        if not await vacancy_repo.exists(vacancy_id):
            raise HTTPException(status_code=404, detail="Vacancy not found")

        # Prevent duplicate candidacy for the same vacancy
        if await repo.exists_for_vacancy(candidate_id, vacancy_id):
            raise HTTPException(
                status_code=409,
                detail="Candidate already has a candidacy for this vacancy",
            )

    row = await repo.create(
        workspace_id=ctx.workspace_id,
        candidate_id=candidate_id,
        vacancy_id=vacancy_id,
        stage=body.stage.value,
        source=body.source,
    )

    # Fetch full row with nested joins for response
    full_row = await repo.get_by_id(row["id"])
    return _build_response(full_row)


@router.patch("/{candidacy_id}/stage", response_model=CandidacyResponse)
async def update_stage(
    candidacy_id: uuid.UUID,
    stage: CandidacyStage = Query(..., description="New stage value"),
    placement: Optional[PlacementCreate] = Body(None),
    ctx: AuthContext = Depends(require_workspace),
):
    """
    Move a candidacy to a different stage (drag-and-drop or dropdown).
    Validates the transition against the state machine, resets stage_updated_at,
    logs an activity, and fires any configured stage-entry agent triggers.

    When transitioning to 'offer', an optional placement body can be included
    to create the placement record in the same call.
    """
    pool = await get_db_pool()

    # Verify candidacy exists and belongs to workspace
    repo = CandidacyRepository(pool)
    check_row = await repo.get_by_id(candidacy_id)
    if not check_row:
        raise HTTPException(status_code=404, detail="Candidacy not found")
    # Verify workspace ownership via the vacancy
    if check_row["vac_id"]:
        vac_row = await pool.fetchrow(
            "SELECT workspace_id FROM ats.vacancies WHERE id = $1", check_row["vac_id"]
        )
        if not vac_row or vac_row["workspace_id"] != ctx.workspace_id:
            raise HTTPException(status_code=404, detail="Candidacy not found")

    # Create placement BEFORE transition so the background planner can read it
    if stage == CandidacyStage.OFFER and placement:
        placement_repo = PlacementRepository(pool)
        await placement_repo.create(
            workspace_id=ctx.workspace_id,
            candidate_id=uuid.UUID(placement.candidate_id),
            vacancy_id=uuid.UUID(placement.vacancy_id),
            application_id=check_row["app_id"] if check_row["app_id"] else None,
            client_id=uuid.UUID(placement.client_id) if placement.client_id else None,
            start_date=placement.start_date,
            regime=placement.regime.value if placement.regime else None,
            contract_id=placement.contract_id,
        )

    transition_service = CandidacyStageTransitionService(pool)

    try:
        await transition_service.transition(
            candidacy_id=candidacy_id,
            to_stage=stage,
            triggered_by="recruiter",
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Candidacy not found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    repo = CandidacyRepository(pool)
    full_row = await repo.get_by_id(candidacy_id)

    return _build_response(full_row)
