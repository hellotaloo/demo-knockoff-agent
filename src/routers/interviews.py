"""
Interview Generation endpoints.

Thin routing layer — all business logic lives in
agents/pre_screening/interview_question_generator/session.py.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException

from src.models.interview import (
    GenerateInterviewRequest,
    FeedbackRequest,
    ReorderRequest,
    DeleteQuestionRequest,
    AddQuestionRequest,
    RestoreSessionRequest
)
from src.database import get_db_pool
from src.dependencies import get_session_manager
from agents.pre_screening.interview_question_generator.session import InterviewSessionHandler
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Interview Generation"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def _get_handler() -> InterviewSessionHandler:
    """Create an InterviewSessionHandler with current session manager and DB pool."""
    return InterviewSessionHandler(get_session_manager(), await get_db_pool())


@router.post("/interview/generate")
async def generate_interview(request: GenerateInterviewRequest):
    """Generate interview questions from vacancy text with SSE streaming."""
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {request.vacancy_id}")

    handler = await _get_handler()

    try:
        vacancy_text, vacancy_title = await handler.fetch_vacancy_text(request.vacancy_id)
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))

    session_id = request.session_id or request.vacancy_id
    logger.info(f"[GENERATE] Fetched vacancy '{vacancy_title}' ({len(vacancy_text)} chars)")

    return StreamingResponse(
        handler.stream_interview_generation(vacancy_text, session_id, request.vacancy_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/interview/feedback")
async def process_feedback(request: FeedbackRequest):
    """Process feedback on generated questions with SSE streaming."""
    handler = await _get_handler()
    return StreamingResponse(
        handler.stream_feedback(request.session_id, request.message),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/interview/session/{session_id}")
async def get_interview_session(session_id: str):
    """Get the current interview state for a session."""
    handler = await _get_handler()
    try:
        interview = await handler.get_session_interview(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"session_id": session_id, "interview": interview}


@router.post("/interview/reorder")
async def reorder_questions(request: ReorderRequest):
    """Reorder questions without invoking the agent. Instant response."""
    handler = await _get_handler()
    try:
        interview = await handler.reorder_questions(
            request.session_id, request.knockout_order, request.qualification_order
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return {"status": "success", "interview": interview}


@router.post("/interview/restore-session")
async def restore_session_from_db(request: RestoreSessionRequest):
    """Restore an interview session from saved pre-screening data."""
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {request.vacancy_id}")

    handler = await _get_handler()
    try:
        session_id, interview = await handler.restore_session_from_db(request.vacancy_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "status": "success",
        "session_id": session_id,
        "interview": interview,
        "message": "Session restored from saved pre-screening"
    }


@router.post("/interview/delete")
async def delete_question(request: DeleteQuestionRequest):
    """Delete a question without invoking the agent. Instant response."""
    handler = await _get_handler()
    try:
        interview = await handler.delete_question(request.session_id, request.question_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return {"status": "success", "deleted": request.question_id, "interview": interview}


@router.post("/interview/add")
async def add_question(request: AddQuestionRequest):
    """Add a question without invoking the agent. Instant response."""
    handler = await _get_handler()
    try:
        new_id, new_question, interview = await handler.add_question(
            request.session_id, request.question_type, request.question,
            request.ideal_answer, request.vacancy_snippet
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return {"status": "success", "added": new_id, "question": new_question, "interview": interview}
