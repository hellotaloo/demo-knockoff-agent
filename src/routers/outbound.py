"""
Outbound Screening Router - Voice & WhatsApp screening initiation.
"""
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from google.genai import types

from src.models.outbound import OutboundScreeningRequest, OutboundScreeningResponse
from src.models import InterviewChannel, ActivityEventType, ActorType, ActivityChannel
from src.repositories import ConversationRepository, PreScreeningRepository, CandidateRepository
from src.services import ActivityService
from src.database import get_db_pool
from src.config import TWILIO_WHATSAPP_NUMBER, ELEVENLABS_AGENT_ID, logger
from voice_agent import initiate_outbound_call
from knockout_agent.agent import get_vacancy_whatsapp_agent

router = APIRouter(tags=["Outbound Screening"])

# Global session manager (set by main app)
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager


async def _clear_all_sessions_for_phone(pool, phone_normalized: str):
    """
    Clear ALL active conversations and ADK sessions for a phone number.

    This ensures only one conversation is active at a time per candidate.
    When a new outbound is triggered, we forget all previous conversations
    (screening, document collection, etc.) to prevent routing conflicts.
    """
    global session_manager

    # 1. Find and abandon all active screening conversations (any channel)
    screening_convs = await pool.fetch(
        """
        SELECT id, session_id, channel
        FROM ats.screening_conversations
        WHERE candidate_phone = $1 AND status = 'active'
        """,
        phone_normalized
    )

    if screening_convs:
        # Mark all as abandoned
        await pool.execute(
            """
            UPDATE ats.screening_conversations
            SET status = 'abandoned', updated_at = NOW()
            WHERE candidate_phone = $1 AND status = 'active'
            """,
            phone_normalized
        )
        logger.info(f"🧹 Abandoned {len(screening_convs)} active screening conversation(s) for {phone_normalized}")

        # Delete their ADK sessions
        for conv in screening_convs:
            if conv["session_id"]:
                user_id = conv["channel"] if conv["channel"] in ["whatsapp", "voice"] else "whatsapp"
                await session_manager.delete_session("screening_chat", user_id, conv["session_id"])

    # 2. Find and abandon all active document collection conversations
    doc_convs = await pool.fetch(
        """
        SELECT id, session_id
        FROM ats.document_collection_conversations
        WHERE candidate_phone = $1 AND status = 'active'
        """,
        phone_normalized
    )

    if doc_convs:
        # Mark all as abandoned
        await pool.execute(
            """
            UPDATE ats.document_collection_conversations
            SET status = 'abandoned', updated_at = NOW()
            WHERE candidate_phone = $1 AND status = 'active'
            """,
            phone_normalized
        )
        logger.info(f"🧹 Abandoned {len(doc_convs)} active document collection conversation(s) for {phone_normalized}")

        # Delete their ADK sessions and invalidate runners
        for conv in doc_convs:
            if conv["session_id"]:
                await session_manager.delete_session("document_collection", "whatsapp", conv["session_id"])
            # Invalidate the cached runner
            session_manager.invalidate_document_runner(str(conv["id"]))

    # 3. Also abandon any non-completed applications (they'll get a new one)
    await pool.execute(
        """
        UPDATE ats.applications
        SET status = 'abandoned'
        WHERE candidate_phone = $1 AND status NOT IN ('completed', 'abandoned')
        """,
        phone_normalized
    )

    total_cleared = len(screening_convs) + len(doc_convs)
    if total_cleared > 0:
        logger.info(f"✅ Cleared {total_cleared} session(s) for {phone_normalized} - ready for new conversation")


@router.post("/screening/outbound", response_model=OutboundScreeningResponse)
async def initiate_outbound_screening(request: OutboundScreeningRequest):
    """
    Initiate an outbound screening conversation with a candidate.

    This is the main entry point for starting screening conversations.
    Supports both voice calls (via ElevenLabs + Twilio) and WhatsApp messages.

    The endpoint will:
    1. Look up the vacancy and its published pre-screening
    2. Use the vacancy-specific agent (voice or WhatsApp)
    3. Initiate the conversation on the specified channel

    Prerequisites for voice:
    - ELEVENLABS_API_KEY must be set
    - ELEVENLABS_PHONE_NUMBER_ID must be set

    Prerequisites for WhatsApp:
    - TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN must be set
    - TWILIO_WHATSAPP_NUMBER must be set
    """
    # Import dependencies needed for the endpoint
    from twilio.rest import Client
    from src.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN

    global session_manager
    pool = await get_db_pool()

    # Initialize Twilio client (needed for WhatsApp)
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    # Validate vacancy_id
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {request.vacancy_id}")

    # Get vacancy and pre-screening
    row = await pool.fetchrow(
        """
        SELECT v.id as vacancy_id, v.title as vacancy_title,
               ps.id as pre_screening_id, ps.elevenlabs_agent_id, ps.whatsapp_agent_id,
               ps.is_online, ps.published_at, ps.intro
        FROM ats.vacancies v
        LEFT JOIN ats.pre_screenings ps ON ps.vacancy_id = v.id
        WHERE v.id = $1
        """,
        vacancy_uuid
    )

    if not row:
        raise HTTPException(status_code=404, detail=f"Vacancy not found: {request.vacancy_id}")

    if not row["pre_screening_id"]:
        raise HTTPException(status_code=400, detail="No pre-screening configured for this vacancy")

    if not row["published_at"]:
        raise HTTPException(status_code=400, detail="Pre-screening is not published yet")

    if not row["is_online"]:
        raise HTTPException(status_code=400, detail="Pre-screening is offline. Set it online first.")

    # Normalize phone number
    phone = request.phone_number
    if not phone.startswith("+"):
        phone = f"+{phone}"
    phone_normalized = phone.lstrip("+")

    # Create full name from first_name + last_name
    candidate_name = f"{request.first_name} {request.last_name}".strip()

    # Clear ALL active sessions for this phone number before starting new conversation
    # This ensures only one conversation is active at a time per candidate
    await _clear_all_sessions_for_phone(pool, phone_normalized)

    # Find or create candidate in central candidates table
    candidate_repo = CandidateRepository(pool)
    candidate_id = await candidate_repo.find_or_create(
        full_name=candidate_name,
        phone=phone_normalized,
        first_name=request.first_name,
        last_name=request.last_name,
        is_test=request.is_test
    )
    logger.info(f"👤 Using candidate {candidate_id} for {candidate_name} (is_test={request.is_test})")

    # Create new application record linked to candidate
    app_row = await pool.fetchrow(
        """
        INSERT INTO ats.applications
        (vacancy_id, candidate_id, candidate_name, candidate_phone, channel, qualified, is_test, status)
        VALUES ($1, $2, $3, $4, $5, false, $6, 'active')
        RETURNING id
        """,
        vacancy_uuid,
        candidate_id,
        candidate_name,
        phone_normalized,
        request.channel.value,
        request.is_test
    )
    application_id = app_row["id"]
    logger.info(f"📝 Created application {application_id} with status=active (is_test={request.is_test})")

    # Log activity: screening started
    activity_service = ActivityService(pool)
    channel = ActivityChannel.VOICE if request.channel == InterviewChannel.VOICE else ActivityChannel.WHATSAPP
    await activity_service.log(
        candidate_id=str(candidate_id),
        event_type=ActivityEventType.SCREENING_STARTED,
        application_id=str(application_id),
        vacancy_id=str(vacancy_uuid),
        channel=channel,
        actor_type=ActorType.SYSTEM,
        summary=f"Pre-screening gestart via {request.channel.value}"
    )

    # Handle based on channel
    if request.channel == InterviewChannel.VOICE:
        response = await _initiate_voice_screening(
            pool=pool,
            phone=phone,
            first_name=request.first_name,
            candidate_name=candidate_name,
            vacancy_id=str(vacancy_uuid),
            vacancy_title=row["vacancy_title"],
            pre_screening_id=str(row["pre_screening_id"]),
            test_conversation_id=request.test_conversation_id,
            is_test=request.is_test,
        )
        response.application_id = str(application_id)
        return response
    else:  # WhatsApp
        response = await _initiate_whatsapp_screening(
            pool=pool,
            phone=phone,
            candidate_name=candidate_name,
            vacancy_id=str(vacancy_uuid),
            vacancy_title=row["vacancy_title"],
            pre_screening_id=str(row["pre_screening_id"]),
            whatsapp_agent_id=row["whatsapp_agent_id"],
            intro=row["intro"],
            is_test=request.is_test,
            twilio_client=twilio_client,
        )
        response.application_id = str(application_id)
        return response


async def _initiate_voice_screening(
    pool,
    phone: str,
    first_name: str,
    candidate_name: Optional[str],
    vacancy_id: str,
    vacancy_title: str,
    pre_screening_id: str,
    test_conversation_id: Optional[str] = None,
    is_test: bool = False,
) -> OutboundScreeningResponse:
    """Initiate a voice call screening using ElevenLabs master agent."""

    if not ELEVENLABS_AGENT_ID and not test_conversation_id:
        raise HTTPException(
            status_code=500,
            detail="ELEVENLABS_AGENT_ID not configured in environment"
        )

    try:
        # Normalize phone for database storage
        phone_normalized = phone.lstrip("+")

        # Note: Session cleanup is now handled by _clear_all_sessions_for_phone()
        # called at the start of initiate_outbound_screening()

        # Test mode: skip real call, use provided conversation_id
        if test_conversation_id:
            result = {
                "success": True,
                "message": "Test mode: call simulated",
                "conversation_id": test_conversation_id,
                "call_sid": f"TEST_{test_conversation_id}",
            }
            logger.info(f"TEST MODE: Simulated call with conversation_id={test_conversation_id}")
        else:
            # Initiate the call with the master voice agent
            # Pass first_name and IDs for webhook correlation
            result = initiate_outbound_call(
                to_number=phone,
                agent_id=ELEVENLABS_AGENT_ID,
                first_name=first_name,
                pre_screening_id=pre_screening_id,
                vacancy_id=vacancy_id,
            )

        if result.get("success"):
            # Create conversation record in database to track the call
            conv_row = await pool.fetchrow(
                """
                INSERT INTO ats.screening_conversations
                (vacancy_id, pre_screening_id, session_id, candidate_name, candidate_phone, channel, status, is_test)
                VALUES ($1, $2, $3, $4, $5, 'voice', 'active', $6)
                RETURNING id
                """,
                uuid.UUID(vacancy_id),
                uuid.UUID(pre_screening_id),
                result.get("conversation_id"),  # Use ElevenLabs conversation_id as session_id
                candidate_name,
                phone_normalized,
                is_test
            )
            logger.info(f"Voice screening initiated for vacancy {vacancy_id}, conversation {conv_row['id']}, elevenlabs_conversation_id={result.get('conversation_id')}, is_test={is_test}")

            # Application stays 'active' while call is in progress
            # Status will change to 'processing' when transcript analysis starts,
            # then 'completed' when analysis finishes
            logger.info(f"Voice call initiated, application remains status='active' for phone {phone_normalized}")

        return OutboundScreeningResponse(
            success=result["success"],
            message=result["message"],
            channel=InterviewChannel.VOICE,
            conversation_id=result.get("conversation_id"),
            call_sid=result.get("call_sid"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error initiating voice screening: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate call: {str(e)}")


async def _initiate_whatsapp_screening(
    pool,
    phone: str,
    candidate_name: Optional[str],
    vacancy_id: str,
    vacancy_title: str,
    pre_screening_id: str,
    whatsapp_agent_id: Optional[str],
    intro: Optional[str],
    is_test: bool = False,
    twilio_client = None,
) -> OutboundScreeningResponse:
    """Initiate a WhatsApp screening conversation."""
    global session_manager

    if not whatsapp_agent_id:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp agent not configured. Re-publish the pre-screening with enable_whatsapp=True"
        )

    if not TWILIO_WHATSAPP_NUMBER:
        raise HTTPException(status_code=500, detail="TWILIO_WHATSAPP_NUMBER not configured")

    try:
        # Normalize phone for session lookups
        phone_normalized = phone.lstrip("+")

        # Note: Session cleanup is now handled by _clear_all_sessions_for_phone()
        # called at the start of initiate_outbound_screening()

        # Get pre-screening questions to build the same agent as chat widget
        questions = await pool.fetch(
            """
            SELECT id, question_type, position, question_text, ideal_answer
            FROM ats.pre_screening_questions
            WHERE pre_screening_id = $1
            ORDER BY question_type, position
            """,
            uuid.UUID(pre_screening_id)
        )

        # Get pre-screening config
        ps_row = await pool.fetchrow(
            """
            SELECT intro, knockout_failed_action, final_action
            FROM ats.pre_screenings
            WHERE id = $1
            """,
            uuid.UUID(pre_screening_id)
        )

        # Build pre_screening dict (same format as chat widget)
        pre_screening = {
            "intro": ps_row["intro"],
            "knockout_failed_action": ps_row["knockout_failed_action"],
            "final_action": ps_row["final_action"],
            "knockout_questions": [q for q in questions if q["question_type"] == "knockout"],
            "qualification_questions": [q for q in questions if q["question_type"] == "qualification"],
        }

        # Get or create the same screening runner as chat widget uses
        runner = session_manager.get_or_create_screening_runner(vacancy_id, pre_screening, vacancy_title)

        # Generate a unique session ID for this conversation (like webchat does)
        adk_session_id = str(uuid.uuid4())
        logger.info(f"📱 Creating new WhatsApp session: {adk_session_id}")

        # Create fresh session for this conversation
        await session_manager.screening_session_service.create_session(
            app_name="screening_chat",
            user_id="whatsapp",
            session_id=adk_session_id
        )

        # Generate opening message using ADK agent (same as chat widget)
        name = candidate_name or "daar"
        trigger_message = f"START_SCREENING name={name}"
        content = types.Content(role="user", parts=[types.Part(text=trigger_message)])

        opening_message = ""
        async for event in runner.run_async(user_id="whatsapp", session_id=adk_session_id, new_message=content):
            if event.is_final_response() and event.content and event.content.parts:
                opening_message = event.content.parts[0].text

        if not opening_message:
            raise Exception("Agent did not generate opening message")

        # Send WhatsApp message via Twilio
        message = twilio_client.messages.create(
            body=opening_message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{phone}"
        )

        # Create conversation record in database (store the session_id for webhook lookups)
        conv_row = await pool.fetchrow(
            """
            INSERT INTO ats.screening_conversations
            (vacancy_id, pre_screening_id, session_id, candidate_name, candidate_phone, channel, status, is_test)
            VALUES ($1, $2, $3, $4, $5, 'whatsapp', 'active', $6)
            RETURNING id
            """,
            uuid.UUID(vacancy_id),
            uuid.UUID(pre_screening_id),
            adk_session_id,  # Store the unique session ID
            candidate_name,
            phone_normalized,
            is_test
        )

        conversation_id = conv_row["id"]

        # Store the opening message in conversation_messages table
        await pool.execute(
            """
            INSERT INTO ats.conversation_messages (conversation_id, role, message)
            VALUES ($1, 'agent', $2)
            """,
            conversation_id, opening_message
        )

        # Update message count
        await pool.execute(
            """
            UPDATE ats.screening_conversations
            SET message_count = 1, updated_at = NOW()
            WHERE id = $1
            """,
            conversation_id
        )

        logger.info(f"WhatsApp screening initiated for vacancy {vacancy_id}, conversation {conversation_id}, is_test={is_test}")

        return OutboundScreeningResponse(
            success=True,
            message="WhatsApp screening initiated",
            channel=InterviewChannel.WHATSAPP,
            conversation_id=str(conversation_id),
            whatsapp_message_sid=message.sid,
        )
    except Exception as e:
        logger.error(f"Error initiating WhatsApp screening: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send WhatsApp message: {str(e)}")
