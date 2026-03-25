"""
Pre-screening configuration endpoints.
"""
import uuid
import logging
import time
from datetime import datetime
import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, BackgroundTasks
from google.adk.events import Event, EventActions
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from google.adk.errors.already_exists_error import AlreadyExistsError

from fastapi import Depends

from src.auth.dependencies import AuthContext, require_workspace
from src.models.pre_screening import (
    PreScreeningRequest,
    PreScreeningQuestionResponse,
    PublishPreScreeningRequest,
    StatusUpdateRequest,
    PreScreeningSettingsResponse,
    PreScreeningSettingsUpdateRequest,
    AgentConfigResponse,
    AgentConfigUpdateRequest,
    ApplyPopupContentResponse,
    ApplyPopupContentUpdateRequest,
)
from src.repositories import PreScreeningRepository, AgentConfigRepository, VacancyRepository
from src.database import get_db_pool
from src.dependencies import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pre-Screening"])


async def _verify_vacancy_workspace(pool, vacancy_id, workspace_id):
    """Verify a vacancy exists and belongs to the given workspace. Raises 404 if not."""
    row = await pool.fetchrow(
        "SELECT workspace_id FROM ats.vacancies WHERE id = $1", vacancy_id
    )
    if not row or row["workspace_id"] != workspace_id:
        raise HTTPException(status_code=404, detail="Vacancy not found")


async def _run_background_analysis(pre_screening_id: uuid.UUID, vacancy_id: str):
    """
    Run interview analysis agent in the background after questions are saved.

    This ensures every save triggers a fresh analysis, keeping the
    analysis tab on the pre-screening page always up-to-date.
    """
    from agents.pre_screening.interview_analyzer import analyze_interview

    try:
        pool = await get_db_pool()
        ps_repo = PreScreeningRepository(pool)
        vacancy_repo = VacancyRepository(pool)

        vacancy_uuid = uuid.UUID(vacancy_id)
        vacancy_row = await vacancy_repo.get_basic_info(vacancy_uuid)
        vacancy_title = vacancy_row["title"] if vacancy_row else "Onbekende vacature"
        vacancy_description = (vacancy_row["description"] or "") if vacancy_row else ""

        question_rows = await ps_repo.get_questions(pre_screening_id)
        if not question_rows:
            logger.info(f"[BG ANALYSIS] No questions found for {pre_screening_id}, skipping")
            return

        # Build questions with ko_N/qual_N IDs
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

        logger.info(f"[BG ANALYSIS] Running analysis on {len(questions)} questions for vacancy {vacancy_id}")

        result = await analyze_interview(
            questions=questions,
            vacancy_title=vacancy_title,
            vacancy_description=vacancy_description,
        )

        await ps_repo.save_analysis_result(pre_screening_id, result)
        verdict = result.get("summary", {}).get("verdict", "unknown")
        logger.info(f"[BG ANALYSIS] Saved result for {pre_screening_id} (verdict={verdict})")

    except Exception as e:
        logger.error(f"[BG ANALYSIS] Failed for {pre_screening_id}: {e}", exc_info=True)


@router.put("/vacancies/{vacancy_id}/pre-screening")
async def save_pre_screening(vacancy_id: str, config: PreScreeningRequest, background_tasks: BackgroundTasks, ctx: AuthContext = Depends(require_workspace)):
    """
    Save or update pre-screening configuration for a vacancy.
    Creates pre_screening record and inserts questions into pre_screening_questions.
    Also updates vacancy status to 'agent_created'.
    Automatically triggers interview analysis in the background.
    """
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    # Verify vacancy exists and belongs to workspace
    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    # Prepare question lists
    knockout_questions = [
        {"id": q.id, "question": q.question, "vacancy_snippet": q.vacancy_snippet}
        for q in config.knockout_questions
    ]
    qualification_questions = [
        {"id": q.id, "question": q.question, "ideal_answer": q.ideal_answer, "vacancy_snippet": q.vacancy_snippet}
        for q in config.qualification_questions
    ]

    # Debug: Log what we're receiving
    logger.info(f"[SAVE PRE-SCREENING] display_title: {config.display_title!r}")
    logger.info(f"[SAVE PRE-SCREENING] Knockout questions: {knockout_questions}")
    logger.info(f"[SAVE PRE-SCREENING] Qualification questions: {qualification_questions}")

    # Save pre-screening
    ps_repo = PreScreeningRepository(pool)
    pre_screening_id = await ps_repo.upsert(
        vacancy_uuid,
        config.intro,
        config.knockout_failed_action,
        config.final_action,
        knockout_questions,
        qualification_questions,
        config.approved_ids,
        display_title=config.display_title
    )

    # Invalidate cached interview analysis (questions changed)
    await ps_repo.clear_analysis_result(pre_screening_id)

    # Fire questions_saved event to vacancy_setup workflow (if active)
    try:
        from src.workflows.orchestrator import get_orchestrator
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("vacancy_id", vacancy_id)
        if workflow and workflow["workflow_type"] == "vacancy_setup":
            await orchestrator.handle_event(workflow["id"], "questions_saved", {
                "pre_screening_id": str(pre_screening_id),
                "vacancy_id": vacancy_id,
            })
            logger.info(f"[SAVE PRE-SCREENING] Fired questions_saved event for workflow {workflow['id'][:8]}")
    except Exception as e:
        logger.warning(f"[SAVE PRE-SCREENING] Failed to fire questions_saved event: {e}")

    # Run interview analysis in the background (regardless of workflow)
    background_tasks.add_task(
        _run_background_analysis,
        pre_screening_id=pre_screening_id,
        vacancy_id=vacancy_id,
    )

    return {
        "status": "success",
        "message": "Pre-screening configuration saved",
        "pre_screening_id": str(pre_screening_id),
        "vacancy_id": vacancy_id,
        "vacancy_status": "screening_active"
    }


@router.get("/vacancies/{vacancy_id}/pre-screening/analysis")
async def get_vacancy_analysis(vacancy_id: str, ctx: AuthContext = Depends(require_workspace)):
    """
    Get the interview analysis report for a vacancy's pre-screening.

    Returns the cached analysis result, or 404 if no analysis has been run yet.
    Analysis runs automatically in the background when questions are saved.

    Response includes:
    - summary: overall verdict, completion rate, one-liner
    - questions: per-question clarity scores, drop-off risk, tips
    - funnel: candidate funnel visualization data
    """
    from src.models.interview_analysis import InterviewAnalysisResponse

    pool = await get_db_pool()

    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    ps_repo = PreScreeningRepository(pool)
    ps_row = await ps_repo.get_for_vacancy(vacancy_uuid)

    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    result = await ps_repo.get_analysis_result(ps_row["id"])
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis not yet available. It runs automatically after saving questions."
        )

    try:
        return InterviewAnalysisResponse(**result)
    except Exception as e:
        logger.error(f"Cached analysis result is invalid for vacancy {vacancy_id}: {e}")
        raise HTTPException(status_code=500, detail="Cached analysis data is invalid")


@router.get("/vacancies/{vacancy_id}/pre-screening")
async def get_pre_screening(vacancy_id: str, ctx: AuthContext = Depends(require_workspace)):
    """
    Get pre-screening configuration for a vacancy.

    Always creates/restores an interview session pre-populated with the saved
    questions, returning session_id and interview for use with /interview/feedback.
    """
    session_manager = get_session_manager()
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

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
            ko_questions.append({
                "id": q_id,
                "question": q["question_text"],
                "vacancy_snippet": q["vacancy_snippet"]
            })
            # Use ko_1 style ID instead of database UUID for consistency
            knockout_questions.append(PreScreeningQuestionResponse(
                id=q_id,
                question_type=q["question_type"],
                position=q["position"],
                question_text=q["question_text"],
                vacancy_snippet=q["vacancy_snippet"],
                is_approved=q["is_approved"]
            ))
        else:
            q_id = f"qual_{qual_counter}"
            qual_counter += 1
            # Include ideal_answer for qualification questions
            qual_questions.append({
                "id": q_id,
                "question": q["question_text"],
                "ideal_answer": q["ideal_answer"] or "",
                "vacancy_snippet": q["vacancy_snippet"]
            })
            # Use qual_1 style ID instead of database UUID for consistency
            qualification_questions.append(PreScreeningQuestionResponse(
                id=q_id,
                question_type=q["question_type"],
                position=q["position"],
                question_text=q["question_text"],
                ideal_answer=q["ideal_answer"],
                vacancy_snippet=q["vacancy_snippet"],
                is_approved=q["is_approved"]
            ))

        if q["is_approved"]:
            approved_ids.append(q_id)

    interview = {
        "display_title": ps_row["display_title"],
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
        session_manager = get_session_manager()
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_question_generator", user_id="web", session_id=session_id
        )
        if session:
            return session
        try:
            return await session_manager.interview_session_service.create_session(
                app_name="interview_question_generator", user_id="web", session_id=session_id
            )
        except (IntegrityError, AlreadyExistsError):
            # Session was created by another request or already exists in ADK, fetch it
            logger.info(f"Session {session_id} already exists, fetching it")
            return await session_manager.interview_session_service.get_session(
                app_name="interview_question_generator", user_id="web", session_id=session_id
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
        app_name="interview_question_generator", user_id="web", session_id=session_id
    )

    # Return response with session info
    return {
        "id": str(ps_row["id"]),
        "vacancy_id": str(ps_row["vacancy_id"]),
        "display_title": ps_row["display_title"],
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
        "elevenlabs_agent_id": ps_row["elevenlabs_agent_id"],
        "whatsapp_agent_id": ps_row["whatsapp_agent_id"],
        # Session info
        "session_id": session_id,
        "interview": interview
    }


@router.delete("/vacancies/{vacancy_id}/pre-screening")
async def delete_pre_screening(vacancy_id: str, ctx: AuthContext = Depends(require_workspace)):
    """Delete pre-screening configuration for a vacancy. Resets status to 'new'."""
    pool = await get_db_pool()

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    # Delete pre-screening
    ps_repo = PreScreeningRepository(pool)
    deleted = await ps_repo.delete(vacancy_uuid)

    if not deleted:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    return {
        "status": "success",
        "message": "Pre-screening configuration deleted",
        "vacancy_id": vacancy_id,
        "vacancy_status": "new"
    }


@router.post("/vacancies/{vacancy_id}/pre-screening/publish")
async def publish_pre_screening(vacancy_id: str, request: PublishPreScreeningRequest, ctx: AuthContext = Depends(require_workspace)):
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

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    # Get vacancy title
    vacancy_repo = VacancyRepository(pool)
    vacancy_row = await vacancy_repo.get_basic_info(vacancy_uuid)
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
        "display_title": ps_row["display_title"],
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

    # Voice agent: We now use a single master agent from ELEVENLABS_AGENT_ID env var
    # No per-vacancy agent creation needed - just enable the voice channel
    if request.enable_voice:
        logger.info(f"Voice enabled for vacancy {vacancy_id} (using master agent from ELEVENLABS_AGENT_ID)")
        # elevenlabs_agent_id stays None - we use master agent from environment

    # Enable WhatsApp agent (uses pre_screening_whatsapp_agent with state stored per conversation)
    if request.enable_whatsapp:
        whatsapp_agent_id = vacancy_id  # Agent ID is the vacancy ID for lookup
        logger.info(f"WhatsApp enabled for vacancy {vacancy_id}")

    # Update database with agent IDs and published_at, set online
    published_at = datetime.utcnow()

    await ps_repo.update_publish_state(
        pre_screening_id,
        published_at,
        elevenlabs_agent_id,
        whatsapp_agent_id,
        voice_enabled=request.enable_voice,
        whatsapp_enabled=request.enable_whatsapp,
        cv_enabled=request.enable_cv
    )

    # Sync status to vacancy_agents
    vacancy_repo = VacancyRepository(pool)
    await vacancy_repo.ensure_agent_registered(uuid.UUID(vacancy_id), "prescreening", status="published")

    return {
        "status": "success",
        "published_at": published_at.isoformat(),
        "elevenlabs_agent_id": elevenlabs_agent_id,
        "whatsapp_agent_id": whatsapp_agent_id,
        "message": "Pre-screening published"
    }


@router.patch("/vacancies/{vacancy_id}/pre-screening/status")
async def update_pre_screening_status(vacancy_id: str, request: StatusUpdateRequest, ctx: AuthContext = Depends(require_workspace)):
    """
    Update channel toggles for a pre-screening.

    All fields are optional - only provided fields will be updated.

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

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    # Get vacancy title (needed for agent creation)
    vacancy_repo = VacancyRepository(pool)
    vacancy_row = await vacancy_repo.get_basic_info(vacancy_uuid)
    vacancy_title = vacancy_row["title"]

    # Get pre-screening
    ps_repo = PreScreeningRepository(pool)
    ps_row = await ps_repo.get_for_vacancy(vacancy_uuid)

    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    pre_screening_id = ps_row["id"]
    elevenlabs_agent_id = ps_row["elevenlabs_agent_id"]
    whatsapp_agent_id = ps_row["whatsapp_agent_id"]

    # Voice agent: We now use a single master agent from ELEVENLABS_AGENT_ID env var
    # No per-vacancy agent creation needed
    if request.voice_enabled:
        logger.info(f"Voice enabled for vacancy {vacancy_id} (using master agent from ELEVENLABS_AGENT_ID)")

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
                "display_title": ps_row["display_title"],
                "intro": ps_row["intro"] or "",
                "knockout_questions": knockout_questions,
                "knockout_failed_action": ps_row["knockout_failed_action"] or "",
                "qualification_questions": qualification_questions,
                "final_action": ps_row["final_action"] or ""
            }

        # WhatsApp agent uses vacancy_id as identifier
        whatsapp_agent_id = vacancy_id
        logger.info(f"WhatsApp enabled for vacancy {vacancy_id}")

        # Update the agent ID in database
        await ps_repo.update_agent_id(pre_screening_id, "whatsapp", whatsapp_agent_id)

    # Check if there are fields to update
    if (request.voice_enabled is None and
        request.whatsapp_enabled is None and request.cv_enabled is None):
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update channel flags on pre_screenings table
    await ps_repo.update_channel_flags(
        pre_screening_id,
        voice_enabled=request.voice_enabled,
        whatsapp_enabled=request.whatsapp_enabled,
        cv_enabled=request.cv_enabled
    )

    # Fetch updated channel values
    updated_row = await ps_repo.get_with_channels(pre_screening_id)

    # Calculate effective channel states
    # Voice uses master agent from ELEVENLABS_AGENT_ID env var, no per-vacancy agent ID needed
    voice_active = updated_row["voice_enabled"] or False
    whatsapp_active = (updated_row["whatsapp_agent_id"] is not None) and updated_row["whatsapp_enabled"]
    cv_active = updated_row["cv_enabled"] or False

    return {
        "status": "success",
        "channels": {
            "voice": voice_active,
            "whatsapp": whatsapp_active,
            "cv": cv_active
        },
        "message": "Channel status updated"
    }


@router.get("/vacancies/{vacancy_id}/pre-screening/settings", response_model=PreScreeningSettingsResponse)
async def get_pre_screening_settings(vacancy_id: str, ctx: AuthContext = Depends(require_workspace)):
    """Get pre-screening settings (consent, escalation, channel flags)."""
    pool = await get_db_pool()

    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    from src.services.pre_screening_service import PreScreeningService
    service = PreScreeningService(pool)
    settings = await service.get_settings(vacancy_uuid)

    if settings is None:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    return PreScreeningSettingsResponse(**settings)


@router.patch("/vacancies/{vacancy_id}/pre-screening/settings", response_model=PreScreeningSettingsResponse)
async def update_pre_screening_settings(vacancy_id: str, request: PreScreeningSettingsUpdateRequest, ctx: AuthContext = Depends(require_workspace)):
    """
    Update pre-screening settings. All fields are optional — only provided fields will be updated.

    - voice_enabled: Toggle voice channel
    - whatsapp_enabled: Toggle WhatsApp channel
    - cv_enabled: Toggle CV analysis channel
    """
    pool = await get_db_pool()

    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    await _verify_vacancy_workspace(pool, vacancy_uuid, ctx.workspace_id)

    # Check at least one field is provided
    update_data = request.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    from src.services.pre_screening_service import PreScreeningService
    service = PreScreeningService(pool)
    updated = await service.update_settings(
        vacancy_uuid,
        voice_enabled=request.voice_enabled,
        whatsapp_enabled=request.whatsapp_enabled,
        cv_enabled=request.cv_enabled,
    )

    if updated is None:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")

    return PreScreeningSettingsResponse(**updated)


# ---------------------------------------------------------------------------
# Global pre-screening agent config (agents.agent_config)
# ---------------------------------------------------------------------------

# Preferred display order for settings sections ("Algemeen" first)
_SETTINGS_SECTION_ORDER = [
    "general", "generator", "voice", "planning", "interview", "escalation", "publishing",
]


def _order_settings(settings: dict) -> dict:
    """Return settings dict with keys in the preferred display order."""
    ordered = {}
    for key in _SETTINGS_SECTION_ORDER:
        if key in settings:
            ordered[key] = settings[key]
    # Append any unknown sections at the end
    for key in settings:
        if key not in ordered:
            ordered[key] = settings[key]
    return ordered


@router.get("/pre-screening/config", response_model=AgentConfigResponse)
async def get_pre_screening_config(ctx: AuthContext = Depends(require_workspace)):
    """Get the active pre-screening agent configuration."""
    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    row = await repo.get_active(ctx.workspace_id, "pre_screening")
    if not row:
        raise HTTPException(status_code=404, detail="Pre-screening config not found")

    import json
    settings = row["settings"] if isinstance(row["settings"], dict) else json.loads(row["settings"])

    # Include apply popup content in the response
    popup_row = await repo.get_active(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE)
    if popup_row:
        content_yaml, variables = _get_apply_popup_from_record(popup_row)
    else:
        content_yaml = _load_default_apply_popup_yaml()
        variables = _DEFAULT_VARIABLES.copy()

    return AgentConfigResponse(
        id=str(row["id"]),
        config_type=row["config_type"],
        version=row["version"],
        settings=_order_settings(settings),
        content_yaml=content_yaml,
        variables=variables,
    )


@router.patch("/pre-screening/config", response_model=AgentConfigResponse)
async def update_pre_screening_config(request: AgentConfigUpdateRequest, ctx: AuthContext = Depends(require_workspace)):
    """
    Update the pre-screening agent configuration.
    Creates a new version with merged settings — previous versions are preserved.
    """
    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    update_data = request.settings
    if not update_data:
        raise HTTPException(status_code=400, detail="No settings to update")

    # Merge with current settings
    current = await repo.get_active(ctx.workspace_id, "pre_screening")
    import json
    current_settings = {}
    if current:
        current_settings = current["settings"] if isinstance(current["settings"], dict) else json.loads(current["settings"])

    # Detect if auto_generate is being toggled on
    old_auto_generate = current_settings.get("publishing", {}).get("auto_generate", True)
    new_auto_generate = update_data.get("publishing", {}).get("auto_generate", old_auto_generate)

    merged = _order_settings({**current_settings, **update_data})
    row = await repo.save(ctx.workspace_id, "pre_screening", merged)

    # If auto_generate was just toggled on, generate for pending vacancies
    if new_auto_generate and not old_auto_generate:
        await _trigger_pending_generations(pool, ctx.workspace_id)

    # Save apply popup content if provided
    content_yaml = None
    variables = None
    if request.content_yaml is not None or request.variables is not None:
        import yaml

        # Start from current popup or defaults
        popup_current = await repo.get_active(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE)
        if popup_current:
            current_yaml, current_vars = _get_apply_popup_from_record(popup_current)
        else:
            current_yaml = _load_default_apply_popup_yaml()
            current_vars = _DEFAULT_VARIABLES.copy()

        content_yaml = request.content_yaml if request.content_yaml is not None else current_yaml
        variables = request.variables if request.variables is not None else current_vars

        # Validate YAML syntax
        try:
            yaml.safe_load(content_yaml)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Ongeldige YAML: {e}")

        popup_settings = {"content_yaml": content_yaml, "variables": variables}
        await repo.save(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE, popup_settings)
    else:
        # Return current popup state even when not updating it
        popup_row = await repo.get_active(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE)
        if popup_row:
            content_yaml, variables = _get_apply_popup_from_record(popup_row)
        else:
            content_yaml = _load_default_apply_popup_yaml()
            variables = _DEFAULT_VARIABLES.copy()

    settings = row["settings"] if isinstance(row["settings"], dict) else json.loads(row["settings"])
    return AgentConfigResponse(
        id=str(row["id"]),
        config_type=row["config_type"],
        version=row["version"],
        settings=_order_settings(settings),
        content_yaml=content_yaml,
        variables=variables,
    )


# ---------------------------------------------------------------------------
# Auto-generate toggle (reads from publishing.auto_generate in agent config)
# ---------------------------------------------------------------------------


async def _trigger_pending_generations(pool: asyncpg.Pool, workspace_id: UUID) -> None:
    """Find vacancies waiting for generation and kick off background generation."""
    pending = await pool.fetch(
        """
        SELECT v.id, v.title, v.description
        FROM ats.vacancies v
        LEFT JOIN ats.vacancy_agents va
            ON va.vacancy_id = v.id AND va.agent_type = 'prescreening'
        WHERE v.status NOT IN ('closed', 'filled')
          AND v.workspace_id = $1
          AND (va.status IS NULL OR va.status = 'new')
          AND NOT EXISTS (
              SELECT 1 FROM agents.pre_screenings ps WHERE ps.vacancy_id = v.id
          )
        """,
        workspace_id,
    )
    if not pending:
        return

    import asyncio
    from src.services.vacancy_import_service import VacancyImportService

    vacancy_list = [
        {"id": str(row["id"]), "title": row["title"], "description": row["description"]}
        for row in pending
    ]
    service = VacancyImportService(pool)
    logger.info(f"Auto-generate enabled — triggering generation for {len(vacancy_list)} pending vacancies")
    asyncio.create_task(service._auto_generate_pre_screenings(workspace_id, vacancy_list))


@router.get("/pre-screening/auto-generate")
async def get_auto_generate(ctx: AuthContext = Depends(require_workspace)):
    """
    Get the current auto-generate setting for pre-screening.

    When enabled, newly imported vacancies automatically get pre-screening
    questions generated. When disabled, vacancies are imported without
    generating questions (they show "Genereren" button in the UI).

    Stored in the "publishing" section of the pre_screening agent config.
    """
    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    row = await repo.get_active(ctx.workspace_id, "pre_screening")
    if not row:
        return {"auto_generate": True}

    import json
    settings = row["settings"] if isinstance(row["settings"], dict) else json.loads(row["settings"])
    publishing = settings.get("publishing", {})
    return {"auto_generate": publishing.get("auto_generate", True)}


@router.put("/pre-screening/auto-generate")
async def set_auto_generate(enabled: bool, ctx: AuthContext = Depends(require_workspace)):
    """
    Toggle auto-generate for pre-screening.

    When enabled (default), newly imported vacancies automatically get
    pre-screening questions generated. When disabled, vacancies are
    imported but remain in "Genereren" state.

    When toggled ON, also kicks off generation for any vacancies that
    are currently waiting (agent_status = 'new', no pre-screening yet).

    Stored in the "publishing" section of the pre_screening agent config.
    """
    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    import json
    current = await repo.get_active(ctx.workspace_id, "pre_screening")
    current_settings = {}
    if current:
        current_settings = current["settings"] if isinstance(current["settings"], dict) else json.loads(current["settings"])

    publishing = current_settings.get("publishing", {})
    publishing["auto_generate"] = enabled
    current_settings["publishing"] = publishing

    await repo.save(ctx.workspace_id, "pre_screening", current_settings)

    logger.info(f"Auto-generate toggled to {enabled}")

    if enabled:
        await _trigger_pending_generations(pool, ctx.workspace_id)

    return {"auto_generate": enabled}


# ---------------------------------------------------------------------------
# Apply popup content management
# ---------------------------------------------------------------------------

_APPLY_POPUP_CONFIG_TYPE = "apply_popup"
_DEFAULT_VARIABLES = {"privacy_url": "https://example.com/privacy"}


def _load_default_apply_popup_yaml() -> str:
    """Load the default apply popup YAML template from disk."""
    import pathlib
    template_path = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "defaults" / "apply_popup_content.yaml"
    return template_path.read_text(encoding="utf-8")


def _get_apply_popup_from_record(row) -> tuple[str, dict]:
    """Extract content_yaml and variables from an agent_config record."""
    import json as _json
    settings = row["settings"] if isinstance(row["settings"], dict) else _json.loads(row["settings"])
    content_yaml = settings.get("content_yaml", _load_default_apply_popup_yaml())
    variables = settings.get("variables", _DEFAULT_VARIABLES.copy())
    return content_yaml, variables


@router.get("/pre-screening/apply-popup-content", response_model=ApplyPopupContentResponse)
async def get_apply_popup_content(ctx: AuthContext = Depends(require_workspace)):
    """Get the apply popup content configuration (YAML + variables)."""
    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    row = await repo.get_active(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE)
    if not row:
        return ApplyPopupContentResponse(
            content_yaml=_load_default_apply_popup_yaml(),
            variables=_DEFAULT_VARIABLES.copy(),
            version=0,
        )

    content_yaml, variables = _get_apply_popup_from_record(row)
    return ApplyPopupContentResponse(
        content_yaml=content_yaml,
        variables=variables,
        version=row["version"],
    )


@router.put("/pre-screening/apply-popup-content", response_model=ApplyPopupContentResponse)
async def update_apply_popup_content(
    request: ApplyPopupContentUpdateRequest,
    ctx: AuthContext = Depends(require_workspace),
):
    """
    Save new apply popup content. Creates a new version.
    Validates YAML syntax before saving.
    """
    import yaml

    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    # Start from current or defaults
    current = await repo.get_active(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE)
    if current:
        current_yaml, current_vars = _get_apply_popup_from_record(current)
    else:
        current_yaml = _load_default_apply_popup_yaml()
        current_vars = _DEFAULT_VARIABLES.copy()

    new_yaml = request.content_yaml if request.content_yaml is not None else current_yaml
    new_vars = request.variables if request.variables is not None else current_vars

    # Validate YAML syntax
    try:
        yaml.safe_load(new_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Ongeldige YAML: {e}")

    settings = {"content_yaml": new_yaml, "variables": new_vars}
    row = await repo.save(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE, settings)

    return ApplyPopupContentResponse(
        content_yaml=new_yaml,
        variables=new_vars,
        version=row["version"],
    )


@router.post("/pre-screening/apply-popup-content/preview")
async def preview_apply_popup_content(
    request: ApplyPopupContentUpdateRequest,
    ctx: AuthContext = Depends(require_workspace),
):
    """
    Preview the apply popup content with variables substituted.
    Returns the parsed YAML structure with all {variable} placeholders replaced.
    """
    import yaml

    pool = await get_db_pool()
    repo = AgentConfigRepository(pool)

    # Start from current or defaults
    current = await repo.get_active(ctx.workspace_id, _APPLY_POPUP_CONFIG_TYPE)
    if current:
        current_yaml, current_vars = _get_apply_popup_from_record(current)
    else:
        current_yaml = _load_default_apply_popup_yaml()
        current_vars = _DEFAULT_VARIABLES.copy()

    raw_yaml = request.content_yaml if request.content_yaml is not None else current_yaml
    variables = request.variables if request.variables is not None else current_vars

    # Validate YAML
    try:
        yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Ongeldige YAML: {e}")

    # Inject persona_name from general pre-screening config
    general_config = await repo.get_active(ctx.workspace_id, "pre_screening")
    if general_config:
        import json as _json
        gen_settings = general_config["settings"] if isinstance(general_config["settings"], dict) else _json.loads(general_config["settings"])
        persona_name = gen_settings.get("general", {}).get("persona_name", "Anna")
    else:
        persona_name = "Anna"

    # Substitute variables (popup vars + persona_name from general config)
    all_vars = {"persona_name": persona_name, **variables}
    rendered_yaml = raw_yaml
    for key, value in all_vars.items():
        rendered_yaml = rendered_yaml.replace(f"{{{key}}}", str(value))

    parsed = yaml.safe_load(rendered_yaml)
    return {"rendered": parsed, "variables": all_vars}
