"""
Playground Router - Browser-based voice agent testing via LiveKit WebRTC.

Returns a LiveKit access token that, when used by the browser to connect,
auto-creates a room and dispatches the pre-screening V2 voice agent.
No database records are created — this is for testing/demo only.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import LIVEKIT_URL
from src.database import get_db_pool
from src.services.livekit_service import get_livekit_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Playground"])


# --- Models ---

class PlaygroundStartRequest(BaseModel):
    vacancy_id: str
    candidate_name: str = "Playground Kandidaat"
    start_agent: Optional[str] = None  # e.g. "screening", "scheduling" — skip to specific step
    require_consent: bool = False


class PlaygroundStartResponse(BaseModel):
    success: bool
    livekit_url: str
    access_token: str
    room_name: str


# --- Endpoint ---

@router.post("/playground/start", response_model=PlaygroundStartResponse)
async def start_playground_session(request: PlaygroundStartRequest):
    """
    Start a browser-based voice playground session.

    Creates a LiveKit access token with embedded agent dispatch. When the browser
    connects using this token, LiveKit auto-creates the room and starts the
    pre-screening V2 voice agent.
    """
    if not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LIVEKIT_URL not configured")

    pool = await get_db_pool()

    # Validate vacancy_id
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID: {request.vacancy_id}")

    # Get vacancy, pre-screening, and office location
    row = await pool.fetchrow(
        """
        SELECT v.id as vacancy_id, v.title as vacancy_title,
               ps.id as pre_screening_id, ps.is_online, ps.published_at,
               COALESCE(ol.spoken_name, ol.name) as office_name, ol.address as office_address
        FROM ats.vacancies v
        LEFT JOIN ats.pre_screenings ps ON ps.vacancy_id = v.id
        LEFT JOIN ats.office_locations ol ON ol.id = v.office_location_id
        WHERE v.id = $1
        """,
        vacancy_uuid
    )

    if not row:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    if not row["pre_screening_id"]:
        raise HTTPException(status_code=400, detail="No pre-screening configured for this vacancy")
    if not row["published_at"]:
        raise HTTPException(status_code=400, detail="Pre-screening not published")
    if not row["is_online"]:
        raise HTTPException(status_code=400, detail="Pre-screening is offline")

    # Fetch knockout + qualification questions
    questions = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM ats.pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        row["pre_screening_id"]
    )

    knockout_questions = [
        {"id": str(q["id"]), "question_text": q["question_text"], "ideal_answer": q["ideal_answer"] or ""}
        for q in questions if q["question_type"] == "knockout"
    ]
    qualification_questions = [
        {"id": str(q["id"]), "question_text": q["question_text"], "ideal_answer": q["ideal_answer"] or ""}
        for q in questions if q["question_type"] == "qualification"
    ]

    # Build session input using existing helper
    room_name = f"playground-{uuid.uuid4().hex[:12]}"
    livekit_service = get_livekit_service()

    session_input = livekit_service._build_session_input(
        call_id=room_name,
        candidate_name=request.candidate_name,
        job_title=row["vacancy_title"],
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        office_location=row["office_name"] or "",
        office_address=row["office_address"] or "",
    )

    # Apply playground overrides — zero side effects
    session_input["is_playground"] = True
    session_input["require_consent"] = request.require_consent
    if request.start_agent:
        session_input["start_agent"] = request.start_agent

    # Generate token with embedded agent dispatch
    first_name = request.candidate_name.split()[0]
    result = livekit_service.create_playground_token(
        room_name=room_name,
        session_input=session_input,
        participant_identity=f"playground-{uuid.uuid4().hex[:8]}",
        participant_name=first_name,
    )

    logger.info(
        f"Playground session created: room={room_name}, "
        f"vacancy={row['vacancy_title']}, start_agent={request.start_agent}"
    )

    return PlaygroundStartResponse(
        success=True,
        livekit_url=result["livekit_url"],
        access_token=result["access_token"],
        room_name=result["room_name"],
    )
