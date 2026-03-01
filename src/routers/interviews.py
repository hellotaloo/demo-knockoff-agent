"""
Interview Generation endpoints.
"""
import uuid
import logging
import json
import time
import asyncio
from typing import AsyncGenerator
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from google.adk.events import Event, EventActions
from google.genai import types
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from google.adk.errors.already_exists_error import AlreadyExistsError

from src.models.interview import (
    GenerateInterviewRequest,
    FeedbackRequest,
    ReorderRequest,
    DeleteQuestionRequest,
    AddQuestionRequest,
    RestoreSessionRequest
)
from src.database import get_db_pool
from src.config import SIMPLE_EDIT_KEYWORDS, SIMULATED_REASONING, logger

router = APIRouter(tags=["Interview Generation"])

# Will be set during app startup
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager


# Per-session locks to prevent concurrent feedback processing
_feedback_locks: dict[str, asyncio.Lock] = {}


def get_feedback_lock(session_id: str) -> asyncio.Lock:
    """Get or create a lock for a specific session."""
    if session_id not in _feedback_locks:
        _feedback_locks[session_id] = asyncio.Lock()
    return _feedback_locks[session_id]


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


async def stream_interview_generation(vacancy_text: str, session_id: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during interview generation."""
    global session_manager

    total_start = time.time()
    print(f"\n{'='*60}")
    print(f"[GENERATE] Started - vacancy length: {len(vacancy_text)} chars")
    print(f"[GENERATE] Using: FAST generator (no thinking)")
    print(f"{'='*60}")

    async def reset_interview_session():
        """Delete and recreate session for fresh start, handling race conditions."""
        # Try to delete existing session
        try:
            existing = await session_manager.interview_session_service.get_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
            if existing:
                await session_manager.interview_session_service.delete_session(
                    app_name="interview_generator", user_id="web", session_id=session_id
                )
        except Exception as e:
            logger.warning(f"Error checking/deleting existing session: {e}")

        # Create new session, handling case where it already exists
        try:
            await session_manager.interview_session_service.create_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            )
        except (IntegrityError, AlreadyExistsError):
            # Session exists (maybe delete failed or race condition), that's ok for generation
            logger.info(f"Session {session_id} already exists for generation")

    session_reset_start = time.time()
    await session_manager.with_session_retry(
        reset_interview_session,
        lambda: session_manager.create_interview_session_service(
            session_manager.interview_agent,
            session_manager.interview_editor_agent
        ),
        "reset interview session"
    )
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
    event_queue: asyncio.Queue = asyncio.Queue()

    async def run_agent():
        """Run the agent and put events in queue."""
        nonlocal agent_done
        try:
            async for event in session_manager.interview_runner.run_async(
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
                session = await session_manager.interview_session_service.get_session(
                    app_name="interview_generator",
                    user_id="web",
                    session_id=session_id
                )
                print(f"[TIMING] Session refetch: {time.time() - session_refetch_start:.2f}s")

                interview = get_interview_from_session(session)

                # Debug: Log vacancy_snippet values
                for q in interview.get("knockout_questions", []):
                    print(f"[DEBUG] KO {q.get('id')}: vacancy_snippet = {q.get('vacancy_snippet', 'MISSING')}")
                for q in interview.get("qualification_questions", []):
                    print(f"[DEBUG] QUAL {q.get('id')}: vacancy_snippet = {q.get('vacancy_snippet', 'MISSING')}")

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


async def stream_feedback(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during feedback processing."""
    global session_manager

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
        session = await session_manager.with_session_retry(
            lambda: session_manager.interview_session_service.get_session(
                app_name="interview_generator",
                user_id="web",
                session_id=session_id
            ),
            lambda: session_manager.create_interview_session_service(
                session_manager.interview_agent,
                session_manager.interview_editor_agent
            ),
            "fetch interview session"
        )
        session_fetch_time = time.time() - session_fetch_start
        print(f"[TIMING] Session fetch: {session_fetch_time:.2f}s")

        if not session:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found. Please generate questions first.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # === TIMING: Agent selection ===
        use_fast = should_use_fast_agent(session, message)
        active_runner = session_manager.interview_editor_runner if use_fast else session_manager.interview_runner
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
                        session = await session_manager.interview_session_service.get_session(
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


@router.post("/interview/generate")
async def generate_interview(request: GenerateInterviewRequest):
    """Generate interview questions from vacancy text with SSE streaming."""
    # Validate vacancy_id format
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vacancy ID format: {request.vacancy_id}")

    # Fetch vacancy from database
    pool = await get_db_pool()
    vacancy_row = await pool.fetchrow(
        """
        SELECT id, title, description
        FROM ats.vacancies
        WHERE id = $1
        """,
        vacancy_uuid
    )

    if not vacancy_row:
        raise HTTPException(status_code=404, detail=f"Vacancy not found: {request.vacancy_id}")

    vacancy_text = vacancy_row["description"]
    if not vacancy_text:
        raise HTTPException(status_code=400, detail="Vacancy has no description text")

    # Use vacancy_id as session_id for consistency (allows restore later)
    session_id = request.session_id or request.vacancy_id

    logger.info(f"[GENERATE] Fetched vacancy '{vacancy_row['title']}' ({len(vacancy_text)} chars)")

    return StreamingResponse(
        stream_interview_generation(vacancy_text, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/interview/feedback")
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


@router.get("/interview/session/{session_id}")
async def get_interview_session(session_id: str):
    """Get the current interview state for a session."""
    global session_manager

    try:
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        session_manager.create_interview_session_service(
            session_manager.interview_agent,
            session_manager.interview_editor_agent
        )
        session = await session_manager.interview_session_service.get_session(
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


@router.post("/interview/reorder")
async def reorder_questions(request: ReorderRequest):
    """Reorder questions without invoking the agent. Instant response."""
    global session_manager

    # Debug logging
    logger.info(f"[REORDER] Request received - session_id: {request.session_id}")
    logger.info(f"[REORDER] knockout_order: {request.knockout_order}")
    logger.info(f"[REORDER] qualification_order: {request.qualification_order}")

    try:
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        session_manager.create_interview_session_service(
            session_manager.interview_agent,
            session_manager.interview_editor_agent
        )
        session = await session_manager.interview_session_service.get_session(
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
    await session_manager.safe_append_event(
        session_manager.interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=request.session_id
    )

    return {"status": "success", "interview": interview}


@router.post("/interview/restore-session")
async def restore_session_from_db(request: RestoreSessionRequest):
    """
    Restore an interview session from saved pre-screening data.

    Use this when opening an existing pre-screening for editing.
    Creates a new session with the saved questions pre-populated,
    allowing the user to continue editing via /interview/feedback.
    """
    global session_manager

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

    # Get questions (including ideal_answer and vacancy_snippet)
    question_rows = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer, vacancy_snippet, is_approved
        FROM ats.pre_screening_questions
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
                "question": q["question_text"],
                "vacancy_snippet": q["vacancy_snippet"]
            })
        else:
            q_id = f"qual_{qual_counter}"
            qual_counter += 1
            qualification_questions.append({
                "id": q_id,
                "question": q["question_text"],
                "ideal_answer": q["ideal_answer"] or "",
                "vacancy_snippet": q["vacancy_snippet"]
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
        global session_manager
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_generator", user_id="web", session_id=session_id
        )
        if session:
            return session
        try:
            return await session_manager.interview_session_service.create_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )
        except (IntegrityError, AlreadyExistsError):
            # Session was created by another request, fetch it
            logger.info(f"Session {session_id} already exists, fetching it")
            return await session_manager.interview_session_service.get_session(
                app_name="interview_generator", user_id="web", session_id=session_id
            )

    try:
        session = await get_or_create_feedback_session()
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        session_manager.create_interview_session_service(
            session_manager.interview_agent,
            session_manager.interview_editor_agent
        )
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
    await session_manager.safe_append_event(
        session_manager.interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=session_id
    )

    return {
        "status": "success",
        "session_id": session_id,
        "interview": interview,
        "message": "Session restored from saved pre-screening"
    }


@router.post("/interview/delete")
async def delete_question(request: DeleteQuestionRequest):
    """Delete a question without invoking the agent. Instant response."""
    global session_manager

    try:
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        session_manager.create_interview_session_service(
            session_manager.interview_agent,
            session_manager.interview_editor_agent
        )
        session = await session_manager.interview_session_service.get_session(
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
    await session_manager.safe_append_event(
        session_manager.interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=request.session_id
    )

    return {"status": "success", "deleted": question_id, "interview": interview}


@router.post("/interview/add")
async def add_question(request: AddQuestionRequest):
    """Add a question without invoking the agent. Instant response."""
    global session_manager

    # Validate question type
    if request.question_type not in ("knockout", "qualification"):
        raise HTTPException(status_code=400, detail="question_type must be 'knockout' or 'qualification'")

    # Require ideal_answer for qualification questions
    if request.question_type == "qualification" and not request.ideal_answer:
        raise HTTPException(status_code=400, detail="ideal_answer is required for qualification questions")

    try:
        session = await session_manager.interview_session_service.get_session(
            app_name="interview_generator",
            user_id="web",
            session_id=request.session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating interview session service: {e}")
        session_manager.create_interview_session_service(
            session_manager.interview_agent,
            session_manager.interview_editor_agent
        )
        session = await session_manager.interview_session_service.get_session(
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
            "vacancy_snippet": request.vacancy_snippet,
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
            "vacancy_snippet": request.vacancy_snippet,
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
    await session_manager.safe_append_event(
        session_manager.interview_session_service, session, event,
        app_name="interview_generator", user_id="web", session_id=request.session_id
    )

    return {"status": "success", "added": new_id, "question": new_question, "interview": interview}
