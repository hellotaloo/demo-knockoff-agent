"""
Pre-screening configuration endpoints.
"""
import uuid
import logging
import time
from datetime import datetime
from fastapi import APIRouter, HTTPException
from google.adk.events import Event, EventActions
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from voice_agent import create_or_update_voice_agent
from knockout_agent.agent import create_vacancy_whatsapp_agent

from src.models.pre_screening import (
    PreScreeningRequest,
    PreScreeningQuestionResponse,
    PublishPreScreeningRequest,
    StatusUpdateRequest
)
from src.repositories import PreScreeningRepository, VacancyRepository
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pre-Screening"])

# Will be set during app startup
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager


@router.put("/vacancies/{vacancy_id}/pre-screening")
async def save_pre_screening(vacancy_id: str, config: PreScreeningRequest):
    """
    Save or update pre-screening configuration for a vacancy.
    Creates pre_screening record and inserts questions into pre_screening_questions.
    Also updates vacancy status to 'agent_created'.
    """
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Verify vacancy exists
    vacancy_repo = VacancyRepository(pool)
    if not await vacancy_repo.exists(vacancy_uuid):
        raise HTTPException(status_code=404, detail="Vacancy not found")

    # Prepare question lists
    knockout_questions = [{"id": q.id, "question": q.question} for q in config.knockout_questions]
    qualification_questions = [
        {"id": q.id, "question": q.question, "ideal_answer": q.ideal_answer}
        for q in config.qualification_questions
    ]

    # Save pre-screening
    ps_repo = PreScreeningRepository(pool)
    pre_screening_id = await ps_repo.upsert(
        vacancy_uuid,
        config.intro,
        config.knockout_failed_action,
        config.final_action,
        knockout_questions,
        qualification_questions,
        config.approved_ids
    )

    # Invalidate cached screening runner so next chat uses updated questions
    global session_manager
    session_manager.invalidate_screening_runner(vacancy_id)

    return {
        "status": "success",
        "message": "Pre-screening configuration saved",
        "pre_screening_id": str(pre_screening_id),
        "vacancy_id": vacancy_id,
        "vacancy_status": "screening_active"
    }


@router.get("/vacancies/{vacancy_id}/pre-screening")
async def get_pre_screening(vacancy_id: str):
    """
    Get pre-screening configuration for a vacancy.

    Always creates/restores an interview session pre-populated with the saved
    questions, returning session_id and interview for use with /interview/feedback.
    """
    global session_manager
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Get pre-screening
    ps_repo = PreScreeningRepository(pool)
    ps_row = await ps_repo.get_for_vacancy(vacancy_uuid)

    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    pre_screening_id = ps_row["id"]

    # Get questions
    question_rows = await ps_repo.get_questions(pre_screening_id)

    # Build interview structure and response lists with consistent ko_1/qual_1 IDs
    # This ensures the frontend and session use the same IDs for reordering
    knockout_questions = []
    qualification_questions = []
    ko_questions = []
    qual_questions = []
    approved_ids = []

    ko_counter = 1
    qual_counter = 1

    for q in question_rows:
        if q["question_type"] == "knockout":
            q_id = f"ko_{ko_counter}"
            ko_counter += 1
            ko_questions.append({"id": q_id, "question": q["question_text"]})
            # Use ko_1 style ID instead of database UUID for consistency
            knockout_questions.append(PreScreeningQuestionResponse(
                id=q_id,
                question_type=q["question_type"],
                position=q["position"],
                question_text=q["question_text"],
                is_approved=q["is_approved"]
            ))
        else:
            q_id = f"qual_{qual_counter}"
            qual_counter += 1
            # Include ideal_answer for qualification questions
            qual_questions.append({
                "id": q_id,
                "question": q["question_text"],
                "ideal_answer": q["ideal_answer"] or ""
            })
            # Use qual_1 style ID instead of database UUID for consistency
            qualification_questions.append(PreScreeningQuestionResponse(
                id=q_id,
                question_type=q["question_type"],
                position=q["position"],
                question_text=q["question_text"],
                ideal_answer=q["ideal_answer"],
                is_approved=q["is_approved"]
            ))

        if q["is_approved"]:
            approved_ids.append(q_id)

    interview = {
        "intro": ps_row["intro"] or "",
        "knockout_questions": ko_questions,
        "knockout_failed_action": ps_row["knockout_failed_action"] or "",
        "qualification_questions": qual_questions,
        "final_action": ps_row["final_action"] or "",
        "approved_ids": approved_ids
    }

    # Create or reuse session with vacancy_id as session_id
    session_id = vacancy_id

    async def get_or_create_session():
        """Helper to get existing session or create new one, handling race conditions."""
        global session_manager
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_generator", user_id="web", session_id=session_id
        )
        if session:
            return session
        try:
            return await session_manager.interview_session_service.create_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
        except IntegrityError:
            # Session was created by another request, fetch it
            logger.info(f"Session {session_id} already exists, fetching it")
            return await session_manager.interview_session_service.get_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )

    try:
        session = await get_or_create_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        # Note: We would need interview_agent and interview_editor_agent here
        # This might need to be handled differently in the final architecture
        session = await get_or_create_session()

    # Update session with current interview data (overwrites any stale state)
    state_delta = {"interview": interview}
    actions = EventActions(state_delta=state_delta)
    event = Event(
        invocation_id=f"restore_{int(time.time())}",
        author="system",
        actions=actions,
        timestamp=time.time()
    )
    await session_manager.safe_append_event(
        session_manager.interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=session_id
    )

    # Return response with session info
    return {
        "id": str(ps_row["id"]),
        "vacancy_id": str(ps_row["vacancy_id"]),
        "intro": ps_row["intro"] or "",
        "knockout_questions": [q.model_dump() for q in knockout_questions],
        "knockout_failed_action": ps_row["knockout_failed_action"] or "",
        "qualification_questions": [q.model_dump() for q in qualification_questions],
        "final_action": ps_row["final_action"] or "",
        "status": ps_row["status"],
        "created_at": ps_row["created_at"],
        "updated_at": ps_row["updated_at"],
        # Publishing fields
        "published_at": ps_row["published_at"],
        "is_online": ps_row["is_online"] or False,
        "elevenlabs_agent_id": ps_row["elevenlabs_agent_id"],
        "whatsapp_agent_id": ps_row["whatsapp_agent_id"],
        # Session info
        "session_id": session_id,
        "interview": interview
    }


@router.delete("/vacancies/{vacancy_id}/pre-screening")
async def delete_pre_screening(vacancy_id: str):
    """Delete pre-screening configuration for a vacancy. Resets status to 'new'."""
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Delete pre-screening
    ps_repo = PreScreeningRepository(pool)
    deleted = await ps_repo.delete(vacancy_uuid)

    if not deleted:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    # Invalidate cached screening runner
    global session_manager
    session_manager.invalidate_screening_runner(vacancy_id)

    return {
        "status": "success",
        "message": "Pre-screening configuration deleted",
        "vacancy_id": vacancy_id,
        "vacancy_status": "new"
    }


@router.post("/vacancies/{vacancy_id}/pre-screening/publish")
async def publish_pre_screening(vacancy_id: str, request: PublishPreScreeningRequest):
    """
    Publish a pre-screening configuration by creating the AI agents.

    This creates:
    - ElevenLabs voice agent (if enable_voice=True)
    - WhatsApp agent (if enable_whatsapp=True)

    The agents are created with the current pre-screening questions and configuration.
    After publishing, the pre-screening can be set online/offline.
    """
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Get vacancy title
    vacancy_repo = VacancyRepository(pool)
    vacancy_row = await vacancy_repo.get_basic_info(vacancy_uuid)
    if not vacancy_row:
        raise HTTPException(status_code=404, detail=f"Vacancy not found: {vacancy_id}")

    vacancy_title = vacancy_row["title"]

    # Get pre-screening with questions
    ps_repo = PreScreeningRepository(pool)
    ps_row = await ps_repo.get_for_vacancy(vacancy_uuid)

    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    pre_screening_id = ps_row["id"]

    # Get questions
    question_rows = await ps_repo.get_questions(pre_screening_id)

    # Build config for agent creation
    knockout_questions = []
    qualification_questions = []

    for q in question_rows:
        question_data = {
            "question": q["question_text"],
            "question_text": q["question_text"],
            "ideal_answer": q["ideal_answer"]
        }
        if q["question_type"] == "knockout":
            knockout_questions.append(question_data)
        else:
            qualification_questions.append(question_data)

    config = {
        "intro": ps_row["intro"] or "",
        "knockout_questions": knockout_questions,
        "knockout_failed_action": ps_row["knockout_failed_action"] or "",
        "qualification_questions": qualification_questions,
        "final_action": ps_row["final_action"] or ""
    }

    # Get existing agent IDs (for update instead of create)
    existing_elevenlabs_id = ps_row["elevenlabs_agent_id"]
    existing_whatsapp_id = ps_row["whatsapp_agent_id"]

    elevenlabs_agent_id = None
    whatsapp_agent_id = None

    # Create or update ElevenLabs voice agent
    if request.enable_voice:
        try:
            elevenlabs_agent_id = create_or_update_voice_agent(
                vacancy_id, config,
                existing_agent_id=existing_elevenlabs_id,
                vacancy_title=vacancy_title
            )
            action = "Updated" if existing_elevenlabs_id else "Created"
            logger.info(f"{action} ElevenLabs agent for vacancy {vacancy_id}: {elevenlabs_agent_id}")
        except Exception as e:
            logger.error(f"Failed to create/update ElevenLabs agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create voice agent: {str(e)}")

    # Create WhatsApp agent
    if request.enable_whatsapp:
        try:
            whatsapp_agent_id = create_vacancy_whatsapp_agent(vacancy_id, config)
            logger.info(f"Created WhatsApp agent for vacancy {vacancy_id}: {whatsapp_agent_id}")
        except Exception as e:
            logger.error(f"Failed to create WhatsApp agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create WhatsApp agent: {str(e)}")

    # Update database with agent IDs and published_at, set online
    published_at = datetime.utcnow()

    await ps_repo.update_publish_state(
        pre_screening_id,
        published_at,
        elevenlabs_agent_id,
        whatsapp_agent_id,
        is_online=True,
        voice_enabled=request.enable_voice,
        whatsapp_enabled=request.enable_whatsapp,
        cv_enabled=request.enable_cv
    )

    return {
        "status": "success",
        "published_at": published_at.isoformat(),
        "elevenlabs_agent_id": elevenlabs_agent_id,
        "whatsapp_agent_id": whatsapp_agent_id,
        "is_online": True,  # Publishing automatically sets online
        "message": "Pre-screening published and is now online"
    }


@router.patch("/vacancies/{vacancy_id}/pre-screening/status")
async def update_pre_screening_status(vacancy_id: str, request: StatusUpdateRequest):
    """
    Update the online/offline status and channel toggles for a pre-screening.

    All fields are optional - only provided fields will be updated.

    - is_online: Toggle the overall online/offline status (requires published pre-screening)
    - voice_enabled: Toggle voice channel (creates agent if not exists)
    - whatsapp_enabled: Toggle WhatsApp channel (creates agent if not exists)
    - cv_enabled: Toggle CV analysis channel
    """
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Get vacancy title (needed for agent creation)
    vacancy_repo = VacancyRepository(pool)
    vacancy_row = await vacancy_repo.get_basic_info(vacancy_uuid)
    if not vacancy_row:
        raise HTTPException(status_code=404, detail=f"Vacancy not found: {vacancy_id}")

    vacancy_title = vacancy_row["title"]

    # Get pre-screening
    ps_repo = PreScreeningRepository(pool)
    ps_row = await ps_repo.get_for_vacancy(vacancy_uuid)

    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    pre_screening_id = ps_row["id"]
    elevenlabs_agent_id = ps_row["elevenlabs_agent_id"]
    whatsapp_agent_id = ps_row["whatsapp_agent_id"]

    # If enabling voice and no agent exists, create one
    if request.voice_enabled and not elevenlabs_agent_id:
        # Build config for agent creation
        question_rows = await ps_repo.get_questions(pre_screening_id)

        knockout_questions = []
        qualification_questions = []

        for q in question_rows:
            question_data = {
                "question": q["question_text"],
                "question_text": q["question_text"],
                "ideal_answer": q["ideal_answer"]
            }
            if q["question_type"] == "knockout":
                knockout_questions.append(question_data)
            else:
                qualification_questions.append(question_data)

        config = {
            "intro": ps_row["intro"] or "",
            "knockout_questions": knockout_questions,
            "knockout_failed_action": ps_row["knockout_failed_action"] or "",
            "qualification_questions": qualification_questions,
            "final_action": ps_row["final_action"] or ""
        }

        try:
            elevenlabs_agent_id = create_or_update_voice_agent(
                vacancy_id, config,
                existing_agent_id=None,
                vacancy_title=vacancy_title
            )
            logger.info(f"Created ElevenLabs agent for vacancy {vacancy_id}: {elevenlabs_agent_id}")

            # Update the agent ID in database
            await ps_repo.update_agent_id(pre_screening_id, "elevenlabs", elevenlabs_agent_id)
        except Exception as e:
            logger.error(f"Failed to create ElevenLabs agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create voice agent: {str(e)}")

    # If enabling WhatsApp and no agent exists, create one
    if request.whatsapp_enabled and not whatsapp_agent_id:
        # Build config for agent creation (reuse if already built above)
        if 'config' not in locals():
            question_rows = await ps_repo.get_questions(pre_screening_id)

            knockout_questions = []
            qualification_questions = []

            for q in question_rows:
                question_data = {
                    "question": q["question_text"],
                    "question_text": q["question_text"],
                    "ideal_answer": q["ideal_answer"]
                }
                if q["question_type"] == "knockout":
                    knockout_questions.append(question_data)
                else:
                    qualification_questions.append(question_data)

            config = {
                "intro": ps_row["intro"] or "",
                "knockout_questions": knockout_questions,
                "knockout_failed_action": ps_row["knockout_failed_action"] or "",
                "qualification_questions": qualification_questions,
                "final_action": ps_row["final_action"] or ""
            }

        try:
            whatsapp_agent_id = create_vacancy_whatsapp_agent(vacancy_id, config)
            logger.info(f"Created WhatsApp agent for vacancy {vacancy_id}: {whatsapp_agent_id}")

            # Update the agent ID in database
            await ps_repo.update_agent_id(pre_screening_id, "whatsapp", whatsapp_agent_id)
        except Exception as e:
            logger.error(f"Failed to create WhatsApp agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create WhatsApp agent: {str(e)}")

    # Validate is_online requires published pre-screening
    if request.is_online is not None and not ps_row["published_at"]:
        raise HTTPException(
            status_code=400,
            detail="Pre-screening must be published before changing online status"
        )

    # Check if there are fields to update
    if (request.is_online is None and request.voice_enabled is None and
        request.whatsapp_enabled is None and request.cv_enabled is None):
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update status flags
    await ps_repo.update_status_flags(
        pre_screening_id,
        is_online=request.is_online,
        voice_enabled=request.voice_enabled,
        whatsapp_enabled=request.whatsapp_enabled,
        cv_enabled=request.cv_enabled
    )

    # Fetch updated values
    updated_row = await ps_repo.get_with_status(pre_screening_id)

    # Calculate effective channel states
    voice_active = (updated_row["elevenlabs_agent_id"] is not None) and updated_row["voice_enabled"]
    whatsapp_active = (updated_row["whatsapp_agent_id"] is not None) and updated_row["whatsapp_enabled"]
    cv_active = updated_row["cv_enabled"]

    # Auto-sync is_online based on channel states
    any_channel_on = voice_active or whatsapp_active or cv_active
    all_channels_off = not any_channel_on
    effective_is_online = updated_row["is_online"]
    auto_status_message = ""

    # Auto-set is_online = TRUE if any channel is enabled and agent was offline
    if any_channel_on and not updated_row["is_online"] and ps_row["published_at"]:
        await ps_repo.update_online_status(pre_screening_id, True)
        effective_is_online = True
        auto_status_message = " (auto-online: channel enabled)"

    # Auto-set is_online = FALSE if all channels are disabled
    elif all_channels_off and updated_row["is_online"]:
        await ps_repo.update_online_status(pre_screening_id, False)
        effective_is_online = False
        auto_status_message = " (auto-offline: no channels enabled)"

    return {
        "status": "success",
        "is_online": effective_is_online,
        "channels": {
            "voice": voice_active,
            "whatsapp": whatsapp_active,
            "cv": cv_active
        },
        "message": "Pre-screening status updated" + auto_status_message
    }
