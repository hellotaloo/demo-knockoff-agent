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

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Centralized session management for all ADK services.

    Manages session service creation, event appending with retry logic,
    and document runner caching.

    Note: Screening (WhatsApp/Web chat) now uses pre_screening_whatsapp_agent
    with JSON state storage instead of ADK sessions.
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        # SQLAlchemy engine kwargs optimized for Supabase Session Mode Pooler
        # - pool_pre_ping: Validates connections before use (prevents stale connection errors)
        # - pool_recycle: Recycle connections every 5 min (match Supabase pooler timeout)
        # - pool_size: Smaller pools per service to avoid connection exhaustion
        # - connect_args: Disable statement caching for Supabase compatibility
        self.engine_kwargs = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 2,
            "max_overflow": 2,
            "connect_args": {"statement_cache_size": 0},
        }

        # Session services
        self.session_service: Optional[DatabaseSessionService] = None
        self.interview_session_service: Optional[DatabaseSessionService] = None
        self.analyst_session_service: Optional[DatabaseSessionService] = None
        self.document_session_service: Optional[DatabaseSessionService] = None

        # Runners (stateful)
        self.interview_runner: Optional[Runner] = None
        self.interview_editor_runner: Optional[Runner] = None
        self.analyst_runner: Optional[Runner] = None

        # Document collection runners cache (keyed by collection_id)
        self.document_runners: dict[str, Runner] = {}

    def create_session_service(self) -> DatabaseSessionService:
        """Create the main session service."""
        self.session_service = DatabaseSessionService(
            db_url=self.database_url,
            **self.engine_kwargs
        )
        logger.info("Created session service (pool_pre_ping=True, pool_recycle=300s)")
        return self.session_service

    def create_interview_session_service(
        self,
        interview_agent: Agent,
        interview_editor_agent: Agent
    ) -> DatabaseSessionService:
        """Create interview generator session service and runners."""
        self.interview_session_service = DatabaseSessionService(
            db_url=self.database_url,
            **self.engine_kwargs
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
            **self.engine_kwargs
        )
        self.analyst_runner = Runner(
            agent=recruiter_analyst_agent,
            app_name="recruiter_analyst",
            session_service=self.analyst_session_service
        )
        logger.info("Created recruiter analyst session service and runner")
        return self.analyst_session_service

    def create_document_session_service(self) -> DatabaseSessionService:
        """Create document collection session service."""
        self.document_session_service = DatabaseSessionService(
            db_url=self.database_url,
            **self.engine_kwargs
        )
        logger.info("Created document collection session service (pool_pre_ping=True)")
        return self.document_session_service

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

    def get_or_create_document_runner(
        self,
        collection_id: str,
        candidate_name: str,
        documents_required: list[str]
    ) -> Runner:
        """
        Get or create a document collection runner for a specific collection.

        Runners are cached per collection_id to avoid recreating them on every webhook.
        """
        # Check cache
        if collection_id in self.document_runners:
            logger.info(f"Using cached document runner for collection {collection_id[:8]}")
            return self.document_runners[collection_id]

        # Create agent
        from document_collection_agent import create_document_collection_agent
        agent = create_document_collection_agent(
            collection_id=collection_id,
            candidate_name=candidate_name,
            documents_required=documents_required
        )

        # Create runner
        runner = Runner(
            agent=agent,
            app_name="document_collection",
            session_service=self.document_session_service
        )

        # Cache it
        self.document_runners[collection_id] = runner
        logger.info(f"✅ Document collection runner ready: {collection_id[:8]}")

        return runner

    def invalidate_document_runner(self, collection_id: str):
        """Remove a document runner from cache."""
        if collection_id in self.document_runners:
            del self.document_runners[collection_id]
            logger.info(f"🔄 Cleared cached document runner for collection {collection_id[:8]}...")

    async def delete_session(self, app_name: str, user_id: str, session_id: str):
        """
        Delete a specific ADK session from the database.

        Args:
            app_name: The ADK app name (e.g., "document_collection")
            user_id: The user ID (e.g., "whatsapp", "web")
            session_id: The UUID session ID
        """
        try:
            if app_name == "document_collection" and self.document_session_service:
                await self.document_session_service.delete_session(
                    app_name=app_name, user_id=user_id, session_id=session_id
                )
                logger.info(f"🗑️ Deleted ADK session: {app_name}/{user_id}/{session_id[:8]}...")
        except Exception as e:
            # Log but don't fail - session may already be deleted
            logger.warning(f"Could not delete ADK session {session_id[:8]}: {e}")
