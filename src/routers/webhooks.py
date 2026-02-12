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

    # Get conversation details BEFORE processing
    conv_row = await pool.fetchrow(
        """
        SELECT vacancy_id, candidate_name, candidate_phone, is_test
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

    # Find existing application and set status to 'processing' BEFORE AI processing
    # IMPORTANT: Only find applications for the WHATSAPP channel to avoid race conditions with voice
    existing_app = None
    if candidate_phone:
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
                    result.interview_slot,
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
                    result.interview_slot,
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


async def _webhook_impl_vacancy_specific(
    pool,
    conversation_id: uuid.UUID,
    incoming_msg: str,
    candidate_name: str,
) -> tuple[str, bool, str | None]:
    """
    Handle webhook using pre-screening WhatsApp agent.

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
    # Load agent state from database
    row = await pool.fetchrow(
        """
        SELECT agent_state FROM ats.screening_conversations WHERE id = $1
        """,
        conversation_id
    )

    if not row or not row["agent_state"]:
        logger.error(f"No agent state found for conversation {conversation_id}")
        return "Er is een fout opgetreden. Probeer het later opnieuw.", False, None

    try:
        # Restore agent from saved state
        # Handle multiple levels of JSON encoding from legacy data
        agent_state = row["agent_state"]

        # Unwrap any string encoding until we get a dict
        # This handles double/triple-encoded JSON from before the fix
        max_unwrap = 3  # Safety limit
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

        # Now convert dict to JSON string for restore_agent_from_state
        state_json = json.dumps(agent_state)
        agent = restore_agent_from_state(state_json)
        logger.info(f"📱 Restored agent for conversation {conversation_id}, phase={agent.state.phase.value}")

        # Process the message
        response_text = await agent.process_message(incoming_msg)
        logger.info(f"📱 Agent response: phase={agent.state.phase.value}, response={response_text[:100]}...")

        # Save updated state back to database
        updated_state = agent.state.to_dict()
        await pool.execute(
            """
            UPDATE ats.screening_conversations
            SET agent_state = $1, updated_at = NOW()
            WHERE id = $2
            """,
            json.dumps(updated_state),  # Serialize to JSON string for JSONB column
            conversation_id
        )

        # Save scheduled interview if agent has scheduling info
        if agent.state.selected_date and agent.state.selected_time:
            await _save_whatsapp_scheduled_interview(
                pool=pool,
                conversation_id=conversation_id,
                selected_date=agent.state.selected_date,
                selected_time=agent.state.selected_time,
                selected_slot_text=agent.state.scheduled_time,
                candidate_name=candidate_name,
            )

        # Check if conversation is complete
        complete = is_conversation_complete(agent)
        completion_outcome = None
        if complete:
            outcome = get_conversation_outcome(agent)
            completion_outcome = outcome.get("outcome", "completed")
            logger.info(f"🏁 Conversation complete: phase={agent.state.phase.value}, outcome={completion_outcome}")

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

    Routes to the correct agent based on active conversation type:
    1. Document collection (if active document_collection_conversation exists)
    2. Pre-screening (if active screening_conversation exists)
    3. Generic demo agent (fallback)
    """
    incoming_msg = Body
    from_number = From

    # Use phone number as user/session ID for conversation continuity
    # Remove "whatsapp:" prefix and "+" to match outbound format
    phone_normalized = from_number.replace("whatsapp:", "").lstrip("+")

    pool = await get_db_pool()

    # SMART ROUTING: Check for active DOCUMENT COLLECTION first
    logger.info(f"🔍 Webhook received from {phone_normalized} - checking routing...")

    doc_conv_row = await pool.fetchrow(
        """
        SELECT id, vacancy_id, session_id, candidate_name
        FROM ats.document_collection_conversations
        WHERE candidate_phone = $1
        AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        phone_normalized
    )

    if doc_conv_row:
        # Route to document collection webhook
        logger.info(f"📄 SMART ROUTING → Document collection (conversation_id={doc_conv_row['id']})")
        from src.routers.document_collection import router as doc_router
        # Import the webhook handler
        from src.routers import document_collection as doc_module
        return await doc_module.document_webhook(
            Body=Body,
            From=From,
            NumMedia=NumMedia,
            MediaUrl0=MediaUrl0,
            MediaContentType0=MediaContentType0
        )

    logger.info(f"❌ No active document collection found for {phone_normalized}")

    # Check for active WhatsApp SCREENING conversation
    conv_row = await pool.fetchrow(
        """
        SELECT sc.id, sc.vacancy_id, sc.pre_screening_id, sc.session_id, sc.candidate_name,
               v.title as vacancy_title
        FROM ats.screening_conversations sc
        JOIN ats.vacancies v ON v.id = sc.vacancy_id
        WHERE sc.candidate_phone = $1
        AND sc.channel = 'whatsapp'
        AND sc.status = 'active'
        ORDER BY sc.started_at DESC
        LIMIT 1
        """,
        phone_normalized
    )

    if conv_row:
        logger.info(f"📞 SMART ROUTING → Pre-screening (conversation_id={conv_row['id']})")
    else:
        logger.info(f"❌ No active pre-screening found for {phone_normalized}")
        logger.info(f"🔀 SMART ROUTING → Generic fallback (no active conversations)")

    is_complete = False
    completion_outcome = None
    conversation_id = None

    try:
        if conv_row:
            # Found active outbound screening - use vacancy-specific agent
            vacancy_id = str(conv_row["vacancy_id"])
            pre_screening_id = str(conv_row["pre_screening_id"])
            vacancy_title = conv_row["vacancy_title"]
            conversation_id = conv_row["id"]
            candidate_name = conv_row["candidate_name"] or "Kandidaat"

            logger.info(f"📱 WhatsApp webhook: Found active conversation {conversation_id}")

            # Process message with the pre-screening agent
            response_text, is_complete, completion_outcome = await _webhook_impl_vacancy_specific(
                pool, conversation_id, incoming_msg, candidate_name
            )

            # Get pre-screening config for transcript processing (only needed if conversation completes)
            pre_screening = None
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

            # Store messages in conversation_messages table
            if conversation_id:
                # Store user message
                await pool.execute(
                    """
                    INSERT INTO ats.conversation_messages (conversation_id, role, message)
                    VALUES ($1, 'user', $2)
                    """,
                    conversation_id, incoming_msg
                )
                # Store agent response
                if response_text:
                    await pool.execute(
                        """
                        INSERT INTO ats.conversation_messages (conversation_id, role, message)
                        VALUES ($1, 'agent', $2)
                        """,
                        conversation_id, response_text
                    )

            # If conversation is complete, trigger transcript processing in background
            if is_complete and conversation_id:
                logger.info(f"🔄 Triggering background transcript processing for conversation {conversation_id}")
                asyncio.create_task(_safe_process_conversation(
                    pool, conversation_id, vacancy_id, pre_screening, completion_outcome
                ))
        else:
            # No active outbound screening - use generic demo agent
            logger.info(f"WhatsApp webhook routing to generic agent (no active screening found)")
            response_text = await _webhook_impl_generic(phone_normalized, incoming_msg)

    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error: {e}")
        # Retry with generic agent on connection error
        response_text = await _webhook_impl_generic(phone_normalized, incoming_msg)

    # Send TwiML response
    resp = MessagingResponse()
    resp.message(response_text or "Sorry, I couldn't process that.")
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
               v.title as vacancy_title
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

    # Find existing application and set status to 'processing' BEFORE AI analysis
    # IMPORTANT: Only find applications for the VOICE channel to avoid race conditions with WhatsApp
    existing_app = None
    if candidate_phone:
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

    # Process transcript with the agent (AI analysis happens here)
    result = await process_transcript(
        transcript=data.transcript,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        call_date=call_date,
    )

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
                    result.interview_slot,
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
                    result.interview_slot
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
