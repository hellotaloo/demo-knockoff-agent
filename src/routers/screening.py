"""
Screening-related endpoints.
"""
import json
import logging
import uuid
from typing import AsyncGenerator, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from pre_screening_whatsapp_agent import (
    create_simple_agent,
    Phase,
    is_conversation_complete,
)
from candidate_simulator.agent import SimulationPersona, build_simulator_instruction
from src.utils.random_candidate import generate_random_candidate
from src.models.screening import ScreeningChatRequest, SimulateInterviewRequest
from src.repositories import ConversationRepository
from src.database import get_db_pool
from src.config import logger

router = APIRouter(tags=["Screening"])

# In-memory cache for web chat sessions (session_id -> agent)
# Web chat is ephemeral - no database persistence needed
_web_chat_sessions: dict[str, "SimplePreScreeningAgent"] = {}


async def stream_screening_chat(
    vacancy_id: str,
    message: str,
    session_id: Optional[str],
    candidate_name: Optional[str],
    is_test: bool = False
) -> AsyncGenerator[str, None]:
    """Stream SSE events during screening chat using pre_screening_whatsapp_agent."""
    global _web_chat_sessions

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

    # Handle new conversation vs continuation
    is_new_conversation = session_id is None or message.upper() == "START"

    if is_new_conversation:
        # Generate random candidate if name not provided
        if not candidate_name:
            random_candidate = generate_random_candidate()
            candidate_name = random_candidate.first_name

        # Create new session ID
        session_id = str(uuid.uuid4())

        # Build questions for the agent
        knockout_questions = [
            {"question": q["question_text"], "requirement": q["ideal_answer"] or ""}
            for q in questions if q["question_type"] == "knockout"
        ]
        open_questions = [
            q["question_text"]
            for q in questions if q["question_type"] == "qualification"
        ]

        # Create new agent
        agent = create_simple_agent(
            candidate_name=candidate_name,
            vacancy_title=vacancy["title"],
            company_name="",
            knockout_questions=knockout_questions,
            open_questions=open_questions,
        )

        # Cache it for this session
        _web_chat_sessions[session_id] = agent

        logger.info("=" * 60)
        logger.info("🎬 NEW SCREENING CONVERSATION STARTED (Web Chat)")
        logger.info("=" * 60)
        logger.info(f"Vacancy: {vacancy['title']} ({vacancy_id[:8]}...)")
        logger.info(f"👤 Candidate: {candidate_name}")
        logger.info(f"🔑 Session ID: {session_id}")
        logger.info("=" * 60)

        # For new conversation, generate greeting directly
        is_new = True
    else:
        # Continuation - get agent from cache
        agent = _web_chat_sessions.get(session_id)
        if not agent:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found. Please start a new conversation.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if not candidate_name:
            candidate_name = agent.state.candidate_name or "Kandidaat"

        is_new = False
        logger.info(f"💬 Continuing conversation - Session: {session_id[:8]}...")
        logger.info(f"📩 User message: {message}")

    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Antwoord genereren...'})}\n\n"

    try:
        # For new conversation, use get_initial_message() for proper greeting
        # For continuation, process the user's message
        if is_new:
            response_text = await agent.get_initial_message()
        else:
            response_text = await agent.process_message(message)

        if response_text:
            logger.info(f"🤖 Agent response: {response_text[:100]}..." if len(response_text) > 100 else f"🤖 Agent response: {response_text}")

            # Check for completion
            is_complete = is_conversation_complete(agent)
            if is_complete:
                logger.info(f"🏁 Conversation complete: phase={agent.state.phase.value}")
                # Clean up session from cache
                if session_id in _web_chat_sessions:
                    del _web_chat_sessions[session_id]

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

    # Get messages from conversation_messages table
    messages = []
    stored_messages = await conv_repo.get_messages(conv_uuid)

    if stored_messages:
        for msg in stored_messages:
            messages.append({
                "role": msg["role"],
                "content": msg["message"],
                "timestamp": msg["created_at"].isoformat() if msg["created_at"] else None
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
    1. Screening agent (interviewer) - uses pre_screening_whatsapp_agent
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

    # Build pre-screening config dict for simulator
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

    # Build simulator instruction (contains persona behavior and question context)
    simulator_instruction = build_simulator_instruction(
        config=config,
        persona=persona_enum,
        custom_persona=custom_persona,
        vacancy_title=vacancy_title
    )

    # Create screening agent using pre_screening_whatsapp_agent
    knockout_questions = [
        {"question": q["question_text"], "requirement": q["ideal_answer"] or ""}
        for q in questions if q["question_type"] == "knockout"
    ]
    open_questions = [
        q["question_text"]
        for q in questions if q["question_type"] == "qualification"
    ]

    screening_agent = create_simple_agent(
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        company_name="",
        knockout_questions=knockout_questions,
        open_questions=open_questions,
    )

    logger.info(f"🎭 Created screening agent for simulation: {vacancy_id[:8]}")

    # Track conversation
    conversation = []
    qa_pairs = []
    outcome = "unknown"
    total_turns = 0

    yield f"data: {json.dumps({'type': 'start', 'message': f'Starting simulation with {persona} persona...', 'candidate_name': candidate_name})}\n\n"

    try:
        # Run simulation using run_simulation from candidate_simulator
        # But we need to adapt it since it expects ADK agents
        # For now, let's run a simple turn-based simulation

        max_turns = 20
        turn = 0

        # Get opening message from screening agent (proper greeting)
        response = await screening_agent.get_initial_message()
        turn += 1

        yield f"data: {json.dumps({'type': 'agent', 'message': response, 'turn': turn})}\n\n"
        conversation.append({"role": "agent", "message": response, "turn": turn})

        while turn < max_turns and not is_conversation_complete(screening_agent):
            # Simulator responds using LLM with context of the actual question
            simulator_response = await _simulate_candidate_response(
                simulator_instruction, response, conversation
            )
            turn += 1

            yield f"data: {json.dumps({'type': 'candidate', 'message': simulator_response, 'turn': turn})}\n\n"
            conversation.append({"role": "candidate", "message": simulator_response, "turn": turn})

            # Screening agent processes response
            response = await screening_agent.process_message(simulator_response)
            turn += 1

            if response:
                yield f"data: {json.dumps({'type': 'agent', 'message': response, 'turn': turn})}\n\n"
                conversation.append({"role": "agent", "message": response, "turn": turn})

        # Determine outcome based on final phase and knockout results
        if screening_agent.state.phase == Phase.DONE:
            # Check if all knockout questions passed
            all_passed = all(r.get("passed", False) for r in screening_agent.state.knockout_results)
            outcome = "qualified" if all_passed else "disqualified"
        elif screening_agent.state.phase == Phase.FAILED:
            outcome = "failed"
        else:
            outcome = "incomplete"

        total_turns = turn

        yield f"data: {json.dumps({'type': 'complete', 'outcome': outcome, 'qa_pairs': qa_pairs, 'total_turns': total_turns})}\n\n"

        logger.info(f"✅ Simulation completed: {persona} persona, {total_turns} turns, outcome: {outcome}")

    except Exception as e:
        logger.error(f"Error during simulation: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    yield "data: [DONE]\n\n"


async def _simulate_candidate_response(
    simulator_instruction: str,
    agent_message: str,
    conversation_history: list[dict],
) -> str:
    """
    Generate a simulated candidate response using LLM with persona context.

    Args:
        simulator_instruction: The persona instruction (from build_simulator_instruction)
        agent_message: The last message from the screening agent
        conversation_history: List of {"role": "agent"|"candidate", "message": str}

    Returns:
        str: Simulated candidate response based on the actual question
    """
    from google import genai

    # Build conversation context for the simulator
    # Include recent history so simulator knows what's been discussed
    context_messages = []
    for msg in conversation_history[-6:]:  # Last 3 exchanges
        role = "Recruiter" if msg["role"] == "agent" else "Jij (kandidaat)"
        context_messages.append(f"{role}: {msg['message']}")

    context = "\n".join(context_messages) if context_messages else ""

    # Build prompt for simulator
    prompt = f"""Je bent een kandidaat in een WhatsApp sollicitatiegesprek.

GESPREK TOT NU TOE:
{context}

LAATSTE BERICHT VAN RECRUITER:
{agent_message}

Geef je antwoord als kandidaat. Volg je persona-instructies. MAX 1-2 zinnen!"""

    # Combine persona instruction with conversation prompt
    full_prompt = f"{simulator_instruction}\n\n{prompt}"

    client = genai.Client()
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash-lite",  # Fast model for simulation
        contents=full_prompt,
    )

    return response.text.strip() if response.text else "Ja, dat klopt."


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
