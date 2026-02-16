"""
Vacancy-related endpoints.
"""
import uuid
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
from cv_analyzer import analyze_cv_base64
from src.utils.date_utils import get_next_business_days, get_dutch_date

from src.models.vacancy import VacancyStatsResponse, DashboardStatsResponse, VacancyDetailResponse
from src.models.application import ApplicationResponse, QuestionAnswerResponse, CVApplicationRequest
from src.repositories import VacancyRepository
from src.services import VacancyService, ActivityService
from src.database import get_db_pool
from src.dependencies import get_vacancy_repo, get_vacancy_service
from src.exceptions import parse_uuid

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vacancies"])


@router.get("/vacancies")
async def list_vacancies(
    status: Optional[str] = Query(None, description="Filter by status"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: VacancyRepository = Depends(get_vacancy_repo),
    service: VacancyService = Depends(get_vacancy_service)
):
    """List all vacancies with optional filtering, including linked applicants."""
    rows, total = await repo.list_with_stats(status=status, source=source, limit=limit, offset=offset)

    # Fetch applicants for all vacancies in one query
    vacancy_ids = [row["id"] for row in rows]
    applicants_by_vacancy = await repo.get_applicants_by_vacancy_ids(vacancy_ids)

    # Build responses with applicants
    vacancies = [
        service.build_vacancy_response(row, applicants_by_vacancy.get(row["id"], []))
        for row in rows
    ]

    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/vacancies/{vacancy_id}", response_model=VacancyDetailResponse)
async def get_vacancy(
    vacancy_id: str,
    repo: VacancyRepository = Depends(get_vacancy_repo),
    service: VacancyService = Depends(get_vacancy_service)
):
    """Get a single vacancy by ID with activity timeline and applicants."""
    vacancy_uuid = parse_uuid(vacancy_id, field="vacancy_id")
    row = await repo.get_by_id(vacancy_uuid)

    if not row:
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


@router.post("/vacancies/{vacancy_id}/cv-application")
async def create_cv_application(vacancy_id: str, request: CVApplicationRequest):
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

    # Verify vacancy exists
    vacancy_row = await pool.fetchrow(
        "SELECT id, title FROM ats.vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_row:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    # Get pre-screening
    ps_row = await pool.fetchrow(
        """
        SELECT id, intro, knockout_failed_action, final_action
        FROM ats.pre_screenings
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
        FROM ats.pre_screening_questions
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
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert application
            # Only set completed_at if status is 'completed'
            # qualified = true if all knockout questions passed
            if application_status == 'completed':
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO ats.applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     completed_at, summary, status, is_test)
                    VALUES ($1, $2, $3, 'cv', $4, NOW(), $5, $6, $7)
                    RETURNING id, started_at, completed_at
                    """,
                    vacancy_uuid,
                    request.candidate_name,
                    request.candidate_phone,
                    knockout_all_passed,  # True if all knockouts passed
                    result.cv_summary,
                    application_status,
                    True  # CV applications are always in test mode for now
                )
            else:
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO ats.applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     summary, status, is_test)
                    VALUES ($1, $2, $3, 'cv', $4, $5, $6, $7)
                    RETURNING id, started_at, completed_at
                    """,
                    vacancy_uuid,
                    request.candidate_name,
                    request.candidate_phone,
                    False,  # Not qualified - knockouts need clarification
                    result.cv_summary,
                    application_status,
                    True  # CV applications are always in test mode for now
                )
            application_id = app_row["id"]
            started_at = app_row["started_at"]

            logger.info(f"Created CV application {application_id} for {request.candidate_name} (is_test=True)")

            # Insert knockout answers
            # passed=true if CV provides evidence for the knockout question
            for ka in result.knockout_analysis:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
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
                    INSERT INTO ats.application_answers
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

    # Generate meeting slots if qualified
    meeting_slots = None
    if knockout_all_passed:
        now = datetime.now()
        next_days = get_next_business_days(now, 2)
        meeting_slots = [
            get_dutch_date(next_days[0]) + " om 10:00",
            get_dutch_date(next_days[0]) + " om 14:00",
            get_dutch_date(next_days[1]) + " om 11:00",
        ]

    return ApplicationResponse(
        id=str(application_id),
        vacancy_id=vacancy_id,
        candidate_name=request.candidate_name,
        channel="cv",
        status=application_status,
        qualified=knockout_all_passed,  # Qualified if all knockouts passed
        started_at=app_row["started_at"],
        completed_at=app_row["completed_at"],
        interaction_seconds=0,
        answers=answers,
        synced=False,
        knockout_passed=knockout_passed,
        knockout_total=knockout_total,
        qualification_count=len(result.qualification_analysis),
        summary=result.cv_summary,
        meeting_slots=meeting_slots
    )


@router.get("/vacancies/{vacancy_id}/stats")
async def get_vacancy_stats(vacancy_id: str):
    """Get aggregated statistics for a vacancy."""
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    # Verify vacancy exists
    if not await repo.exists(vacancy_uuid):
        raise HTTPException(status_code=404, detail="Vacancy not found")

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
async def get_dashboard_stats():
    """Get dashboard-level aggregate statistics across all vacancies."""
    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    row = await repo.get_dashboard_stats()

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
