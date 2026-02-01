import os
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from datetime import datetime
from enum import Enum
from dotenv import load_dotenv
load_dotenv()  # Load .env file for local development

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
from knockout_agent.agent import root_agent, build_screening_instruction
from interview_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
from data_query_agent.agent import set_db_pool as set_data_query_db_pool
from recruiter_analyst.agent import root_agent as recruiter_analyst_agent
from fixtures import load_vacancies, load_applications, load_pre_screenings
from utils.random_candidate import generate_random_candidate
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from google.adk.agents.llm_agent import Agent

# Configure logging to show INFO level messages
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Use Supabase PostgreSQL for persistent session storage
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")


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
# Enums and Models for Vacancies/Applications API
# ============================================================================

class VacancyStatus(str, Enum):
    NEW = "new"
    DRAFT = "draft"
    SCREENING_ACTIVE = "screening_active"
    ARCHIVED = "archived"


class VacancySource(str, Enum):
    SALESFORCE = "salesforce"
    BULLHORN = "bullhorn"
    MANUAL = "manual"


class InterviewChannel(str, Enum):
    VOICE = "voice"
    WHATSAPP = "whatsapp"


class QuestionAnswerResponse(BaseModel):
    question_id: str
    question_text: str
    answer: Optional[str] = None
    passed: Optional[bool] = None
    score: Optional[int] = None  # 0-100
    rating: Optional[str] = None  # weak, below_average, average, good, excellent


class ChannelsResponse(BaseModel):
    voice: bool = False
    whatsapp: bool = False


class VacancyResponse(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str] = None
    description: Optional[str] = None
    status: str
    created_at: datetime
    archived_at: Optional[datetime] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    has_screening: bool = False  # True if pre-screening exists
    is_online: Optional[bool] = None  # None=draft/unpublished, True=online, False=offline
    channels: ChannelsResponse = ChannelsResponse()  # Voice/WhatsApp channel availability


class ApplicationResponse(BaseModel):
    id: str
    vacancy_id: str
    candidate_name: str
    channel: str
    completed: bool
    qualified: bool
    started_at: datetime
    completed_at: Optional[datetime] = None
    interaction_seconds: int
    answers: list[QuestionAnswerResponse] = []
    synced: bool
    synced_at: Optional[datetime] = None
    # Score summary
    overall_score: Optional[int] = None  # Average of all scores (0-100)
    knockout_passed: int = 0  # Number of knockout questions passed
    knockout_total: int = 0  # Total knockout questions
    qualification_count: int = 0  # Number of qualification questions answered
    summary: Optional[str] = None  # AI-generated executive summary
    interview_slot: Optional[str] = None  # Selected interview date/time, or "none_fit"


class VacancyStatsResponse(BaseModel):
    vacancy_id: str
    total_applications: int
    completed: int
    completion_rate: int
    qualified: int
    qualification_rate: int
    channel_breakdown: dict[str, int]
    avg_interaction_seconds: int
    last_application_at: Optional[datetime] = None


class PreScreeningQuestionRequest(BaseModel):
    """Request model for a pre-screening question."""
    id: str  # Client-provided ID (e.g., "ko_1", "qual_2")
    question: str
    ideal_answer: Optional[str] = None  # Scoring guidance for qualification questions


class PreScreeningQuestionResponse(BaseModel):
    """Response model for a pre-screening question."""
    id: str  # Database UUID
    question_type: str  # "knockout" or "qualification"
    position: int
    question_text: str
    ideal_answer: Optional[str] = None  # Scoring guidance for qualification questions
    is_approved: bool


class PreScreeningRequest(BaseModel):
    """Request model for saving pre-screening configuration."""
    intro: str
    knockout_questions: list[PreScreeningQuestionRequest]
    knockout_failed_action: str
    qualification_questions: list[PreScreeningQuestionRequest]
    final_action: str
    approved_ids: list[str] = []


class PreScreeningResponse(BaseModel):
    """Response model for pre-screening configuration."""
    id: str  # Pre-screening UUID
    vacancy_id: str
    intro: str
    knockout_questions: list[PreScreeningQuestionResponse]
    knockout_failed_action: str
    qualification_questions: list[PreScreeningQuestionResponse]
    final_action: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Publishing fields
    published_at: Optional[datetime] = None
    is_online: bool = False
    elevenlabs_agent_id: Optional[str] = None
    whatsapp_agent_id: Optional[str] = None


class PublishPreScreeningRequest(BaseModel):
    """Request model for publishing a pre-screening."""
    enable_voice: bool = True      # Create ElevenLabs agent
    enable_whatsapp: bool = True   # Create WhatsApp agent


class PublishPreScreeningResponse(BaseModel):
    """Response model for publish operation."""
    published_at: datetime
    elevenlabs_agent_id: Optional[str] = None
    whatsapp_agent_id: Optional[str] = None
    is_online: bool


class StatusUpdateRequest(BaseModel):
    """Request model for updating pre-screening status."""
    is_online: bool


# ============================================================================
# Database Connection Pool for Vacancies/Applications
# ============================================================================

db_pool: Optional[asyncpg.Pool] = None


async def get_db_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global db_pool
    if db_pool is None:
        # Convert SQLAlchemy URL to asyncpg format
        raw_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        db_pool = await asyncpg.create_pool(raw_url, min_size=1, max_size=10)
    return db_pool


async def close_db_pool():
    """Close the database connection pool."""
    global db_pool
    if db_pool is not None:
        await db_pool.close()
        db_pool = None


# Global references that can be recreated on connection errors
session_service = None
runner = None

def create_session_service():
    """Create a new DatabaseSessionService instance."""
    global session_service, runner
    session_service = DatabaseSessionService(db_url=DATABASE_URL)
    runner = Runner(agent=root_agent, app_name="whatsapp_app", session_service=session_service)
    logger.info("Created new session service and runner")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - create session services on startup."""
    create_session_service()
    create_interview_session_service()
    pool = await get_db_pool()  # Initialize database pool
    
    # Run schema migrations
    await run_schema_migrations(pool)
    
    # Set up data query agent with db pool (used by recruiter analyst sub-agent)
    set_data_query_db_pool(pool)
    create_analyst_session_service()
    create_screening_session_service()  # Screening chat sessions
    yield
    # Cleanup on shutdown
    await close_db_pool()


async def run_schema_migrations(pool: asyncpg.Pool):
    """Run schema migrations to ensure required columns exist."""
    try:
        # Add 'channel' column to screening_conversations if it doesn't exist
        await pool.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'screening_conversations' 
                    AND column_name = 'channel'
                ) THEN
                    ALTER TABLE screening_conversations 
                    ADD COLUMN channel VARCHAR(20) DEFAULT 'chat';
                END IF;
            END $$;
        """)
        logger.info("Schema migrations completed")
    except Exception as e:
        logger.warning(f"Schema migration warning (may be ok if already done): {e}")

app = FastAPI(lifespan=lifespan)

# CORS middleware for cross-origin requests from job board
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Twilio client for proactive messages
twilio_client = Client(
    os.environ.get("TWILIO_ACCOUNT_SID"),
    os.environ.get("TWILIO_AUTH_TOKEN")
)
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")  # e.g., "whatsapp:+14155238886"


class StartDemoRequest(BaseModel):
    phone_number: str  # Format: "+31612345678"
    firstname: str     # Candidate's first name for personalization

async def _start_demo_impl(phone: str, firstname: str):
    """Internal implementation of start_demo that can be retried."""
    global session_service, runner
    
    # 1. Delete existing session if present (fresh start for demos)
    existing = await session_service.get_session(
        app_name="whatsapp_app", user_id=phone, session_id=phone
    )
    if existing:
        await session_service.delete_session(
            app_name="whatsapp_app", user_id=phone, session_id=phone
        )
    
    # 2. Create fresh session
    await session_service.create_session(
        app_name="whatsapp_app", user_id=phone, session_id=phone
    )
    
    # 3. Generate initial agent greeting with candidate's name
    trigger_message = f"START_SCREENING name={firstname}"
    content = types.Content(role="user", parts=[types.Part(text=trigger_message)])
    greeting = ""
    async for event in runner.run_async(user_id=phone, session_id=phone, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            greeting = event.content.parts[0].text
    
    return greeting


@app.post("/start-demo")
async def start_demo(request: StartDemoRequest):
    """Start a new demo session - called from the job board when a candidate applies."""
    phone = request.phone_number.lstrip("+")  # Normalize phone number
    
    # Try to run, and if we get a stale connection error, recreate the service and retry
    try:
        greeting = await _start_demo_impl(phone, request.firstname)
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating session service: {e}")
        create_session_service()
        greeting = await _start_demo_impl(phone, request.firstname)
    
    # Send via Twilio WhatsApp
    if not TWILIO_WHATSAPP_NUMBER:
        raise HTTPException(status_code=500, detail="TWILIO_WHATSAPP_NUMBER not configured")
    
    try:
        twilio_client.messages.create(
            body=greeting or "Hoi! Leuk dat je gesolliciteerd hebt. Ben je klaar voor een paar korte vragen?",
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:+{phone}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send WhatsApp message: {str(e)}")
    
    return {"status": "ok", "message": "Demo started", "phone": phone}


async def _webhook_impl_vacancy_specific(phone_normalized: str, incoming_msg: str, vacancy_id: str, pre_screening: dict, vacancy_title: str) -> str:
    """Handle webhook using vacancy-specific agent (for outbound screenings)."""
    global screening_session_service
    
    # Get or create the same screening runner as was used for outbound
    runner = get_or_create_screening_runner(vacancy_id, pre_screening, vacancy_title)
    
    # Run agent and get response
    content = types.Content(role="user", parts=[types.Part(text=incoming_msg)])
    response_text = ""
    async for event in runner.run_async(user_id=phone_normalized, session_id=phone_normalized, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text
    
    return response_text


async def _webhook_impl_generic(user_id: str, incoming_msg: str) -> str:
    """Handle webhook using generic agent (for demo/start-demo conversations)."""
    global session_service, runner
    
    # Get or create session for this user
    session = await session_service.get_session(
        app_name="whatsapp_app", user_id=user_id, session_id=user_id
    )
    if not session:
        try:
            session = await session_service.create_session(
                app_name="whatsapp_app", user_id=user_id, session_id=user_id
            )
        except IntegrityError:
            # Session was created by another request, fetch it
            session = await session_service.get_session(
                app_name="whatsapp_app", user_id=user_id, session_id=user_id
            )
    
    # Run agent and get response
    content = types.Content(role="user", parts=[types.Part(text=incoming_msg)])
    response_text = ""
    async for event in runner.run_async(user_id=user_id, session_id=user_id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text
    
    return response_text


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
        SELECT sc.vacancy_id, sc.pre_screening_id, v.title as vacancy_title
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
    
    try:
        if conv_row:
            # Found active outbound screening - use vacancy-specific agent
            vacancy_id = str(conv_row["vacancy_id"])
            pre_screening_id = str(conv_row["pre_screening_id"])
            vacancy_title = conv_row["vacancy_title"]
            
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
                "knockout_questions": [q for q in questions if q["question_type"] == "knockout"],
                "qualification_questions": [q for q in questions if q["question_type"] == "qualification"],
            }
            
            logger.info(f"WhatsApp webhook routing to vacancy-specific agent for {vacancy_id[:8]}")
            response_text = await _webhook_impl_vacancy_specific(
                phone_normalized, incoming_msg, vacancy_id, pre_screening, vacancy_title
            )
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


# Keywords that indicate simple edit operations (Dutch)
SIMPLE_EDIT_KEYWORDS = [
    "verwijder", "delete",  # delete
    "korter", "kort",  # shorter
    "herformuleer",  # rephrase
    "verplaats", "zet",  # move/reorder
    "wijzig", "aanpas", "pas aan",  # change/adjust
    "voeg toe", "toevoeg",  # add (simple additions)
    "goedkeur", "approve",  # approve
]

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
    interview_session_service = DatabaseSessionService(db_url=DATABASE_URL)
    
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


class GenerateInterviewRequest(BaseModel):
    vacancy_text: str
    session_id: str | None = None  # Optional: reuse session for feedback


class FeedbackRequest(BaseModel):
    session_id: str
    message: str


class ReorderRequest(BaseModel):
    session_id: str
    knockout_order: list[str] | None = None  # List of question IDs in new order
    qualification_order: list[str] | None = None


class DeleteQuestionRequest(BaseModel):
    session_id: str
    question_id: str  # ID of question to delete (e.g., "ko_1" or "qual_2")


class AddQuestionRequest(BaseModel):
    session_id: str
    question_type: str  # "knockout" or "qualification"
    question: str
    ideal_answer: str | None = None  # Required for qualification questions


# Simulated reasoning messages - feel like AI is analyzing
SIMULATED_REASONING = [
    "Vacaturetekst ontvangen, begin met analyse...",
    "Kernvereisten identificeren uit de functieomschrijving...",
    "Zoeken naar harde eisen: werkvergunning, locatie, beschikbaarheid...",
    "Ploegensysteem of flexibele uren detecteren...",
    "Fysieke vereisten en werkomstandigheden analyseren...",
    "Knockout criteria formuleren op basis van must-haves...",
    "Kwalificatievragen opstellen voor ervaring en motivatie...",
    "Interview structuur optimaliseren voor WhatsApp/voice...",
    "Vragen afronden en valideren...",
]


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
    reasoning_interval = 0.8  # seconds between messages
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


async def stream_feedback(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during feedback processing."""
    global interview_session_service, interview_runner, interview_editor_runner
    
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
            
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
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
                
                total_time = time.time() - total_start
                print(f"[TIMING] === TOTAL REQUEST TIME: {total_time:.2f}s ===")
                
                yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'interview': interview})}\n\n"
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


class RestoreSessionRequest(BaseModel):
    vacancy_id: str


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
    analyst_session_service = DatabaseSessionService(db_url=DATABASE_URL)
    analyst_runner = Runner(
        agent=recruiter_analyst_agent,
        app_name="recruiter_analyst",
        session_service=analyst_session_service
    )
    logger.info("Created recruiter analyst session service and runner")


class DataQueryRequest(BaseModel):
    question: str
    session_id: str | None = None  # Optional: reuse session for context


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
    pool = await get_db_pool()
    
    # Build query with optional filters
    conditions = []
    params = []
    param_idx = 1
    
    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1
    
    if source:
        conditions.append(f"source = ${param_idx}")
        params.append(source)
        param_idx += 1
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM vacancies {where_clause}"
    total = await pool.fetchval(count_query, *params)
    
    # Get vacancies
    query = f"""
        SELECT v.id, v.title, v.company, v.location, v.description, v.status, 
               v.created_at, v.archived_at, v.source, v.source_id,
               (ps.id IS NOT NULL) as has_screening,
               CASE 
                   WHEN ps.published_at IS NULL THEN NULL
                   ELSE ps.is_online
               END as is_online,
               (ps.elevenlabs_agent_id IS NOT NULL) as voice_enabled,
               (ps.whatsapp_agent_id IS NOT NULL) as whatsapp_enabled
        FROM vacancies v
        LEFT JOIN pre_screenings ps ON ps.vacancy_id = v.id
        {where_clause}
        ORDER BY v.created_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])
    
    rows = await pool.fetch(query, *params)
    
    vacancies = [
        VacancyResponse(
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
            is_online=row["is_online"],
            channels=ChannelsResponse(
                voice=row["voice_enabled"] or False,
                whatsapp=row["whatsapp_enabled"] or False
            )
        )
        for row in rows
    ]
    
    return {
        "vacancies": vacancies,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/vacancies/{vacancy_id}")
async def get_vacancy(vacancy_id: str):
    """Get a single vacancy by ID."""
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    query = """
        SELECT v.id, v.title, v.company, v.location, v.description, v.status,
               v.created_at, v.archived_at, v.source, v.source_id,
               (SELECT EXISTS(SELECT 1 FROM pre_screenings ps WHERE ps.vacancy_id = v.id)) as has_screening
        FROM vacancies v
        WHERE v.id = $1
    """
    
    row = await pool.fetchrow(query, vacancy_uuid)
    
    if not row:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    
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
        has_screening=row["has_screening"]
    )


@app.get("/vacancies/{vacancy_id}/applications")
async def list_applications(
    vacancy_id: str,
    qualified: Optional[bool] = Query(None),
    completed: Optional[bool] = Query(None),
    synced: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List all applications for a vacancy."""
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
        conditions.append(f"completed = ${param_idx}")
        params.append(completed)
        param_idx += 1
    
    if synced is not None:
        conditions.append(f"synced = ${param_idx}")
        params.append(synced)
        param_idx += 1
    
    where_clause = f"WHERE {' AND '.join(conditions)}"
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM applications {where_clause}"
    total = await pool.fetchval(count_query, *params)
    
    # Get applications
    query = f"""
        SELECT id, vacancy_id, candidate_name, channel, completed, qualified,
               started_at, completed_at, interaction_seconds, synced, synced_at, summary, interview_slot
        FROM applications
        {where_clause}
        ORDER BY started_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """
    params.extend([limit, offset])
    
    rows = await pool.fetch(query, *params)
    
    # Fetch answers for each application
    applications = []
    for row in rows:
        answers_query = """
            SELECT question_id, question_text, answer, passed, score, rating
            FROM application_answers
            WHERE application_id = $1
            ORDER BY id
        """
        answer_rows = await pool.fetch(answers_query, row["id"])
        
        answers = []
        total_score = 0
        score_count = 0
        knockout_passed = 0
        knockout_total = 0
        qualification_count = 0
        
        for a in answer_rows:
            answers.append(QuestionAnswerResponse(
                question_id=a["question_id"],
                question_text=a["question_text"],
                answer=a["answer"],
                passed=a["passed"],
                score=a["score"],
                rating=a["rating"]
            ))
            
            # Calculate stats
            if a["question_id"].startswith("ko_"):
                knockout_total += 1
                if a["passed"]:
                    knockout_passed += 1
            else:
                qualification_count += 1
            
            if a["score"] is not None:
                total_score += a["score"]
                score_count += 1
        
        # Calculate overall score as average
        overall_score = round(total_score / score_count) if score_count > 0 else None
        
        applications.append(ApplicationResponse(
            id=str(row["id"]),
            vacancy_id=str(row["vacancy_id"]),
            candidate_name=row["candidate_name"],
            channel=row["channel"],
            completed=row["completed"],
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
            interview_slot=row["interview_slot"]
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
        SELECT id, vacancy_id, candidate_name, channel, completed, qualified,
               started_at, completed_at, interaction_seconds, synced, synced_at, summary, interview_slot
        FROM applications
        WHERE id = $1
    """
    
    row = await pool.fetchrow(query, application_uuid)
    
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Fetch answers
    answers_query = """
        SELECT question_id, question_text, answer, passed, score, rating
        FROM application_answers
        WHERE application_id = $1
        ORDER BY id
    """
    answer_rows = await pool.fetch(answers_query, row["id"])
    
    answers = []
    total_score = 0
    score_count = 0
    knockout_passed = 0
    knockout_total = 0
    qualification_count = 0
    
    for a in answer_rows:
        answers.append(QuestionAnswerResponse(
            question_id=a["question_id"],
            question_text=a["question_text"],
            answer=a["answer"],
            passed=a["passed"],
            score=a["score"],
            rating=a["rating"]
        ))
        
        # Calculate stats
        if a["question_id"].startswith("ko_"):
            knockout_total += 1
            if a["passed"]:
                knockout_passed += 1
        else:
            qualification_count += 1
        
        if a["score"] is not None:
            total_score += a["score"]
            score_count += 1
    
    # Calculate overall score as average
    overall_score = round(total_score / score_count) if score_count > 0 else None
    
    return ApplicationResponse(
        id=str(row["id"]),
        vacancy_id=str(row["vacancy_id"]),
        candidate_name=row["candidate_name"],
        channel=row["channel"],
        completed=row["completed"],
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
        interview_slot=row["interview_slot"]
    )


@app.get("/vacancies/{vacancy_id}/stats")
async def get_vacancy_stats(vacancy_id: str):
    """Get aggregated statistics for a vacancy."""
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
    
    # Get stats
    stats_query = """
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE completed = true) as completed_count,
            COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
            COUNT(*) FILTER (WHERE channel = 'voice') as voice_count,
            COUNT(*) FILTER (WHERE channel = 'whatsapp') as whatsapp_count,
            COALESCE(AVG(interaction_seconds), 0) as avg_seconds,
            MAX(started_at) as last_application
        FROM applications
        WHERE vacancy_id = $1
    """
    
    row = await pool.fetchrow(stats_query, vacancy_uuid)
    
    total = row["total"]
    completed_count = row["completed_count"]
    qualified_count = row["qualified_count"]
    
    # Calculate rates (avoid division by zero)
    completion_rate = int((completed_count / total * 100) if total > 0 else 0)
    qualification_rate = int((qualified_count / completed_count * 100) if completed_count > 0 else 0)
    
    return VacancyStatsResponse(
        vacancy_id=vacancy_id,
        total_applications=total,
        completed=completed_count,
        completion_rate=completion_rate,
        qualified=qualified_count,
        qualification_rate=qualification_rate,
        channel_breakdown={
            "voice": row["voice_count"],
            "whatsapp": row["whatsapp_count"]
        },
        avg_interaction_seconds=int(row["avg_seconds"]),
        last_application_at=row["last_application"]
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
            updated_at = NOW()
        WHERE id = $4
        """,
        published_at, elevenlabs_agent_id, whatsapp_agent_id, pre_screening_id
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
    Update the online/offline status of a published pre-screening.
    
    The pre-screening must be published first (have agents created).
    When online, the agents will actively handle incoming calls/messages.
    """
    pool = await get_db_pool()
    
    # Validate UUID format
    try:
        vacancy_uuid = uuid.UUID(vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {vacancy_id}")
    
    # Get pre-screening
    ps_row = await pool.fetchrow(
        """
        SELECT id, published_at, elevenlabs_agent_id, whatsapp_agent_id, is_online
        FROM pre_screenings
        WHERE vacancy_id = $1
        """,
        vacancy_uuid
    )
    
    if not ps_row:
        raise HTTPException(status_code=404, detail="No pre-screening found for this vacancy")
    
    if not ps_row["published_at"]:
        raise HTTPException(
            status_code=400, 
            detail="Pre-screening must be published before changing status"
        )
    
    # Update status
    await pool.execute(
        """
        UPDATE pre_screenings 
        SET is_online = $1, updated_at = NOW()
        WHERE id = $2
        """,
        request.is_online, ps_row["id"]
    )
    
    status_text = "online" if request.is_online else "offline"
    
    return {
        "status": "success",
        "is_online": request.is_online,
        "message": f"Pre-screening is now {status_text}",
        "elevenlabs_agent_id": ps_row["elevenlabs_agent_id"],
        "whatsapp_agent_id": ps_row["whatsapp_agent_id"]
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
    screening_session_service = DatabaseSessionService(db_url=DATABASE_URL)
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
    
    # Create agent
    agent = Agent(
        name=f"screening_{vacancy_id[:8]}",
        model="gemini-2.5-flash",
        instruction=instruction,
        description=f"Screening agent for vacancy {vacancy_title}",
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


class ScreeningChatRequest(BaseModel):
    vacancy_id: str
    message: str
    session_id: Optional[str] = None
    candidate_name: Optional[str] = None  # Optional - if not provided, random name generated


class ScreeningConversationResponse(BaseModel):
    id: str
    vacancy_id: str
    candidate_name: str
    candidate_email: Optional[str] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    message_count: int


async def stream_screening_chat(
    vacancy_id: str, 
    message: str, 
    session_id: Optional[str],
    candidate_name: Optional[str]
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
        
        # Create conversation record
        await pool.execute(
            """
            INSERT INTO screening_conversations 
            (vacancy_id, pre_screening_id, session_id, candidate_name, candidate_email, candidate_phone, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'active')
            """,
            vacancy_uuid, ps_row["id"], session_id, candidate_name, candidate_email, candidate_phone
        )
        
        # Log candidate and session info
        logger.info(f"👤 Candidate: {candidate_name}")
        logger.info(f"🔑 Session ID: {session_id}")
        logger.info("=" * 60)
        
        # Trigger screening start
        trigger_message = f"START_SCREENING name={candidate_name}"
    else:
        # Continuation - verify session exists
        conv = await pool.fetchrow(
            "SELECT id, candidate_name FROM screening_conversations WHERE session_id = $1",
            session_id
        )
        if not conv:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        
        candidate_name = conv["candidate_name"]
        trigger_message = message
        logger.info(f"💬 Continuing conversation - Session: {session_id[:8]}... | Candidate: {candidate_name}")
        logger.info(f"📩 User message: {message}")
    
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Antwoord genereren...'})}\n\n"
    
    # Run agent
    content = types.Content(role="user", parts=[types.Part(text=trigger_message)])
    
    try:
        async for event in runner.run_async(
            user_id="web",
            session_id=session_id,
            new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                logger.info(f"🤖 Agent response: {response_text[:100]}..." if len(response_text) > 100 else f"🤖 Agent response: {response_text}")
                
                # Update message count
                await pool.execute(
                    """
                    UPDATE screening_conversations 
                    SET message_count = message_count + 2, updated_at = NOW()
                    WHERE session_id = $1
                    """,
                    session_id
                )
                
                yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'session_id': session_id, 'candidate_name': candidate_name})}\n\n"
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
            request.candidate_name
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
    """Get a single conversation with its messages from the ADK session."""
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
               candidate_email, candidate_phone, status, started_at, completed_at, message_count
        FROM screening_conversations
        WHERE id = $1
        """,
        conv_uuid
    )
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Get messages from ADK events table
    messages = []
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
        "started_at": conv["started_at"],
        "completed_at": conv["completed_at"],
        "message_count": conv["message_count"],
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
                (vacancy_id, pre_screening_id, candidate_name, channel, completed, qualified, completed_at)
                VALUES ($1, $2, $3, 'whatsapp', true, $4, NOW())
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


class OutboundScreeningRequest(BaseModel):
    """Request model for initiating outbound screening (voice or WhatsApp)."""
    vacancy_id: str  # UUID of the vacancy
    channel: InterviewChannel  # "voice" or "whatsapp"
    phone_number: str  # E.164 format, e.g., "+32412345678"
    first_name: str  # Candidate's first name
    last_name: str  # Candidate's last name
    test_conversation_id: Optional[str] = None  # For testing: skip real call, use this ID


class OutboundScreeningResponse(BaseModel):
    """Response model for outbound screening initiation."""
    success: bool
    message: str
    channel: InterviewChannel
    conversation_id: Optional[str] = None
    application_id: Optional[str] = None  # UUID of the created/updated application
    # Voice-specific fields
    call_sid: Optional[str] = None
    # WhatsApp-specific fields
    whatsapp_message_sid: Optional[str] = None


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
    
    # Register/update candidate in applications table
    existing_app = await pool.fetchrow(
        """
        SELECT id FROM applications 
        WHERE vacancy_id = $1 AND candidate_phone = $2
        """,
        vacancy_uuid,
        phone_normalized
    )
    
    if existing_app:
        # Update existing record
        application_id = existing_app["id"]
        await pool.execute(
            """
            UPDATE applications 
            SET candidate_name = $1, channel = $2, completed = false
            WHERE id = $3
            """,
            candidate_name,
            request.channel.value,
            application_id
        )
        logger.info(f"Updated candidate {application_id} for outbound screening")
    else:
        # Create new application record
        app_row = await pool.fetchrow(
            """
            INSERT INTO applications 
            (vacancy_id, candidate_name, candidate_phone, channel, completed, qualified)
            VALUES ($1, $2, $3, $4, false, false)
            RETURNING id
            """,
            vacancy_uuid,
            candidate_name,
            phone_normalized,
            request.channel.value
        )
        application_id = app_row["id"]
        logger.info(f"Created candidate {application_id} for outbound screening")
    
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
                (vacancy_id, pre_screening_id, session_id, candidate_name, candidate_phone, channel, status)
                VALUES ($1, $2, $3, $4, $5, 'voice', 'active')
                RETURNING id
                """,
                uuid.UUID(vacancy_id),
                uuid.UUID(pre_screening_id),
                result.get("conversation_id"),  # Use ElevenLabs conversation_id as session_id
                candidate_name,
                phone_normalized
            )
            logger.info(f"Voice screening initiated for vacancy {vacancy_id}, conversation {conv_row['id']}, elevenlabs_conversation_id={result.get('conversation_id')}")
        
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
        
        # Delete existing session if present (fresh start for each outbound screening)
        existing = await screening_session_service.get_session(
            app_name="screening_chat",
            user_id=phone_normalized,
            session_id=phone_normalized
        )
        if existing:
            await screening_session_service.delete_session(
                app_name="screening_chat",
                user_id=phone_normalized,
                session_id=phone_normalized
            )
        
        # Create fresh session for this conversation
        await screening_session_service.create_session(
            app_name="screening_chat",
            user_id=phone_normalized,
            session_id=phone_normalized
        )
        
        # Generate opening message using ADK agent (same as chat widget)
        name = candidate_name or "daar"
        trigger_message = f"START_SCREENING name={name}"
        content = types.Content(role="user", parts=[types.Part(text=trigger_message)])
        
        opening_message = ""
        async for event in runner.run_async(user_id=phone_normalized, session_id=phone_normalized, new_message=content):
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
        
        # Create conversation record in database
        conv_row = await pool.fetchrow(
            """
            INSERT INTO screening_conversations 
            (vacancy_id, pre_screening_id, session_id, candidate_name, candidate_phone, channel, status)
            VALUES ($1, $2, $3, $4, $5, 'whatsapp', 'active')
            RETURNING id
            """,
            uuid.UUID(vacancy_id),
            uuid.UUID(pre_screening_id),
            phone_normalized,
            candidate_name,
            phone_normalized
        )
        
        # Note: ADK session is already initialized by runner.run_async above
        
        logger.info(f"WhatsApp screening initiated for vacancy {vacancy_id}, conversation {conv_row['id']}")
        
        return OutboundScreeningResponse(
            success=True,
            message="WhatsApp screening initiated",
            channel=InterviewChannel.WHATSAPP,
            conversation_id=str(conv_row["id"]),
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

# HMAC secret for webhook validation (set in ElevenLabs dashboard)
ELEVENLABS_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")


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


class ElevenLabsWebhookData(BaseModel):
    """Data object from ElevenLabs post-call webhook."""
    agent_id: str
    conversation_id: str
    status: Optional[str] = None
    transcript: list[dict] = []
    metadata: Optional[dict] = None
    analysis: Optional[dict] = None


class ElevenLabsWebhookPayload(BaseModel):
    """Full payload from ElevenLabs post-call webhook."""
    type: str  # "post_call_transcription", "post_call_audio", "call_initiation_failure"
    event_timestamp: int
    data: ElevenLabsWebhookData


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
    
    # Process transcript with the agent
    result = await process_transcript(
        transcript=data.transcript,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        call_date=call_date,
    )
    
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
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Try to find existing application by phone number (registered candidate)
            existing_app = None
            if candidate_phone:
                existing_app = await conn.fetchrow(
                    """
                    SELECT id FROM applications 
                    WHERE vacancy_id = $1 AND candidate_phone = $2 AND completed = false
                    """,
                    vacancy_id,
                    candidate_phone
                )
            
            if existing_app:
                # Update existing application
                application_id = existing_app["id"]
                await conn.execute(
                    """
                    UPDATE applications 
                    SET completed = true, qualified = $1, interaction_seconds = $2, 
                        completed_at = NOW(), conversation_id = $3, channel = 'voice',
                        summary = $4, interview_slot = $5
                    WHERE id = $6
                    """,
                    result.overall_passed,
                    call_duration,
                    data.conversation_id,
                    result.summary,
                    result.interview_slot,
                    application_id
                )
                logger.info(f"Updated existing application {application_id} for phone {candidate_phone}")
            else:
                # Create new application record
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO applications 
                    (vacancy_id, candidate_name, candidate_phone, channel, completed, qualified, 
                     interaction_seconds, completed_at, conversation_id, summary, interview_slot)
                    VALUES ($1, $2, $3, 'voice', true, $4, $5, NOW(), $6, $7, $8)
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
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, 'voice')
                    """,
                    application_id,
                    qr.id,
                    qr.question_text,
                    qr.answer,
                    qr.score,
                    qr.rating
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
                
                row = await conn.fetchrow("""
                    INSERT INTO applications 
                    (vacancy_id, candidate_name, channel, completed, qualified, 
                     interaction_seconds, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, started_at
                """, vacancy_id, app_data["candidate_name"], app_data["channel"],
                    app_data["completed"], app_data["qualified"], 
                    app_data["interaction_seconds"], completed_at)
                
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


@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
