import os
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from dotenv import load_dotenv
load_dotenv()  # Load .env file for local development

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.genai import types
from knockout_agent.agent import root_agent
from interview_generator.agent import root_agent as interview_agent
from sqlalchemy.exc import InterfaceError, OperationalError

logger = logging.getLogger(__name__)

# Use Supabase PostgreSQL for persistent session storage
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

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
    """Manage application lifecycle - create session service on startup."""
    create_session_service()
    yield
    # Cleanup on shutdown (if needed)

app = FastAPI(lifespan=lifespan)

# CORS middleware for cross-origin requests from job board
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["POST", "GET"],
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


async def _webhook_impl(user_id: str, incoming_msg: str) -> str:
    """Internal implementation of webhook that can be retried."""
    global session_service, runner
    
    # Get or create session for this user
    session = await session_service.get_session(
        app_name="whatsapp_app", user_id=user_id, session_id=user_id
    )
    if not session:
        session = await session_service.create_session(
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

# In-memory session service for interview generator (stateless per request)
interview_session_service = InMemorySessionService()
interview_runner = Runner(
    agent=interview_agent, 
    app_name="interview_generator", 
    session_service=interview_session_service
)


class GenerateInterviewRequest(BaseModel):
    vacancy_text: str
    session_id: str | None = None  # Optional: reuse session for feedback


class FeedbackRequest(BaseModel):
    session_id: str
    message: str


async def stream_interview_generation(vacancy_text: str, session_id: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during interview generation."""
    
    # Create session
    await interview_session_service.create_session(
        app_name="interview_generator",
        user_id="web",
        session_id=session_id
    )
    
    # Send initial status
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Vacature analyseren...'})}\n\n"
    
    # Run the agent
    content = types.Content(role="user", parts=[types.Part(text=vacancy_text)])
    
    async for event in interview_runner.run_async(
        user_id="web",
        session_id=session_id,
        new_message=content
    ):
        # Check for tool calls
        if hasattr(event, 'tool_calls') and event.tool_calls:
            yield f"data: {json.dumps({'type': 'status', 'status': 'tool_call', 'message': 'Vragen genereren...'})}\n\n"
        
        # Check for thinking/reasoning content
        if hasattr(event, 'content') and event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, 'thought') and part.thought:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': part.text})}\n\n"
        
        # Final response
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text
            
            # Get the interview from session state
            session = await interview_session_service.get_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            )
            
            interview = session.state.get("interview", {}) if session else {}
            
            yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'interview': interview, 'session_id': session_id})}\n\n"
    
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
    
    # Check if session exists
    session = await interview_session_service.get_session(
        app_name="interview_generator",
        user_id="web",
        session_id=session_id
    )
    
    if not session:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
        return
    
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Feedback verwerken...'})}\n\n"
    
    # Run agent with feedback
    content = types.Content(role="user", parts=[types.Part(text=message)])
    
    async for event in interview_runner.run_async(
        user_id="web",
        session_id=session_id,
        new_message=content
    ):
        if hasattr(event, 'tool_calls') and event.tool_calls:
            yield f"data: {json.dumps({'type': 'status', 'status': 'tool_call', 'message': 'Vragen aanpassen...'})}\n\n"
        
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text
            
            # Get updated interview from session state
            session = await interview_session_service.get_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            )
            
            interview = session.state.get("interview", {}) if session else {}
            
            yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'interview': interview})}\n\n"
    
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
    session = await interview_session_service.get_session(
        app_name="interview_generator",
        user_id="web",
        session_id=session_id
    )
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "interview": session.state.get("interview", {})
    }


@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
