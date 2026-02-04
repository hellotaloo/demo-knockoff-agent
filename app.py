import os
import json
import logging
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from datetime import datetime
from enum import Enum
import asyncpg
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.adk.events import Event, EventActions
from google.genai import types
import time
from knockout_agent.agent import build_screening_instruction, is_closing_message, clean_response_text, conversation_complete_tool
from interview_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
from candidate_simulator.agent import SimulationPersona, create_simulator_agent, run_simulation
from data_query_agent.agent import set_db_pool as set_data_query_db_pool
from recruiter_analyst.agent import root_agent as recruiter_analyst_agent
from fixtures import load_vacancies, load_applications, load_pre_screenings
from utils.random_candidate import generate_random_candidate
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from google.adk.agents.llm_agent import Agent

# Import configuration from centralized config module
from src.config import (
    DATABASE_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
    ELEVENLABS_WEBHOOK_SECRET,
    SIMPLE_EDIT_KEYWORDS,
    SIMULATED_REASONING,
    logger
)

# Import models from centralized models module
from src.models import (
    VacancyStatus,
    VacancySource,
    InterviewChannel,
    ChannelsResponse,
    VacancyResponse,
    VacancyStatsResponse,
    DashboardStatsResponse,
    QuestionAnswerResponse,
    ApplicationResponse,
    CVApplicationRequest,
    PreScreeningQuestionRequest,
    PreScreeningQuestionResponse,
    PreScreeningRequest,
    PreScreeningResponse,
    PublishPreScreeningRequest,
    PublishPreScreeningResponse,
    StatusUpdateRequest,
    GenerateInterviewRequest,
    FeedbackRequest,
    ReorderRequest,
    DeleteQuestionRequest,
    AddQuestionRequest,
    RestoreSessionRequest,
    ScreeningChatRequest,
    SimulateInterviewRequest,
    ScreeningConversationResponse,
    OutboundScreeningRequest,
    OutboundScreeningResponse,
    ElevenLabsWebhookData,
    ElevenLabsWebhookPayload,
    CVQuestionRequest,
    CVAnalyzeRequest,
    CVQuestionAnalysisResponse,
    CVAnalyzeResponse,
    DataQueryRequest,
)

# Import database utilities
from src.database import get_db_pool, close_db_pool, run_schema_migrations


# ============================================================================
# Helper function for safe session event appending
# ============================================================================

async def safe_append_event(session_service, session, event, app_name: str, user_id: str, session_id: str):
    """
    Safely append an event to a session, handling stale session errors.
    
    If the session is stale (update_time mismatch), re-fetches the session and retries.
    If still failing, logs a warning and continues (the data is in our DB anyway).
    """
    try:
        await session_service.append_event(session, event)
    except ValueError as e:
        error_msg = str(e).lower()
        if "stale session" in error_msg or "last_update_time" in error_msg or "earlier than" in error_msg:
            logger.warning(f"Stale session detected for {session_id}, re-fetching: {e}")
            # Re-fetch fresh session and retry
            fresh_session = await session_service.get_session(
                app_name=app_name, user_id=user_id, session_id=session_id
            )
            if fresh_session:
                # Create new event with updated timestamp
                new_event = Event(
                    invocation_id=event.invocation_id + "_retry",
                    author=event.author,
                    actions=event.actions,
                    timestamp=time.time()
                )
                try:
                    await session_service.append_event(fresh_session, new_event)
                except ValueError:
                    # If still failing, log and continue
                    logger.warning(f"Could not update session state for {session_id}, continuing without it")
        else:
            raise


# ============================================================================
# Helper Functions
# ============================================================================

def build_vacancy_response(row) -> VacancyResponse:
    """
    Build a VacancyResponse model from a database row.

    Calculates effective channel states and is_online status based on
    published state and active channels.
    """
    # Calculate effective channel states
    voice_active = row["voice_enabled"] or False
    whatsapp_active = row["whatsapp_enabled"] or False
    cv_active = row["cv_enabled"] or False

    # is_online is only true if at least one channel is active
    any_channel_active = voice_active or whatsapp_active or cv_active
    effective_is_online = row["is_online"] and any_channel_active

    return VacancyResponse(
        id=str(row["id"]),
        title=row["title"],
        company=row["company"],
        location=row["location"],
        description=row["description"],
        status=row["status"],
        created_at=row["created_at"],
        archived_at=row["archived_at"],
        source=row["source"],
        source_id=row["source_id"],
        has_screening=row["has_screening"],
        is_online=effective_is_online,
        channels=ChannelsResponse(
            voice=voice_active,
            whatsapp=whatsapp_active,
            cv=cv_active
        ),
        candidates_count=row["candidates_count"],
        completed_count=row["completed_count"],
        qualified_count=row["qualified_count"],
        last_activity_at=row["last_activity_at"]
    )


# Global session service (legacy - kept for backward compatibility with existing sessions)
session_service = None

def create_session_service():
    """Create a new DatabaseSessionService instance."""
    global session_service
    # Disable statement cache for Supabase transaction-level pooling compatibility
    session_service = DatabaseSessionService(
        db_url=DATABASE_URL,
        connect_args={"statement_cache_size": 0}
    )
    logger.info("Created session service")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - create session services on startup."""
    create_session_service()
    create_interview_session_service()
    pool = await get_db_pool()  # Initialize database pool

    # Run schema migrations
    await run_schema_migrations(pool)

    # Initialize ADK session tables
    # The ADK library auto-creates tables on first use, but may show warnings
    # We suppress these by attempting a test session creation
    try:
        global interview_session_service
        # Try to create and delete a test session to initialize tables
        test_session = await interview_session_service.create_session(
            app_name="interview_generator",
            user_id="__init_test__",
            session_id="__init_test__"
        )
        await interview_session_service.delete_session(
            app_name="interview_generator",
            user_id="__init_test__",
            session_id="__init_test__"
        )
        logger.info("✓ ADK session tables initialized successfully")
    except ValueError as e:
        # Expected on first run - ADK will create tables automatically
        if "Schema version not found" in str(e) or "malformed" in str(e):
            logger.info("ADK session tables will be auto-created on first use")
        else:
            logger.warning(f"ADK session initialization: {e}")
    except Exception as e:
        logger.warning(f"ADK session initialization (non-fatal): {e}")

    # Set up data query agent with db pool (used by recruiter analyst sub-agent)
    set_data_query_db_pool(pool)
    create_analyst_session_service()
    create_screening_session_service()  # Screening chat sessions
    yield
    # Cleanup on shutdown
    await close_db_pool()

app = FastAPI(lifespan=lifespan)

# CORS middleware for cross-origin requests from job board
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Twilio client for proactive messages
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


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
    from transcript_processor import process_transcript
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
    global screening_session_service
    
    # Get or create the same screening runner as was used for outbound
    runner = get_or_create_screening_runner(vacancy_id, pre_screening, vacancy_title)
    
    # CRITICAL: Verify session exists before running agent
    # The session should have been created during _initiate_whatsapp_screening
    # If it doesn't exist (e.g., DB connection issue), the agent would start fresh without history
    async def verify_or_create_session():
        session = await screening_session_service.get_session(
            app_name="screening_chat",
            user_id="whatsapp",
            session_id=session_id
        )
        if not session:
            logger.warning(f"⚠️ Session not found for session_id={session_id}, creating new one (history may be lost!)")
            try:
                await screening_session_service.create_session(
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
        create_screening_session_service()
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


@app.post("/webhook")
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
        create_session_service()
        create_screening_session_service()
        # Retry with generic agent on connection error
        response_text = await _webhook_impl_generic(phone_normalized, incoming_msg)
    
    # Send TwiML response
    resp = MessagingResponse()
    resp.message(response_text or "Sorry, I couldn't process that.")
    return PlainTextResponse(content=str(resp), media_type="application/xml")

# ============================================================================
# Interview Generator API (SSE streaming)
# ============================================================================

# Use DatabaseSessionService for persistence (shares connection with knockout_agent)
interview_session_service = None
interview_runner = None  # Full thinking agent for initial generation
interview_editor_runner = None  # Fast agent for simple edits

def get_interview_from_session(session) -> dict:
    """
    Safely get the interview dict from session state.
    Handles both dict and JSON string storage formats.
    """
    if not session:
        return {}
    
    interview = session.state.get("interview", {})
    
    # Handle case where interview is stored as JSON string
    if isinstance(interview, str):
        try:
            interview = json.loads(interview)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    return interview if isinstance(interview, dict) else {}


def get_questions_snapshot(interview: dict) -> str:
    """
    Create a snapshot of questions for comparison.
    Returns a string representation of questions (ignoring change_status).
    """
    if not interview:
        return ""
    
    ko = interview.get("knockout_questions", [])
    qual = interview.get("qualification_questions", [])
    
    # Create snapshot without change_status
    ko_snap = [(q.get("id"), q.get("question")) for q in ko]
    qual_snap = [(q.get("id"), q.get("question"), q.get("ideal_answer")) for q in qual]
    
    return str((ko_snap, qual_snap))


def reset_change_statuses(interview: dict) -> dict:
    """
    Reset all change_status values to 'unchanged'.
    Used when the agent didn't modify the interview in this turn.
    """
    if not interview:
        return interview
    
    for q in interview.get("knockout_questions", []):
        q["change_status"] = "unchanged"
    
    for q in interview.get("qualification_questions", []):
        q["change_status"] = "unchanged"
    
    return interview


# Keywords that indicate simple edit operations (Dutch)
def should_use_fast_agent(session, message: str) -> bool:
    """
    Determine if we should use the fast editor agent (no thinking) 
    or the full generator agent (with thinking).
    
    Returns True for simple edits, False for complex operations.
    """
    # No interview yet = always use full generator
    interview = get_interview_from_session(session)
    if not interview.get("knockout_questions"):
        return False
    
    message_lower = message.lower()
    
    # Short message + interview exists = likely simple edit
    if len(message) < 150:
        return True
    
    # Check for edit keywords
    if any(keyword in message_lower for keyword in SIMPLE_EDIT_KEYWORDS):
        return True
    
    return False


def create_interview_session_service():
    """Create interview generator session service and runners."""
    global interview_session_service, interview_runner, interview_editor_runner
    # Disable statement cache for Supabase transaction-level pooling compatibility
    interview_session_service = DatabaseSessionService(
        db_url=DATABASE_URL,
        connect_args={"statement_cache_size": 0}
    )
    
    # Full thinking agent for initial generation
    interview_runner = Runner(
        agent=interview_agent, 
        app_name="interview_generator", 
        session_service=interview_session_service
    )
    
    # Fast agent for simple edits (no thinking)
    interview_editor_runner = Runner(
        agent=interview_editor_agent,
        app_name="interview_generator",  # Same app_name to share sessions
        session_service=interview_session_service
    )
    
    logger.info("Created interview generator session service with both runners (generator + editor)")


async def stream_interview_generation(vacancy_text: str, session_id: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during interview generation."""
    global interview_session_service, interview_runner
    
    total_start = time.time()
    print(f"\n{'='*60}")
    print(f"[GENERATE] Started - vacancy length: {len(vacancy_text)} chars")
    print(f"[GENERATE] Using: FAST generator (no thinking)")
    print(f"{'='*60}")
    
    async def reset_interview_session():
        """Delete and recreate session for fresh start, handling race conditions."""
        global interview_session_service
        # Try to delete existing session
        try:
            existing = await interview_session_service.get_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
            if existing:
                await interview_session_service.delete_session(
                    app_name="interview_generator", user_id="web", session_id=session_id
                )
        except Exception as e:
            logger.warning(f"Error checking/deleting existing session: {e}")
        
        # Create new session, handling case where it already exists
        try:
            await interview_session_service.create_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            )
        except IntegrityError:
            # Session exists (maybe delete failed or race condition), that's ok for generation
            logger.info(f"Session {session_id} already exists for generation")
    
    session_reset_start = time.time()
    try:
        await reset_interview_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
        await reset_interview_session()
    print(f"[TIMING] Session reset: {time.time() - session_reset_start:.2f}s")
    
    # Send initial status
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Vacature analyseren...'})}\n\n"
    
    # Run the agent
    content = types.Content(role="user", parts=[types.Part(text=vacancy_text)])
    
    # === TIMING: Agent processing ===
    agent_start = time.time()
    first_event_time = None
    event_count = 0
    agent_done = False
    
    # Collect agent events in a queue so we can interleave with simulated reasoning
    import asyncio
    event_queue: asyncio.Queue = asyncio.Queue()
    
    async def run_agent():
        """Run the agent and put events in queue."""
        nonlocal agent_done
        try:
            async for event in interview_runner.run_async(
                user_id="web",
                session_id=session_id,
                new_message=content
            ):
                await event_queue.put(("event", event))
        except Exception as e:
            await event_queue.put(("error", e))
        finally:
            agent_done = True
            await event_queue.put(("done", None))
    
    # Start agent in background
    agent_task = asyncio.create_task(run_agent())
    
    # Send simulated reasoning while waiting for agent
    reasoning_index = 0
    reasoning_interval = 1.5  # seconds between messages (~20s total for 13 messages)
    last_reasoning_time = time.time()
    
    try:
        while True:
            # Check if we should send simulated reasoning
            current_time = time.time()
            if (not agent_done and 
                reasoning_index < len(SIMULATED_REASONING) and 
                current_time - last_reasoning_time >= reasoning_interval):
                
                reasoning_msg = SIMULATED_REASONING[reasoning_index]
                yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning_msg})}\n\n"
                print(f"[SIMULATED #{reasoning_index + 1}] {reasoning_msg}")
                reasoning_index += 1
                last_reasoning_time = current_time
            
            # Try to get an event from the queue (non-blocking with timeout)
            try:
                event_type, event_data = await asyncio.wait_for(
                    event_queue.get(), 
                    timeout=0.1  # Check every 100ms
                )
            except asyncio.TimeoutError:
                continue
            
            if event_type == "done":
                break
            
            if event_type == "error":
                raise event_data
            
            # Process agent event
            event = event_data
            event_count += 1
            event_time = time.time() - agent_start
            
            if first_event_time is None:
                first_event_time = event_time
                print(f"[TIMING] First event received: {event_time:.2f}s (time to first response)")
            
            # Log event type
            evt_type = type(event).__name__
            has_content = hasattr(event, 'content') and event.content is not None
            is_final = event.is_final_response() if hasattr(event, 'is_final_response') else False
            print(f"[EVENT #{event_count}] {evt_type} at {event_time:.2f}s - has_content={has_content}, is_final={is_final}")
            
            # Check for tool calls
            if hasattr(event, 'tool_calls') and event.tool_calls:
                tool_names = [tc.name if hasattr(tc, 'name') else str(tc) for tc in event.tool_calls]
                print(f"[TIMING] Tool call at {event_time:.2f}s: {tool_names}")
                yield f"data: {json.dumps({'type': 'status', 'status': 'tool_call', 'message': 'Vragen genereren...'})}\n\n"
            
            # Final response
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                agent_total_time = time.time() - agent_start
                print(f"[TIMING] Agent total processing: {agent_total_time:.2f}s ({event_count} events)")
                
                # Get the interview from session state
                session_refetch_start = time.time()
                session = await interview_session_service.get_session(
                    app_name="interview_generator",
                    user_id="web",
                    session_id=session_id
                )
                print(f"[TIMING] Session refetch: {time.time() - session_refetch_start:.2f}s")
                
                interview = get_interview_from_session(session)
                
                total_time = time.time() - total_start
                print(f"[TIMING] === TOTAL GENERATION TIME: {total_time:.2f}s ===")
                
                yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'interview': interview, 'session_id': session_id})}\n\n"
    except Exception as e:
        logger.error(f"Error during interview generation: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        # Ensure agent task is cleaned up
        if not agent_task.done():
            agent_task.cancel()
    
    yield "data: [DONE]\n\n"


@app.post("/interview/generate")
async def generate_interview(request: GenerateInterviewRequest):
    """Generate interview questions from vacancy text with SSE streaming."""
    session_id = request.session_id or str(uuid.uuid4())
    
    return StreamingResponse(
        stream_interview_generation(request.vacancy_text, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# Per-session locks to prevent concurrent feedback processing
_feedback_locks: dict[str, asyncio.Lock] = {}


def get_feedback_lock(session_id: str) -> asyncio.Lock:
    """Get or create a lock for a specific session."""
    if session_id not in _feedback_locks:
        _feedback_locks[session_id] = asyncio.Lock()
    return _feedback_locks[session_id]


async def stream_feedback(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during feedback processing."""
    global interview_session_service, interview_runner, interview_editor_runner
    
    # Acquire per-session lock to prevent concurrent processing
    lock = get_feedback_lock(session_id)
    if lock.locked():
        print(f"[FEEDBACK] Session {session_id} already processing, rejecting duplicate request")
        yield f"data: {json.dumps({'type': 'error', 'message': 'Een verzoek wordt al verwerkt. Even geduld.'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    async with lock:
        total_start = time.time()
        print(f"\n{'='*60}")
        print(f"[FEEDBACK] Started - message: {message[:80]}...")
        print(f"{'='*60}")
        
        # === TIMING: Session fetch ===
        session_fetch_start = time.time()
        try:
            # Check if session exists
            session = await interview_session_service.get_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            )
        except (InterfaceError, OperationalError) as e:
            logger.warning(f"Database connection error, recreating interview session service: {e}")
            create_interview_session_service()
            session = await interview_session_service.get_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            )
        session_fetch_time = time.time() - session_fetch_start
        print(f"[TIMING] Session fetch: {session_fetch_time:.2f}s")
        
        if not session:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found. Please generate questions first.'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        
        # === TIMING: Agent selection ===
        use_fast = should_use_fast_agent(session, message)
        active_runner = interview_editor_runner if use_fast else interview_runner
        agent_type = "FAST editor (no thinking)" if use_fast else "FULL generator (with thinking)"
        
        # Log session history size
        history_count = len(session.events) if hasattr(session, 'events') else 0
        print(f"[AGENT] Using: {agent_type}")
        print(f"[AGENT] Message length: {len(message)} chars")
        print(f"[AGENT] Session history: {history_count} events")
        
        status_message = 'Feedback verwerken...' if use_fast else 'Feedback analyseren...'
        yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': status_message})}\n\n"
        
        # Include current interview state in the message so agent knows current order
        # This is needed because user may have reordered/deleted via direct endpoints
        current_interview = get_interview_from_session(session)
        
        # Snapshot for comparison - to detect if agent made changes
        interview_snapshot_before = get_questions_snapshot(current_interview)
        
        if current_interview:
            # Build context with FULL interview structure so model knows actual question texts
            # Format questions for readability (include ideal_answer for qualification questions)
            ko_questions = current_interview.get("knockout_questions", [])
            qual_questions = current_interview.get("qualification_questions", [])
            
            ko_formatted = "\n".join([f'  - {q["id"]}: "{q["question"]}"' for q in ko_questions])
            # Include ideal_answer in the context so agent can preserve it
            qual_formatted = "\n".join([
                f'  - {q["id"]}: "{q["question"]}" (ideal_answer: "{q.get("ideal_answer", "")}")'
                for q in qual_questions
            ])
            
            state_context = f"""[SYSTEEM: Huidige interview structuur - BEHOUD alle vragen exact zoals ze zijn, tenzij de gebruiker expliciet vraagt om te wijzigen]

Huidige knockout vragen:
{ko_formatted}

Huidige kwalificatievragen (met ideal_answer):
{qual_formatted}

Andere velden:
- intro: "{current_interview.get('intro', '')}"
- knockout_failed_action: "{current_interview.get('knockout_failed_action', '')}"
- final_action: "{current_interview.get('final_action', '')}"
- approved_ids: {current_interview.get('approved_ids', [])}

Gebruiker: {message}"""
        else:
            state_context = message
        
        # Run agent with feedback (including state context)
        content = types.Content(role="user", parts=[types.Part(text=state_context)])
        
        # === TIMING: Agent processing ===
        agent_start = time.time()
        first_event_time = None
        tool_call_times = []
        event_count = 0
        
        try:
            async for event in active_runner.run_async(
                user_id="web",
                session_id=session_id,
                new_message=content
            ):
                event_count += 1
                event_time = time.time() - agent_start
                
                if first_event_time is None:
                    first_event_time = event_time
                    print(f"[TIMING] First event received: {event_time:.2f}s (time to first response)")
                
                # Log event type
                event_type = type(event).__name__
                has_content = hasattr(event, 'content') and event.content is not None
                is_final = event.is_final_response() if hasattr(event, 'is_final_response') else False
                print(f"[EVENT #{event_count}] {event_type} at {event_time:.2f}s - has_content={has_content}, is_final={is_final}")
                
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    tool_call_start = time.time()
                    tool_names = [tc.name if hasattr(tc, 'name') else str(tc) for tc in event.tool_calls]
                    print(f"[TIMING] Tool call at {event_time:.2f}s: {tool_names}")
                    yield f"data: {json.dumps({'type': 'status', 'status': 'tool_call', 'message': 'Vragen aanpassen...'})}\n\n"
                
                if event.is_final_response():
                    print(f"[FINAL] is_final_response=True, has_content={event.content is not None}")
                    if event.content:
                        print(f"[FINAL] content.parts count: {len(event.content.parts) if event.content.parts else 0}")
                    
                    try:
                        # Extract response text if available
                        response_text = ""
                        if event.content and event.content.parts:
                            response_text = event.content.parts[0].text if hasattr(event.content.parts[0], 'text') else str(event.content.parts[0])
                            print(f"[FINAL] response_text: {response_text[:100] if response_text else 'EMPTY'}...")
                        else:
                            # No text parts - agent completed silently after tool use
                            response_text = "Wijzigingen opgeslagen."
                            print(f"[FINAL] No content parts - using default message")
                        
                        agent_total_time = time.time() - agent_start
                        print(f"[TIMING] Agent total processing: {agent_total_time:.2f}s ({event_count} events)")
                        
                        # Get updated interview from session state
                        session_refetch_start = time.time()
                        session = await interview_session_service.get_session(
                            app_name="interview_generator",
                            user_id="web",
                            session_id=session_id
                        )
                        session_refetch_time = time.time() - session_refetch_start
                        print(f"[TIMING] Session refetch: {session_refetch_time:.2f}s")
                        
                        interview = get_interview_from_session(session)
                        print(f"[FINAL] interview retrieved: {interview is not None}")
                        
                        # Compare with snapshot to detect if agent made changes
                        interview_snapshot_after = get_questions_snapshot(interview)
                        if interview_snapshot_before == interview_snapshot_after:
                            # No changes made - reset all change_status to "unchanged"
                            print(f"[FINAL] No changes detected - resetting change_statuses")
                            interview = reset_change_statuses(interview)
                        else:
                            print(f"[FINAL] Changes detected - keeping change_statuses")
                        
                        total_time = time.time() - total_start
                        print(f"[TIMING] === TOTAL REQUEST TIME: {total_time:.2f}s ===")
                        
                        complete_data = json.dumps({'type': 'complete', 'message': response_text, 'interview': interview})
                        print(f"[FINAL] Yielding complete event, size: {len(complete_data)} bytes")
                        yield f"data: {complete_data}\n\n"
                        print(f"[FINAL] Complete event yielded successfully")
                    except Exception as inner_e:
                        print(f"[ERROR] Exception in final response processing: {inner_e}")
                        logger.error(f"Error processing final response: {inner_e}", exc_info=True)
                        yield f"data: {json.dumps({'type': 'error', 'message': f'Error processing response: {str(inner_e)}'})}\n\n"
        except Exception as e:
            logger.error(f"Error during feedback processing: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        
        yield "data: [DONE]\n\n"


@app.post("/interview/feedback")
async def process_feedback(request: FeedbackRequest):
    """Process feedback on generated questions with SSE streaming."""
    return StreamingResponse(
        stream_feedback(request.session_id, request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/interview/session/{session_id}")
async def get_interview_session(session_id: str):
    """Get the current interview state for a session."""
    global interview_session_service
    
    try:
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=session_id
        )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "interview": get_interview_from_session(session)
    }


@app.post("/interview/reorder")
async def reorder_questions(request: ReorderRequest):
    """Reorder questions without invoking the agent. Instant response."""
    global interview_session_service
    
    # Debug logging
    logger.info(f"[REORDER] Request received - session_id: {request.session_id}")
    logger.info(f"[REORDER] knockout_order: {request.knockout_order}")
    logger.info(f"[REORDER] qualification_order: {request.qualification_order}")
    
    try:
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    
    if not session:
        logger.warning(f"[REORDER] Session not found: {request.session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    interview = get_interview_from_session(session)
    if not interview:
        logger.warning(f"[REORDER] No interview in session: {request.session_id}")
        logger.warning(f"[REORDER] Session state keys: {list(session.state.keys())}")
        raise HTTPException(status_code=400, detail="No interview in session")
    
    # Log current question IDs for debugging
    ko_ids = [q.get("id") for q in interview.get("knockout_questions", [])]
    qual_ids = [q.get("id") for q in interview.get("qualification_questions", [])]
    logger.info(f"[REORDER] Current knockout IDs in session: {ko_ids}")
    logger.info(f"[REORDER] Current qualification IDs in session: {qual_ids}")
    
    # Reorder knockout questions
    if request.knockout_order:
        id_to_question = {q["id"]: q for q in interview.get("knockout_questions", [])}
        # Validate all IDs exist
        for qid in request.knockout_order:
            if qid not in id_to_question:
                logger.error(f"[REORDER] Unknown knockout ID '{qid}' - available IDs: {list(id_to_question.keys())}")
                raise HTTPException(status_code=400, detail=f"Unknown question ID: {qid}")
        interview["knockout_questions"] = [id_to_question[qid] for qid in request.knockout_order]
    
    # Reorder qualification questions
    if request.qualification_order:
        id_to_question = {q["id"]: q for q in interview.get("qualification_questions", [])}
        for qid in request.qualification_order:
            if qid not in id_to_question:
                logger.error(f"[REORDER] Unknown qualification ID '{qid}' - available IDs: {list(id_to_question.keys())}")
                raise HTTPException(status_code=400, detail=f"Unknown question ID: {qid}")
        interview["qualification_questions"] = [id_to_question[qid] for qid in request.qualification_order]
    
    # Update session state via append_event with state_delta
    state_delta = {"interview": interview}
    actions = EventActions(state_delta=state_delta)
    event = Event(
        invocation_id=f"reorder_{int(time.time())}",
        author="system",
        actions=actions,
        timestamp=time.time()
    )
    await safe_append_event(
        interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=request.session_id
    )
    
    return {"status": "success", "interview": interview}


@app.post("/interview/restore-session")
async def restore_session_from_db(request: RestoreSessionRequest):
    """
    Restore an interview session from saved pre-screening data.
    
    Use this when opening an existing pre-screening for editing.
    Creates a new session with the saved questions pre-populated,
    allowing the user to continue editing via /interview/feedback.
    """
    global interview_session_service
    
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {request.vacancy_id}")
    
    # Get pre-screening from database
    ps_row = await pool.fetchrow(
        """
        SELECT id, intro, knockout_failed_action, final_action
        FROM pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    
    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")
    
    pre_screening_id = ps_row["id"]
    
    # Get questions (including ideal_answer for qualification questions)
    question_rows = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer, is_approved
        FROM pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )
    
    # Build interview structure matching the agent's format
    knockout_questions = []
    qualification_questions = []
    approved_ids = []
    
    ko_counter = 1
    qual_counter = 1
    
    for q in question_rows:
        if q["question_type"] == "knockout":
            q_id = f"ko_{ko_counter}"
            ko_counter += 1
            knockout_questions.append({
                "id": q_id,
                "question": q["question_text"]
            })
        else:
            q_id = f"qual_{qual_counter}"
            qual_counter += 1
            qualification_questions.append({
                "id": q_id,
                "question": q["question_text"],
                "ideal_answer": q["ideal_answer"] or ""
            })
        
        if q["is_approved"]:
            approved_ids.append(q_id)
    
    interview = {
        "intro": ps_row["intro"] or "",
        "knockout_questions": knockout_questions,
        "knockout_failed_action": ps_row["knockout_failed_action"] or "",
        "qualification_questions": qualification_questions,
        "final_action": ps_row["final_action"] or "",
        "approved_ids": approved_ids
    }
    
    # Create or reuse session with vacancy_id as session_id for consistency
    session_id = request.vacancy_id
    
    async def get_or_create_feedback_session():
        """Helper to get existing session or create new one, handling race conditions."""
        global interview_session_service
        session = await interview_session_service.get_session(
            app_name="interview_generator", user_id="web", session_id=session_id
        )
        if session:
            return session
        try:
            return await interview_session_service.create_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
        except IntegrityError:
            # Session was created by another request, fetch it
            logger.info(f"Session {session_id} already exists, fetching it")
            return await interview_session_service.get_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
    
    try:
        session = await get_or_create_feedback_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
        session = await get_or_create_feedback_session()
    
    # Update session with current interview data (overwrites any stale state)
    state_delta = {"interview": interview}
    actions = EventActions(state_delta=state_delta)
    event = Event(
        invocation_id=f"restore_{int(time.time())}",
        author="system",
        actions=actions,
        timestamp=time.time()
    )
    await safe_append_event(
        interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=session_id
    )
    
    return {
        "status": "success",
        "session_id": session_id,
        "interview": interview,
        "message": "Session restored from saved pre-screening"
    }


@app.post("/interview/delete")
async def delete_question(request: DeleteQuestionRequest):
    """Delete a question without invoking the agent. Instant response."""
    global interview_session_service
    
    try:
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    interview = get_interview_from_session(session)
    if not interview:
        raise HTTPException(status_code=400, detail="No interview in session")
    
    question_id = request.question_id
    deleted = False
    
    # Check if it's a knockout question
    if question_id.startswith("ko_"):
        original_len = len(interview.get("knockout_questions", []))
        interview["knockout_questions"] = [
            q for q in interview.get("knockout_questions", []) if q["id"] != question_id
        ]
        deleted = len(interview["knockout_questions"]) < original_len
    
    # Check if it's a qualification question
    elif question_id.startswith("qual_"):
        original_len = len(interview.get("qualification_questions", []))
        interview["qualification_questions"] = [
            q for q in interview.get("qualification_questions", []) if q["id"] != question_id
        ]
        deleted = len(interview["qualification_questions"]) < original_len
    
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Question not found: {question_id}")
    
    # Also remove from approved_ids if present
    if question_id in interview.get("approved_ids", []):
        interview["approved_ids"] = [qid for qid in interview["approved_ids"] if qid != question_id]
    
    # Update session state via append_event with state_delta
    state_delta = {"interview": interview}
    actions = EventActions(state_delta=state_delta)
    event = Event(
        invocation_id=f"delete_{question_id}_{int(time.time())}",
        author="system",
        actions=actions,
        timestamp=time.time()
    )
    await safe_append_event(
        interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=request.session_id
    )
    
    return {"status": "success", "deleted": question_id, "interview": interview}


@app.post("/interview/add")
async def add_question(request: AddQuestionRequest):
    """Add a question without invoking the agent. Instant response."""
    global interview_session_service
    
    # Validate question type
    if request.question_type not in ("knockout", "qualification"):
        raise HTTPException(status_code=400, detail="question_type must be 'knockout' or 'qualification'")
    
    # Require ideal_answer for qualification questions
    if request.question_type == "qualification" and not request.ideal_answer:
        raise HTTPException(status_code=400, detail="ideal_answer is required for qualification questions")
    
    try:
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
        session = await interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    interview = get_interview_from_session(session)
    if not interview:
        raise HTTPException(status_code=400, detail="No interview in session")
    
    # Generate unique ID based on question type
    if request.question_type == "knockout":
        existing_ids = [q["id"] for q in interview.get("knockout_questions", [])]
        # Find next available ko_N
        n = 1
        while f"ko_{n}" in existing_ids:
            n += 1
        new_id = f"ko_{n}"
        
        new_question = {
            "id": new_id,
            "question": request.question,
            "change_status": "new"
        }
        interview.setdefault("knockout_questions", []).append(new_question)
    else:
        existing_ids = [q["id"] for q in interview.get("qualification_questions", [])]
        # Find next available qual_N
        n = 1
        while f"qual_{n}" in existing_ids:
            n += 1
        new_id = f"qual_{n}"
        
        new_question = {
            "id": new_id,
            "question": request.question,
            "ideal_answer": request.ideal_answer,
            "change_status": "new"
        }
        interview.setdefault("qualification_questions", []).append(new_question)
    
    # Update session state via append_event with state_delta
    state_delta = {"interview": interview}
    actions = EventActions(state_delta=state_delta)
    event = Event(
        invocation_id=f"add_{new_id}_{int(time.time())}",
        author="system",
        actions=actions,
        timestamp=time.time()
    )
    await safe_append_event(
        interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=request.session_id
    )
    
    return {"status": "success", "added": new_id, "question": new_question, "interview": interview}


# ============================================================================
# Recruiter Analyst Agent API (SSE streaming)
# ============================================================================

# Session service for recruiter analyst agent (multi-agent with data_query sub-agent)
analyst_session_service = None
analyst_runner = None


def create_analyst_session_service():
    """Create recruiter analyst session service and runner."""
    global analyst_session_service, analyst_runner
    # Disable statement cache for Supabase transaction-level pooling compatibility
    analyst_session_service = DatabaseSessionService(
        db_url=DATABASE_URL,
        connect_args={"statement_cache_size": 0}
    )
    analyst_runner = Runner(
        agent=recruiter_analyst_agent,
        app_name="recruiter_analyst",
        session_service=analyst_session_service
    )
    logger.info("Created recruiter analyst session service and runner")


async def stream_analyst_query(question: str, session_id: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during analyst query processing."""
    global analyst_session_service, analyst_runner
    
    async def get_or_create_analyst_session():
        """Helper to get existing session or create new one, handling race conditions."""
        global analyst_session_service
        existing = await analyst_session_service.get_session(
            app_name="recruiter_analyst", user_id="web", session_id=session_id
        )
        if existing:
            return
        try:
            await analyst_session_service.create_session(
                app_name="recruiter_analyst",
                user_id="web",
                session_id=session_id
            )
        except IntegrityError:
            # Session was created by another request, that's fine
            logger.info(f"Analyst session {session_id} already exists")
    
    try:
        await get_or_create_analyst_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating analyst session service: {e}")
        create_analyst_session_service()
        await get_or_create_analyst_session()
    
    # Send initial status
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Vraag analyseren...'})}\n\n"
    
    # Run the agent
    content = types.Content(role="user", parts=[types.Part(text=question)])
    
    try:
        async for event in analyst_runner.run_async(
            user_id="web",
            session_id=session_id,
            new_message=content
        ):
            # Check for tool calls or sub-agent delegation
            if hasattr(event, 'tool_calls') and event.tool_calls:
                yield f"data: {json.dumps({'type': 'status', 'status': 'tool_call', 'message': 'Data ophalen...'})}\n\n"
            
            # Check for thinking/reasoning content
            if hasattr(event, 'content') and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'thought') and part.thought:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': part.text})}\n\n"
            
            # Final response
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'session_id': session_id})}\n\n"
    except Exception as e:
        logger.error(f"Error during analyst query: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    yield "data: [DONE]\n\n"


@app.post("/data-query")
async def analyst_query(request: DataQueryRequest):
    """Query the recruiter analyst using natural language with SSE streaming."""
    session_id = request.session_id or str(uuid.uuid4())
    
    return StreamingResponse(
        stream_analyst_query(request.question, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/data-query/session/{session_id}")
async def get_analyst_session(session_id: str):
    """Get the current session state for an analyst session."""
    global analyst_session_service
    
    try:
        session = await analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating analyst session service: {e}")
        create_analyst_session_service()
        session = await analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "state": session.state
    }


@app.delete("/data-query/session/{session_id}")
async def delete_analyst_session(session_id: str):
    """Delete an analyst session to start fresh."""
    global analyst_session_service
    
    try:
        session = await analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating analyst session service: {e}")
        create_analyst_session_service()
        session = await analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await analyst_session_service.delete_session(
        app_name="recruiter_analyst",
        user_id="web",
        session_id=session_id
    )
    
    return {"status": "success", "message": "Session deleted"}


# ============================================================================
# Vacancies & Applications REST API
# ============================================================================

@app.get("/vacancies")
async def list_vacancies(
    status: Optional[str] = Query(None, description="Filter by status"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List all vacancies with optional filtering."""
    from src.repositories import VacancyRepository

    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    rows, total = await repo.list_with_stats(status=status, source=source, limit=limit, offset=offset)
    vacancies = [build_vacancy_response(row) for row in rows]

    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/vacancies/{vacancy_id}")
async def get_vacancy(vacancy_id: str):
    """Get a single vacancy by ID."""
    from src.repositories import VacancyRepository

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    row = await repo.get_by_id(vacancy_uuid)

    if not row:
        raise HTTPException(status_code=404, detail="Vacancy not found")

    return build_vacancy_response(row)


@app.post("/vacancies/{vacancy_id}/cv-application")
async def create_cv_application(vacancy_id: str, request: CVApplicationRequest):
    """
    Create an application from a CV PDF.
    
    Analyzes the CV against the vacancy's pre-screening questions,
    creates an application with pre-filled answers from the CV,
    and identifies which questions still need clarification.
    """
    from cv_analyzer import analyze_cv_base64
    
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    # Verify vacancy exists
    vacancy_row = await pool.fetchrow(
        "SELECT id, title FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_row:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    
    # Get pre-screening
    ps_row = await pool.fetchrow(
        """
        SELECT id, intro, knockout_failed_action, final_action
        FROM pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    
    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy. Configure interview questions first.")
    
    pre_screening_id = ps_row["id"]
    
    # Get questions
    question_rows = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )
    
    if not question_rows:
        raise HTTPException(status_code=400, detail="No interview questions configured for this vacancy")
    
    # Build question lists for CV analyzer
    knockout_questions = []
    qualification_questions = []
    ko_idx = 1
    qual_idx = 1
    
    for q in question_rows:
        if q["question_type"] == "knockout":
            knockout_questions.append({
                "id": f"ko_{ko_idx}",
                "question_text": q["question_text"]
            })
            ko_idx += 1
        else:
            qualification_questions.append({
                "id": f"qual_{qual_idx}",
                "question_text": q["question_text"],
                "ideal_answer": q["ideal_answer"] or ""
            })
            qual_idx += 1
    
    # Analyze CV
    logger.info(f"Analyzing CV for vacancy {vacancy_id} ({vacancy_row['title']})")
    try:
        result = await analyze_cv_base64(
            pdf_base64=request.pdf_base64,
            knockout_questions=knockout_questions,
            qualification_questions=qualification_questions,
        )
    except Exception as e:
        logger.error(f"CV analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"CV analysis failed: {str(e)}")
    
    # Determine if all knockout questions passed (have CV evidence)
    knockout_all_passed = all(ka.is_answered for ka in result.knockout_analysis)
    
    # Status and qualified are based on KNOCKOUT questions only
    # - If all knockouts passed → completed + qualified (can book meeting with recruiter)
    # - If any knockout needs clarification → active + not qualified (needs follow-up)
    # Qualification questions are extra info but don't block qualification
    application_status = 'completed' if knockout_all_passed else 'active'
    
    # Create application
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert application
            # Only set completed_at if status is 'completed'
            # qualified = true if all knockout questions passed
            if application_status == 'completed':
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     completed_at, summary, status, is_test)
                    VALUES ($1, $2, $3, 'cv', $4, NOW(), $5, $6, $7)
                    RETURNING id, started_at, completed_at
                    """,
                    vacancy_uuid,
                    request.candidate_name,
                    request.candidate_phone,
                    knockout_all_passed,  # True if all knockouts passed
                    result.cv_summary,
                    application_status,
                    True  # CV applications are always in test mode for now
                )
            else:
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     summary, status, is_test)
                    VALUES ($1, $2, $3, 'cv', $4, $5, $6, $7)
                    RETURNING id, started_at, completed_at
                    """,
                    vacancy_uuid,
                    request.candidate_name,
                    request.candidate_phone,
                    False,  # Not qualified - knockouts need clarification
                    result.cv_summary,
                    application_status,
                    True  # CV applications are always in test mode for now
                )
            application_id = app_row["id"]
            started_at = app_row["started_at"]
            
            logger.info(f"Created CV application {application_id} for {request.candidate_name} (is_test=True)")
            
            # Insert knockout answers
            # passed=true if CV provides evidence for the knockout question
            for ka in result.knockout_analysis:
                await conn.execute(
                    """
                    INSERT INTO application_answers
                    (application_id, question_id, question_text, answer, passed, source)
                    VALUES ($1, $2, $3, $4, $5, 'cv')
                    """,
                    application_id,
                    ka.id,
                    ka.question_text,
                    ka.cv_evidence if ka.is_answered else ka.clarification_needed,
                    ka.is_answered if ka.is_answered else None
                )
            
            # Insert qualification answers
            for qa in result.qualification_analysis:
                # If answered by CV, give a default score of 80
                score = 80 if qa.is_answered else None
                rating = "good" if qa.is_answered else None
                
                await conn.execute(
                    """
                    INSERT INTO application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, 'cv')
                    """,
                    application_id,
                    qa.id,
                    qa.question_text,
                    qa.cv_evidence if qa.is_answered else qa.clarification_needed,
                    score,
                    rating
                )
    
    # Build response
    answers = []
    
    # Add knockout answers
    # passed=true if CV provides evidence (knockout determines qualification)
    for ka in result.knockout_analysis:
        answers.append(QuestionAnswerResponse(
            question_id=ka.id,
            question_text=ka.question_text,
            question_type="knockout",
            answer=ka.cv_evidence if ka.is_answered else ka.clarification_needed,
            passed=ka.is_answered if ka.is_answered else None
        ))
    
    # Add qualification answers
    for qa in result.qualification_analysis:
        answers.append(QuestionAnswerResponse(
            question_id=qa.id,
            question_text=qa.question_text,
            question_type="qualification",
            answer=qa.cv_evidence if qa.is_answered else qa.clarification_needed,
            passed=None,
            score=80 if qa.is_answered else None,
            rating="good" if qa.is_answered else None
        ))
    
    # Count knockout questions passed (with CV evidence)
    knockout_passed = sum(1 for ka in result.knockout_analysis if ka.is_answered)
    knockout_total = len(result.knockout_analysis)
    
    # Generate meeting slots if qualified
    meeting_slots = None
    if knockout_all_passed:
        from knockout_agent.agent import get_next_business_days, get_dutch_date
        now = datetime.now()
        next_days = get_next_business_days(now, 2)
        meeting_slots = [
            get_dutch_date(next_days[0]) + " om 10:00",
            get_dutch_date(next_days[0]) + " om 14:00",
            get_dutch_date(next_days[1]) + " om 11:00",
        ]
    
    return ApplicationResponse(
        id=str(application_id),
        vacancy_id=vacancy_id,
        candidate_name=request.candidate_name,
        channel="cv",
        status=application_status,
        qualified=knockout_all_passed,  # Qualified if all knockouts passed
        started_at=app_row["started_at"],
        completed_at=app_row["completed_at"],
        interaction_seconds=0,
        answers=answers,
        synced=False,
        knockout_passed=knockout_passed,
        knockout_total=knockout_total,
        qualification_count=len(result.qualification_analysis),
        summary=result.cv_summary,
        meeting_slots=meeting_slots
    )


@app.get("/vacancies/{vacancy_id}/applications")
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
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    # Verify vacancy exists
    vacancy_exists = await pool.fetchval(
        "SELECT 1 FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_exists:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    
    # Build query with filters
    conditions = ["vacancy_id = $1"]
    params = [vacancy_uuid]
    param_idx = 2
    
    if qualified is not None:
        conditions.append(f"qualified = ${param_idx}")
        params.append(qualified)
        param_idx += 1
    
    if completed is not None:
        # Translate completed boolean to status filter for backwards compatibility
        if completed:
            conditions.append(f"status = 'completed'")
        else:
            conditions.append(f"status != 'completed'")
    
    if synced is not None:
        conditions.append(f"synced = ${param_idx}")
        params.append(synced)
        param_idx += 1
    
    if is_test is not None:
        conditions.append(f"is_test = ${param_idx}")
        params.append(is_test)
        param_idx += 1
    
    where_clause = f"WHERE {' AND '.join(conditions)}"
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM applications {where_clause}"
    total = await pool.fetchval(count_query, *params)
    
    # Get applications
    query = f"""
        SELECT id, vacancy_id, candidate_name, channel, status, qualified,
               started_at, completed_at, interaction_seconds, synced, synced_at, summary, interview_slot, is_test
        FROM applications
        {where_clause}
        ORDER BY started_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])
    
    rows = await pool.fetch(query, *params)
    
    # Fetch all pre-screening questions for this vacancy once
    questions_query = """
        SELECT psq.id, psq.question_type, psq.position, psq.question_text
        FROM pre_screening_questions psq
        JOIN pre_screenings ps ON ps.id = psq.pre_screening_id
        WHERE ps.vacancy_id = $1
        ORDER BY 
            CASE psq.question_type WHEN 'knockout' THEN 0 ELSE 1 END,
            psq.position
    """
    all_questions = await pool.fetch(questions_query, vacancy_uuid)
    
    # Fetch answers for each application
    applications = []
    for row in rows:
        answers_query = """
            SELECT question_id, question_text, answer, passed, score, rating, motivation
            FROM application_answers
            WHERE application_id = $1
            ORDER BY id
        """
        answer_rows = await pool.fetch(answers_query, row["id"])
        
        # Build a map of existing answers by question_id
        answer_map = {a["question_id"]: a for a in answer_rows}
        
        answers = []
        total_score = 0
        score_count = 0
        knockout_passed = 0
        knockout_total = 0
        qualification_count = 0
        
        # Process all questions, merging with answers where available
        for q in all_questions:
            q_id = str(q["id"])
            # Check both UUID format and ko_/qual_ prefix format
            existing_answer = answer_map.get(q_id)
            if not existing_answer:
                # Try legacy format (ko_1, qual_2, etc.)
                # Note: position in DB is 0-indexed, but ko_/qual_ IDs are 1-indexed
                if q["question_type"] == "knockout":
                    legacy_id = f"ko_{q['position'] + 1}"
                else:
                    legacy_id = f"qual_{q['position'] + 1}"
                existing_answer = answer_map.get(legacy_id)
            
            if existing_answer:
                answers.append(QuestionAnswerResponse(
                    question_id=existing_answer["question_id"],
                    question_text=existing_answer["question_text"],
                    question_type=q["question_type"],
                    answer=existing_answer["answer"],
                    passed=existing_answer["passed"],
                    score=existing_answer["score"],
                    rating=existing_answer["rating"],
                    motivation=existing_answer["motivation"]
                ))
                
                # Calculate stats
                if q["question_type"] == "knockout":
                    knockout_total += 1
                    if existing_answer["passed"]:
                        knockout_passed += 1
                else:
                    qualification_count += 1
                
                if existing_answer["score"] is not None:
                    total_score += existing_answer["score"]
                    score_count += 1
            else:
                # Question exists but no answer yet - include with null values
                answers.append(QuestionAnswerResponse(
                    question_id=q_id,
                    question_text=q["question_text"],
                    question_type=q["question_type"],
                    answer=None,
                    passed=None,
                    score=None,
                    rating=None,
                    motivation=None
                ))
                
                # Count knockout questions even if unanswered
                if q["question_type"] == "knockout":
                    knockout_total += 1
        
        # Calculate overall score as average
        overall_score = round(total_score / score_count) if score_count > 0 else None
        
        applications.append(ApplicationResponse(
            id=str(row["id"]),
            vacancy_id=str(row["vacancy_id"]),
            candidate_name=row["candidate_name"],
            channel=row["channel"],
            status=row["status"] or "completed",
            qualified=row["qualified"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            interaction_seconds=row["interaction_seconds"],
            answers=answers,
            synced=row["synced"],
            synced_at=row["synced_at"],
            overall_score=overall_score,
            knockout_passed=knockout_passed,
            knockout_total=knockout_total,
            qualification_count=qualification_count,
            summary=row["summary"],
            interview_slot=row["interview_slot"],
            is_test=row["is_test"] or False
        ))
    
    return {
        "applications": applications,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/applications/{application_id}")
async def get_application(application_id: str):
    """Get a single application by ID."""
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        application_uuid = uuid.UUID(application_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid application ID format: {application_id}")
    
    query = """
        SELECT id, vacancy_id, candidate_name, channel, status, qualified,
               started_at, completed_at, interaction_seconds, synced, synced_at, summary, interview_slot, is_test
        FROM applications
        WHERE id = $1
    """
    
    row = await pool.fetchrow(query, application_uuid)
    
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Fetch answers that exist
    answers_query = """
        SELECT question_id, question_text, answer, passed, score, rating, motivation
        FROM application_answers
        WHERE application_id = $1
        ORDER BY id
    """
    answer_rows = await pool.fetch(answers_query, row["id"])
    
    # Build a map of existing answers by question_id
    answer_map = {a["question_id"]: a for a in answer_rows}
    
    # Fetch all pre-screening questions for this vacancy to include unanswered questions
    questions_query = """
        SELECT psq.id, psq.question_type, psq.position, psq.question_text
        FROM pre_screening_questions psq
        JOIN pre_screenings ps ON ps.id = psq.pre_screening_id
        WHERE ps.vacancy_id = $1
        ORDER BY 
            CASE psq.question_type WHEN 'knockout' THEN 0 ELSE 1 END,
            psq.position
    """
    question_rows = await pool.fetch(questions_query, row["vacancy_id"])
    
    answers = []
    total_score = 0
    score_count = 0
    knockout_passed = 0
    knockout_total = 0
    qualification_count = 0
    
    # Process all questions, merging with answers where available
    for q in question_rows:
        q_id = str(q["id"])
        # Check both UUID format and ko_/qual_ prefix format
        existing_answer = answer_map.get(q_id)
        if not existing_answer:
            # Try legacy format (ko_1, qual_2, etc.)
            # Note: position in DB is 0-indexed, but ko_/qual_ IDs are 1-indexed
            if q["question_type"] == "knockout":
                legacy_id = f"ko_{q['position'] + 1}"
            else:
                legacy_id = f"qual_{q['position'] + 1}"
            existing_answer = answer_map.get(legacy_id)
        
        if existing_answer:
            answers.append(QuestionAnswerResponse(
                question_id=existing_answer["question_id"],
                question_text=existing_answer["question_text"],
                question_type=q["question_type"],
                answer=existing_answer["answer"],
                passed=existing_answer["passed"],
                score=existing_answer["score"],
                rating=existing_answer["rating"],
                motivation=existing_answer["motivation"]
            ))
            
            # Calculate stats
            if q["question_type"] == "knockout":
                knockout_total += 1
                if existing_answer["passed"]:
                    knockout_passed += 1
            else:
                qualification_count += 1
            
            if existing_answer["score"] is not None:
                total_score += existing_answer["score"]
                score_count += 1
        else:
            # Question exists but no answer yet - include with null values
            answers.append(QuestionAnswerResponse(
                question_id=q_id,
                question_text=q["question_text"],
                question_type=q["question_type"],
                answer=None,
                passed=None,
                score=None,
                rating=None,
                motivation=None
            ))
            
            # Count knockout questions even if unanswered
            if q["question_type"] == "knockout":
                knockout_total += 1
    
    # Calculate overall score as average
    overall_score = round(total_score / score_count) if score_count > 0 else None
    
    return ApplicationResponse(
        id=str(row["id"]),
        vacancy_id=str(row["vacancy_id"]),
        candidate_name=row["candidate_name"],
        channel=row["channel"],
        status=row["status"] or "completed",
        qualified=row["qualified"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        interaction_seconds=row["interaction_seconds"],
        answers=answers,
        synced=row["synced"],
        synced_at=row["synced_at"],
        overall_score=overall_score,
        knockout_passed=knockout_passed,
        knockout_total=knockout_total,
        qualification_count=qualification_count,
        summary=row["summary"],
        interview_slot=row["interview_slot"],
        is_test=row["is_test"] or False
    )


@app.post("/applications/reprocess-tests")
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
    from transcript_processor import process_transcript
    from datetime import datetime
    
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


@app.get("/vacancies/{vacancy_id}/stats")
async def get_vacancy_stats(vacancy_id: str):
    """Get aggregated statistics for a vacancy."""
    from src.repositories import VacancyRepository

    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")

    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    # Verify vacancy exists
    if not await repo.exists(vacancy_uuid):
        raise HTTPException(status_code=404, detail="Vacancy not found")

    # Get stats
    row = await repo.get_stats(vacancy_uuid)

    total = row["total"]
    completed_count = row["completed_count"]
    qualified_count = row["qualified_count"]

    # Calculate rates (avoid division by zero)
    completion_rate = int((completed_count / total * 100) if total > 0 else 0)
    qualification_rate = int((qualified_count / completed_count * 100) if completed_count > 0 else 0)

    return VacancyStatsResponse(
        vacancy_id=vacancy_id,
        total_applications=total,
        completed_count=completed_count,
        completion_rate=completion_rate,
        qualified_count=qualified_count,
        qualification_rate=qualification_rate,
        channel_breakdown={
            "voice": row["voice_count"],
            "whatsapp": row["whatsapp_count"]
        },
        avg_interaction_seconds=int(row["avg_seconds"]),
        last_application_at=row["last_application"]
    )


@app.get("/stats")
async def get_dashboard_stats():
    """Get dashboard-level aggregate statistics across all vacancies."""
    from src.repositories import VacancyRepository

    pool = await get_db_pool()
    repo = VacancyRepository(pool)

    row = await repo.get_dashboard_stats()

    total = row["total"]
    this_week = row["this_week"]
    completed_count = row["completed_count"]
    qualified_count = row["qualified_count"]

    # Calculate rates (avoid division by zero)
    completion_rate = int((completed_count / total * 100) if total > 0 else 0)
    qualification_rate = int((qualified_count / completed_count * 100) if completed_count > 0 else 0)

    return DashboardStatsResponse(
        total_prescreenings=total,
        total_prescreenings_this_week=this_week,
        completed_count=completed_count,
        completion_rate=completion_rate,
        qualified_count=qualified_count,
        qualification_rate=qualification_rate,
        channel_breakdown={
            "voice": row["voice_count"],
            "whatsapp": row["whatsapp_count"],
            "cv": row["cv_count"]
        }
    )


# ============================================================================
# Pre-Screening Configuration Endpoints
# ============================================================================

@app.put("/vacancies/{vacancy_id}/pre-screening")
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
    vacancy_exists = await pool.fetchval(
        "SELECT 1 FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_exists:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Check if pre-screening already exists for this vacancy
            existing_id = await conn.fetchval(
                "SELECT id FROM pre_screenings WHERE vacancy_id = $1",
                vacancy_uuid
            )
            
            if existing_id:
                # Update existing pre-screening
                await conn.execute(
                    """
                    UPDATE pre_screenings 
                    SET intro = $1, knockout_failed_action = $2, final_action = $3, 
                        status = 'active', updated_at = NOW()
                    WHERE id = $4
                    """,
                    config.intro, config.knockout_failed_action, config.final_action, existing_id
                )
                pre_screening_id = existing_id
                
                # Delete existing questions (will be replaced)
                await conn.execute(
                    "DELETE FROM pre_screening_questions WHERE pre_screening_id = $1",
                    pre_screening_id
                )
            else:
                # Create new pre-screening
                row = await conn.fetchrow(
                    """
                    INSERT INTO pre_screenings (vacancy_id, intro, knockout_failed_action, final_action, status)
                    VALUES ($1, $2, $3, $4, 'active')
                    RETURNING id
                    """,
                    vacancy_uuid, config.intro, config.knockout_failed_action, config.final_action
                )
                pre_screening_id = row["id"]
            
            # Insert knockout questions
            for position, q in enumerate(config.knockout_questions):
                is_approved = q.id in config.approved_ids
                await conn.execute(
                    """
                    INSERT INTO pre_screening_questions 
                    (pre_screening_id, question_type, position, question_text, is_approved)
                    VALUES ($1, 'knockout', $2, $3, $4)
                    """,
                    pre_screening_id, position, q.question, is_approved
                )
            
            # Insert qualification questions (with ideal_answer)
            for position, q in enumerate(config.qualification_questions):
                is_approved = q.id in config.approved_ids
                await conn.execute(
                    """
                    INSERT INTO pre_screening_questions 
                    (pre_screening_id, question_type, position, question_text, ideal_answer, is_approved)
                    VALUES ($1, 'qualification', $2, $3, $4, $5)
                    """,
                    pre_screening_id, position, q.question, q.ideal_answer, is_approved
                )
            
            # Update vacancy status
            await conn.execute(
                "UPDATE vacancies SET status = 'screening_active' WHERE id = $1",
                vacancy_uuid
            )
    
    # Invalidate cached screening runner so next chat uses updated questions
    if vacancy_id in screening_runners:
        del screening_runners[vacancy_id]
        logger.info(f"🔄 Cleared cached screening runner for vacancy {vacancy_id[:8]}...")
    
    return {
        "status": "success",
        "message": "Pre-screening configuration saved",
        "pre_screening_id": str(pre_screening_id),
        "vacancy_id": vacancy_id,
        "vacancy_status": "screening_active"
    }


@app.get("/vacancies/{vacancy_id}/pre-screening")
async def get_pre_screening(vacancy_id: str):
    """
    Get pre-screening configuration for a vacancy.
    
    Always creates/restores an interview session pre-populated with the saved
    questions, returning session_id and interview for use with /interview/feedback.
    """
    global interview_session_service
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    # Get pre-screening
    ps_row = await pool.fetchrow(
        """
        SELECT id, vacancy_id, intro, knockout_failed_action, final_action, status, 
               created_at, updated_at, published_at, is_online, elevenlabs_agent_id, whatsapp_agent_id
        FROM pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    
    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")
    
    pre_screening_id = ps_row["id"]
    
    # Get questions (including ideal_answer for qualification questions)
    question_rows = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer, is_approved
        FROM pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )
    
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
        global interview_session_service
        session = await interview_session_service.get_session(
            app_name="interview_generator", user_id="web", session_id=session_id
        )
        if session:
            return session
        try:
            return await interview_session_service.create_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
        except IntegrityError:
            # Session was created by another request, fetch it
            logger.info(f"Session {session_id} already exists, fetching it")
            return await interview_session_service.get_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
    
    try:
        session = await get_or_create_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        create_interview_session_service()
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
    await safe_append_event(
        interview_session_service, session, event,
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


@app.delete("/vacancies/{vacancy_id}/pre-screening")
async def delete_pre_screening(vacancy_id: str):
    """Delete pre-screening configuration for a vacancy. Resets status to 'new'."""
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    # Check if pre-screening exists
    pre_screening_id = await pool.fetchval(
        "SELECT id FROM pre_screenings WHERE vacancy_id = $1",
        vacancy_uuid
    )
    
    if not pre_screening_id:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete pre-screening (questions cascade automatically)
            await conn.execute(
                "DELETE FROM pre_screenings WHERE id = $1",
                pre_screening_id
            )
            
            # Reset vacancy status
            await conn.execute(
                "UPDATE vacancies SET status = 'new' WHERE id = $1",
                vacancy_uuid
            )
    
    # Invalidate cached screening runner
    if vacancy_id in screening_runners:
        del screening_runners[vacancy_id]
        logger.info(f"🔄 Cleared cached screening runner for vacancy {vacancy_id[:8]}...")
    
    return {
        "status": "success",
        "message": "Pre-screening configuration deleted",
        "vacancy_id": vacancy_id,
        "vacancy_status": "new"
    }


@app.post("/vacancies/{vacancy_id}/pre-screening/publish")
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
    vacancy_row = await pool.fetchrow(
        "SELECT title FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_row:
        raise HTTPException(status_code=404, detail=f"Vacancy not found: {vacancy_id}")
    
    vacancy_title = vacancy_row["title"]
    
    # Get pre-screening with questions and existing agent IDs
    ps_row = await pool.fetchrow(
        """
        SELECT id, vacancy_id, intro, knockout_failed_action, final_action, status,
               elevenlabs_agent_id, whatsapp_agent_id
        FROM pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    
    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")
    
    pre_screening_id = ps_row["id"]
    
    # Get questions
    question_rows = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer, is_approved
        FROM pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )
    
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
    
    await pool.execute(
        """
        UPDATE pre_screenings 
        SET published_at = $1, 
            elevenlabs_agent_id = $2, 
            whatsapp_agent_id = $3,
            is_online = TRUE,
            voice_enabled = $5,
            whatsapp_enabled = $6,
            cv_enabled = $7,
            updated_at = NOW()
        WHERE id = $4
        """,
        published_at, elevenlabs_agent_id, whatsapp_agent_id, pre_screening_id,
        request.enable_voice, request.enable_whatsapp, request.enable_cv
    )
    
    return {
        "status": "success",
        "published_at": published_at.isoformat(),
        "elevenlabs_agent_id": elevenlabs_agent_id,
        "whatsapp_agent_id": whatsapp_agent_id,
        "is_online": True,  # Publishing automatically sets online
        "message": "Pre-screening published and is now online"
    }


@app.patch("/vacancies/{vacancy_id}/pre-screening/status")
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
    vacancy_row = await pool.fetchrow(
        "SELECT title FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_row:
        raise HTTPException(status_code=404, detail=f"Vacancy not found: {vacancy_id}")
    
    vacancy_title = vacancy_row["title"]
    
    # Get pre-screening
    ps_row = await pool.fetchrow(
        """
        SELECT id, published_at, elevenlabs_agent_id, whatsapp_agent_id, is_online,
               voice_enabled, whatsapp_enabled, cv_enabled, intro, knockout_failed_action, final_action
        FROM pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    
    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")
    
    pre_screening_id = ps_row["id"]
    elevenlabs_agent_id = ps_row["elevenlabs_agent_id"]
    whatsapp_agent_id = ps_row["whatsapp_agent_id"]
    
    # If enabling voice and no agent exists, create one
    if request.voice_enabled and not elevenlabs_agent_id:
        # Build config for agent creation
        question_rows = await pool.fetch(
            """
            SELECT id, question_type, position, question_text, ideal_answer, is_approved
            FROM pre_screening_questions
            WHERE pre_screening_id = $1
            ORDER BY question_type, position
            """,
            pre_screening_id
        )
        
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
            await pool.execute(
                "UPDATE pre_screenings SET elevenlabs_agent_id = $1, updated_at = NOW() WHERE id = $2",
                elevenlabs_agent_id, pre_screening_id
            )
        except Exception as e:
            logger.error(f"Failed to create ElevenLabs agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create voice agent: {str(e)}")
    
    # If enabling WhatsApp and no agent exists, create one
    if request.whatsapp_enabled and not whatsapp_agent_id:
        # Build config for agent creation (reuse if already built above)
        if 'config' not in locals():
            question_rows = await pool.fetch(
                """
                SELECT id, question_type, position, question_text, ideal_answer, is_approved
                FROM pre_screening_questions
                WHERE pre_screening_id = $1
                ORDER BY question_type, position
                """,
                pre_screening_id
            )
            
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
            await pool.execute(
                "UPDATE pre_screenings SET whatsapp_agent_id = $1, updated_at = NOW() WHERE id = $2",
                whatsapp_agent_id, pre_screening_id
            )
        except Exception as e:
            logger.error(f"Failed to create WhatsApp agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create WhatsApp agent: {str(e)}")
    
    # Build dynamic update query based on provided fields
    updates = []
    params = []
    param_idx = 1
    
    if request.is_online is not None:
        # is_online requires published pre-screening
        if not ps_row["published_at"]:
            raise HTTPException(
                status_code=400, 
                detail="Pre-screening must be published before changing online status"
            )
        updates.append(f"is_online = ${param_idx}")
        params.append(request.is_online)
        param_idx += 1
    
    if request.voice_enabled is not None:
        updates.append(f"voice_enabled = ${param_idx}")
        params.append(request.voice_enabled)
        param_idx += 1
    
    if request.whatsapp_enabled is not None:
        updates.append(f"whatsapp_enabled = ${param_idx}")
        params.append(request.whatsapp_enabled)
        param_idx += 1
    
    if request.cv_enabled is not None:
        updates.append(f"cv_enabled = ${param_idx}")
        params.append(request.cv_enabled)
        param_idx += 1
    
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # Add updated_at and the WHERE clause parameter
    updates.append("updated_at = NOW()")
    params.append(ps_row["id"])
    
    # Execute update
    query = f"""
        UPDATE pre_screenings 
        SET {", ".join(updates)}
        WHERE id = ${param_idx}
    """
    await pool.execute(query, *params)
    
    # Fetch updated values
    updated_row = await pool.fetchrow(
        """
        SELECT is_online, voice_enabled, whatsapp_enabled, cv_enabled,
               elevenlabs_agent_id, whatsapp_agent_id
        FROM pre_screenings
        WHERE id = $1
        """,
        ps_row["id"]
    )
    
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
        await pool.execute(
            "UPDATE pre_screenings SET is_online = TRUE WHERE id = $1",
            ps_row["id"]
        )
        effective_is_online = True
        auto_status_message = " (auto-online: channel enabled)"
    
    # Auto-set is_online = FALSE if all channels are disabled
    elif all_channels_off and updated_row["is_online"]:
        await pool.execute(
            "UPDATE pre_screenings SET is_online = FALSE WHERE id = $1",
            ps_row["id"]
        )
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


# ============================================================================
# Screening Chat API (Dynamic agent with conversation saving)
# ============================================================================

# Session service for screening chat (separate from knockout agent)
screening_session_service = None
screening_runners: dict[str, Runner] = {}  # Cache runners by vacancy_id


def create_screening_session_service():
    """Create screening chat session service."""
    global screening_session_service
    # Disable statement cache for Supabase transaction-level pooling compatibility
    screening_session_service = DatabaseSessionService(
        db_url=DATABASE_URL,
        connect_args={"statement_cache_size": 0}
    )
    logger.info("Created screening chat session service")


def get_or_create_screening_runner(vacancy_id: str, pre_screening: dict, vacancy_title: str) -> Runner:
    """Get or create a screening runner for a specific vacancy."""
    global screening_session_service, screening_runners
    
    # Check cache
    if vacancy_id in screening_runners:
        logger.info(f"Using cached screening runner for vacancy {vacancy_id[:8]}")
        return screening_runners[vacancy_id]
    
    # Build dynamic instruction
    instruction = build_screening_instruction(pre_screening, vacancy_title)
    
    # Log the full system prompt
    logger.info("=" * 60)
    logger.info(f"📋 SCREENING AGENT CREATED: screening_{vacancy_id[:8]}")
    logger.info("=" * 60)
    logger.info("FULL SYSTEM PROMPT:")
    logger.info("=" * 60)
    for line in instruction.split('\n'):
        logger.info(line)
    logger.info("=" * 60)
    
    # Create agent with conversation_complete tool
    agent = Agent(
        name=f"screening_{vacancy_id[:8]}",
        model="gemini-2.5-flash",
        instruction=instruction,
        description=f"Screening agent for vacancy {vacancy_title}",
        tools=[conversation_complete_tool],
    )
    
    # Create runner
    runner = Runner(
        agent=agent,
        app_name="screening_chat",
        session_service=screening_session_service
    )
    
    # Cache it
    screening_runners[vacancy_id] = runner
    logger.info(f"✅ Screening runner ready: screening_{vacancy_id[:8]}")
    
    return runner


async def stream_screening_chat(
    vacancy_id: str, 
    message: str, 
    session_id: Optional[str],
    candidate_name: Optional[str],
    is_test: bool = False
) -> AsyncGenerator[str, None]:
    """Stream SSE events during screening chat."""
    global screening_session_service
    
    pool = await get_db_pool()
    
    # Validate vacancy UUID
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Invalid vacancy ID format'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    # Get vacancy
    vacancy = await pool.fetchrow(
        "SELECT id, title FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Vacancy not found'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    # Get pre-screening config
    ps_row = await pool.fetchrow(
        """
        SELECT id, intro, knockout_failed_action, final_action 
        FROM pre_screenings WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    if not ps_row:
        yield f"data: {json.dumps({'type': 'error', 'message': 'No pre-screening found for this vacancy'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    # Get questions
    questions = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        ps_row["id"]
    )
    
    pre_screening = {
        "intro": ps_row["intro"],
        "knockout_failed_action": ps_row["knockout_failed_action"],
        "final_action": ps_row["final_action"],
        "knockout_questions": [q for q in questions if q["question_type"] == "knockout"],
        "qualification_questions": [q for q in questions if q["question_type"] == "qualification"],
    }
    
    # Get or create runner
    runner = get_or_create_screening_runner(vacancy_id, pre_screening, vacancy["title"])
    
    # Handle new conversation vs continuation
    is_new_conversation = session_id is None or message.upper() == "START"
    
    if is_new_conversation:
        # Build and log the full system prompt for every new conversation
        full_system_prompt = build_screening_instruction(pre_screening, vacancy["title"])
        
        logger.info("=" * 60)
        logger.info("🎬 NEW SCREENING CONVERSATION STARTED")
        logger.info("=" * 60)
        logger.info(f"Vacancy: {vacancy['title']} ({vacancy_id[:8]}...)")
        logger.info("=" * 60)
        logger.info("📋 FULL SYSTEM PROMPT:")
        logger.info("=" * 60)
        for line in full_system_prompt.split('\n'):
            logger.info(line)
        logger.info("=" * 60)
        
        # Generate random candidate if name not provided
        if not candidate_name:
            random_candidate = generate_random_candidate()
            candidate_name = random_candidate.first_name
            candidate_email = random_candidate.email
            candidate_phone = random_candidate.phone
        else:
            candidate_email = None
            candidate_phone = None
        
        # Create new session ID
        session_id = str(uuid.uuid4())
        
        # Create session
        async def create_screening_session():
            try:
                await screening_session_service.create_session(
                    app_name="screening_chat",
                    user_id="web",
                    session_id=session_id
                )
            except IntegrityError:
                logger.info(f"Screening session {session_id} already exists")
        
        try:
            await create_screening_session()
        except (InterfaceError, OperationalError) as e:
            logger.warning(f"Database connection error, recreating screening session service: {e}")
            create_screening_session_service()
            await create_screening_session()
        
        # Web chat conversations are not saved (only outbound voice/whatsapp are saved)
        logger.info(f"💬 Web chat started for {candidate_name} (not saved to database)")
        
        # Log candidate and session info
        logger.info(f"👤 Candidate: {candidate_name}")
        logger.info(f"🔑 Session ID: {session_id}")
        logger.info("=" * 60)
        
        # Trigger screening start
        trigger_message = f"START_SCREENING name={candidate_name}"
    else:
        # Continuation - use provided candidate_name or default
        if not candidate_name:
            candidate_name = "Kandidaat"
        trigger_message = message
        logger.info(f"💬 Continuing conversation - Session: {session_id[:8]}...")
        logger.info(f"📩 User message: {message}")
    
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Antwoord genereren...'})}\n\n"
    
    # Run agent
    content = types.Content(role="user", parts=[types.Part(text=trigger_message)])
    
    try:
        response_text = ""
        tool_called = False
        completion_outcome = None
        
        async for event in runner.run_async(
            user_id="web",
            session_id=session_id,
            new_message=content
        ):
            # Check for conversation_complete tool call
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        if part.function_call.name == "conversation_complete":
                            tool_called = True
                            args = part.function_call.args or {}
                            completion_outcome = args.get("outcome", "completed")
                            logger.info(f"🏁 conversation_complete tool called in chat: {completion_outcome}")
                    
                    if hasattr(part, 'text') and part.text and event.is_final_response():
                        response_text = clean_response_text(part.text)
        
        if response_text:
            logger.info(f"🤖 Agent response: {response_text[:100]}..." if len(response_text) > 100 else f"🤖 Agent response: {response_text}")
            
            # Check for completion (tool call or closing pattern)
            is_complete = tool_called
            if not tool_called and is_closing_message(response_text):
                is_complete = True
                logger.info(f"🏁 Closing pattern detected in chat response")
            
            yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'session_id': session_id, 'candidate_name': candidate_name, 'is_complete': is_complete})}\n\n"
    except Exception as e:
        logger.error(f"Error during screening chat: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    yield "data: [DONE]\n\n"


@app.post("/screening/chat")
async def screening_chat(request: ScreeningChatRequest):
    """
    Chat with the screening agent for a specific vacancy.
    
    For new conversations:
    - Send message="START" 
    - Optionally provide candidate_name, otherwise a random one is generated
    
    For continuing conversations:
    - Include session_id from previous response
    """
    # Initialize session service if needed
    global screening_session_service
    if screening_session_service is None:
        create_screening_session_service()
    
    return StreamingResponse(
        stream_screening_chat(
            request.vacancy_id,
            request.message,
            request.session_id,
            request.candidate_name,
            request.is_test
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# =============================================================================
# Interview Simulation (Auto-Tester)
# =============================================================================

async def stream_interview_simulation(
    vacancy_id: str,
    persona: str,
    custom_persona: Optional[str],
    candidate_name: str
) -> AsyncGenerator[str, None]:
    """
    Stream SSE events during an interview simulation.
    
    This runs two agents against each other:
    1. Screening agent (interviewer)
    2. Candidate simulator (simulated candidate)
    """
    pool = await get_db_pool()
    
    # Validate vacancy exists
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Invalid vacancy ID: {vacancy_id}'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    vacancy = await pool.fetchrow(
        "SELECT id, title FROM vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Vacancy not found'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    vacancy_title = vacancy["title"]
    
    # Get pre-screening config
    pre_screening = await pool.fetchrow(
        "SELECT * FROM pre_screenings WHERE vacancy_id = $1",
        vacancy_uuid
    )
    if not pre_screening:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Pre-screening not configured for this vacancy'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    # Build pre-screening config dict
    questions = await pool.fetch(
        """SELECT id, question_type, question_text, ideal_answer, position 
           FROM pre_screening_questions 
           WHERE pre_screening_id = $1 
           ORDER BY question_type DESC, position ASC""",
        pre_screening["id"]
    )
    
    config = {
        "intro": pre_screening["intro"],
        "knockout_failed_action": pre_screening["knockout_failed_action"],
        "final_action": pre_screening["final_action"],
        "knockout_questions": [],
        "qualification_questions": []
    }
    
    for q in questions:
        q_dict = {
            "id": str(q["id"]),
            "question_text": q["question_text"],
            "ideal_answer": q["ideal_answer"]
        }
        if q["question_type"] == "knockout":
            config["knockout_questions"].append(q_dict)
        else:
            config["qualification_questions"].append(q_dict)
    
    # Validate and convert persona
    try:
        persona_enum = SimulationPersona(persona)
    except ValueError:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Invalid persona: {persona}. Valid options: qualified, borderline, unqualified, rushed, enthusiastic, custom'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    # Create simulator agent
    simulator_agent = create_simulator_agent(
        config=config,
        persona=persona_enum,
        custom_persona=custom_persona,
        vacancy_title=vacancy_title
    )
    
    # Create a FRESH screening agent for simulation (not cached)
    # This ensures no state leakage from real conversations
    screening_instruction = build_screening_instruction(config, vacancy_title)
    screening_agent = Agent(
        name=f"sim_screening_{vacancy_id[:8]}",
        model="gemini-2.5-flash",
        instruction=screening_instruction,
        description=f"Simulation screening agent for vacancy {vacancy_title}",
        tools=[conversation_complete_tool],
    )
    
    logger.info(f"🎭 Created fresh screening agent for simulation: {vacancy_id[:8]}")
    
    # Track conversation for storage
    conversation = []
    qa_pairs = []
    outcome = "unknown"
    total_turns = 0
    
    yield f"data: {json.dumps({'type': 'start', 'message': f'Starting simulation with {persona} persona...', 'candidate_name': candidate_name})}\n\n"
    
    try:
        async for event in run_simulation(
            screening_agent=screening_agent,
            simulator_agent=simulator_agent,
            candidate_name=candidate_name,
            max_turns=20
        ):
            if event["type"] == "agent":
                conversation.append({
                    "role": "agent",
                    "message": event["message"],
                    "turn": event["turn"]
                })
                yield f"data: {json.dumps({'type': 'agent', 'message': event['message'], 'turn': event['turn']})}\n\n"
            
            elif event["type"] == "candidate":
                conversation.append({
                    "role": "candidate", 
                    "message": event["message"],
                    "turn": event["turn"]
                })
                yield f"data: {json.dumps({'type': 'candidate', 'message': event['message'], 'turn': event['turn']})}\n\n"
            
            elif event["type"] == "qa_pair":
                qa_pairs.append(event["data"])
            
            elif event["type"] == "complete":
                outcome = event["outcome"]
                total_turns = event["total_turns"]
                qa_pairs = event["qa_pairs"]
        
        # No database storage needed - simulations are just for live testing
        yield f"data: {json.dumps({'type': 'complete', 'outcome': outcome, 'qa_pairs': qa_pairs, 'total_turns': total_turns})}\n\n"
        
        logger.info(f"✅ Simulation completed: {persona} persona, {total_turns} turns, outcome: {outcome}")
        
    except Exception as e:
        logger.error(f"Error during simulation: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    yield "data: [DONE]\n\n"


@app.post("/vacancies/{vacancy_id}/simulate")
async def simulate_interview(vacancy_id: str, request: SimulateInterviewRequest):
    """
    Run an automated interview simulation for testing.
    
    This creates a simulated conversation between the screening agent and
    a candidate simulator with the specified persona.
    
    Personas:
    - qualified: Ideal candidate who passes all questions
    - borderline: Uncertain candidate who asks clarifications
    - unqualified: Candidate who fails knockout questions
    - rushed: Short answers, seems busy
    - enthusiastic: Very eager, detailed answers
    - custom: Provide your own persona in custom_persona field
    
    Returns SSE stream with conversation events.
    """
    # Generate random name if not provided
    candidate_name = request.candidate_name
    if not candidate_name:
        candidate = generate_random_candidate()
        candidate_name = candidate["name"]
    
    return StreamingResponse(
        stream_interview_simulation(
            vacancy_id=vacancy_id,
            persona=request.persona,
            custom_persona=request.custom_persona,
            candidate_name=candidate_name
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/vacancies/{vacancy_id}/conversations")
async def list_screening_conversations(
    vacancy_id: str,
    status: Optional[str] = Query(None, description="Filter by status: active, completed, abandoned"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List all screening conversations for a vacancy."""
    pool = await get_db_pool()
    
    # Validate UUID
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    # Build query
    conditions = ["vacancy_id = $1"]
    params = [vacancy_uuid]
    param_idx = 2
    
    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1
    
    where_clause = " AND ".join(conditions)
    
    # Get total count
    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM screening_conversations WHERE {where_clause}",
        *params
    )
    
    # Get conversations
    query = f"""
        SELECT id, vacancy_id, candidate_name, candidate_email, status, 
               started_at, completed_at, message_count
        FROM screening_conversations
        WHERE {where_clause}
        ORDER BY started_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])
    
    rows = await pool.fetch(query, *params)
    
    conversations = [
        ScreeningConversationResponse(
            id=str(row["id"]),
            vacancy_id=str(row["vacancy_id"]),
            candidate_name=row["candidate_name"],
            candidate_email=row["candidate_email"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            message_count=row["message_count"]
        )
        for row in rows
    ]
    
    return {
        "conversations": conversations,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/screening/conversations/{conversation_id}")
async def get_screening_conversation(conversation_id: str):
    """Get a single conversation with its messages."""
    pool = await get_db_pool()
    
    # Validate UUID
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid conversation ID format: {conversation_id}")
    
    # Get conversation
    conv = await pool.fetchrow(
        """
        SELECT id, vacancy_id, pre_screening_id, session_id, candidate_name, 
               candidate_email, candidate_phone, status, started_at, completed_at, 
               message_count, channel, is_test
        FROM screening_conversations
        WHERE id = $1
        """,
        conv_uuid
    )
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Try to get messages from conversation_messages table first (new approach)
    messages = []
    stored_messages = await pool.fetch(
        """
        SELECT role, message, created_at
        FROM conversation_messages
        WHERE conversation_id = $1
        ORDER BY created_at ASC
        """,
        conv_uuid
    )
    
    if stored_messages:
        # Use messages from our table
        for msg in stored_messages:
            messages.append({
                "role": msg["role"],
                "content": msg["message"],
                "timestamp": msg["created_at"].isoformat() if msg["created_at"] else None
            })
    else:
        # Fallback: Get messages from ADK events table (legacy)
        events = await pool.fetch(
            """
            SELECT event_data, timestamp
            FROM events
            WHERE app_name = 'screening_chat' AND session_id = $1
            ORDER BY timestamp ASC
            """,
            conv["session_id"]
        )
        
        for event in events:
            event_data = event["event_data"]
            if isinstance(event_data, str):
                try:
                    event_data = json.loads(event_data)
                except:
                    continue
            
            # Extract message content from event
            if event_data and "content" in event_data:
                content = event_data["content"]
                if "parts" in content and content["parts"]:
                    text = content["parts"][0].get("text", "")
                    role = content.get("role", "unknown")
                    
                    # Skip system triggers
                    if text.startswith("START_SCREENING"):
                        continue
                    
                    messages.append({
                        "role": "agent" if role == "model" else "user",
                        "content": text,
                        "timestamp": event["timestamp"].isoformat() if event["timestamp"] else None
                    })
    
    return {
        "id": str(conv["id"]),
        "vacancy_id": str(conv["vacancy_id"]),
        "session_id": conv["session_id"],
        "candidate": {
            "name": conv["candidate_name"],
            "email": conv["candidate_email"],
            "phone": conv["candidate_phone"]
        },
        "status": conv["status"],
        "channel": conv["channel"],
        "is_test": conv["is_test"] or False,
        "started_at": conv["started_at"],
        "completed_at": conv["completed_at"],
        "message_count": len(messages) if messages else conv["message_count"],
        "messages": messages
    }


@app.post("/screening/conversations/{conversation_id}/complete")
async def complete_screening_conversation(conversation_id: str, qualified: bool = Query(...)):
    """Mark a conversation as completed with qualification status."""
    pool = await get_db_pool()
    
    # Validate UUID
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid conversation ID format: {conversation_id}")
    
    # Get conversation
    conv = await pool.fetchrow(
        "SELECT id, vacancy_id, pre_screening_id, candidate_name, candidate_email FROM screening_conversations WHERE id = $1",
        conv_uuid
    )
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update conversation status
            await conn.execute(
                """
                UPDATE screening_conversations 
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE id = $1
                """,
                conv_uuid
            )
            
            # Create application record
            app_row = await conn.fetchrow(
                """
                INSERT INTO applications 
                (vacancy_id, pre_screening_id, candidate_name, channel, qualified, completed_at, status)
                VALUES ($1, $2, $3, 'whatsapp', $4, NOW(), 'completed')
                RETURNING id
                """,
                conv["vacancy_id"], conv["pre_screening_id"], conv["candidate_name"], qualified
            )
    
    return {
        "status": "success",
        "conversation_id": str(conv_uuid),
        "application_id": str(app_row["id"]),
        "qualified": qualified
    }


# ============================================================================
# Outbound Screening API (Voice & WhatsApp)
# ============================================================================

from voice_agent import initiate_outbound_call, create_or_update_voice_agent, list_voice_agents, delete_voice_agent
from knockout_agent.agent import create_vacancy_whatsapp_agent, get_vacancy_whatsapp_agent


@app.post("/screening/outbound", response_model=OutboundScreeningResponse)
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
    pool = await get_db_pool()
    
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
        FROM vacancies v
        LEFT JOIN pre_screenings ps ON ps.vacancy_id = v.id
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
    
    # Delete any existing applications for this phone/vacancy (and their related records)
    existing_apps = await pool.fetch(
        """
        SELECT id FROM applications 
        WHERE vacancy_id = $1 AND candidate_phone = $2
        """,
        vacancy_uuid,
        phone_normalized
    )
    
    if existing_apps:
        app_ids = [row["id"] for row in existing_apps]
        logger.info(f"🗑️ Deleting {len(app_ids)} existing application(s) for phone {phone_normalized}")
        
        # Delete related application_answers first (foreign key constraint)
        for app_id in app_ids:
            await pool.execute(
                "DELETE FROM application_answers WHERE application_id = $1",
                app_id
            )
        
        # Delete the applications
        await pool.execute(
            """
            DELETE FROM applications 
            WHERE vacancy_id = $1 AND candidate_phone = $2
            """,
            vacancy_uuid,
            phone_normalized
        )
    
    # Delete any existing screening_conversations for this phone/vacancy (and their messages)
    existing_convs = await pool.fetch(
        """
        SELECT id FROM screening_conversations 
        WHERE vacancy_id = $1 AND candidate_phone = $2
        """,
        vacancy_uuid,
        phone_normalized
    )
    
    if existing_convs:
        conv_ids = [row["id"] for row in existing_convs]
        logger.info(f"🗑️ Deleting {len(conv_ids)} existing conversation(s) for phone {phone_normalized}")
        
        # Delete related conversation_messages first
        for conv_id in conv_ids:
            await pool.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = $1",
                conv_id
            )
        
        # Delete the conversations
        await pool.execute(
            """
            DELETE FROM screening_conversations 
            WHERE vacancy_id = $1 AND candidate_phone = $2
            """,
            vacancy_uuid,
            phone_normalized
        )
    
    # Create new application record
    app_row = await pool.fetchrow(
        """
        INSERT INTO applications 
        (vacancy_id, candidate_name, candidate_phone, channel, qualified, is_test, status)
        VALUES ($1, $2, $3, $4, false, $5, 'active')
        RETURNING id
        """,
        vacancy_uuid,
        candidate_name,
        phone_normalized,
        request.channel.value,
        request.is_test
    )
    application_id = app_row["id"]
    logger.info(f"📝 Created application {application_id} with status=active (is_test={request.is_test})")
    
    # Handle based on channel
    if request.channel == InterviewChannel.VOICE:
        response = await _initiate_voice_screening(
            pool=pool,
            phone=phone,
            candidate_name=candidate_name,
            vacancy_id=str(vacancy_uuid),
            vacancy_title=row["vacancy_title"],
            pre_screening_id=str(row["pre_screening_id"]),
            elevenlabs_agent_id=row["elevenlabs_agent_id"],
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
        )
        response.application_id = str(application_id)
        return response


async def _initiate_voice_screening(
    pool,
    phone: str,
    candidate_name: Optional[str],
    vacancy_id: str,
    vacancy_title: str,
    pre_screening_id: str,
    elevenlabs_agent_id: Optional[str],
    test_conversation_id: Optional[str] = None,
    is_test: bool = False,
) -> OutboundScreeningResponse:
    """Initiate a voice call screening using ElevenLabs."""
    
    if not elevenlabs_agent_id and not test_conversation_id:
        raise HTTPException(
            status_code=400, 
            detail="Voice agent not configured. Re-publish the pre-screening with enable_voice=True"
        )
    
    try:
        # Normalize phone for database storage
        phone_normalized = phone.lstrip("+")
        
        # Abandon any existing active voice conversations for this phone number
        abandoned = await pool.execute(
            """
            UPDATE screening_conversations 
            SET status = 'abandoned'
            WHERE candidate_phone = $1 
            AND channel = 'voice' 
            AND status = 'active'
            """,
            phone_normalized
        )
        if abandoned != "UPDATE 0":
            logger.info(f"Abandoned previous voice conversations for phone {phone_normalized}: {abandoned}")
        
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
            # Initiate the call with the vacancy-specific agent
            # Note: candidate_name not passed - voice agent doesn't use names to avoid mispronunciation
            result = initiate_outbound_call(
                to_number=phone,
                agent_id=elevenlabs_agent_id,
            )
        
        if result.get("success"):
            # Create conversation record in database to track the call
            conv_row = await pool.fetchrow(
                """
                INSERT INTO screening_conversations 
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
) -> OutboundScreeningResponse:
    """Initiate a WhatsApp screening conversation."""
    
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
        
        # Abandon any existing active WhatsApp conversations for this phone number
        # This ensures the webhook will route to the correct new conversation
        abandoned = await pool.execute(
            """
            UPDATE screening_conversations 
            SET status = 'abandoned'
            WHERE candidate_phone = $1 
            AND channel = 'whatsapp' 
            AND status = 'active'
            """,
            phone_normalized
        )
        if abandoned != "UPDATE 0":
            logger.info(f"Abandoned previous WhatsApp conversations for phone {phone_normalized}: {abandoned}")
        
        # Get pre-screening questions to build the same agent as chat widget
        questions = await pool.fetch(
            """
            SELECT id, question_type, position, question_text, ideal_answer
            FROM pre_screening_questions
            WHERE pre_screening_id = $1
            ORDER BY question_type, position
            """,
            uuid.UUID(pre_screening_id)
        )
        
        # Get pre-screening config
        ps_row = await pool.fetchrow(
            """
            SELECT intro, knockout_failed_action, final_action
            FROM pre_screenings
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
        runner = get_or_create_screening_runner(vacancy_id, pre_screening, vacancy_title)
        
        # Generate a unique session ID for this conversation (like webchat does)
        adk_session_id = str(uuid.uuid4())
        logger.info(f"📱 Creating new WhatsApp session: {adk_session_id}")
        
        # Create fresh session for this conversation
        await screening_session_service.create_session(
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
            INSERT INTO screening_conversations 
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
            INSERT INTO conversation_messages (conversation_id, role, message)
            VALUES ($1, 'agent', $2)
            """,
            conversation_id, opening_message
        )
        
        # Update message count
        await pool.execute(
            """
            UPDATE screening_conversations 
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


# ============================================================================
# ElevenLabs Post-Call Webhook
# ============================================================================

import hmac
from hashlib import sha256
from transcript_processor import process_transcript

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


from fastapi import Request


@app.post("/webhook/elevenlabs")
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


# ============================================================================
# Demo Data Management (Seed & Reset)
# ============================================================================
# Demo data is loaded from fixtures/ directory - edit JSON files there


@app.post("/demo/seed")
async def seed_demo_data():
    """Populate the database with demo vacancies, applications, and pre-screenings."""
    pool = await get_db_pool()
    
    # Load fixtures from JSON files
    vacancies_data = load_vacancies()
    applications_data = load_applications()
    pre_screenings_data = load_pre_screenings()
    
    created_vacancies = []
    created_applications = []
    created_pre_screenings = []
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert vacancies
            for vac in vacancies_data:
                row = await conn.fetchrow("""
                    INSERT INTO vacancies (title, company, location, description, status, source, source_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                """, vac["title"], vac["company"], vac["location"], vac["description"], 
                    vac["status"], vac["source"], vac["source_id"])
                created_vacancies.append({"id": str(row["id"]), "title": vac["title"]})
            
            # Insert applications
            for app_data in applications_data:
                vacancy_id = uuid.UUID(created_vacancies[app_data["vacancy_idx"]]["id"])
                
                # Calculate completed_at if completed
                completed_at = None
                if app_data["completed"]:
                    # Use current time minus some offset for realism
                    from datetime import timedelta
                    completed_at = datetime.now() - timedelta(hours=len(created_applications) * 2)
                
                # Convert completed boolean to status
                status = 'completed' if app_data["completed"] else 'active'
                
                row = await conn.fetchrow("""
                    INSERT INTO applications 
                    (vacancy_id, candidate_name, channel, qualified, 
                     interaction_seconds, completed_at, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, started_at
                """, vacancy_id, app_data["candidate_name"], app_data["channel"],
                    app_data["qualified"], 
                    app_data["interaction_seconds"], completed_at, status)
                
                application_id = row["id"]
                
                # Insert answers
                for answer in app_data["answers"]:
                    await conn.execute("""
                        INSERT INTO application_answers 
                        (application_id, question_id, question_text, answer, passed)
                        VALUES ($1, $2, $3, $4, $5)
                    """, application_id, answer["question_id"], answer["question_text"],
                        answer["answer"], answer["passed"])
                
                created_applications.append({
                    "id": str(application_id),
                    "candidate": app_data["candidate_name"]
                })
            
            # Insert pre-screenings
            for ps_data in pre_screenings_data:
                vacancy_id = uuid.UUID(created_vacancies[ps_data["vacancy_idx"]]["id"])
                
                # Update vacancy status to match pre-screening status
                vacancy_status = "draft" if ps_data["status"] == "draft" else "screening_active"
                await conn.execute("""
                    UPDATE vacancies SET status = $1 WHERE id = $2
                """, vacancy_status, vacancy_id)
                
                # Use fixed ID if provided, otherwise auto-generate
                fixed_id = ps_data.get("id")
                if fixed_id:
                    pre_screening_id = uuid.UUID(fixed_id)
                    await conn.execute("""
                        INSERT INTO pre_screenings (id, vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, pre_screening_id, vacancy_id, ps_data["intro"], ps_data["knockout_failed_action"], 
                        ps_data["final_action"], ps_data["status"])
                else:
                    row = await conn.fetchrow("""
                        INSERT INTO pre_screenings (vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                    """, vacancy_id, ps_data["intro"], ps_data["knockout_failed_action"], 
                        ps_data["final_action"], ps_data["status"])
                    pre_screening_id = row["id"]
                
                # Insert knockout questions
                for position, q in enumerate(ps_data.get("knockout_questions", [])):
                    await conn.execute("""
                        INSERT INTO pre_screening_questions 
                        (pre_screening_id, question_type, position, question_text, is_approved)
                        VALUES ($1, $2, $3, $4, $5)
                    """, pre_screening_id, "knockout", position, q["question"], q.get("is_approved", False))
                
                # Insert qualification questions (with ideal_answer)
                for position, q in enumerate(ps_data.get("qualification_questions", [])):
                    await conn.execute("""
                        INSERT INTO pre_screening_questions 
                        (pre_screening_id, question_type, position, question_text, ideal_answer, is_approved)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, pre_screening_id, "qualification", position, q["question"], q.get("ideal_answer"), q.get("is_approved", False))
                
                created_pre_screenings.append({
                    "id": str(pre_screening_id),
                    "vacancy_id": str(vacancy_id),
                    "vacancy_title": created_vacancies[ps_data["vacancy_idx"]]["title"]
                })
    
    return {
        "status": "success",
        "message": f"Created {len(created_vacancies)} vacancies, {len(created_applications)} applications, {len(created_pre_screenings)} pre-screenings",
        "vacancies": created_vacancies,
        "applications_count": len(created_applications),
        "pre_screenings": created_pre_screenings
    }


@app.post("/demo/reset")
async def reset_demo_data(reseed: bool = Query(True, description="Reseed with demo data after reset")):
    """Clear all vacancies, applications, and pre-screenings, optionally reseed with demo data."""
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete in correct order respecting foreign key constraints
            await conn.execute("DELETE FROM screening_conversations")
            await conn.execute("DELETE FROM application_answers")
            await conn.execute("DELETE FROM applications")
            await conn.execute("DELETE FROM pre_screening_questions")
            await conn.execute("DELETE FROM pre_screenings")
            await conn.execute("DELETE FROM vacancies")
    
    # Clean up ElevenLabs voice agents (keep only the base agent)
    KEEP_AGENT_ID = "agent_2101kg9wn4xbefbrbet9p5fqnncn"
    deleted_agents = []
    failed_agents = []
    
    try:
        agents = list_voice_agents()
        for agent in agents:
            if agent["agent_id"] != KEEP_AGENT_ID:
                if delete_voice_agent(agent["agent_id"]):
                    deleted_agents.append(agent["agent_id"])
                else:
                    failed_agents.append(agent["agent_id"])
    except Exception as e:
        logger.warning(f"Failed to clean up ElevenLabs agents: {e}")
    
    result = {
        "status": "success",
        "message": "All demo data cleared",
        "elevenlabs_cleanup": {
            "deleted": len(deleted_agents),
            "failed": len(failed_agents),
            "kept": KEEP_AGENT_ID
        }
    }
    
    # Optionally reseed
    if reseed:
        seed_result = await seed_demo_data()
        result["message"] = "Demo data reset and reseeded"
        result["seed"] = seed_result
    
    return result


# ============================================================================
# CV Analyzer
# ============================================================================

@app.post("/cv/analyze", response_model=CVAnalyzeResponse)
async def analyze_cv_endpoint(request: CVAnalyzeRequest):
    """
    Analyze a PDF CV against interview questions.
    
    Takes a base64-encoded PDF and lists of knockout/qualification questions,
    returns analysis of what information is in the CV and what clarification
    questions need to be asked.
    """
    from cv_analyzer import analyze_cv_base64
    
    # Convert request questions to dict format
    knockout_questions = [
        {
            "id": q.id,
            "question_text": q.question,
        }
        for q in request.knockout_questions
    ]
    
    qualification_questions = [
        {
            "id": q.id,
            "question_text": q.question,
            "ideal_answer": q.ideal_answer or "",
        }
        for q in request.qualification_questions
    ]
    
    # Run the CV analyzer
    result = await analyze_cv_base64(
        pdf_base64=request.pdf_base64,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
    )
    
    # Convert to response format
    return CVAnalyzeResponse(
        knockout_analysis=[
            CVQuestionAnalysisResponse(
                id=qa.id,
                question_text=qa.question_text,
                cv_evidence=qa.cv_evidence,
                is_answered=qa.is_answered,
                clarification_needed=qa.clarification_needed,
            )
            for qa in result.knockout_analysis
        ],
        qualification_analysis=[
            CVQuestionAnalysisResponse(
                id=qa.id,
                question_text=qa.question_text,
                cv_evidence=qa.cv_evidence,
                is_answered=qa.is_answered,
                clarification_needed=qa.clarification_needed,
            )
            for qa in result.qualification_analysis
        ],
        cv_summary=result.cv_summary,
        clarification_questions=result.clarification_questions,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
