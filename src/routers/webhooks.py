"""
Webhook endpoints for Twilio and ElevenLabs integrations.
"""
import os
import json
import logging
import uuid
import asyncio
import hmac
from hashlib import sha256
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from pre_screening_whatsapp_agent import (
    create_simple_agent,
    restore_agent_from_state,
    is_conversation_complete,
    get_conversation_outcome,
    Phase,
)
from transcript_processor import process_transcript
from src.config import ELEVENLABS_WEBHOOK_SECRET, logger
from src.models.webhook import ElevenLabsWebhookPayload
from src.models import ActivityEventType, ActorType, ActivityChannel
from src.services import ActivityService
from src.database import get_db_pool
from src.utils.conversation_cache import conversation_cache, agent_cache, ConversationType, CachedConversation
from src.services.whatsapp_service import send_whatsapp_message
from src.services.screening_notes_integration_service import trigger_screening_notes_integration
from src.workflows import get_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

# ============================================================================
# Helper Functions
# ============================================================================

async def _safe_process_conversation(
    pool,
    conversation_id: uuid.UUID,
    vacancy_id: str,
    pre_screening: dict,
    completion_outcome: str | None
):
    """
    Wrapper for background transcript processing with error handling.

    This runs as a background task so errors don't affect the user response.
    Logs errors instead of raising them.
    """
    try:
        await _process_whatsapp_conversation(
            pool, conversation_id, vacancy_id, pre_screening, completion_outcome
        )
    except Exception as e:
        logger.error(f"❌ Background transcript processing failed for {conversation_id}: {e}")
        # Don't re-raise - this is a background task


async def _process_whatsapp_conversation(
    pool,
    conversation_id: uuid.UUID,
    vacancy_id: str,
    pre_screening: dict,
    completion_outcome: str | None
):
    """
    Process a completed WhatsApp conversation using the transcript processor.

    Fetches messages from conversation_messages table and runs them through
    the same transcript processor used for voice calls.
    """
    from datetime import datetime

    logger.info(f"Processing WhatsApp conversation {conversation_id}")

    # Fetch all messages for this conversation
    messages = await pool.fetch(
        """
        SELECT role, message, created_at
        FROM ats.conversation_messages
        WHERE conversation_id = $1
        ORDER BY created_at
        """,
        conversation_id
    )

    if not messages:
        logger.warning(f"No messages found for conversation {conversation_id}")
        return

    # Convert to transcript format (same as voice)
    transcript = []
    for msg in messages:
        transcript.append({
            "role": "user" if msg["role"] == "user" else "agent",
            "message": msg["message"],
            "time_in_call_secs": 0  # Not applicable for WhatsApp
        })

    # Get knockout and qualification questions
    knockout_questions = []
    qualification_questions = []

    for i, q in enumerate(pre_screening.get("knockout_questions", []), 1):
        q_dict = dict(q) if hasattr(q, 'keys') else q
        q_dict["id"] = q_dict.get("id") or f"ko_{i}"
        knockout_questions.append(q_dict)

    for i, q in enumerate(pre_screening.get("qualification_questions", []), 1):
        q_dict = dict(q) if hasattr(q, 'keys') else q
        q_dict["id"] = q_dict.get("id") or f"qual_{i}"
        qualification_questions.append(q_dict)

    # Get conversation details BEFORE processing (including linked application_id)
    conv_row = await pool.fetchrow(
        """
        SELECT vacancy_id, candidate_name, candidate_phone, is_test, application_id
        FROM ats.screening_conversations
        WHERE id = $1
        """,
        conversation_id
    )

    if not conv_row:
        logger.error(f"Conversation {conversation_id} not found")
        return

    vacancy_uuid = conv_row["vacancy_id"]
    candidate_name = conv_row["candidate_name"] or "Unknown"
    candidate_phone = conv_row["candidate_phone"]
    is_test = conv_row["is_test"] or False

    # Find existing application - prefer the linked application_id from conversation
    existing_app = None
    if conv_row["application_id"]:
        # Use the directly linked application (unique per conversation)
        existing_app = await pool.fetchrow(
            """
            SELECT id, candidate_id FROM ats.applications
            WHERE id = $1 AND status != 'completed'
            """,
            conv_row["application_id"]
        )

    # Fallback to phone/name matching for legacy conversations without application_id
    if not existing_app and candidate_phone:
        existing_app = await pool.fetchrow(
            """
            SELECT id, candidate_id FROM ats.applications
            WHERE vacancy_id = $1 AND candidate_phone = $2 AND channel = 'whatsapp' AND status != 'completed'
            """,
            vacancy_uuid, candidate_phone
        )

    if not existing_app:
        existing_app = await pool.fetchrow(
            """
            SELECT id, candidate_id FROM ats.applications
            WHERE vacancy_id = $1 AND candidate_name = $2 AND channel = 'whatsapp' AND status != 'completed'
            """,
            vacancy_uuid, candidate_name
        )

    if existing_app:
        # Set status to 'processing' BEFORE transcript analysis (commits immediately)
        await pool.execute(
            "UPDATE ats.applications SET status = 'processing' WHERE id = $1",
            existing_app["id"]
        )
        logger.info(f"🔄 Application {existing_app['id']} status -> processing")

    # Update workflow to 'processing' step
    try:
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", str(conversation_id))
        if workflow:
            await orchestrator.service.update_step(workflow["id"], "processing")
            logger.info(f"🔄 Workflow {workflow['id']} step -> processing")
    except Exception as e:
        logger.warning(f"Could not update workflow to processing: {e}")

    # Process transcript (AI analysis happens here)
    call_date = datetime.now().strftime("%Y-%m-%d")
    result = await process_transcript(
        transcript=transcript,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        call_date=call_date,
    )

    logger.info(f"Transcript processing complete: overall_passed={result.overall_passed}")

    # Calculate call duration (approximate from message timestamps)
    first_msg = messages[0]["created_at"]
    last_msg = messages[-1]["created_at"]
    duration_seconds = int((last_msg - first_msg).total_seconds()) if first_msg and last_msg else 0

    # Look up interview_slot from scheduled_interviews table (created during conversation)
    interview_slot = None
    scheduled = await pool.fetchrow(
        "SELECT selected_date, selected_time FROM ats.scheduled_interviews WHERE conversation_id = $1",
        str(conversation_id)
    )
    if scheduled:
        from zoneinfo import ZoneInfo
        try:
            hour = int(scheduled["selected_time"].replace("u", "").replace("h", ""))
            tz = ZoneInfo("Europe/Brussels")
            dt = datetime.combine(scheduled["selected_date"], datetime.min.time(), tzinfo=tz).replace(hour=hour)
            interview_slot = dt.isoformat()
        except Exception as e:
            logger.warning(f"Could not parse interview slot: {e}")
            interview_slot = f"{scheduled['selected_date']} {scheduled['selected_time']}"

    async with pool.acquire() as conn:
        async with conn.transaction():
            if existing_app:
                # Update existing application with results
                application_id = existing_app["id"]
                await conn.execute(
                    """
                    UPDATE ats.applications
                    SET qualified = $1, interaction_seconds = $2,
                        completed_at = NOW(), channel = 'whatsapp',
                        summary = $3, interview_slot = $4, status = 'completed'
                    WHERE id = $5
                    """,
                    result.overall_passed,
                    duration_seconds,
                    result.summary,
                    interview_slot,
                    application_id
                )
                logger.info(f"✅ Application {application_id} status -> completed")
            else:
                # Create new application (already completed)
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO ats.applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     interaction_seconds, completed_at, summary, interview_slot, is_test, status)
                    VALUES ($1, $2, $3, 'whatsapp', $4, $5, NOW(), $6, $7, $8, 'completed')
                    RETURNING id
                    """,
                    vacancy_uuid,
                    candidate_name,
                    candidate_phone,
                    result.overall_passed,
                    duration_seconds,
                    result.summary,
                    interview_slot,
                    is_test
                )
                application_id = app_row["id"]
                logger.info(f"Created new application {application_id} with status=completed")

            # Store knockout results
            for kr in result.knockout_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'whatsapp')
                    """,
                    application_id,
                    kr.id,
                    kr.question_text,
                    kr.answer,
                    kr.passed,
                    kr.score,
                    kr.rating
                )

            # Store qualification results
            for qr in result.qualification_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source, motivation)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, 'whatsapp', $7)
                    """,
                    application_id,
                    qr.id,
                    qr.question_text,
                    qr.answer,
                    qr.score,
                    qr.rating,
                    qr.motivation
                )

            # Mark conversation as completed
            await conn.execute(
                """
                UPDATE ats.screening_conversations
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE id = $1
                """,
                conversation_id
            )

    logger.info(f"✅ WhatsApp conversation {conversation_id} processed: application {application_id}")

    # Log activity: screening completed + processed with rich metadata
    candidate_id = existing_app["candidate_id"] if existing_app and existing_app.get("candidate_id") else None
    if candidate_id:
        activity_service = ActivityService(pool)

        # Calculate overall score from qualification results
        scores = [qr.score for qr in result.qualification_results if qr.score is not None]
        avg_score = round(sum(scores) / len(scores)) if scores else None

        # Calculate knockout stats
        knockout_passed = sum(1 for kr in result.knockout_results if kr.passed)
        knockout_total = len(result.knockout_results)

        # Get last answer from messages for context
        last_user_answer = None
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_answer = msg["message"][:100] + "..." if len(msg["message"]) > 100 else msg["message"]
                break

        # Build rich metadata
        activity_metadata = {
            "score": avg_score,
            "knockout_passed": knockout_passed,
            "knockout_total": knockout_total,
            "duration_seconds": duration_seconds,
        }
        if last_user_answer:
            activity_metadata["last_answer"] = last_user_answer

        # If disqualified, add reason
        if not result.overall_passed:
            failed_knockouts = [kr.question_text for kr in result.knockout_results if not kr.passed]
            if failed_knockouts:
                activity_metadata["knockout_failed"] = failed_knockouts[0][:50]

        # Log screening completed
        event_type = ActivityEventType.QUALIFIED if result.overall_passed else ActivityEventType.DISQUALIFIED
        await activity_service.log(
            candidate_id=str(candidate_id),
            event_type=event_type,
            application_id=str(application_id),
            vacancy_id=str(vacancy_uuid),
            channel=ActivityChannel.WHATSAPP,
            actor_type=ActorType.AGENT,
            metadata=activity_metadata,
            summary=f"Pre-screening {'geslaagd' if result.overall_passed else 'niet geslaagd'}" + (f" (score: {avg_score}%)" if avg_score else "")
        )

    # Trigger screening notes integration (Google Doc creation + calendar attachment)
    # Runs as background task for qualified candidates with scheduled interviews
    if result.overall_passed:
        asyncio.create_task(trigger_screening_notes_integration(
            pool=pool,
            application_id=application_id,
            recruiter_email=os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL"),
        ))
        logger.info(f"📄 Triggered screening notes integration for application {application_id}")

    # Notify workflow orchestrator that screening is complete
    # This triggers unified notification handling (WhatsApp confirmation + Teams notification)
    try:
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", str(conversation_id))
        if workflow:
            # Get interview_slot from scheduled_interviews table (created during conversation)
            interview_slot = None
            scheduled = await pool.fetchrow(
                "SELECT selected_date, selected_time FROM ats.scheduled_interviews WHERE conversation_id = $1",
                str(conversation_id)
            )
            if scheduled:
                from zoneinfo import ZoneInfo
                try:
                    hour = int(scheduled["selected_time"].replace("u", "").replace("h", ""))
                    tz = ZoneInfo("Europe/Brussels")
                    dt = datetime.combine(scheduled["selected_date"], datetime.min.time(), tzinfo=tz).replace(hour=hour)
                    interview_slot = dt.isoformat()
                except Exception as e:
                    logger.warning(f"Could not parse interview slot: {e}")
                    interview_slot = f"{scheduled['selected_date']} {scheduled['selected_time']}"

            await orchestrator.handle_event(
                workflow_id=workflow["id"],
                event="screening_completed",
                payload={
                    "qualified": result.overall_passed,
                    "interview_slot": interview_slot,
                    "application_id": str(application_id),
                    "candidate_name": candidate_name,
                    "candidate_phone": candidate_phone,
                    "summary": result.summary,
                },
            )
            logger.info(f"✅ Workflow event sent for conversation {conversation_id}")
        else:
            logger.debug(f"No workflow found for conversation {conversation_id} (legacy flow)")
    except Exception as e:
        logger.error(f"❌ Failed to notify workflow orchestrator: {e}")
        # Don't fail the whole process if workflow notification fails


async def _save_whatsapp_scheduled_interview(
    pool,
    conversation_id: uuid.UUID,
    selected_date: str,
    selected_time: str,
    selected_slot_text: str,
    candidate_name: str,
):
    """
    Save a scheduled interview from the WhatsApp agent.

    Looks up vacancy info from the conversation and creates a scheduled_interview record.
    Also creates a Google Calendar event.
    Idempotent - checks if already scheduled to avoid duplicates.
    """
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository
    from src.services.google_calendar_service import calendar_service

    try:
        # Check if already scheduled (avoid duplicates on message retries)
        existing = await pool.fetchrow(
            """
            SELECT id FROM ats.scheduled_interviews
            WHERE conversation_id = $1
            """,
            str(conversation_id)
        )
        if existing:
            logger.info(f"📅 Interview already scheduled for conversation {conversation_id}")
            return

        # Look up vacancy info from conversation
        conv_info = await pool.fetchrow(
            """
            SELECT sc.vacancy_id, sc.candidate_name, sc.candidate_phone,
                   v.title as vacancy_title
            FROM ats.screening_conversations sc
            JOIN ats.vacancies v ON v.id = sc.vacancy_id
            WHERE sc.id = $1
            """,
            conversation_id
        )

        if not conv_info:
            logger.error(f"No conversation found for {conversation_id}")
            return

        # Parse date
        try:
            date_obj = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid date format: {selected_date}")
            return

        # Create scheduled interview record
        repo = ScheduledInterviewRepository(pool)
        interview_id = await repo.create(
            vacancy_id=conv_info["vacancy_id"],
            conversation_id=str(conversation_id),
            selected_date=date_obj,
            selected_time=selected_time,
            selected_slot_text=selected_slot_text,
            candidate_name=candidate_name or conv_info["candidate_name"],
            candidate_phone=conv_info["candidate_phone"],
            channel="whatsapp",
        )

        logger.info(
            f"📅 Scheduled interview {interview_id} for conversation {conversation_id}: "
            f"{selected_date} at {selected_time}"
        )

        # Create Google Calendar event
        calendar_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
        if calendar_email:
            try:
                # Parse time from "14u" format to hour
                hour = int(selected_time.replace("u", "").replace("h", ""))
                tz = ZoneInfo("Europe/Brussels")
                start_time = datetime.combine(date_obj, datetime.min.time(), tzinfo=tz).replace(hour=hour)

                # Create event
                name = candidate_name or conv_info["candidate_name"]
                vacancy_title = conv_info["vacancy_title"]
                event = await calendar_service.create_event(
                    calendar_email=calendar_email,
                    summary=f"Interview - {name} ({vacancy_title})",
                    start_time=start_time,
                    description=f"WhatsApp pre-screening interview\nKandidaat: {name}\nVacature: {vacancy_title}",
                )

                # Update scheduled interview with calendar event ID
                if event and event.get("id"):
                    await repo.update_calendar_event_id(interview_id, event["id"])
                    logger.info(f"📅 Created calendar event {event['id']} for interview {interview_id}")

            except Exception as cal_error:
                logger.error(f"Failed to create calendar event: {cal_error}")
                # Don't fail the whole operation if calendar creation fails

    except Exception as e:
        logger.error(f"Failed to save scheduled interview for {conversation_id}: {e}")
        # Don't re-raise - scheduling failure shouldn't break the conversation


async def _save_agent_state_background(
    pool,
    conversation_id: uuid.UUID,
    agent_state_dict: dict,
):
    """Background task to save agent state to DB."""
    try:
        await pool.execute(
            """
            UPDATE ats.screening_conversations
            SET agent_state = $1, updated_at = NOW()
            WHERE id = $2
            """,
            json.dumps(agent_state_dict),
            conversation_id
        )
        logger.debug(f"💾 Agent state saved for {conversation_id}")
    except Exception as e:
        logger.error(f"❌ Failed to save agent state for {conversation_id}: {e}")


async def _save_messages_background(
    pool,
    conversation_id: uuid.UUID,
    user_message: str,
    agent_response: Optional[str],
):
    """Background task to save conversation messages to DB."""
    try:
        # Store user message
        await pool.execute(
            """
            INSERT INTO ats.conversation_messages (conversation_id, role, message)
            VALUES ($1, 'user', $2)
            """,
            conversation_id, user_message
        )
        # Store agent response
        if agent_response:
            await pool.execute(
                """
                INSERT INTO ats.conversation_messages (conversation_id, role, message)
                VALUES ($1, 'agent', $2)
                """,
                conversation_id, agent_response
            )
        logger.debug(f"💾 Messages saved for {conversation_id}")
    except Exception as e:
        logger.error(f"❌ Failed to save messages for {conversation_id}: {e}")


async def _webhook_impl_vacancy_specific(
    pool,
    conversation_id: uuid.UUID,
    incoming_msg: str,
    candidate_name: str,
) -> tuple[str, bool, str | None]:
    """
    Handle webhook using pre-screening WhatsApp agent.

    Uses in-memory agent cache to avoid loading/restoring agent state from DB
    on every message. DB writes happen in background to minimize latency.

    Args:
        pool: Database connection pool
        conversation_id: The conversation UUID
        incoming_msg: The user's message
        candidate_name: The candidate's name

    Returns:
        tuple: (response_text, is_complete, completion_outcome)
        - response_text: The agent's response message
        - is_complete: True if conversation is in terminal state (DONE or FAILED)
        - completion_outcome: The outcome description if complete, None otherwise
    """
    import time as time_module
    conv_id_str = str(conversation_id)
    timings = {}
    t_start = time_module.perf_counter()

    try:
        # Check agent cache first
        t0 = time_module.perf_counter()
        agent = await agent_cache.get(conv_id_str)
        timings["cache_check"] = (time_module.perf_counter() - t0) * 1000

        if agent:
            logger.info(f"⚡ Agent cache HIT for conversation {conversation_id}")
            timings["cache_hit"] = True
        else:
            timings["cache_hit"] = False
            # Cache miss - load from database
            logger.info(f"💾 Agent cache MISS for conversation {conversation_id} - loading from DB...")
            t0 = time_module.perf_counter()
            row = await pool.fetchrow(
                """
                SELECT agent_state FROM ats.screening_conversations WHERE id = $1
                """,
                conversation_id
            )
            timings["db_load"] = (time_module.perf_counter() - t0) * 1000

            if not row or not row["agent_state"]:
                logger.error(f"No agent state found for conversation {conversation_id}")
                return "Er is een fout opgetreden. Probeer het later opnieuw.", False, None

            # Restore agent from saved state
            # Handle multiple levels of JSON encoding from legacy data
            agent_state = row["agent_state"]

            # Unwrap any string encoding until we get a dict
            t0 = time_module.perf_counter()
            max_unwrap = 3
            for _ in range(max_unwrap):
                if isinstance(agent_state, dict):
                    break
                if isinstance(agent_state, str):
                    try:
                        agent_state = json.loads(agent_state)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse agent_state JSON: {agent_state[:100]}...")
                        return "Er is een fout opgetreden. Probeer het later opnieuw.", False, None

            if not isinstance(agent_state, dict):
                logger.error(f"agent_state is not a dict after unwrapping: {type(agent_state)}")
                return "Er is een fout opgetreden. Probeer het later opnieuw.", False, None

            # Restore agent and cache it
            state_json = json.dumps(agent_state)
            agent = restore_agent_from_state(state_json)
            timings["restore_agent"] = (time_module.perf_counter() - t0) * 1000

            t0 = time_module.perf_counter()
            await agent_cache.set(conv_id_str, agent)
            timings["cache_set"] = (time_module.perf_counter() - t0) * 1000
            logger.info(f"📱 Restored agent for conversation {conversation_id}, phase={agent.state.phase.value}")

        # Process the message (this is the LLM call - main latency)
        t0 = time_module.perf_counter()
        response_text = await agent.process_message(incoming_msg)
        timings["llm_call"] = (time_module.perf_counter() - t0) * 1000

        timings["total"] = (time_module.perf_counter() - t_start) * 1000
        logger.info(f"⏱️ TIMINGS: {timings}")
        logger.info(f"📱 Agent response: phase={agent.state.phase.value}, response={response_text[:100]}...")

        # Update cache with new state
        await agent_cache.set(conv_id_str, agent)

        # Save state to DB in background (don't wait)
        updated_state = agent.state.to_dict()
        asyncio.create_task(_save_agent_state_background(pool, conversation_id, updated_state))

        # Save scheduled interview if agent has scheduling info (in background)
        if agent.state.selected_date and agent.state.selected_time:
            asyncio.create_task(_save_whatsapp_scheduled_interview(
                pool=pool,
                conversation_id=conversation_id,
                selected_date=agent.state.selected_date,
                selected_time=agent.state.selected_time,
                selected_slot_text=agent.state.scheduled_time,
                candidate_name=candidate_name,
            ))

        # Check if conversation is complete
        complete = is_conversation_complete(agent)
        completion_outcome = None
        if complete:
            outcome = get_conversation_outcome(agent)
            completion_outcome = outcome.get("outcome", "completed")
            logger.info(f"🏁 Conversation complete: phase={agent.state.phase.value}, outcome={completion_outcome}")
            # Invalidate agent cache on completion
            await agent_cache.invalidate(conv_id_str)

        return response_text, complete, completion_outcome

    except Exception as e:
        logger.error(f"Error processing message for conversation {conversation_id}: {e}")
        return "Er is een fout opgetreden. Probeer het later opnieuw.", False, None


async def _webhook_impl_generic(user_id: str, incoming_msg: str) -> str:
    """Handle webhook when there's no active screening conversation.

    Returns a polite message indicating no active conversation exists.
    All screenings should be initiated via the outbound screening API.
    """
    logger.info(f"No active screening for {user_id}, returning default message")
    return "Hallo! Er is momenteel geen actief gesprek. Als je bent uitgenodigd voor een screening, wacht dan even op ons bericht. 👋"


async def _process_and_respond_async(
    phone_normalized: str,
    incoming_msg: str,
    conv_row: Optional[dict],
):
    """
    Background task to process message and send response via Twilio REST API.

    This enables fast webhook response times by processing asynchronously.
    """
    import time as time_module
    t_start = time_module.perf_counter()

    try:
        pool = await get_db_pool()
        response_text = None
        is_complete = False
        completion_outcome = None
        conversation_id = None
        vacancy_id = None
        pre_screening = None

        if conv_row:
            # Found active outbound screening - use vacancy-specific agent
            vacancy_id = str(conv_row["vacancy_id"])
            conversation_id = conv_row["id"]
            candidate_name = conv_row["candidate_name"] or "Kandidaat"

            logger.info(f"📱 [ASYNC] Processing message for conversation {conversation_id}")

            # Process message with the pre-screening agent
            response_text, is_complete, completion_outcome = await _webhook_impl_vacancy_specific(
                pool, conversation_id, incoming_msg, candidate_name
            )

            # Get pre-screening config for transcript processing (only needed if conversation completes)
            if is_complete:
                ps_row = await pool.fetchrow(
                    """
                    SELECT intro, knockout_failed_action, final_action
                    FROM ats.pre_screenings
                    WHERE id = $1
                    """,
                    conv_row["pre_screening_id"]
                )

                questions = await pool.fetch(
                    """
                    SELECT id, question_type, position, question_text, ideal_answer
                    FROM ats.pre_screening_questions
                    WHERE pre_screening_id = $1
                    ORDER BY question_type, position
                    """,
                    conv_row["pre_screening_id"]
                )

                pre_screening = {
                    "intro": ps_row["intro"],
                    "knockout_failed_action": ps_row["knockout_failed_action"],
                    "final_action": ps_row["final_action"],
                    "knockout_questions": [dict(q) for q in questions if q["question_type"] == "knockout"],
                    "qualification_questions": [dict(q) for q in questions if q["question_type"] == "qualification"],
                }

            # Store messages in background (don't wait)
            if conversation_id:
                asyncio.create_task(_save_messages_background(
                    pool, conversation_id, incoming_msg, response_text
                ))

            # If conversation is complete, trigger transcript processing in background
            if is_complete and conversation_id:
                logger.info(f"🔄 Triggering background transcript processing for conversation {conversation_id}")
                await conversation_cache.invalidate(phone_normalized)
                asyncio.create_task(_safe_process_conversation(
                    pool, conversation_id, vacancy_id, pre_screening, completion_outcome
                ))
        else:
            # No active outbound screening - use generic demo agent
            logger.info(f"[ASYNC] No active screening for {phone_normalized}")
            response_text = await _webhook_impl_generic(phone_normalized, incoming_msg)

        # Send response via Twilio REST API
        if response_text:
            t_send = time_module.perf_counter()
            success = await send_whatsapp_message(phone_normalized, response_text)
            send_time = (time_module.perf_counter() - t_send) * 1000

            total_time = (time_module.perf_counter() - t_start) * 1000
            logger.info(f"⏱️ [ASYNC] Total processing: {total_time:.0f}ms, send: {send_time:.0f}ms, success={success}")

    except Exception as e:
        logger.error(f"❌ [ASYNC] Error processing message for {phone_normalized}: {e}")
        # Try to send error message
        try:
            await send_whatsapp_message(
                phone_normalized,
                "Er is een fout opgetreden. Probeer het later opnieuw."
            )
        except Exception:
            pass


async def verify_elevenlabs_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verify ElevenLabs webhook HMAC signature.

    Signature format: t=timestamp,v0=hash
    Hash is sha256 HMAC of "timestamp.request_body"
    """
    if not ELEVENLABS_WEBHOOK_SECRET:
        logger.warning("ELEVENLABS_WEBHOOK_SECRET not set, skipping signature validation")
        return True  # Allow for development without secret

    if not signature_header:
        logger.warning("No elevenlabs-signature header provided")
        return False

    try:
        # Parse signature header
        parts = signature_header.split(",")
        timestamp = None
        hmac_signature = None

        for part in parts:
            if part.startswith("t="):
                timestamp = part[2:]
            elif part.startswith("v0="):
                hmac_signature = part

        if not timestamp or not hmac_signature:
            logger.warning(f"Invalid signature format: {signature_header}")
            return False

        # Validate timestamp (within 30 minutes)
        import time
        tolerance = int(time.time()) - 30 * 60
        if int(timestamp) < tolerance:
            logger.warning("Webhook timestamp too old")
            return False

        # Validate signature
        payload_to_sign = f"{timestamp}.{request_body.decode('utf-8')}"
        mac = hmac.new(
            key=ELEVENLABS_WEBHOOK_SECRET.encode("utf-8"),
            msg=payload_to_sign.encode("utf-8"),
            digestmod=sha256,
        )
        expected = "v0=" + mac.hexdigest()

        if not hmac.compare_digest(hmac_signature, expected):
            logger.warning("HMAC signature mismatch")
            return False

        return True
    except Exception as e:
        logger.error(f"Error validating signature: {e}")
        return False


# ============================================================================
# Webhook Endpoints
# ============================================================================

@router.post("/webhook")
async def webhook(
    Body: str = Form(""),
    From: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None)
):
    """
    Handle incoming WhatsApp messages from Twilio with SMART ROUTING.

    Uses ASYNC RESPONSE pattern for pre-screening:
    - Returns empty TwiML immediately (~50ms)
    - Processes message in background
    - Sends response via Twilio REST API

    This dramatically reduces perceived latency from ~5s to ~2s.
    """
    import time as time_module
    webhook_start = time_module.perf_counter()

    incoming_msg = Body
    from_number = From

    # Use phone number as user/session ID for conversation continuity
    phone_normalized = from_number.replace("whatsapp:", "").lstrip("+")

    logger.info(f"🔍 Webhook received from {phone_normalized}")

    # ==========================================================================
    # TEST MODE: Measure pure Twilio round-trip time without LLM
    # Commands:
    #   LATENCY_TEST     - Single ping/pong
    #   TEST_CONV        - Start simulated conversation
    #   TEST_1, TEST_2.. - Continue simulated conversation
    # ==========================================================================
    test_msg = incoming_msg.strip().upper()

    if test_msg == "LATENCY_TEST":
        test_response = f"🏓 PONG! Server received at {time_module.time():.3f}"
        logger.info(f"🧪 LATENCY TEST MODE - sending hardcoded response")

        asyncio.create_task(send_whatsapp_message(phone_normalized, test_response))

        webhook_total = (time_module.perf_counter() - webhook_start) * 1000
        logger.info(f"⏱️ LATENCY TEST webhook response: {webhook_total:.0f}ms")

        resp = MessagingResponse()
        return PlainTextResponse(content=str(resp), media_type="application/xml")

    # Simulated conversation test - hardcoded responses for each step
    TEST_RESPONSES = {
        "TEST_CONV": "👋 Hallo! Welkom bij de test-screening. Dit is een gesimuleerde reactie om latency te meten. Stuur 'TEST_1' voor de volgende stap.",
        "TEST_1": "✅ Geweldig! Eerste vraag: Hoeveel jaar ervaring heb je? (Stuur 'TEST_2' om door te gaan)",
        "TEST_2": "📝 Bedankt voor je antwoord. Tweede vraag: Ben je beschikbaar voor fulltime werk? (Stuur 'TEST_3')",
        "TEST_3": "🎯 Uitstekend! Laatste vraag: Wanneer zou je kunnen beginnen? (Stuur 'TEST_END' om af te ronden)",
        "TEST_END": "🏁 Test voltooid! Je hebt alle stappen doorlopen. Gemiddelde latency kun je nu berekenen uit de logs.",
    }

    if test_msg in TEST_RESPONSES:
        test_response = TEST_RESPONSES[test_msg]
        logger.info(f"🧪 TEST CONV MODE [{test_msg}] - sending hardcoded response")

        asyncio.create_task(send_whatsapp_message(phone_normalized, test_response))

        webhook_total = (time_module.perf_counter() - webhook_start) * 1000
        logger.info(f"⏱️ TEST CONV [{test_msg}] webhook response: {webhook_total:.0f}ms")

        resp = MessagingResponse()
        return PlainTextResponse(content=str(resp), media_type="application/xml")

    # Check cache first for fast routing
    cached = await conversation_cache.get(phone_normalized)
    conv_row = None

    if cached:
        logger.info(f"⚡ Cache HIT for {phone_normalized}: {cached.conversation_type.value}")

        if cached.conversation_type == ConversationType.DOCUMENT_COLLECTION:
            # Document collection still uses TwiML (has media handling)
            logger.info(f"📄 SMART ROUTING → Document collection (cached)")
            from src.routers import document_collection as doc_module
            return await doc_module.document_webhook(
                Body=Body, From=From, NumMedia=NumMedia,
                MediaUrl0=MediaUrl0, MediaContentType0=MediaContentType0
            )
        elif cached.conversation_type == ConversationType.PRE_SCREENING:
            logger.info(f"📞 SMART ROUTING → Pre-screening (async, cached)")
            conv_row = {
                "id": uuid.UUID(cached.conversation_id) if cached.conversation_id else None,
                "vacancy_id": uuid.UUID(cached.vacancy_id) if cached.vacancy_id else None,
                "pre_screening_id": uuid.UUID(cached.pre_screening_id) if cached.pre_screening_id else None,
                "session_id": cached.session_id,
                "candidate_name": cached.candidate_name,
                "vacancy_title": cached.vacancy_title,
            }
        elif cached.conversation_type == ConversationType.NONE:
            logger.info(f"🔀 SMART ROUTING → Generic fallback (async, cached)")
            conv_row = None
    else:
        # Cache miss - run both routing queries in parallel
        logger.info(f"💾 Cache MISS for {phone_normalized} - querying DB...")
        pool = await get_db_pool()

        doc_task = pool.fetchrow(
            """
            SELECT id, vacancy_id, session_id, candidate_name
            FROM ats.document_collection_conversations
            WHERE candidate_phone = $1 AND status = 'active'
            ORDER BY started_at DESC LIMIT 1
            """,
            phone_normalized
        )
        conv_task = pool.fetchrow(
            """
            SELECT sc.id, sc.vacancy_id, sc.pre_screening_id, sc.session_id, sc.candidate_name,
                   v.title as vacancy_title
            FROM ats.screening_conversations sc
            JOIN ats.vacancies v ON v.id = sc.vacancy_id
            WHERE sc.candidate_phone = $1 AND sc.channel = 'whatsapp' AND sc.status = 'active'
            ORDER BY sc.started_at DESC LIMIT 1
            """,
            phone_normalized
        )

        doc_conv_row, conv_row = await asyncio.gather(doc_task, conv_task)

        # Cache and route
        if doc_conv_row:
            await conversation_cache.set(
                phone=phone_normalized,
                conversation_type=ConversationType.DOCUMENT_COLLECTION,
                conversation_id=str(doc_conv_row["id"]),
                vacancy_id=str(doc_conv_row["vacancy_id"]) if doc_conv_row["vacancy_id"] else None,
                session_id=doc_conv_row["session_id"],
                candidate_name=doc_conv_row["candidate_name"],
            )
            logger.info(f"📄 SMART ROUTING → Document collection")
            from src.routers import document_collection as doc_module
            return await doc_module.document_webhook(
                Body=Body, From=From, NumMedia=NumMedia,
                MediaUrl0=MediaUrl0, MediaContentType0=MediaContentType0
            )
        elif conv_row:
            await conversation_cache.set(
                phone=phone_normalized,
                conversation_type=ConversationType.PRE_SCREENING,
                conversation_id=str(conv_row["id"]),
                vacancy_id=str(conv_row["vacancy_id"]),
                pre_screening_id=str(conv_row["pre_screening_id"]),
                session_id=conv_row["session_id"],
                candidate_name=conv_row["candidate_name"],
                vacancy_title=conv_row["vacancy_title"],
            )
            logger.info(f"📞 SMART ROUTING → Pre-screening (async)")
        else:
            await conversation_cache.set(
                phone=phone_normalized,
                conversation_type=ConversationType.NONE,
            )
            logger.info(f"🔀 SMART ROUTING → Generic fallback (async)")

    # Launch background processing and return immediately
    asyncio.create_task(_process_and_respond_async(
        phone_normalized=phone_normalized,
        incoming_msg=incoming_msg,
        conv_row=conv_row,
    ))

    webhook_total = (time_module.perf_counter() - webhook_start) * 1000
    logger.info(f"⏱️ WEBHOOK RESPONSE TIME: {webhook_total:.0f}ms (processing in background)")

    # Return empty TwiML - response will be sent via REST API
    resp = MessagingResponse()
    return PlainTextResponse(content=str(resp), media_type="application/xml")


@router.post("/webhook/elevenlabs")
async def elevenlabs_webhook(request: Request):
    """
    Handle ElevenLabs post-call webhooks.

    Processes voice call transcripts after a call ends:
    1. Validates HMAC signature (if ELEVENLABS_WEBHOOK_SECRET is set)
    2. Looks up the pre-screening by agent_id
    3. Processes the transcript using the transcript_processor agent
    4. Stores evaluation results in application_answers

    Event types:
    - post_call_transcription: Contains full conversation data (main handler)
    - post_call_audio: Audio data (ignored)
    - call_initiation_failure: Call failed to connect (logged only)
    """
    # Read raw body for signature validation
    body = await request.body()

    # Validate signature
    signature = request.headers.get("elevenlabs-signature", "")
    if not await verify_elevenlabs_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    try:
        payload_dict = json.loads(body)
        payload = ElevenLabsWebhookPayload(**payload_dict)
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    event_type = payload.type
    data = payload.data

    logger.info(f"ElevenLabs webhook received: type={event_type}, agent_id={data.agent_id}, conversation_id={data.conversation_id}")
    # Debug: log raw request body (truncated if large)
    try:
        body_preview = body.decode("utf-8", errors="replace")
        if len(body_preview) > 2000:
            body_preview = body_preview[:2000] + "... [truncated]"
        logger.info(f"[webhook/elevenlabs] request body: {body_preview}")
    except Exception:
        logger.info(f"[webhook/elevenlabs] request body (raw bytes len={len(body)})")

    # Handle based on event type
    if event_type == "call_initiation_failure":
        resp = {"status": "received", "action": "logged"}
        logger.warning(f"Call initiation failed for conversation {data.conversation_id}")
        logger.info(f"[webhook/elevenlabs] response: {resp}")
        return resp

    if event_type == "post_call_audio":
        resp = {"status": "received", "action": "ignored"}
        logger.info(f"Audio webhook received for conversation {data.conversation_id} (ignored)")
        logger.info(f"[webhook/elevenlabs] response: {resp}")
        return resp

    if event_type != "post_call_transcription":
        resp = {"status": "received", "action": "unknown_type"}
        logger.warning(f"Unknown webhook type: {event_type}")
        logger.info(f"[webhook/elevenlabs] response: {resp}")
        return resp

    # Process transcription webhook
    pool = await get_db_pool()

    # Look up screening conversation by ElevenLabs conversation_id
    # This maps back to the pre-screening since we store conversation_id in session_id
    screening_conv = await pool.fetchrow(
        """
        SELECT sc.pre_screening_id, sc.vacancy_id, sc.candidate_phone, sc.candidate_name, sc.is_test,
               sc.application_id, v.title as vacancy_title
        FROM ats.screening_conversations sc
        JOIN ats.vacancies v ON v.id = sc.vacancy_id
        WHERE sc.session_id = $1 AND sc.channel = 'voice'
        """,
        data.conversation_id
    )

    if not screening_conv:
        logger.error(f"No screening conversation found for conversation_id: {data.conversation_id}")
        raise HTTPException(status_code=404, detail=f"No conversation found: {data.conversation_id}")

    pre_screening_id = screening_conv["pre_screening_id"]
    vacancy_id = screening_conv["vacancy_id"]
    vacancy_title = screening_conv["vacancy_title"]
    candidate_phone = screening_conv["candidate_phone"]
    candidate_name = screening_conv["candidate_name"] or "Voice Candidate"

    logger.info(f"Processing transcript for vacancy '{vacancy_title}' (pre-screening {pre_screening_id})")

    # Get pre-screening questions
    questions = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM ats.pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )

    # Build question lists with proper IDs (ko_1, qual_1, etc.)
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

    # Convert event timestamp to ISO date for interview slot calculation
    from datetime import datetime as dt
    call_date = dt.fromtimestamp(payload.event_timestamp).strftime("%Y-%m-%d")

    # Extract metadata
    metadata = data.metadata or {}
    call_duration = metadata.get("call_duration_secs", 0)

    # candidate_phone and candidate_name already retrieved from screening_conv above

    # Find existing application - prefer the linked application_id from conversation
    existing_app = None
    if screening_conv["application_id"]:
        # Use the directly linked application (unique per conversation)
        existing_app = await pool.fetchrow(
            """
            SELECT id, candidate_id FROM ats.applications
            WHERE id = $1 AND status != 'completed'
            """,
            screening_conv["application_id"]
        )

    # Fallback to phone matching for legacy conversations without application_id
    if not existing_app and candidate_phone:
        existing_app = await pool.fetchrow(
            """
            SELECT id, candidate_id FROM ats.applications
            WHERE vacancy_id = $1 AND candidate_phone = $2 AND channel = 'voice' AND status != 'completed'
            """,
            vacancy_id,
            candidate_phone
        )

    if existing_app:
        # Set status to 'processing' BEFORE transcript analysis (commits immediately)
        await pool.execute(
            "UPDATE ats.applications SET status = 'processing' WHERE id = $1",
            existing_app["id"]
        )
        logger.info(f"🔄 Application {existing_app['id']} status -> processing")

    # Update workflow to 'processing' step
    try:
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", data.conversation_id)
        if workflow:
            await orchestrator.service.update_step(workflow["id"], "processing")
            logger.info(f"🔄 Workflow {workflow['id']} step -> processing")
    except Exception as e:
        logger.warning(f"Could not update workflow to processing for voice: {e}")

    # Process transcript with the agent (AI analysis happens here)
    result = await process_transcript(
        transcript=data.transcript,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        call_date=call_date,
    )

    # Look up interview_slot from scheduled_interviews table (created during conversation)
    interview_slot = None
    scheduled = await pool.fetchrow(
        "SELECT selected_date, selected_time FROM ats.scheduled_interviews WHERE conversation_id = $1",
        data.conversation_id
    )
    if scheduled:
        from zoneinfo import ZoneInfo
        try:
            hour = int(scheduled["selected_time"].replace("u", "").replace("h", ""))
            tz = ZoneInfo("Europe/Brussels")
            dt = datetime.combine(scheduled["selected_date"], datetime.min.time(), tzinfo=tz).replace(hour=hour)
            interview_slot = dt.isoformat()
        except Exception as e:
            logger.warning(f"Could not parse interview slot for voice: {e}")
            interview_slot = f"{scheduled['selected_date']} {scheduled['selected_time']}"

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Use the existing_app we found earlier (already set to 'processing')
            if existing_app:
                # Update existing application to completed
                application_id = existing_app["id"]
                await conn.execute(
                    """
                    UPDATE ats.applications
                    SET qualified = $1, interaction_seconds = $2,
                        completed_at = NOW(), conversation_id = $3, channel = 'voice',
                        summary = $4, interview_slot = $5, status = 'completed'
                    WHERE id = $6
                    """,
                    result.overall_passed,
                    call_duration,
                    data.conversation_id,
                    result.summary,
                    interview_slot,
                    application_id
                )
                logger.info(f"Updated existing application {application_id} for phone {candidate_phone} with status=completed")
            else:
                # Create new application record
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO ats.applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     interaction_seconds, completed_at, conversation_id, summary, interview_slot, status)
                    VALUES ($1, $2, $3, 'voice', $4, $5, NOW(), $6, $7, $8, 'completed')
                    RETURNING id
                    """,
                    vacancy_id,
                    candidate_name,
                    candidate_phone,
                    result.overall_passed,
                    call_duration,
                    data.conversation_id,
                    result.summary,
                    interview_slot
                )
                application_id = app_row["id"]
                logger.info(f"Created new application {application_id}")

            # Store knockout results
            for kr in result.knockout_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'voice')
                    """,
                    application_id,
                    kr.id,
                    kr.question_text,
                    kr.answer,
                    kr.passed,
                    kr.score,
                    kr.rating
                )

            # Store qualification results
            for qr in result.qualification_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source, motivation)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, 'voice', $7)
                    """,
                    application_id,
                    qr.id,
                    qr.question_text,
                    qr.answer,
                    qr.score,
                    qr.rating,
                    qr.motivation
                )

            # Update screening_conversations status to completed
            # The session_id in screening_conversations is the ElevenLabs conversation_id
            await conn.execute(
                """
                UPDATE ats.screening_conversations
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE session_id = $1 AND channel = 'voice'
                """,
                data.conversation_id
            )

            # Store voice transcript in conversation_messages for unified storage
            # First, get the screening_conversation ID
            conv_id_row = await conn.fetchrow(
                """
                SELECT id FROM ats.screening_conversations
                WHERE session_id = $1 AND channel = 'voice'
                """,
                data.conversation_id
            )

            if conv_id_row:
                voice_conv_id = conv_id_row["id"]
                # Store each transcript message
                for msg in data.transcript:
                    role = "user" if msg.get("role") == "user" else "agent"
                    message_text = msg.get("message", "")
                    if message_text:
                        await conn.execute(
                            """
                            INSERT INTO ats.conversation_messages (conversation_id, role, message)
                            VALUES ($1, $2, $3)
                            """,
                            voice_conv_id, role, message_text
                        )
                logger.info(f"Stored {len(data.transcript)} voice transcript messages")

    logger.info(f"Stored application {application_id} with {len(result.knockout_results)} knockout and {len(result.qualification_results)} qualification answers")

    # Log activity: screening completed with rich metadata
    candidate_id = existing_app["candidate_id"] if existing_app and existing_app.get("candidate_id") else None
    if candidate_id:
        activity_service = ActivityService(pool)

        # Calculate overall score from qualification results
        scores = [qr.score for qr in result.qualification_results if qr.score is not None]
        avg_score = round(sum(scores) / len(scores)) if scores else None

        # Calculate knockout stats
        knockout_passed = sum(1 for kr in result.knockout_results if kr.passed)
        knockout_total = len(result.knockout_results)

        # Get transcript preview (last user message for context)
        transcript_preview = None
        for msg in reversed(data.transcript):
            if msg.get("role") == "user" and msg.get("message"):
                transcript_preview = msg["message"][:100] + "..." if len(msg["message"]) > 100 else msg["message"]
                break

        # Build rich metadata
        activity_metadata = {
            "score": avg_score,
            "knockout_passed": knockout_passed,
            "knockout_total": knockout_total,
            "duration_seconds": call_duration,
        }
        if transcript_preview:
            activity_metadata["transcript_preview"] = transcript_preview

        # If disqualified, add reason
        if not result.overall_passed:
            failed_knockouts = [kr.question_text for kr in result.knockout_results if not kr.passed]
            if failed_knockouts:
                activity_metadata["knockout_failed"] = failed_knockouts[0][:50]

        # Log screening completed
        event_type = ActivityEventType.QUALIFIED if result.overall_passed else ActivityEventType.DISQUALIFIED
        await activity_service.log(
            candidate_id=str(candidate_id),
            event_type=event_type,
            application_id=str(application_id),
            vacancy_id=str(vacancy_id),
            channel=ActivityChannel.VOICE,
            actor_type=ActorType.AGENT,
            metadata=activity_metadata,
            summary=f"Pre-screening {'geslaagd' if result.overall_passed else 'niet geslaagd'}" + (f" (score: {avg_score}%)" if avg_score else "")
        )

    # Trigger screening notes integration (Google Doc creation + calendar attachment)
    # Runs as background task for qualified candidates with scheduled interviews
    if result.overall_passed:
        asyncio.create_task(trigger_screening_notes_integration(
            pool=pool,
            application_id=application_id,
            recruiter_email=os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL"),
        ))
        logger.info(f"📄 Triggered screening notes integration for application {application_id}")

    # Notify workflow orchestrator that screening is complete
    # This triggers unified notification handling (WhatsApp confirmation + Teams notification)
    try:
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", data.conversation_id)
        if workflow:
            # Get interview_slot from scheduled_interviews table (created during conversation)
            interview_slot = None
            scheduled = await pool.fetchrow(
                "SELECT selected_date, selected_time FROM ats.scheduled_interviews WHERE conversation_id = $1",
                data.conversation_id
            )
            if scheduled:
                from zoneinfo import ZoneInfo
                try:
                    hour = int(scheduled["selected_time"].replace("u", "").replace("h", ""))
                    tz = ZoneInfo("Europe/Brussels")
                    dt = datetime.combine(scheduled["selected_date"], datetime.min.time(), tzinfo=tz).replace(hour=hour)
                    interview_slot = dt.isoformat()
                except Exception as e:
                    logger.warning(f"Could not parse interview slot for voice: {e}")
                    interview_slot = f"{scheduled['selected_date']} {scheduled['selected_time']}"

            await orchestrator.handle_event(
                workflow_id=workflow["id"],
                event="screening_completed",
                payload={
                    "qualified": result.overall_passed,
                    "interview_slot": interview_slot,
                    "application_id": str(application_id),
                    "candidate_name": candidate_name,
                    "candidate_phone": candidate_phone,
                    "summary": result.summary,
                },
            )
            logger.info(f"✅ Workflow event sent for voice conversation {data.conversation_id}")
        else:
            logger.debug(f"No workflow found for voice conversation {data.conversation_id} (legacy flow)")
    except Exception as e:
        logger.error(f"❌ Failed to notify workflow orchestrator for voice: {e}")
        # Don't fail the whole process if workflow notification fails

    response = {
        "status": "processed",
        "application_id": str(application_id),
        "overall_passed": result.overall_passed,
        "knockout_results": len(result.knockout_results),
        "qualification_results": len(result.qualification_results),
        "notes": result.notes,
        "summary": result.summary,
        "interview_slot": result.interview_slot
    }
    logger.info(f"[webhook/elevenlabs] response: {response}")
    return response


# ============================================================================
# Cache Management
# ============================================================================

@router.delete("/webhook/cache")
async def clear_conversation_cache():
    """
    Clear all in-memory conversation and agent caches.

    Use this to reset cached conversations when testing.
    """
    from src.utils.conversation_cache import clear_all_caches
    result = await clear_all_caches()
    return {
        "status": "cleared",
        "conversations_cleared": result["conversations"],
        "agents_cleared": result["agents"]
    }


# ============================================================================
# Meta WhatsApp Cloud API Webhooks
# ============================================================================

# Verify token for Meta webhook setup - should match what you enter in Meta Developer Console
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "taloo_verify_token_2024")


@router.get("/webhook/meta")
async def meta_webhook_verify(
    request: Request,
):
    """
    Handle Meta WhatsApp webhook verification (GET request).

    Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge
    to verify the webhook URL is valid.
    """
    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logger.info(f"🔔 Meta webhook verification: mode={mode}, token={token[:10] if token else 'None'}... challenge={challenge[:20] if challenge else 'None'}...")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        logger.info("✅ Meta webhook verified successfully!")
        # Return the challenge as plain text
        return PlainTextResponse(content=challenge, status_code=200)
    else:
        logger.warning(f"❌ Meta webhook verification failed: mode={mode}, token mismatch={token != META_VERIFY_TOKEN}")
        raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook/meta")
async def meta_webhook_receive(request: Request):
    """
    Handle incoming WhatsApp messages from Meta Cloud API (POST request).

    This endpoint receives message notifications from Meta when users send messages.
    Supports LATENCY_TEST command to measure Meta API round-trip time.
    """
    import time as time_module
    from src.services.meta_whatsapp_service import send_meta_whatsapp_message

    webhook_start = time_module.perf_counter()

    try:
        body = await request.json()
        logger.info(f"📱 Meta webhook received: {json.dumps(body, indent=2)[:500]}")

        # Extract message details from Meta's webhook format
        # Structure: body.entry[0].changes[0].value.messages[0]
        entry = body.get("entry", [])
        if not entry:
            return {"status": "ok"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ok"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Could be a status update, not a message
            statuses = value.get("statuses", [])
            if statuses:
                logger.info(f"📊 Message status update: {statuses[0].get('status')}")
            return {"status": "ok"}

        # Process the incoming message
        message = messages[0]
        from_number = message.get("from")  # Phone number without +
        message_type = message.get("type")
        timestamp = message.get("timestamp")

        # Extract text message
        text_body = ""
        if message_type == "text":
            text_body = message.get("text", {}).get("body", "")

        logger.info(f"📨 Meta message from {from_number}: {text_body[:100]}")

        # ==========================================================================
        # TEST MODE: Measure pure Meta API round-trip time without LLM
        # Commands:
        #   LATENCY_TEST     - Single ping/pong
        #   TEST_CONV        - Start simulated conversation
        #   TEST_1, TEST_2.. - Continue simulated conversation
        # ==========================================================================
        test_msg = text_body.strip().upper()

        if test_msg == "LATENCY_TEST":
            test_response = f"🏓 META PONG! Server received at {time_module.time():.3f}"
            logger.info(f"🧪 META LATENCY TEST MODE - sending hardcoded response")

            # Send response via Meta API (in background for fast webhook response)
            asyncio.create_task(send_meta_whatsapp_message(from_number, test_response))

            webhook_total = (time_module.perf_counter() - webhook_start) * 1000
            logger.info(f"⏱️ META LATENCY TEST webhook response: {webhook_total:.0f}ms")

            return {"status": "ok"}

        # Simulated conversation test - hardcoded responses for each step
        META_TEST_RESPONSES = {
            "TEST_CONV": "👋 META Hallo! Welkom bij de test-screening via Meta API. Stuur 'TEST_1' voor de volgende stap.",
            "TEST_1": "✅ META Geweldig! Eerste vraag: Hoeveel jaar ervaring heb je? (Stuur 'TEST_2' om door te gaan)",
            "TEST_2": "📝 META Bedankt voor je antwoord. Tweede vraag: Ben je beschikbaar voor fulltime werk? (Stuur 'TEST_3')",
            "TEST_3": "🎯 META Uitstekend! Laatste vraag: Wanneer zou je kunnen beginnen? (Stuur 'TEST_END' om af te ronden)",
            "TEST_END": "🏁 META Test voltooid! Je hebt alle stappen doorlopen via Meta API. Vergelijk de latency met Twilio!",
        }

        if test_msg in META_TEST_RESPONSES:
            test_response = META_TEST_RESPONSES[test_msg]
            logger.info(f"🧪 META TEST CONV MODE [{test_msg}] - sending hardcoded response")

            asyncio.create_task(send_meta_whatsapp_message(from_number, test_response))

            webhook_total = (time_module.perf_counter() - webhook_start) * 1000
            logger.info(f"⏱️ META TEST CONV [{test_msg}] webhook response: {webhook_total:.0f}ms")

            return {"status": "ok"}

        # TODO: Route to pre-screening agent similar to Twilio webhook
        # For now, just acknowledge receipt
        logger.info(f"📨 No handler for message from {from_number}: {text_body[:50]}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"❌ Meta webhook error: {e}")
        # Always return 200 to Meta to prevent retries
        return {"status": "error", "message": str(e)}
