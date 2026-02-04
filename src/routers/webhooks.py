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
from twilio.rest import Client
from google.genai import types
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError

from knockout_agent.agent import build_screening_instruction, is_closing_message, clean_response_text, conversation_complete_tool
from transcript_processor import process_transcript
from src.config import ELEVENLABS_WEBHOOK_SECRET, logger
from src.models.webhook import ElevenLabsWebhookPayload
from src.database import get_db_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

# Global session_manager will be set by main app
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager

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
        FROM conversation_messages
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
        FROM screening_conversations
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
    existing_app = None
    if candidate_phone:
        existing_app = await pool.fetchrow(
            """
            SELECT id FROM applications
            WHERE vacancy_id = $1 AND candidate_phone = $2 AND status != 'completed'
            """,
            vacancy_uuid, candidate_phone
        )

    if not existing_app:
        existing_app = await pool.fetchrow(
            """
            SELECT id FROM applications
            WHERE vacancy_id = $1 AND candidate_name = $2 AND status != 'completed'
            """,
            vacancy_uuid, candidate_name
        )

    if existing_app:
        # Set status to 'processing' BEFORE transcript analysis (commits immediately)
        await pool.execute(
            "UPDATE applications SET status = 'processing' WHERE id = $1",
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
                    UPDATE applications
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
                    INSERT INTO applications
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
                    INSERT INTO application_answers
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
                    INSERT INTO application_answers
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
                UPDATE screening_conversations
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE id = $1
                """,
                conversation_id
            )

    logger.info(f"✅ WhatsApp conversation {conversation_id} processed: application {application_id}")


async def _webhook_impl_vacancy_specific(session_id: str, incoming_msg: str, vacancy_id: str, pre_screening: dict, vacancy_title: str) -> tuple[str, bool, str | None]:
    """
    Handle webhook using vacancy-specific agent (for outbound screenings).

    Args:
        session_id: The ADK session ID (stored in screening_conversations.session_id)
        incoming_msg: The user's message
        vacancy_id: The vacancy UUID
        pre_screening: Pre-screening configuration dict
        vacancy_title: The vacancy title

    Returns:
        tuple: (response_text, is_complete, completion_outcome)
        - response_text: The agent's response message
        - is_complete: True if conversation is complete (tool called or closing pattern)
        - completion_outcome: The outcome string if tool was called, None otherwise
    """
    global session_manager

    # Get or create the same screening runner as was used for outbound
    runner = session_manager.get_or_create_screening_runner(vacancy_id, pre_screening, vacancy_title)

    # CRITICAL: Verify session exists before running agent
    # The session should have been created during _initiate_whatsapp_screening
    # If it doesn't exist (e.g., DB connection issue), the agent would start fresh without history
    async def verify_or_create_session():
        session = await session_manager.screening_session_service.get_session(
            app_name="screening_chat",
            user_id="whatsapp",
            session_id=session_id
        )
        if not session:
            logger.warning(f"⚠️ Session not found for session_id={session_id}, creating new one (history may be lost!)")
            try:
                await session_manager.screening_session_service.create_session(
                    app_name="screening_chat",
                    user_id="whatsapp",
                    session_id=session_id
                )
            except IntegrityError:
                # Session was created by another concurrent request, that's fine
                pass
        else:
            # Log session details for debugging
            num_events = len(session.events) if session.events else 0
            logger.info(f"✅ Found existing session session_id={session_id} with {num_events} events")

    try:
        await verify_or_create_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error during session check, recreating screening session service: {e}")
        session_manager.create_screening_session_service()
        # Retry after recreating service
        await verify_or_create_session()

    # Run agent and get response
    content = types.Content(role="user", parts=[types.Part(text=incoming_msg)])
    response_text = ""
    completion_outcome = None
    tool_called = False

    async for event in runner.run_async(user_id="whatsapp", session_id=session_id, new_message=content):
        # Check for conversation_complete tool call
        if event.actions and event.actions.requested_auth_configs:
            pass  # Not a tool call we care about

        # Check for function call events (tool calls)
        if hasattr(event, 'actions') and event.actions:
            # Check if there are function calls in the response
            if hasattr(event.actions, 'state_delta') and event.actions.state_delta:
                # Tool might update state
                pass

        # Check for tool call in content
        if event.content and event.content.parts:
            for part in event.content.parts:
                # Check for function call
                if hasattr(part, 'function_call') and part.function_call:
                    if part.function_call.name == "conversation_complete":
                        tool_called = True
                        args = part.function_call.args or {}
                        completion_outcome = args.get("outcome", "completed")
                        logger.info(f"🏁 conversation_complete tool called: {completion_outcome}")

                # Get response text
                if hasattr(part, 'text') and part.text:
                    if event.is_final_response():
                        response_text = clean_response_text(part.text)

    # Fallback: Check for closing patterns if tool wasn't called
    is_complete = tool_called
    if not tool_called and response_text and is_closing_message(response_text):
        is_complete = True
        completion_outcome = "detected via closing pattern"
        logger.info(f"🏁 Closing pattern detected in response")

    return response_text, is_complete, completion_outcome


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
async def webhook(Body: str = Form(""), From: str = Form("")):
    """
    Handle incoming WhatsApp messages from Twilio.

    Routes to the correct agent based on whether there's an active outbound screening:
    - If there's an active WhatsApp conversation for this phone, use the vacancy-specific agent
    - Otherwise, fall back to the generic demo agent
    """
    incoming_msg = Body
    from_number = From

    # Use phone number as user/session ID for conversation continuity
    # Remove "whatsapp:" prefix and "+" to match outbound format
    phone_normalized = from_number.replace("whatsapp:", "").lstrip("+")

    pool = await get_db_pool()

    # Check for active WhatsApp conversation for this phone number
    conv_row = await pool.fetchrow(
        """
        SELECT sc.id, sc.vacancy_id, sc.pre_screening_id, sc.session_id, v.title as vacancy_title
        FROM screening_conversations sc
        JOIN vacancies v ON v.id = sc.vacancy_id
        WHERE sc.candidate_phone = $1
        AND sc.channel = 'whatsapp'
        AND sc.status = 'active'
        ORDER BY sc.started_at DESC
        LIMIT 1
        """,
        phone_normalized
    )

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
            adk_session_id = conv_row["session_id"]  # Use the stored session_id, not phone!

            logger.info(f"📱 WhatsApp webhook: Found active conversation {conversation_id}, session_id={adk_session_id}")

            # Get pre-screening config to build the agent
            ps_row = await pool.fetchrow(
                """
                SELECT intro, knockout_failed_action, final_action
                FROM pre_screenings
                WHERE id = $1
                """,
                conv_row["pre_screening_id"]
            )

            questions = await pool.fetch(
                """
                SELECT id, question_type, position, question_text, ideal_answer
                FROM pre_screening_questions
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

            logger.info(f"WhatsApp webhook routing to vacancy-specific agent for {vacancy_id[:8]}")
            response_text, is_complete, completion_outcome = await _webhook_impl_vacancy_specific(
                adk_session_id, incoming_msg, vacancy_id, pre_screening, vacancy_title
            )

            # Store messages in conversation_messages table
            if conversation_id:
                # Store user message
                await pool.execute(
                    """
                    INSERT INTO conversation_messages (conversation_id, role, message)
                    VALUES ($1, 'user', $2)
                    """,
                    conversation_id, incoming_msg
                )
                # Store agent response
                if response_text:
                    await pool.execute(
                        """
                        INSERT INTO conversation_messages (conversation_id, role, message)
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
        logger.warning(f"Database connection error, recreating services and retrying: {e}")
        session_manager.create_session_service()
        session_manager.create_screening_session_service()
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

    # Handle based on event type
    if event_type == "call_initiation_failure":
        logger.warning(f"Call initiation failed for conversation {data.conversation_id}")
        return {"status": "received", "action": "logged"}

    if event_type == "post_call_audio":
        logger.info(f"Audio webhook received for conversation {data.conversation_id} (ignored)")
        return {"status": "received", "action": "ignored"}

    if event_type != "post_call_transcription":
        logger.warning(f"Unknown webhook type: {event_type}")
        return {"status": "received", "action": "unknown_type"}

    # Process transcription webhook
    pool = await get_db_pool()

    # Look up pre-screening by ElevenLabs agent_id
    ps_row = await pool.fetchrow(
        """
        SELECT ps.id as pre_screening_id, ps.vacancy_id, v.title as vacancy_title
        FROM pre_screenings ps
        JOIN vacancies v ON v.id = ps.vacancy_id
        WHERE ps.elevenlabs_agent_id = $1
        """,
        data.agent_id
    )

    if not ps_row:
        logger.error(f"No pre-screening found for agent_id: {data.agent_id}")
        raise HTTPException(status_code=404, detail=f"No pre-screening found for agent: {data.agent_id}")

    pre_screening_id = ps_row["pre_screening_id"]
    vacancy_id = ps_row["vacancy_id"]
    vacancy_title = ps_row["vacancy_title"]

    logger.info(f"Processing transcript for vacancy '{vacancy_title}' (pre-screening {pre_screening_id})")

    # Get pre-screening questions
    questions = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM pre_screening_questions
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

    # Try to find registered candidate by phone number from screening_conversations
    screening_conv = await pool.fetchrow(
        """
        SELECT candidate_phone, candidate_name
        FROM screening_conversations
        WHERE session_id = $1 AND channel = 'voice'
        """,
        data.conversation_id
    )

    candidate_phone = screening_conv["candidate_phone"] if screening_conv else None
    candidate_name = screening_conv["candidate_name"] if screening_conv else "Voice Candidate"

    # Find existing application and set status to 'processing' BEFORE AI analysis
    existing_app = None
    if candidate_phone:
        existing_app = await pool.fetchrow(
            """
            SELECT id FROM applications
            WHERE vacancy_id = $1 AND candidate_phone = $2 AND status != 'completed'
            """,
            vacancy_id,
            candidate_phone
        )

    if existing_app:
        # Set status to 'processing' BEFORE transcript analysis (commits immediately)
        await pool.execute(
            "UPDATE applications SET status = 'processing' WHERE id = $1",
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
                    UPDATE applications
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
                    INSERT INTO applications
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
                    INSERT INTO application_answers
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
                    INSERT INTO application_answers
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
                UPDATE screening_conversations
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE session_id = $1 AND channel = 'voice'
                """,
                data.conversation_id
            )

            # Store voice transcript in conversation_messages for unified storage
            # First, get the screening_conversation ID
            conv_id_row = await conn.fetchrow(
                """
                SELECT id FROM screening_conversations
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
                            INSERT INTO conversation_messages (conversation_id, role, message)
                            VALUES ($1, $2, $3)
                            """,
                            voice_conv_id, role, message_text
                        )
                logger.info(f"Stored {len(data.transcript)} voice transcript messages")

    logger.info(f"Stored application {application_id} with {len(result.knockout_results)} knockout and {len(result.qualification_results)} qualification answers")

    return {
        "status": "processed",
        "application_id": str(application_id),
        "overall_passed": result.overall_passed,
        "knockout_results": len(result.knockout_results),
        "qualification_results": len(result.qualification_results),
        "notes": result.notes,
        "summary": result.summary,
        "interview_slot": result.interview_slot
    }
