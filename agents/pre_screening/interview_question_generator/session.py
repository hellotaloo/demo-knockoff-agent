"""
Interview session management — handles generation, feedback, and question manipulation.

This module contains all business logic for the interview question generator agent.
The router (src/routers/interviews.py) is a thin HTTP layer that delegates here.
"""
import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator

import asyncpg
from google.adk.events import Event, EventActions
from google.genai import types
from sqlalchemy.exc import IntegrityError

from src.config import SIMPLE_EDIT_KEYWORDS, SIMULATED_REASONING

logger = logging.getLogger(__name__)

APP_NAME = "interview_question_generator"
USER_ID = "web"


# =============================================================================
# Pure helper functions (no dependencies)
# =============================================================================

def get_interview_from_session(session) -> dict:
    """
    Safely get the interview dict from session state.
    Handles both dict and JSON string storage formats.
    """
    if not session:
        return {}

    interview = session.state.get("interview", {})

    if isinstance(interview, str):
        try:
            interview = json.loads(interview)
        except (json.JSONDecodeError, TypeError):
            return {}

    return interview if isinstance(interview, dict) else {}


def get_questions_snapshot(interview: dict) -> str:
    """
    Create a comparable snapshot of questions (ignoring change_status).
    Used to detect whether the agent actually modified questions in a turn.
    """
    if not interview:
        return ""

    ko = interview.get("knockout_questions", [])
    qual = interview.get("qualification_questions", [])

    ko_snap = [(q.get("id"), q.get("question")) for q in ko]
    qual_snap = [(q.get("id"), q.get("question"), q.get("ideal_answer")) for q in qual]

    return str((ko_snap, qual_snap))


def reset_change_statuses(interview: dict) -> dict:
    """Reset all change_status values to 'unchanged'."""
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
    """
    interview = get_interview_from_session(session)
    if not interview.get("knockout_questions"):
        return False

    if len(message) < 150:
        return True

    message_lower = message.lower()
    if any(keyword in message_lower for keyword in SIMPLE_EDIT_KEYWORDS):
        return True

    return False


def _build_feedback_context(interview: dict, message: str) -> str:
    """
    Build the context string sent to the agent during feedback.
    Includes current interview state so the agent knows what exists.
    """
    if not interview:
        return message

    ko_questions = interview.get("knockout_questions", [])
    qual_questions = interview.get("qualification_questions", [])

    ko_formatted = "\n".join([f'  - {q["id"]}: "{q["question"]}"' for q in ko_questions])
    qual_formatted = "\n".join([
        f'  - {q["id"]}: "{q["question"]}" (ideal_answer: "{q.get("ideal_answer", "")}")'
        for q in qual_questions
    ])

    return f"""[SYSTEEM: Huidige interview structuur - BEHOUD alle vragen exact zoals ze zijn, tenzij de gebruiker expliciet vraagt om te wijzigen]

Huidige knockout vragen:
{ko_formatted}

Huidige kwalificatievragen (met ideal_answer):
{qual_formatted}

Andere velden:
- intro: "{interview.get('intro', '')}"
- knockout_failed_action: "{interview.get('knockout_failed_action', '')}"
- final_action: "{interview.get('final_action', '')}"
- approved_ids: {interview.get('approved_ids', [])}

Gebruiker: {message}"""


def _build_interview_from_db_rows(ps_row, question_rows) -> dict:
    """Build interview dict from database rows (for session restore)."""
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

    return {
        "intro": ps_row["intro"] or "",
        "knockout_questions": knockout_questions,
        "knockout_failed_action": ps_row["knockout_failed_action"] or "",
        "qualification_questions": qualification_questions,
        "final_action": ps_row["final_action"] or "",
        "approved_ids": approved_ids
    }


# =============================================================================
# Interview session handler
# =============================================================================

class InterviewSessionHandler:
    """
    Manages ADK sessions and agent interactions for interview question generation.

    Handles generation, feedback processing, question manipulation,
    and session state persistence.
    """

    def __init__(self, session_manager, pool: asyncpg.Pool):
        self.session_manager = session_manager
        self.pool = pool
        self._feedback_locks: dict[str, asyncio.Lock] = {}

    def _get_feedback_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._feedback_locks:
            self._feedback_locks[session_id] = asyncio.Lock()
        return self._feedback_locks[session_id]

    def _recreate_session_service(self):
        """Recreate the interview session service (e.g. after a connection error)."""
        self.session_manager.create_interview_session_service(
            self.session_manager.interview_agent,
            self.session_manager.interview_editor_agent
        )

    async def _get_session(self, session_id: str):
        """Get a session with automatic retry on connection errors."""
        return await self.session_manager.with_session_retry(
            lambda: self.session_manager.interview_session_service.get_session(
                app_name=APP_NAME, user_id=USER_ID, session_id=session_id
            ),
            self._recreate_session_service,
            "fetch interview session"
        )

    async def _update_session_state(self, session, session_id: str, interview: dict, invocation_prefix: str):
        """Persist interview state to the ADK session via an append_event."""
        state_delta = {"interview": interview}
        actions = EventActions(state_delta=state_delta)
        event = Event(
            invocation_id=f"{invocation_prefix}_{int(time.time())}",
            author="system",
            actions=actions,
            timestamp=time.time()
        )
        await self.session_manager.safe_append_event(
            self.session_manager.interview_session_service, session, event,
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )

    # -------------------------------------------------------------------------
    # Vacancy / config helpers
    # -------------------------------------------------------------------------

    async def fetch_vacancy_text(self, vacancy_id: str) -> tuple[str, str]:
        """
        Fetch vacancy from DB and build the text prompt for the agent.
        Returns (vacancy_text, vacancy_title).
        Raises ValueError if vacancy not found or has no description.
        """
        vacancy_uuid = uuid.UUID(vacancy_id)

        vacancy_row = await self.pool.fetchrow(
            "SELECT id, title, description FROM ats.vacancies WHERE id = $1",
            vacancy_uuid
        )
        if not vacancy_row:
            raise ValueError(f"Vacancy not found: {vacancy_id}")

        vacancy_description = vacancy_row["description"]
        if not vacancy_description:
            raise ValueError("Vacancy has no description text")

        vacancy_title = vacancy_row["title"] or ""
        vacancy_text = f"Vacaturetitel: {vacancy_title}\n\n{vacancy_description}" if vacancy_title else vacancy_description

        # Append custom generator instructions if configured
        workspace_id = await self.pool.fetchval(
            "SELECT workspace_id FROM ats.vacancies WHERE id = $1", vacancy_uuid
        )
        if workspace_id:
            config_row = await self.pool.fetchrow(
                "SELECT settings FROM agents.agent_config WHERE workspace_id = $1 AND config_type = 'pre_screening' AND is_active = true LIMIT 1",
                workspace_id,
            )
            if config_row:
                settings = config_row["settings"] if isinstance(config_row["settings"], dict) else json.loads(config_row["settings"])
                custom_instructions = (settings.get("generator", {}).get("custom_instructions") or "").strip()
                if custom_instructions:
                    vacancy_text += f"\n\n---\nEXTRA INSTRUCTIES VAN DE RECRUITER:\n{custom_instructions}"
                    logger.info(f"[GENERATE] Appended custom instructions ({len(custom_instructions)} chars)")

        return vacancy_text, vacancy_title

    # -------------------------------------------------------------------------
    # SSE streaming: generation
    # -------------------------------------------------------------------------

    async def stream_interview_generation(
        self, vacancy_text: str, session_id: str, vacancy_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream SSE events during interview generation."""
        from google.adk.errors.already_exists_error import AlreadyExistsError
        from src.utils.sse_helpers import sse_done, sse_error, sse_status

        total_start = time.time()
        logger.info(f"[GENERATE] Started - vacancy length: {len(vacancy_text)} chars")

        # Reset session for a fresh generation
        async def reset_interview_session():
            svc = self.session_manager.interview_session_service
            try:
                existing = await svc.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
                if existing:
                    await svc.delete_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
            except Exception as e:
                logger.warning(f"Error checking/deleting existing session: {e}")

            try:
                await svc.create_session(
                    app_name=APP_NAME, user_id=USER_ID, session_id=session_id,
                    state={"vacancy_id": vacancy_id},
                )
            except (IntegrityError, AlreadyExistsError):
                logger.info(f"Session {session_id} already exists for generation")

        await self.session_manager.with_session_retry(
            reset_interview_session, self._recreate_session_service, "reset interview session"
        )

        yield sse_status('thinking', 'Vacature analyseren...')

        content = types.Content(role="user", parts=[types.Part(text=vacancy_text)])

        # Run agent in background, interleave simulated reasoning messages
        agent_start = time.time()
        event_count = 0
        agent_done = False
        event_queue: asyncio.Queue = asyncio.Queue()

        async def run_agent():
            nonlocal agent_done
            try:
                async for event in self.session_manager.interview_runner.run_async(
                    user_id=USER_ID, session_id=session_id, new_message=content
                ):
                    await event_queue.put(("event", event))
            except Exception as e:
                await event_queue.put(("error", e))
            finally:
                agent_done = True
                await event_queue.put(("done", None))

        agent_task = asyncio.create_task(run_agent())

        reasoning_index = 0
        reasoning_interval = 3.0
        last_reasoning_time = time.time()

        try:
            while True:
                current_time = time.time()
                if (not agent_done
                        and reasoning_index < len(SIMULATED_REASONING)
                        and current_time - last_reasoning_time >= reasoning_interval):
                    yield f"data: {json.dumps({'type': 'thinking', 'content': SIMULATED_REASONING[reasoning_index]})}\n\n"
                    reasoning_index += 1
                    last_reasoning_time = current_time

                try:
                    event_type, event_data = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if event_type == "done":
                    break
                if event_type == "error":
                    raise event_data

                event = event_data
                event_count += 1

                if hasattr(event, 'tool_calls') and event.tool_calls:
                    yield sse_status('tool_call', 'Vragen genereren...')

                if event.is_final_response() and event.content and event.content.parts:
                    response_text = event.content.parts[0].text

                    session = await self.session_manager.interview_session_service.get_session(
                        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
                    )
                    interview = get_interview_from_session(session)

                    total_time = time.time() - total_start
                    logger.info(f"[GENERATE] Completed in {total_time:.2f}s ({event_count} events)")

                    yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'interview': interview, 'session_id': session_id})}\n\n"
        except Exception as e:
            logger.error(f"Error during interview generation: {e}")
            yield sse_error(str(e))
        finally:
            if not agent_task.done():
                agent_task.cancel()

        yield sse_done()

    # -------------------------------------------------------------------------
    # SSE streaming: feedback
    # -------------------------------------------------------------------------

    async def stream_feedback(self, session_id: str, message: str) -> AsyncGenerator[str, None]:
        """Stream SSE events during feedback processing."""
        from src.utils.sse_helpers import sse_done, sse_error, sse_status

        lock = self._get_feedback_lock(session_id)
        if lock.locked():
            logger.info(f"[FEEDBACK] Session {session_id} already processing, rejecting duplicate")
            yield sse_error('Een verzoek wordt al verwerkt. Even geduld.')
            yield sse_done()
            return

        async with lock:
            total_start = time.time()
            logger.info(f"[FEEDBACK] Started - message: {message[:80]}...")

            session = await self._get_session(session_id)
            if not session:
                yield sse_error('Session not found. Please generate questions first.')
                yield sse_done()
                return

            # Select agent based on message complexity
            use_fast = should_use_fast_agent(session, message)
            active_runner = (
                self.session_manager.interview_editor_runner if use_fast
                else self.session_manager.interview_runner
            )
            logger.info(f"[FEEDBACK] Using {'FAST editor' if use_fast else 'FULL generator'}, message length: {len(message)}")

            status_message = 'Feedback verwerken...' if use_fast else 'Feedback analyseren...'
            yield sse_status('thinking', status_message)

            # Build context with current interview state
            current_interview = get_interview_from_session(session)
            interview_snapshot_before = get_questions_snapshot(current_interview)
            state_context = _build_feedback_context(current_interview, message)

            content = types.Content(role="user", parts=[types.Part(text=state_context)])

            agent_start = time.time()
            event_count = 0

            try:
                async for event in active_runner.run_async(
                    user_id=USER_ID, session_id=session_id, new_message=content
                ):
                    event_count += 1

                    if hasattr(event, 'tool_calls') and event.tool_calls:
                        yield sse_status('tool_call', 'Vragen aanpassen...')

                    if event.is_final_response():
                        response_text = ""
                        if event.content and event.content.parts:
                            response_text = event.content.parts[0].text if hasattr(event.content.parts[0], 'text') else str(event.content.parts[0])
                        else:
                            response_text = "Wijzigingen opgeslagen."

                        # Re-fetch session to get updated interview
                        session = await self.session_manager.interview_session_service.get_session(
                            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
                        )
                        interview = get_interview_from_session(session)

                        # Detect if agent actually changed questions
                        interview_snapshot_after = get_questions_snapshot(interview)
                        if interview_snapshot_before == interview_snapshot_after:
                            interview = reset_change_statuses(interview)

                        total_time = time.time() - total_start
                        logger.info(f"[FEEDBACK] Completed in {total_time:.2f}s ({event_count} events)")

                        yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'interview': interview})}\n\n"
            except Exception as e:
                logger.error(f"Error during feedback processing: {e}")
                yield sse_error(str(e))

            yield sse_done()

    # -------------------------------------------------------------------------
    # Session state operations (instant, no agent involved)
    # -------------------------------------------------------------------------

    async def get_session_interview(self, session_id: str) -> dict:
        """Get the current interview state for a session. Raises ValueError if not found."""
        session = await self._get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        return get_interview_from_session(session)

    async def reorder_questions(
        self, session_id: str, knockout_order: list[str] | None, qualification_order: list[str] | None
    ) -> dict:
        """Reorder questions in a session. Returns updated interview."""
        session = await self._get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        interview = get_interview_from_session(session)
        if not interview:
            raise ValueError("No interview in session")

        if knockout_order:
            id_to_question = {q["id"]: q for q in interview.get("knockout_questions", [])}
            for qid in knockout_order:
                if qid not in id_to_question:
                    raise ValueError(f"Unknown question ID: {qid}")
            interview["knockout_questions"] = [id_to_question[qid] for qid in knockout_order]

        if qualification_order:
            id_to_question = {q["id"]: q for q in interview.get("qualification_questions", [])}
            for qid in qualification_order:
                if qid not in id_to_question:
                    raise ValueError(f"Unknown question ID: {qid}")
            interview["qualification_questions"] = [id_to_question[qid] for qid in qualification_order]

        await self._update_session_state(session, session_id, interview, "reorder")
        return interview

    async def delete_question(self, session_id: str, question_id: str) -> dict:
        """Delete a question from a session. Returns updated interview."""
        session = await self._get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        interview = get_interview_from_session(session)
        if not interview:
            raise ValueError("No interview in session")

        deleted = False
        if question_id.startswith("ko_"):
            original_len = len(interview.get("knockout_questions", []))
            interview["knockout_questions"] = [
                q for q in interview.get("knockout_questions", []) if q["id"] != question_id
            ]
            deleted = len(interview["knockout_questions"]) < original_len
        elif question_id.startswith("qual_"):
            original_len = len(interview.get("qualification_questions", []))
            interview["qualification_questions"] = [
                q for q in interview.get("qualification_questions", []) if q["id"] != question_id
            ]
            deleted = len(interview["qualification_questions"]) < original_len

        if not deleted:
            raise ValueError(f"Question not found: {question_id}")

        # Remove from approved_ids if present
        if question_id in interview.get("approved_ids", []):
            interview["approved_ids"] = [qid for qid in interview["approved_ids"] if qid != question_id]

        await self._update_session_state(session, session_id, interview, f"delete_{question_id}")
        return interview

    async def add_question(
        self, session_id: str, question_type: str, question: str,
        ideal_answer: str | None = None, vacancy_snippet: str | None = None
    ) -> tuple[str, dict, dict]:
        """Add a question to a session. Returns (new_id, new_question, interview)."""
        if question_type not in ("knockout", "qualification"):
            raise ValueError("question_type must be 'knockout' or 'qualification'")
        if question_type == "qualification" and not ideal_answer:
            raise ValueError("ideal_answer is required for qualification questions")

        session = await self._get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        interview = get_interview_from_session(session)
        if not interview:
            raise ValueError("No interview in session")

        if question_type == "knockout":
            existing_ids = [q["id"] for q in interview.get("knockout_questions", [])]
            n = 1
            while f"ko_{n}" in existing_ids:
                n += 1
            new_id = f"ko_{n}"
            new_question_obj = {
                "id": new_id, "question": question,
                "vacancy_snippet": vacancy_snippet, "change_status": "new"
            }
            interview.setdefault("knockout_questions", []).append(new_question_obj)
        else:
            existing_ids = [q["id"] for q in interview.get("qualification_questions", [])]
            n = 1
            while f"qual_{n}" in existing_ids:
                n += 1
            new_id = f"qual_{n}"
            new_question_obj = {
                "id": new_id, "question": question, "ideal_answer": ideal_answer,
                "vacancy_snippet": vacancy_snippet, "change_status": "new"
            }
            interview.setdefault("qualification_questions", []).append(new_question_obj)

        await self._update_session_state(session, session_id, interview, f"add_{new_id}")
        return new_id, new_question_obj, interview

    async def restore_session_from_db(self, vacancy_id: str) -> tuple[str, dict]:
        """
        Restore an interview session from saved pre-screening data.
        Returns (session_id, interview).
        """
        from google.adk.errors.already_exists_error import AlreadyExistsError

        vacancy_uuid = uuid.UUID(vacancy_id)

        ps_row = await self.pool.fetchrow(
            "SELECT id, intro, knockout_failed_action, final_action FROM pre_screenings WHERE vacancy_id = $1",
            vacancy_uuid
        )
        if not ps_row:
            raise ValueError("No pre-screening found for this vacancy")

        question_rows = await self.pool.fetch(
            """
            SELECT id, question_type, position, question_text, ideal_answer, vacancy_snippet, is_approved
            FROM agents.pre_screening_questions
            WHERE pre_screening_id = $1
            ORDER BY question_type, position
            """,
            ps_row["id"]
        )

        interview = _build_interview_from_db_rows(ps_row, question_rows)
        session_id = vacancy_id

        # Get or create session
        svc = self.session_manager.interview_session_service
        session = await svc.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
        if not session:
            try:
                session = await svc.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
            except (IntegrityError, AlreadyExistsError):
                logger.info(f"Session {session_id} already exists, fetching it")
                session = await svc.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)

        await self._update_session_state(session, session_id, interview, "restore")
        return session_id, interview
