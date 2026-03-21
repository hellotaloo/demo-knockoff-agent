import os
import json
import logging
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from datetime import datetime
from enum import Enum
import asyncpg
import sentry_sdk
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.adk.events import Event, EventActions
from google.genai import types
import time
from agents.interview_question_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
from agents.candidate_simulator.agent import SimulationPersona, create_simulator_agent, run_simulation
from agents.database_query.agent import set_db_pool as set_data_query_db_pool
from agents.recruiter_analyst.agent import root_agent as recruiter_analyst_agent
from data.fixtures import load_vacancies, load_applications, load_pre_screenings
from src.utils.random_candidate import generate_random_candidate
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError
from google.adk.agents.llm_agent import Agent

# Import configuration from centralized config module
from src.config import (
    DATABASE_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
    ELEVENLABS_WEBHOOK_SECRET,
    SIMPLE_EDIT_KEYWORDS,
    SIMULATED_REASONING,
    logger
)

# Import models from centralized models module
from src.models import (
    VacancyStatus,
    VacancySource,
    InterviewChannel,
    ChannelsResponse,
    VacancyResponse,
    VacancyStatsResponse,
    DashboardStatsResponse,
    QuestionAnswerResponse,
    ApplicationResponse,
    CVApplicationRequest,
    PreScreeningQuestionRequest,
    PreScreeningQuestionResponse,
    PreScreeningRequest,
    PreScreeningResponse,
    PublishPreScreeningRequest,
    PublishPreScreeningResponse,
    StatusUpdateRequest,
    GenerateInterviewRequest,
    FeedbackRequest,
    ReorderRequest,
    DeleteQuestionRequest,
    AddQuestionRequest,
    RestoreSessionRequest,
    ScreeningChatRequest,
    SimulateInterviewRequest,
    ScreeningConversationResponse,
    OutboundScreeningRequest,
    OutboundScreeningResponse,
    ElevenLabsWebhookData,
    ElevenLabsWebhookPayload,
    CVQuestionRequest,
    CVAnalyzeRequest,
    CVQuestionAnalysisResponse,
    CVAnalyzeResponse,
    DataQueryRequest,
)

# Import database utilities
from src.database import get_db_pool, close_db_pool, run_schema_migrations

# Import services and dependencies
from src.services import SessionManager
from src.dependencies import set_session_manager as set_global_session_manager
from src.exceptions import register_exception_handlers

# Import TalooAgent registry + implementations (triggers @AgentRegistry.register)
from src.agents.registry import AgentRegistry
import src.agents.pre_screening_agent  # noqa: F401 — registers PreScreeningTalooAgent
import src.agents.document_collection_agent  # noqa: F401 — registers DocumentCollectionTalooAgent

# Import routers
from src.routers import (
    health_router,
    vacancies_router,
    applications_router,
    pre_screenings_router,
    interviews_router,
    screening_router,
    webhooks_router,
    data_query_router,
    outbound_router,
    cv_router,
    demo_router,
    documents_router,
    document_collection_router,
    scheduling_router,
    candidates_router,
    agents_router,
    activities_router,
    monitoring_router,
    auth_router,
    workspaces_router,
    livekit_webhook_router,
    teams_router,
    architecture_router,
    interview_analysis_router,
    ats_simulator_router,
    playground_router,
    playground_chat_router,
    document_collection_v2_router,
    ontology_router,
    redirect_router,
    yousign_webhook_router,
    candidacy_router,
    candidate_attributes_router,
    integrations_router,
    clients_router,
    admin_router,
)


# ============================================================================
# Logging Configuration
# ============================================================================

class EndpointFilter(logging.Filter):
    """Filter out noisy polling endpoints from access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Filter out GET requests to /vacancies/.../applications (polling endpoint)
        message = record.getMessage()
        if "/applications HTTP" in message and "GET" in message:
            return False
        return True

# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())


# ============================================================================
# Global Variables
# ============================================================================

# Global session manager
session_manager: Optional[SessionManager] = None

# Background task for workflow timer processing
_workflow_ticker_task: Optional[asyncio.Task] = None

# Background task for health monitoring
_health_monitor_task: Optional[asyncio.Task] = None


# ============================================================================
# Application Lifecycle
# ============================================================================

async def _workflow_ticker_loop():
    """Background task that processes workflow timers every 60 seconds."""
    from src.services.workflow_service import WorkflowService
    from src.workflows.orchestrator import get_orchestrator

    logger.info("🕐 Workflow ticker started (processing timers every 60s)")

    # Process immediately on startup, then every 60 seconds
    first_run = True

    while True:
        try:
            if not first_run:
                await asyncio.sleep(60)
            first_run = False

            pool = await get_db_pool()
            service = WorkflowService(pool)
            await service.ensure_table()
            result = await service.process_timers()

            # Handle auto triggers via orchestrator
            if result.get("auto_triggers"):
                orchestrator = await get_orchestrator()
                for trigger in result["auto_triggers"]:
                    try:
                        event = trigger.get("event", "auto")
                        logger.info(f"🤖 AUTO-TRIGGER (delayed): {trigger['workflow_type']} | step={trigger['step']} | event={event} | id={trigger['id'][:8]}")
                        await orchestrator.handle_event(trigger["id"], event, {})
                    except Exception as e:
                        logger.error(f"🕐 Failed to trigger auto event for {trigger['id']}: {e}")

            if result["processed"] > 0:
                logger.info(f"🕐 Workflow ticker: processed {result['processed']} timers")
        except asyncio.CancelledError:
            logger.info("🕐 Workflow ticker stopped")
            break
        except Exception as e:
            logger.error(f"🕐 Workflow ticker error: {e}")
            # Continue running despite errors
            first_run = False  # Ensure we don't retry immediately on error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - create session services on startup."""
    global session_manager, _workflow_ticker_task, _health_monitor_task

    # Initialize SessionManager
    session_manager = SessionManager(DATABASE_URL)

    # Create session services (only the ones actually used)
    # Note: Generic session_service removed — it was unused and wasted DB connections
    session_manager.create_interview_session_service(interview_agent, interview_editor_agent)
    session_manager.create_analyst_session_service(recruiter_analyst_agent)
    session_manager.create_document_session_service()

    pool = await get_db_pool()  # Initialize database pool

    # Validate TalooAgent registry (all agent types must be registered)
    AgentRegistry.validate_all()

    # Run schema migrations
    await run_schema_migrations(pool)

    # Initialize ADK session tables
    # The ADK library auto-creates tables on first use, but may show warnings
    # We suppress these by attempting a test session creation
    try:
        # Try to create and delete a test session to initialize tables
        test_session = await session_manager.interview_session_service.create_session(
            app_name="interview_question_generator",
            user_id="__init_test__",
            session_id="__init_test__"
        )
        await session_manager.interview_session_service.delete_session(
            app_name="interview_question_generator",
            user_id="__init_test__",
            session_id="__init_test__"
        )
        logger.info("✓ ADK session tables initialized successfully")
    except ValueError as e:
        # Expected on first run - ADK will create tables automatically
        if "Schema version not found" in str(e) or "malformed" in str(e):
            logger.info("ADK session tables will be auto-created on first use")
        else:
            logger.warning(f"ADK session initialization: {e}")
    except Exception as e:
        logger.warning(f"ADK session initialization (non-fatal): {e}")

    # Set up data query agent with db pool (used by recruiter analyst sub-agent)
    set_data_query_db_pool(pool)

    # Set global session_manager for dependency injection
    set_global_session_manager(session_manager)

    # Start background workflow ticker
    _workflow_ticker_task = asyncio.create_task(_workflow_ticker_loop())

    # Start background health monitor (WhatsApp alerts on outages)
    from src.services.health_monitor import health_monitor_loop
    _health_monitor_task = asyncio.create_task(health_monitor_loop())

    yield

    # Cleanup on shutdown
    if _health_monitor_task:
        _health_monitor_task.cancel()
        try:
            await _health_monitor_task
        except asyncio.CancelledError:
            pass

    if _workflow_ticker_task:
        _workflow_ticker_task.cancel()
        try:
            await _workflow_ticker_task
        except asyncio.CancelledError:
            pass

    await close_db_pool()


# ============================================================================
# Sentry Error Tracking
# ============================================================================

if os.getenv("SENTRY_DSN") and os.getenv("ENVIRONMENT") != "local":
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "production"),
    )
    logger.info(f"Sentry initialized for environment: {os.getenv('ENVIRONMENT', 'production')}")
else:
    logger.info("Sentry disabled for local development")


# ============================================================================
# Application Initialization
# ============================================================================

app = FastAPI(lifespan=lifespan)

# Register custom exception handlers
register_exception_handlers(app)

# CORS middleware — restrict origins by environment
from src.config import ENVIRONMENT

_cors_kwargs = {
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": ["*"],
}
if ENVIRONMENT == "local":
    _cors_kwargs["allow_origins"] = ["http://localhost:3000", "http://localhost:8080"]
else:
    _cors_kwargs["allow_origin_regex"] = r"https://.*\.taloo\.eu|https://.*\.vercel\.app"

app.add_middleware(CORSMiddleware, **_cors_kwargs)

# Include all routers
app.include_router(health_router)
app.include_router(vacancies_router)
app.include_router(applications_router)
app.include_router(pre_screenings_router)
app.include_router(interviews_router)
app.include_router(screening_router)
app.include_router(webhooks_router)
app.include_router(data_query_router)
app.include_router(outbound_router)
app.include_router(cv_router)
app.include_router(demo_router)
app.include_router(documents_router)
app.include_router(document_collection_router)
app.include_router(scheduling_router)
app.include_router(candidates_router)
app.include_router(agents_router)
app.include_router(activities_router)
app.include_router(monitoring_router)
app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(livekit_webhook_router)
app.include_router(teams_router)
app.include_router(architecture_router)
app.include_router(interview_analysis_router)
app.include_router(ats_simulator_router)
app.include_router(playground_router)
app.include_router(playground_chat_router)
app.include_router(document_collection_v2_router)
app.include_router(ontology_router)
app.include_router(redirect_router)
app.include_router(yousign_webhook_router)
app.include_router(candidacy_router)
app.include_router(candidate_attributes_router)
app.include_router(integrations_router)
app.include_router(clients_router)
app.include_router(admin_router)
