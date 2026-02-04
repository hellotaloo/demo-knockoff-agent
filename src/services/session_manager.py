"""
Session management service - handles ADK session lifecycle and runner caching.
"""
import logging
import time
from typing import Optional, Callable, Any
from google.adk.sessions import DatabaseSessionService
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.agents.llm_agent import Agent
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from knockout_agent.agent import build_screening_instruction, conversation_complete_tool

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Centralized session management for all ADK services.

    Manages session service creation, event appending with retry logic,
    and screening runner caching.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.connect_args = {"statement_cache_size": 0}  # Supabase compatibility

        # Session services
        self.session_service: Optional[DatabaseSessionService] = None
        self.interview_session_service: Optional[DatabaseSessionService] = None
        self.analyst_session_service: Optional[DatabaseSessionService] = None
        self.screening_session_service: Optional[DatabaseSessionService] = None

        # Runners (stateful)
        self.interview_runner: Optional[Runner] = None
        self.interview_editor_runner: Optional[Runner] = None
        self.analyst_runner: Optional[Runner] = None

        # Screening runners cache (keyed by vacancy_id)
        self.screening_runners: dict[str, Runner] = {}

    def create_session_service(self) -> DatabaseSessionService:
        """Create the main session service."""
        self.session_service = DatabaseSessionService(
            db_url=self.database_url,
            connect_args=self.connect_args
        )
        logger.info("Created session service")
        return self.session_service

    def create_interview_session_service(
        self,
        interview_agent: Agent,
        interview_editor_agent: Agent
    ) -> DatabaseSessionService:
        """Create interview generator session service and runners."""
        self.interview_session_service = DatabaseSessionService(
            db_url=self.database_url,
            connect_args=self.connect_args
        )

        # Full thinking agent for initial generation
        self.interview_runner = Runner(
            agent=interview_agent,
            app_name="interview_generator",
            session_service=self.interview_session_service
        )

        # Fast agent for simple edits (no thinking)
        self.interview_editor_runner = Runner(
            agent=interview_editor_agent,
            app_name="interview_generator",  # Same app_name to share sessions
            session_service=self.interview_session_service
        )

        logger.info("Created interview generator session service with both runners (generator + editor)")
        return self.interview_session_service

    def create_analyst_session_service(
        self,
        recruiter_analyst_agent: Agent
    ) -> DatabaseSessionService:
        """Create recruiter analyst session service and runner."""
        self.analyst_session_service = DatabaseSessionService(
            db_url=self.database_url,
            connect_args=self.connect_args
        )
        self.analyst_runner = Runner(
            agent=recruiter_analyst_agent,
            app_name="recruiter_analyst",
            session_service=self.analyst_session_service
        )
        logger.info("Created recruiter analyst session service and runner")
        return self.analyst_session_service

    def create_screening_session_service(self) -> DatabaseSessionService:
        """Create screening chat session service."""
        self.screening_session_service = DatabaseSessionService(
            db_url=self.database_url,
            connect_args=self.connect_args
        )
        logger.info("Created screening chat session service")
        return self.screening_session_service

    async def safe_append_event(
        self,
        session_service: DatabaseSessionService,
        session,
        event: Event,
        app_name: str,
        user_id: str,
        session_id: str
    ):
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

    async def with_session_retry(
        self,
        operation: Callable,
        recreate_service: Callable,
        operation_name: str = "operation"
    ) -> Any:
        """
        Execute an operation with automatic session service recreation on connection errors.

        Args:
            operation: Async function to execute
            recreate_service: Function to call to recreate the session service
            operation_name: Name of the operation for logging

        Returns:
            Result of the operation

        Raises:
            Exception: If operation fails after retry
        """
        try:
            return await operation()
        except (InterfaceError, OperationalError) as e:
            logger.warning(f"Database connection error during {operation_name}, recreating session service: {e}")
            recreate_service()
            return await operation()

    def get_or_create_screening_runner(
        self,
        vacancy_id: str,
        pre_screening: dict,
        vacancy_title: str
    ) -> Runner:
        """
        Get or create a screening runner for a specific vacancy.

        Runners are cached per vacancy_id to avoid recreating them on every request.
        """
        # Check cache
        if vacancy_id in self.screening_runners:
            logger.info(f"Using cached screening runner for vacancy {vacancy_id[:8]}")
            return self.screening_runners[vacancy_id]

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
            session_service=self.screening_session_service
        )

        # Cache it
        self.screening_runners[vacancy_id] = runner
        logger.info(f"✅ Screening runner ready: screening_{vacancy_id[:8]}")

        return runner

    def invalidate_screening_runner(self, vacancy_id: str):
        """Remove a screening runner from cache (e.g., after pre-screening update)."""
        if vacancy_id in self.screening_runners:
            del self.screening_runners[vacancy_id]
            logger.info(f"🔄 Cleared cached screening runner for vacancy {vacancy_id[:8]}...")
