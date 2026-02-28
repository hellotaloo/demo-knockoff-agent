"""
Interview Analysis Router.

Evaluates pre-screening interview questions and returns per-question
analytics, overall verdict, funnel data, and a one-liner summary.
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException

from interview_analysis_agent import analyze_interview
from src.models.interview_analysis import (
    InterviewAnalysisRequest,
    InterviewAnalysisResponse,
)
from src.repositories.pre_screening_repo import PreScreeningRepository
from src.repositories.vacancy_repo import VacancyRepository
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Interview Analysis"])


@router.post(
    "/pre-screenings/{pre_screening_id}/analyze",
    response_model=InterviewAnalysisResponse,
)
async def analyze_interview_endpoint(
    pre_screening_id: str,
    request: InterviewAnalysisRequest = None,
):
    """
    Analyze pre-screening interview questions for quality and drop-off risk.

    If questions/vacancy are provided in the body, those are used (draft mode, not persisted).
    Otherwise, questions and vacancy are loaded from the database and the result is cached.
    """
    try:
        ps_uuid = uuid.UUID(pre_screening_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pre-screening ID: {pre_screening_id}")

    # Determine if this is draft mode (body provided) or DB mode
    is_draft = request is not None and request.questions is not None and request.vacancy is not None

    if is_draft:
        questions = [
            {"id": q.id, "text": q.text, "type": q.type}
            for q in request.questions
        ]
        vacancy_title = request.vacancy.title
        vacancy_description = request.vacancy.description or ""
    else:
        # Load from database
        pool = await get_db_pool()
        ps_repo = PreScreeningRepository(pool)

        ps_row = await pool.fetchrow(
            "SELECT id, vacancy_id FROM ats.pre_screenings WHERE id = $1",
            ps_uuid,
        )
        if not ps_row:
            raise HTTPException(status_code=404, detail="Pre-screening not found")

        vacancy_id = ps_row["vacancy_id"]

        # Get vacancy info
        vacancy_repo = VacancyRepository(pool)
        vacancy_row = await vacancy_repo.get_basic_info(vacancy_id)
        vacancy_title = vacancy_row["title"] if vacancy_row else "Onbekende vacature"
        vacancy_description = (vacancy_row["description"] or "") if vacancy_row else ""

        # Get questions with ko_N/qual_N ID mapping
        question_rows = await ps_repo.get_questions(ps_uuid)
        if not question_rows:
            raise HTTPException(status_code=404, detail="No questions found for this pre-screening")

        questions = []
        ko_counter = 1
        qual_counter = 1
        for q in question_rows:
            if q["question_type"] == "knockout":
                q_id = f"ko_{ko_counter}"
                ko_counter += 1
                q_type = "knockout"
            else:
                q_id = f"qual_{qual_counter}"
                qual_counter += 1
                q_type = "qualifying"
            questions.append({"id": q_id, "text": q["question_text"], "type": q_type})

    if not questions:
        raise HTTPException(status_code=400, detail="No questions provided or found")

    # Run the analysis agent
    result = await analyze_interview(
        questions=questions,
        vacancy_title=vacancy_title,
        vacancy_description=vacancy_description,
    )

    # Validate through Pydantic
    try:
        response = InterviewAnalysisResponse(**result)
    except Exception as e:
        logger.error(f"Failed to validate analysis response: {e}")
        raise HTTPException(status_code=500, detail="Interview analysis returned invalid data")

    # Persist result if loaded from DB (not draft mode)
    if not is_draft:
        try:
            pool = await get_db_pool()
            ps_repo = PreScreeningRepository(pool)
            await ps_repo.save_analysis_result(ps_uuid, result)
            logger.info(f"[INTERVIEW ANALYSIS] Saved result for pre-screening {pre_screening_id}")
        except Exception as e:
            logger.warning(f"Failed to cache analysis result: {e}")

    return response


@router.get(
    "/pre-screenings/{pre_screening_id}/analysis",
    response_model=InterviewAnalysisResponse,
)
async def get_interview_analysis(pre_screening_id: str):
    """
    Get cached interview analysis result for a pre-screening.

    Returns 404 if no analysis has been run yet.
    """
    try:
        ps_uuid = uuid.UUID(pre_screening_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pre-screening ID: {pre_screening_id}")

    pool = await get_db_pool()
    ps_repo = PreScreeningRepository(pool)

    result = await ps_repo.get_analysis_result(ps_uuid)
    if result is None:
        raise HTTPException(status_code=404, detail="No analysis found. Run POST /pre-screenings/{id}/analyze first.")

    try:
        return InterviewAnalysisResponse(**result)
    except Exception as e:
        logger.error(f"Cached analysis result is invalid: {e}")
        raise HTTPException(status_code=500, detail="Cached analysis data is invalid")
