"""
Vacancy-related endpoints.
"""
import uuid
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
from agents.cv_analyzer import analyze_cv_base64
from src.utils.dutch_dates import get_next_business_days, get_dutch_date

from pydantic import BaseModel

from src.auth.dependencies import AuthContext, require_workspace
from src.models.common import PaginatedResponse
from src.models.vacancy import VacancyResponse, VacancyStatsResponse, DashboardStatsResponse, VacancyDetailResponse, VacancyUpdateRequest
from src.models.application import ApplicationResponse, QuestionAnswerResponse, CVApplicationRequest
from src.repositories import VacancyRepository, ApplicationRepository
from src.repositories.vacancy_agent_repo import VacancyAgentRepository
from src.services import VacancyService, ActivityService
from src.database import get_db_pool
from src.dependencies import get_vacancy_repo, get_vacancy_service
from src.exceptions import parse_uuid

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vacancies"])


async def _verify_vacancy_workspace(pool, vacancy_id: uuid.UUID, workspace_id: uuid.UUID):
    """Verify a vacancy exists and belongs to the given workspace. Raises 404 if not."""
    row = await pool.fetchrow(
        "SELECT workspace_id FROM ats.vacancies WHERE id = $1", vacancy_id
    )
    if not row or row["workspace_id"] != workspace_id:
        raise HTTPException(status_code=404, detail="Vacancy not found")


@router.get("/vacancies", response_model=PaginatedResponse[VacancyResponse])
async def list_vacancies(
    status: Optional[str] = Query(None, description="Filter by status"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_workspace),
    repo: VacancyRepository = Depends(get_vacancy_repo),
    service: VacancyService = Depends(get_vacancy_service)
):
    """List all vacancies with optional filtering, including linked applicants."""
    rows, total = await repo.list_with_stats(status=status, source=source, workspace_id=ctx.workspace_id, limit=limit, offset=offset)

    # Fetch applicants for all vacancies in one query
    vacancy_ids = [row["id"] for row in rows]
    applicants_by_vacancy = await repo.get_applicants_by_vacancy_ids(vacancy_ids)

    # Build responses with applicants
    items = [
        service.build_vacancy_response(row, applicants_by_vacancy.get(row["id"], []))
        for row in rows
    ]

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/vacancies/{vacancy_id}", response_model=VacancyDetailResponse)
async def get_vacancy(
    vacancy_id: str,
    ctx: AuthContext = Depends(require_workspace),
    repo: VacancyRepository = Depends(get_vacancy_repo),
    service: VacancyService = Depends(get_vacancy_service)
):
    """Get a single vacancy by ID with activity timeline and applicants."""
    vacancy_uuid = parse_uuid(vacancy_id, field="vacancy_id")
    row = await repo.get_by_id(vacancy_uuid)

    if not row or row.get("workspace_id") != ctx.workspace_id:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    # Fetch applicants for this vacancy
    applicants_by_vacancy = await repo.get_applicants_by_vacancy_ids([vacancy_uuid])
    applicant_rows = applicants_by_vacancy.get(vacancy_uuid, [])

    # Get activity timeline for this vacancy
    pool = await get_db_pool()
    activity_service = ActivityService(pool)
    timeline = await activity_service.get_vacancy_activities(vacancy_id, limit=50)

    # Build base response with applicants and add timeline
    base_response = service.build_vacancy_response(row, applicant_rows)
    return VacancyDetailResponse(
        **base_response.model_dump(),
        timeline=timeline
    )


@router.patch("/vacancies/{vacancy_id}")
async def update_vacancy(
    vacancy_id: str,
    body: VacancyUpdateRequest,
    ctx: AuthContext = Depends(require_workspace),
    repo: VacancyRepository = Depends(get_vacancy_repo),
):
    """Update vacancy fields (e.g. start_date)."""
    vacancy_uuid = parse_uuid(vacancy_id, field="vacancy_id")

    # Verify workspace ownership before mutating
    existing = await repo.get_by_id(vacancy_uuid)
    if not existing or existing.get("workspace_id") != ctx.workspace_id:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    row = await repo.update(vacancy_uuid, start_date=body.start_date)
    if not row:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    return {"id": str(row["id"]), "start_date": row["start_date"].isoformat() if row["start_date"] else None}


@router.post("/vacancies/{vacancy_id}/cv-application")
async def create_cv_application(vacancy_id: str, request: CVApplicationRequest, ctx: AuthContext = Depends(require_workspace)):
    """
    Create an application from a CV PDF.

    Analyzes the CV against the vacancy's pre-screening questions,
    creates an application with pre-filled answers from the CV,
    and identifies which questions still need clarification.
    """
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Verify vacancy exists and belongs to workspace
    vacancy_row = await pool.fetchrow(
        "SELECT id, title, workspace_id FROM ats.vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_row or vacancy_row["workspace_id"] != ctx.workspace_id:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    # Get pre-screening
    ps_row = await pool.fetchrow(
        """
        SELECT id, intro, knockout_failed_action, final_action
        FROM agents.pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )

    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy. Configure interview questions first.")

    pre_screening_id = ps_row["id"]

    # Get questions
    question_rows = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM agents.pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )

    if not question_rows:
        raise HTTPException(status_code=400, detail="No interview questions configured for this vacancy")

    # Build question lists for CV analyzer
    knockout_questions = []
    qualification_questions = []
    ko_idx = 1
    qual_idx = 1

    for q in question_rows:
        if q["question_type"] == "knockout":
            knockout_questions.append({
                "id": f"ko_{ko_idx}",
                "question_text": q["question_text"]
            })
            ko_idx += 1
        else:
            qualification_questions.append({
                "id": f"qual_{qual_idx}",
                "question_text": q["question_text"],
                "ideal_answer": q["ideal_answer"] or ""
            })
            qual_idx += 1

    # Analyze CV
    logger.info(f"Analyzing CV for vacancy {vacancy_id} ({vacancy_row['title']})")
    try:
        result = await analyze_cv_base64(
            pdf_base64=request.pdf_base64,
            knockout_questions=knockout_questions,
            qualification_questions=qualification_questions,
        )
    except Exception as e:
        logger.error(f"CV analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"CV analysis failed: {str(e)}")

    # Determine if all knockout questions passed (have CV evidence)
    knockout_all_passed = all(ka.is_answered for ka in result.knockout_analysis)

    # Status and qualified are based on KNOCKOUT questions only
    # - If all knockouts passed → completed + qualified (can book meeting with recruiter)
    # - If any knockout needs clarification → active + not qualified (needs follow-up)
    # Qualification questions are extra info but don't block qualification
    application_status = 'completed' if knockout_all_passed else 'active'

    # Create application
    app_repo = ApplicationRepository(pool)
    async with pool.acquire() as conn:
        async with conn.transaction():
            app_row = await app_repo.create(
                vacancy_id=vacancy_uuid,
                candidate_name=request.candidate_name,
                channel="cv",
                candidate_phone=request.candidate_phone,
                qualified=knockout_all_passed if application_status == "completed" else False,
                status=application_status,
                summary=result.cv_summary,
                is_test=True,  # CV applications are always in test mode for now
                set_completed_now=(application_status == "completed"),
                conn=conn,
            )
            application_id = app_row["id"]
            started_at = app_row["started_at"]

            logger.info(f"Created CV application {application_id} for {request.candidate_name} (is_test=True)")

            # Insert knockout answers
            # passed=true if CV provides evidence for the knockout question
            for ka in result.knockout_analysis:
                await conn.execute(
                    """
                    INSERT INTO agents.pre_screening_answers
                    (application_id, question_id, question_text, answer, passed, source)
                    VALUES ($1, $2, $3, $4, $5, 'cv')
                    """,
                    application_id,
                    ka.id,
                    ka.question_text,
                    ka.cv_evidence if ka.is_answered else ka.clarification_needed,
                    ka.is_answered if ka.is_answered else None
                )

            # Insert qualification answers
            for qa in result.qualification_analysis:
                # If answered by CV, give a default score of 80
                score = 80 if qa.is_answered else None
                rating = "good" if qa.is_answered else None

                await conn.execute(
                    """
                    INSERT INTO agents.pre_screening_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, 'cv')
                    """,
                    application_id,
                    qa.id,
                    qa.question_text,
                    qa.cv_evidence if qa.is_answered else qa.clarification_needed,
                    score,
                    rating
                )

    # Build response
    answers = []

    # Add knockout answers
    # passed=true if CV provides evidence (knockout determines qualification)
    for ka in result.knockout_analysis:
        answers.append(QuestionAnswerResponse(
            question_id=ka.id,
            question_text=ka.question_text,
            question_type="knockout",
            answer=ka.cv_evidence if ka.is_answered else ka.clarification_needed,
            passed=ka.is_answered if ka.is_answered else None
        ))

    # Add qualification answers
    for qa in result.qualification_analysis:
        answers.append(QuestionAnswerResponse(
            question_id=qa.id,
            question_text=qa.question_text,
            question_type="qualification",
            answer=qa.cv_evidence if qa.is_answered else qa.clarification_needed,
            passed=None,
            score=80 if qa.is_answered else None,
            rating="good" if qa.is_answered else None
        ))

    # Count knockout questions passed (with CV evidence)
    knockout_passed = sum(1 for ka in result.knockout_analysis if ka.is_answered)
    knockout_total = len(result.knockout_analysis)

    return ApplicationResponse(
        id=str(application_id),
        vacancy_id=vacancy_id,
        candidate_name=request.candidate_name,
        channel="cv",
        status=application_status,
        qualified=knockout_all_passed,
        started_at=app_row["started_at"],
        completed_at=app_row["completed_at"],
        interaction_seconds=0,
        answers=answers,
        synced=False,
        knockout_passed=knockout_passed,
        knockout_total=knockout_total,
        open_questions_total=len(result.qualification_analysis),
        summary=result.cv_summary,
    )


@router.get("/vacancies/{vacancy_id}/stats")
async def get_vacancy_stats(vacancy_id: str, ctx: AuthContext = Depends(require_workspace)):
    """Get aggregated statistics for a vacancy."""
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    pool = await get_db_pool()
    repo = VacancyRepository(pool)
    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    # Get stats
    row = await repo.get_stats(vacancy_uuid)

    total = row["total"]
    completed_count = row["completed_count"]
    qualified_count = row["qualified_count"]

    # Calculate rates (avoid division by zero)
    completion_rate = int((completed_count / total * 100) if total > 0 else 0)
    qualification_rate = int((qualified_count / completed_count * 100) if completed_count > 0 else 0)

    return VacancyStatsResponse(
        vacancy_id=vacancy_id,
        total_applications=total,
        completed_count=completed_count,
        completion_rate=completion_rate,
        qualified_count=qualified_count,
        qualification_rate=qualification_rate,
        channel_breakdown={
            "voice": row["voice_count"],
            "whatsapp": row["whatsapp_count"]
        },
        avg_interaction_seconds=int(row["avg_seconds"]),
        last_application_at=row["last_application"]
    )


@router.get("/stats")
async def get_dashboard_stats(ctx: AuthContext = Depends(require_workspace)):
    """Get dashboard-level aggregate statistics across all vacancies."""
    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    row = await repo.get_dashboard_stats(workspace_id=ctx.workspace_id)

    total = row["total"]
    this_week = row["this_week"]
    completed_count = row["completed_count"]
    qualified_count = row["qualified_count"]

    # Calculate rates (avoid division by zero)
    completion_rate = int((completed_count / total * 100) if total > 0 else 0)
    qualification_rate = int((qualified_count / completed_count * 100) if completed_count > 0 else 0)

    return DashboardStatsResponse(
        total_prescreenings=total,
        total_prescreenings_this_week=this_week,
        completed_count=completed_count,
        completion_rate=completion_rate,
        qualified_count=qualified_count,
        qualification_rate=qualification_rate,
        channel_breakdown={
            "voice": row["voice_count"],
            "whatsapp": row["whatsapp_count"],
            "cv": row["cv_count"]
        }
    )


# ─── Workstation Sheets (Werkpostfiches) ─────────────────────────────────────


@router.get("/vacancies/{vacancy_id}/workstation-sheet")
async def get_workstation_sheet(vacancy_id: str, ctx: AuthContext = Depends(require_workspace)):
    """Get workstation sheet parameters for a vacancy."""
    vid = parse_uuid(vacancy_id, "vacancy_id")
    pool = await get_db_pool()
    await _verify_vacancy_workspace(pool, vid, ctx.workspace_id)

    rows = await pool.fetch(
        """
        SELECT param_key, param_value, notes, updated_at
        FROM ats.workstation_sheets
        WHERE vacancy_id = $1
        ORDER BY param_key
        """,
        vid,
    )

    return [
        {
            "param_key": r["param_key"],
            "param_value": r["param_value"],
            "notes": r["notes"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


@router.put("/vacancies/{vacancy_id}/workstation-sheet/{param_key}")
async def set_workstation_sheet_param(vacancy_id: str, param_key: str, body: dict, ctx: AuthContext = Depends(require_workspace)):
    """Set a workstation sheet parameter for a vacancy."""
    vid = parse_uuid(vacancy_id, "vacancy_id")
    pool = await get_db_pool()
    await _verify_vacancy_workspace(pool, vid, ctx.workspace_id)

    param_value = body.get("param_value", "yes")
    notes = body.get("notes")

    await pool.execute(
        """
        INSERT INTO ats.workstation_sheets (vacancy_id, param_key, param_value, notes)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (vacancy_id, param_key)
        DO UPDATE SET param_value = $3, notes = $4, updated_at = NOW()
        """,
        vid, param_key, param_value, notes,
    )

    return {"param_key": param_key, "param_value": param_value, "notes": notes}


@router.delete("/vacancies/{vacancy_id}/workstation-sheet/{param_key}")
async def delete_workstation_sheet_param(vacancy_id: str, param_key: str, ctx: AuthContext = Depends(require_workspace)):
    """Remove a workstation sheet parameter from a vacancy."""
    vid = parse_uuid(vacancy_id, "vacancy_id")
    pool = await get_db_pool()
    await _verify_vacancy_workspace(pool, vid, ctx.workspace_id)

    await pool.execute(
        "DELETE FROM ats.workstation_sheets WHERE vacancy_id = $1 AND param_key = $2",
        vid, param_key,
    )

    return {"deleted": True}


# ─── Werkpostfiche reference data ─────────────────────────────────────────────


MEDICAL_RISKS_PARENT_ID = "39e4c112-4856-4745-a23c-ab021faf7ab3"


@router.get("/werkpostfiche/medical-risks")
async def list_medical_risks(search: Optional[str] = Query(None, description="Search by name")):
    """List available medical risk options from types_documents."""
    pool = await get_db_pool()

    if search:
        rows = await pool.fetch(
            """
            SELECT id, name
            FROM ontology.types_documents
            WHERE parent_id = $1 AND name ILIKE $2
            ORDER BY name
            LIMIT 50
            """,
            uuid.UUID(MEDICAL_RISKS_PARENT_ID),
            f"%{search}%",
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, name
            FROM ontology.types_documents
            WHERE parent_id = $1
            ORDER BY name
            LIMIT 50
            """,
            uuid.UUID(MEDICAL_RISKS_PARENT_ID),
        )

    return [{"id": str(r["id"]), "name": r["name"]} for r in rows]


# ─── Vacancy Agent Status ───────────────────────────────────────────────────


class AgentStatusUpdate(BaseModel):
    """Toggle is_online for a vacancy agent."""
    is_online: bool


@router.patch("/vacancies/{vacancy_id}/agents/{agent_type}/status")
async def update_agent_status(
    vacancy_id: str,
    agent_type: str,
    body: AgentStatusUpdate,
    ctx: AuthContext = Depends(require_workspace),
):
    """Toggle online/offline for a vacancy agent."""
    vacancy_uuid = parse_uuid(vacancy_id, field="vacancy_id")
    pool = await get_db_pool()
    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)
    repo = VacancyAgentRepository(pool)

    row = await repo.set_online(vacancy_uuid, agent_type, body.is_online)
    if not row:
        raise HTTPException(status_code=404, detail="Vacancy agent not found")

    return {
        "vacancy_id": str(row["vacancy_id"]),
        "agent_type": row["agent_type"],
        "is_online": row["is_online"],
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/vacancies/{vacancy_id}/agents/{agent_type}/status")
async def get_agent_status(
    vacancy_id: str,
    agent_type: str,
    ctx: AuthContext = Depends(require_workspace),
):
    """Get online/offline status for a vacancy agent."""
    vacancy_uuid = parse_uuid(vacancy_id, field="vacancy_id")
    pool = await get_db_pool()
    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)
    repo = VacancyAgentRepository(pool)

    row = await repo.get(vacancy_uuid, agent_type)
    if not row:
        raise HTTPException(status_code=404, detail="Vacancy agent not found")

    return {
        "vacancy_id": str(row["vacancy_id"]),
        "agent_type": row["agent_type"],
        "is_online": row["is_online"],
        "created_at": row["created_at"].isoformat(),
    }
