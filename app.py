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
from knockout_agent.agent import root_agent
from interview_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
from data_query_agent.agent import set_db_pool as set_data_query_db_pool
from recruiter_analyst.agent import root_agent as recruiter_analyst_agent
from fixtures import load_vacancies, load_applications, load_pre_screenings
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError

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
    # Set up data query agent with db pool (used by recruiter analyst sub-agent)
    set_data_query_db_pool(pool)
    create_analyst_session_service()
    yield
    # Cleanup on shutdown
    await close_db_pool()

app = FastAPI(lifespan=lifespan)

# CORS middleware for cross-origin requests from job board
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
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


async def _webhook_impl(user_id: str, incoming_msg: str) -> str:
    """Internal implementation of webhook that can be retried."""
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
    incoming_msg = Body
    from_number = From
    
    # Use phone number as user/session ID for conversation continuity
    # Remove "whatsapp:" prefix and "+" to match /start-demo format
    user_id = from_number.replace("whatsapp:", "").lstrip("+")
    
    # Try to run, and if we get a stale connection error, recreate the service and retry
    try:
        response_text = await _webhook_impl(user_id, incoming_msg)
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating session service: {e}")
        create_session_service()
        response_text = await _webhook_impl(user_id, incoming_msg)
    
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
               (SELECT EXISTS(SELECT 1 FROM pre_screenings ps WHERE ps.vacancy_id = v.id)) as has_screening
        FROM vacancies v
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
            has_screening=row["has_screening"]
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
               started_at, completed_at, interaction_seconds, synced, synced_at
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
            SELECT question_id, question_text, answer, passed
            FROM application_answers
            WHERE application_id = $1
            ORDER BY id
        """
        answer_rows = await pool.fetch(answers_query, row["id"])
        
        answers = [
            QuestionAnswerResponse(
                question_id=a["question_id"],
                question_text=a["question_text"],
                answer=a["answer"],
                passed=a["passed"]
            )
            for a in answer_rows
        ]
        
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
            synced_at=row["synced_at"]
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
               started_at, completed_at, interaction_seconds, synced, synced_at
        FROM applications
        WHERE id = $1
    """
    
    row = await pool.fetchrow(query, application_uuid)
    
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Fetch answers
    answers_query = """
        SELECT question_id, question_text, answer, passed
        FROM application_answers
        WHERE application_id = $1
        ORDER BY id
    """
    answer_rows = await pool.fetch(answers_query, row["id"])
    
    answers = [
        QuestionAnswerResponse(
            question_id=a["question_id"],
            question_text=a["question_text"],
            answer=a["answer"],
            passed=a["passed"]
        )
        for a in answer_rows
    ]
    
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
        synced_at=row["synced_at"]
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
        SELECT id, vacancy_id, intro, knockout_failed_action, final_action, status, created_at, updated_at
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
    
    return {
        "status": "success",
        "message": "Pre-screening configuration deleted",
        "vacancy_id": vacancy_id,
        "vacancy_status": "new"
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
                
                # Insert pre-screening record
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
            await conn.execute("DELETE FROM application_answers")
            await conn.execute("DELETE FROM applications")
            await conn.execute("DELETE FROM pre_screening_questions")
            await conn.execute("DELETE FROM pre_screenings")
            await conn.execute("DELETE FROM vacancies")
    
    result = {
        "status": "success",
        "message": "All demo data cleared"
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
