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
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.adk.events import Event, EventActions
from google.genai import types
import time
from interview_generator.agent import generator_agent as interview_agent, editor_agent as interview_editor_agent
from candidate_simulator.agent import SimulationPersona, create_simulator_agent, run_simulation
from data_query_agent.agent import set_db_pool as set_data_query_db_pool
from recruiter_analyst.agent import root_agent as recruiter_analyst_agent
from fixtures import load_vacancies, load_applications, load_pre_screenings
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
    elevenlabs_router,
    auth_router,
    workspaces_router,
    vapi_router,
    teams_router,
    workflow_poc_router,
)
import src.routers.pre_screenings as pre_screenings_router_module
import src.routers.interviews as interviews_router_module
import src.routers.data_query as data_query_router_module
import src.routers.document_collection as document_collection_router_module


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


# ============================================================================
# Application Lifecycle
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - create session services on startup."""
    global session_manager

    # Initialize SessionManager
    session_manager = SessionManager(DATABASE_URL)

    # Create all session services
    # Note: Screening now uses pre_screening_whatsapp_agent with JSON state, not ADK sessions
    session_manager.create_session_service()
    session_manager.create_interview_session_service(interview_agent, interview_editor_agent)
    session_manager.create_analyst_session_service(recruiter_analyst_agent)
    session_manager.create_document_session_service()

    pool = await get_db_pool()  # Initialize database pool

    # Run schema migrations
    await run_schema_migrations(pool)

    # Initialize ADK session tables
    # The ADK library auto-creates tables on first use, but may show warnings
    # We suppress these by attempting a test session creation
    try:
        # Try to create and delete a test session to initialize tables
        test_session = await session_manager.interview_session_service.create_session(
            app_name="interview_generator",
            user_id="__init_test__",
            session_id="__init_test__"
        )
        await session_manager.interview_session_service.delete_session(
            app_name="interview_generator",
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

    # Set session_manager in routers that need it (for backwards compatibility)
    pre_screenings_router_module.set_session_manager(session_manager)
    interviews_router_module.set_session_manager(session_manager)
    data_query_router_module.set_session_manager(session_manager)
    document_collection_router_module.set_session_manager(session_manager)

    yield
    # Cleanup on shutdown
    await close_db_pool()


# ============================================================================
# Application Initialization
# ============================================================================

app = FastAPI(lifespan=lifespan)

# Register custom exception handlers
register_exception_handlers(app)

# CORS middleware for cross-origin requests from job board
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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
app.include_router(elevenlabs_router)
app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(vapi_router)
app.include_router(teams_router)
app.include_router(workflow_poc_router)

# Twilio client for proactive messages
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
