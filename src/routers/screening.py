"""
Screening-related endpoints.
"""
import json
import logging
import uuid
from typing import AsyncGenerator, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from google.genai import types
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

from knockout_agent.agent import (
    build_screening_instruction,
    is_closing_message,
    clean_response_text,
    conversation_complete_tool,
)
from candidate_simulator.agent import SimulationPersona, create_simulator_agent, run_simulation
from google.adk.agents.llm_agent import Agent
from src.utils.random_candidate import generate_random_candidate
from src.models.screening import ScreeningChatRequest, SimulateInterviewRequest
from src.repositories import ConversationRepository
from src.database import get_db_pool
from src.config import logger

router = APIRouter(tags=["Screening"])

# Will be set during app startup
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager


async def stream_screening_chat(
    vacancy_id: str,
    message: str,
    session_id: Optional[str],
    candidate_name: Optional[str],
    is_test: bool = False
) -> AsyncGenerator[str, None]:
    """Stream SSE events during screening chat."""
    global session_manager

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
        "SELECT id, title FROM ats.vacancies WHERE id = $1",
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
        FROM ats.pre_screenings WHERE vacancy_id = $1
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
        FROM ats.pre_screening_questions
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
    runner = session_manager.get_or_create_screening_runner(vacancy_id, pre_screening, vacancy["title"])

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
                await session_manager.screening_session_service.create_session(
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
            session_manager.create_screening_session_service()
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

                    # Capture text from any response (not just final)
                    # because text may come alongside tool calls like schedule_interview
                    if hasattr(part, 'text') and part.text:
                        cleaned = clean_response_text(part.text)
                        if cleaned:
                            response_text = cleaned

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


@router.post("/screening/chat")
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
    global session_manager
    if session_manager.screening_session_service is None:
        session_manager.create_screening_session_service()

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


@router.get("/screening/conversations/{conversation_id}")
async def get_screening_conversation(conversation_id: str):
    """Get a single conversation with its messages."""
    pool = await get_db_pool()

    # Validate UUID
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid conversation ID format: {conversation_id}")

    # Get conversation
    conv_repo = ConversationRepository(pool)
    conv = await conv_repo.get_by_id(conv_uuid)

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Try to get messages from conversation_messages table first (new approach)
    messages = []
    stored_messages = await conv_repo.get_messages(conv_uuid)

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
            FROM adk.events
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


@router.post("/screening/conversations/{conversation_id}/complete")
async def complete_screening_conversation(conversation_id: str, qualified: bool = Query(...)):
    """Mark a conversation as completed with qualification status."""
    pool = await get_db_pool()

    # Validate UUID
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid conversation ID format: {conversation_id}")

    # Get conversation
    conv_repo = ConversationRepository(pool)
    conv = await conv_repo.get_by_id(conv_uuid)

    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update conversation status
            await conv_repo.complete(conv_uuid)

            # Create application record
            app_row = await conn.fetchrow(
                """
                INSERT INTO ats.applications
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
        "SELECT id, title FROM ats.vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Vacancy not found'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    vacancy_title = vacancy["title"]

    # Get pre-screening config
    pre_screening = await pool.fetchrow(
        "SELECT * FROM ats.pre_screenings WHERE vacancy_id = $1",
        vacancy_uuid
    )
    if not pre_screening:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Pre-screening not configured for this vacancy'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Build pre-screening config dict
    questions = await pool.fetch(
        """SELECT id, question_type, question_text, ideal_answer, position
           FROM ats.pre_screening_questions
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


@router.post("/vacancies/{vacancy_id}/simulate")
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
