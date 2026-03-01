"""
Interview service - handles interview generation, feedback, and question management.
"""
import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional
from google.genai import types
from google.adk.events import Event, EventActions
from src.config import SIMPLE_EDIT_KEYWORDS, SIMULATED_REASONING

logger = logging.getLogger(__name__)


class InterviewService:
    """
    Service for interview generation and management.
    
    Handles interview generation, feedback processing, question manipulation,
    and session state management.
    """
    
    def __init__(self, session_manager):
        self.session_manager = session_manager
        # Feedback locks to prevent concurrent processing
        self._feedback_locks: dict[str, asyncio.Lock] = {}
    
    def get_feedback_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific session to prevent concurrent feedback processing."""
        if session_id not in self._feedback_locks:
            self._feedback_locks[session_id] = asyncio.Lock()
        return self._feedback_locks[session_id]
    
    @staticmethod
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
    
    @staticmethod
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
    
    @staticmethod
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
    
    def should_use_fast_agent(self, session, message: str) -> bool:
        """
        Determine if we should use the fast editor agent (no thinking) 
        or the full generator agent (with thinking).
        
        Returns True for simple edits, False for complex operations.
        """
        # No interview yet = always use full generator
        interview = self.get_interview_from_session(session)
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
    
    async def stream_interview_generation(
        self,
        vacancy_text: str,
        session_id: str
    ) -> AsyncGenerator[str, None]:
        """Stream SSE events during interview generation."""
        total_start = time.time()
        print(f"\n{'='*60}")
        print(f"[GENERATE] Started - vacancy length: {len(vacancy_text)} chars")
        print(f"[GENERATE] Using: FAST generator (no thinking)")
        print(f"{'='*60}")
        
        async def reset_interview_session():
            """Delete and recreate session for fresh start, handling race conditions."""
            from sqlalchemy.exc import IntegrityError
            from google.adk.errors.already_exists_error import AlreadyExistsError
            
            # Try to delete existing session
            try:
                existing = await self.session_manager.interview_session_service.get_session(
                    app_name="interview_generator", user_id="web", session_id=session_id
                )
                if existing:
                    await self.session_manager.interview_session_service.delete_session(
                        app_name="interview_generator", user_id="web", session_id=session_id
                    )
            except Exception as e:
                logger.warning(f"Error checking/deleting existing session: {e}")
            
            # Create new session, handling case where it already exists
            try:
                await self.session_manager.interview_session_service.create_session(
                    app_name="interview_generator",
                    user_id="web",
                    session_id=session_id
                )
            except (IntegrityError, AlreadyExistsError):
                # Session exists (maybe delete failed or race condition), that's ok for generation
                logger.info(f"Session {session_id} already exists for generation")
        
        session_reset_start = time.time()
        from interview_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
        await self.session_manager.with_session_retry(
            reset_interview_session,
            lambda: self.session_manager.create_interview_session_service(interview_agent, interview_editor_agent),
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
                async for event in self.session_manager.interview_runner.run_async(
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
        
        # Simulated reasoning messages to show while agent thinks
        reasoning_idx = 0
        reasoning_interval = 1.5  # seconds between simulated messages
        last_reasoning_time = time.time()
        
        # Process events from queue (agent events + simulated reasoning)
        while True:
            try:
                # Check if we should send a simulated reasoning message
                current_time = time.time()
                if (reasoning_idx < len(SIMULATED_REASONING) and 
                    current_time - last_reasoning_time >= reasoning_interval and 
                    not agent_done):
                    # Send simulated reasoning
                    yield f"data: {json.dumps({'type': 'reasoning', 'text': SIMULATED_REASONING[reasoning_idx]})}\n\n"
                    reasoning_idx += 1
                    last_reasoning_time = current_time
                
                # Get next event from queue (with timeout to allow reasoning messages)
                try:
                    event_type, event_data = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue  # No event yet, loop to check for reasoning message
                
                if event_type == "done":
                    break  # Agent finished
                
                if event_type == "error":
                    logger.error(f"Agent error: {event_data}")
                    yield f"data: {json.dumps({'type': 'error', 'message': str(event_data)})}\n\n"
                    break
                
                # Process agent event
                event = event_data
                event_count += 1
                event_time = time.time() - agent_start
                
                if first_event_time is None:
                    first_event_time = event_time
                    print(f"[TIMING] First event received: {event_time:.2f}s (time to first response)")
                
                # Process the event and yield to client
                # (simplified - full implementation would handle all event types)
                if hasattr(event, 'content') and event.content:
                    yield f"data: {json.dumps({'type': 'content', 'content': str(event.content)})}\n\n"
            
            except Exception as e:
                logger.error(f"Error processing event: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break
        
        # Wait for agent task to complete
        await agent_task
        
        # Send completion
        total_time = time.time() - total_start
        print(f"[TIMING] Total generation time: {total_time:.2f}s")
        yield "data: [DONE]\n\n"
    
    async def stream_feedback(
        self,
        session_id: str,
        message: str
    ) -> AsyncGenerator[str, None]:
        """Stream SSE events during feedback processing."""
        # Acquire per-session lock to prevent concurrent processing
        lock = self.get_feedback_lock(session_id)
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
            from interview_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
            session = await self.session_manager.with_session_retry(
                lambda: self.session_manager.interview_session_service.get_session(
                    app_name="interview_generator",
                    user_id="web",
                    session_id=session_id
                ),
                lambda: self.session_manager.create_interview_session_service(interview_agent, interview_editor_agent),
                "fetch interview session"
            )
            session_fetch_time = time.time() - session_fetch_start
            print(f"[TIMING] Session fetch: {session_fetch_time:.2f}s")
            
            if not session:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found. Please generate questions first.'})}\n\n"
                yield "data: [DONE]\n\n"
                return
            
            # === TIMING: Agent selection ===
            use_fast = self.should_use_fast_agent(session, message)
            active_runner = self.session_manager.interview_editor_runner if use_fast else self.session_manager.interview_runner
            agent_type = "FAST editor (no thinking)" if use_fast else "FULL generator (with thinking)"
            
            # Log session history size
            history_count = len(session.events) if hasattr(session, 'events') else 0
            print(f"[AGENT] Using: {agent_type}")
            print(f"[AGENT] Message length: {len(message)} chars")
            print(f"[AGENT] Session history: {history_count} events")
            
            status_message = 'Feedback verwerken...' if use_fast else 'Feedback analyseren...'
            yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': status_message})}\n\n"
            
            # Run agent with feedback
            content = types.Content(role="user", parts=[types.Part(text=message)])
            
            # Stream events from agent
            try:
                async for event in active_runner.run_async(
                    user_id="web",
                    session_id=session_id,
                    new_message=content
                ):
                    # Process and yield event
                    if hasattr(event, 'content') and event.content:
                        yield f"data: {json.dumps({'type': 'content', 'content': str(event.content)})}\n\n"
            except Exception as e:
                logger.error(f"Feedback error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            
            total_time = time.time() - total_start
            print(f"[TIMING] Total feedback time: {total_time:.2f}s")
            yield "data: [DONE]\n\n"
