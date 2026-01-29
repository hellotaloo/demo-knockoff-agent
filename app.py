import os
from dotenv import load_dotenv
load_dotenv()  # Load .env file for local development

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from knockout_agent.agent import root_agent

app = FastAPI()

# CORS middleware for cross-origin requests from job board
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# Use Supabase PostgreSQL for persistent session storage
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")
session_service = DatabaseSessionService(db_url=DATABASE_URL)
runner = Runner(agent=root_agent, app_name="whatsapp_app", session_service=session_service)

# Twilio client for proactive messages
twilio_client = Client(
    os.environ.get("TWILIO_ACCOUNT_SID"),
    os.environ.get("TWILIO_AUTH_TOKEN")
)
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")  # e.g., "whatsapp:+14155238886"


class StartDemoRequest(BaseModel):
    phone_number: str  # Format: "+31612345678"
    firstname: str     # Candidate's first name for personalization

@app.post("/start-demo")
async def start_demo(request: StartDemoRequest):
    """Start a new demo session - called from the job board when a candidate applies."""
    phone = request.phone_number.lstrip("+")  # Normalize phone number
    
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
    trigger_message = f"START_SCREENING name={request.firstname}"
    content = types.Content(role="user", parts=[types.Part(text=trigger_message)])
    greeting = ""
    async for event in runner.run_async(user_id=phone, session_id=phone, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            greeting = event.content.parts[0].text
    
    # 4. Send via Twilio WhatsApp
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


@app.post("/webhook")
async def webhook(Body: str = Form(""), From: str = Form("")):
    incoming_msg = Body
    from_number = From
    
    # Use phone number as user/session ID for conversation continuity
    # Remove "whatsapp:" prefix and "+" to match /start-demo format
    user_id = from_number.replace("whatsapp:", "").lstrip("+")
    
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
    
    # Send TwiML response
    resp = MessagingResponse()
    resp.message(response_text or "Sorry, I couldn't process that.")
    return PlainTextResponse(content=str(resp), media_type="application/xml")

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
