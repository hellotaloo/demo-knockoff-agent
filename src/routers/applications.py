"""
Application-related endpoints.
"""
import uuid
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from transcript_processor import process_transcript

from src.repositories import ApplicationRepository, VacancyRepository
from src.services import ApplicationService
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Applications"])


@router.get("/vacancies/{vacancy_id}/applications")
async def list_applications(
    vacancy_id: str,
    qualified: Optional[bool] = Query(None),
    completed: Optional[bool] = Query(None),
    synced: Optional[bool] = Query(None),
    is_test: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List all applications for a vacancy. Use is_test=true to see test conversations, is_test=false for real ones."""
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    pool = await get_db_pool()
    vacancy_repo = VacancyRepository(pool)
    app_repo = ApplicationRepository(pool)

    # Verify vacancy exists
    if not await vacancy_repo.exists(vacancy_uuid):
        raise HTTPException(status_code=404, detail="Vacancy not found")

    # Get applications
    rows, total = await app_repo.list_for_vacancy(
        vacancy_uuid, qualified=qualified, completed=completed,
        synced=synced, is_test=is_test, limit=limit, offset=offset
    )

    # Fetch all pre-screening questions for this vacancy once
    all_questions = await app_repo.get_questions_for_vacancy(vacancy_uuid)

    # Build application responses
    applications = []
    for row in rows:
        answer_rows = await app_repo.get_answers(row["id"])
        applications.append(ApplicationService.build_application_response(row, all_questions, answer_rows))

    return {
        "applications": applications,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/applications/{application_id}")
async def get_application(application_id: str):
    """Get a single application by ID."""
    # Validate UUID format
    try:
        application_uuid = uuid.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid application ID format: {application_id}")

    pool = await get_db_pool()
    app_repo = ApplicationRepository(pool)

    row = await app_repo.get_by_id(application_uuid)

    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    # Fetch answers and questions
    answer_rows = await app_repo.get_answers(row["id"])
    question_rows = await app_repo.get_questions_for_vacancy(row["vacancy_id"])

    return ApplicationService.build_application_response(row, question_rows, answer_rows)


@router.post("/applications/reprocess-tests")
async def reprocess_test_applications():
    """
    Reprocess all test applications through the transcript processor.

    This endpoint:
    1. Finds all applications where is_test = true
    2. Fetches the original conversation messages
    3. Re-runs the transcript processor with the current questions
    4. Updates the application answers with new scores and motivations

    Useful for testing new transcript processor features on existing test data.
    """
    pool = await get_db_pool()

    # Find all test applications with their screening conversation
    # Match by candidate_phone if available, otherwise by candidate_name
    test_apps = await pool.fetch(
        """
        SELECT
            a.id as application_id,
            a.vacancy_id,
            a.candidate_name,
            a.candidate_phone,
            a.channel,
            a.started_at,
            (
                SELECT sc.id
                FROM screening_conversations sc
                WHERE sc.vacancy_id = a.vacancy_id
                AND sc.is_test = true
                AND sc.status = 'completed'
                AND (
                    (a.candidate_phone IS NOT NULL AND sc.candidate_phone = a.candidate_phone)
                    OR (a.candidate_phone IS NULL AND sc.candidate_name = a.candidate_name)
                )
                ORDER BY ABS(EXTRACT(EPOCH FROM (sc.created_at - a.started_at)))
                LIMIT 1
            ) as conversation_id
        FROM applications a
        WHERE a.is_test = true AND a.status = 'completed'
        ORDER BY a.started_at DESC
        """
    )

    if not test_apps:
        return {
            "status": "complete",
            "message": "No test applications found",
            "processed": 0,
            "errors": 0
        }

    processed = 0
    errors = []
    results = []

    for app in test_apps:
        application_id = app["application_id"]
        vacancy_id = app["vacancy_id"]
        conversation_id = app["conversation_id"]

        try:
            # Skip if no conversation found
            if not conversation_id:
                errors.append({
                    "application_id": str(application_id),
                    "error": "No linked conversation found"
                })
                continue

            # Fetch messages from conversation_messages
            messages = await pool.fetch(
                """
                SELECT role, message, created_at
                FROM conversation_messages
                WHERE conversation_id = $1
                ORDER BY created_at
                """,
                conversation_id
            )

            if not messages:
                errors.append({
                    "application_id": str(application_id),
                    "error": "No messages found for conversation"
                })
                continue

            # Convert to transcript format
            transcript = []
            for msg in messages:
                transcript.append({
                    "role": "user" if msg["role"] == "user" else "agent",
                    "message": msg["message"],
                    "time_in_call_secs": 0
                })

            # Fetch pre-screening for this vacancy
            ps_row = await pool.fetchrow(
                """
                SELECT id FROM pre_screenings WHERE vacancy_id = $1
                """,
                vacancy_id
            )

            if not ps_row:
                errors.append({
                    "application_id": str(application_id),
                    "error": "No pre-screening found for vacancy"
                })
                continue

            # Fetch questions from pre_screening_questions table
            questions = await pool.fetch(
                """
                SELECT id, question_type, question_text, ideal_answer
                FROM pre_screening_questions
                WHERE pre_screening_id = $1
                ORDER BY question_type, position
                """,
                ps_row["id"]
            )

            # Split questions by type
            knockout_questions = []
            qualification_questions = []
            ko_idx = 1
            qual_idx = 1

            for q in questions:
                q_dict = {
                    "db_id": str(q["id"]),
                    "question_text": q["question_text"],
                    "ideal_answer": q["ideal_answer"],
                }
                if q["question_type"] == "knockout":
                    q_dict["id"] = f"ko_{ko_idx}"
                    knockout_questions.append(q_dict)
                    ko_idx += 1
                else:
                    q_dict["id"] = f"qual_{qual_idx}"
                    qualification_questions.append(q_dict)
                    qual_idx += 1

            # Process transcript
            call_date = datetime.now().strftime("%Y-%m-%d")
            result = await process_transcript(
                transcript=transcript,
                knockout_questions=knockout_questions,
                qualification_questions=qualification_questions,
                call_date=call_date,
            )

            # Update application and answers in transaction
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Update application summary and qualified status
                    await conn.execute(
                        """
                        UPDATE applications
                        SET qualified = $1, summary = $2, interview_slot = $3
                        WHERE id = $4
                        """,
                        result.overall_passed,
                        result.summary,
                        result.interview_slot,
                        application_id
                    )

                    # Delete existing answers
                    await conn.execute(
                        "DELETE FROM application_answers WHERE application_id = $1",
                        application_id
                    )

                    # Insert new knockout results
                    for kr in result.knockout_results:
                        await conn.execute(
                            """
                            INSERT INTO application_answers
                            (application_id, question_id, question_text, answer, passed, score, rating, source)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """,
                            application_id,
                            kr.id,
                            kr.question_text,
                            kr.answer,
                            kr.passed,
                            kr.score,
                            kr.rating,
                            app["channel"] or "chat"
                        )

                    # Insert new qualification results with motivation
                    for qr in result.qualification_results:
                        await conn.execute(
                            """
                            INSERT INTO application_answers
                            (application_id, question_id, question_text, answer, passed, score, rating, source, motivation)
                            VALUES ($1, $2, $3, $4, NULL, $5, $6, $7, $8)
                            """,
                            application_id,
                            qr.id,
                            qr.question_text,
                            qr.answer,
                            qr.score,
                            qr.rating,
                            app["channel"] or "chat",
                            qr.motivation
                        )

            processed += 1
            results.append({
                "application_id": str(application_id),
                "overall_passed": result.overall_passed,
                "knockout_count": len(result.knockout_results),
                "qualification_count": len(result.qualification_results),
                "summary": result.summary[:100] + "..." if result.summary and len(result.summary) > 100 else result.summary
            })

            logger.info(f"✅ Reprocessed test application {application_id}")

        except Exception as e:
            logger.error(f"Error reprocessing application {application_id}: {e}")
            errors.append({
                "application_id": str(application_id),
                "error": str(e)
            })

    return {
        "status": "complete",
        "processed": processed,
        "errors": len(errors),
        "results": results,
        "error_details": errors if errors else None
    }
