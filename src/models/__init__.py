"""
Taloo Backend API Models.

This module re-exports all model classes for convenient importing.
"""

# Common models
from .common import PaginatedResponse

# Enums
from .enums import VacancyStatus, VacancySource, InterviewChannel

# Vacancy models
from .vacancy import (
    ChannelsResponse,
    AgentStatusResponse,
    AgentsResponse,
    RecruiterSummary,
    ClientSummary,
    VacancyResponse,
    VacancyStatsResponse,
    DashboardStatsResponse,
)

# Application models
from .application import (
    QuestionAnswerResponse,
    ApplicationResponse,
    CVApplicationRequest,
)

# Pre-screening models
from .pre_screening import (
    PreScreeningQuestionRequest,
    PreScreeningQuestionResponse,
    PreScreeningRequest,
    PreScreeningResponse,
    PublishPreScreeningRequest,
    PublishPreScreeningResponse,
    StatusUpdateRequest,
)

# Interview models
from .interview import (
    GenerateInterviewRequest,
    FeedbackRequest,
    ReorderRequest,
    DeleteQuestionRequest,
    AddQuestionRequest,
    RestoreSessionRequest,
)

# Screening models
from .screening import (
    ScreeningChatRequest,
    SimulateInterviewRequest,
    ScreeningConversationResponse,
)

# Outbound models
from .outbound import (
    OutboundScreeningRequest,
    OutboundScreeningResponse,
)

# Webhook models
from .webhook import (
    ElevenLabsWebhookData,
    ElevenLabsWebhookPayload,
)

# CV analysis models
from .cv import (
    CVQuestionRequest,
    CVAnalyzeRequest,
    CVQuestionAnalysisResponse,
    CVAnalyzeResponse,
)

# Data query models
from .data_query import DataQueryRequest

# Document collection models
from .document_collection import (
    OutboundDocumentRequest,
    OutboundDocumentResponse,
    DocumentCollectionDebugResponse,
)

# Candidate models
from .candidate import (
    CandidateCreate,
    CandidateUpdate,
    CandidateResponse,
    CandidateWithApplicationsResponse,
    CandidateApplicationSummary,
)

# Activity models
from .activity import (
    ActivityEventType,
    ActorType,
    ActivityChannel,
    ActivityCreate,
    ActivityResponse,
    TimelineResponse,
)

__all__ = [
    # Common
    "PaginatedResponse",
    # Enums
    "VacancyStatus",
    "VacancySource",
    "InterviewChannel",
    # Vacancy
    "ChannelsResponse",
    "AgentStatusResponse",
    "AgentsResponse",
    "RecruiterSummary",
    "ClientSummary",
    "VacancyResponse",
    "VacancyStatsResponse",
    "DashboardStatsResponse",
    # Application
    "QuestionAnswerResponse",
    "ApplicationResponse",
    "CVApplicationRequest",
    # Pre-screening
    "PreScreeningQuestionRequest",
    "PreScreeningQuestionResponse",
    "PreScreeningRequest",
    "PreScreeningResponse",
    "PublishPreScreeningRequest",
    "PublishPreScreeningResponse",
    "StatusUpdateRequest",
    # Interview
    "GenerateInterviewRequest",
    "FeedbackRequest",
    "ReorderRequest",
    "DeleteQuestionRequest",
    "AddQuestionRequest",
    "RestoreSessionRequest",
    # Screening
    "ScreeningChatRequest",
    "SimulateInterviewRequest",
    "ScreeningConversationResponse",
    # Outbound
    "OutboundScreeningRequest",
    "OutboundScreeningResponse",
    # Webhook
    "ElevenLabsWebhookData",
    "ElevenLabsWebhookPayload",
    # CV
    "CVQuestionRequest",
    "CVAnalyzeRequest",
    "CVQuestionAnalysisResponse",
    "CVAnalyzeResponse",
    # Data query
    "DataQueryRequest",
    # Document collection
    "OutboundDocumentRequest",
    "OutboundDocumentResponse",
    "DocumentCollectionDebugResponse",
    # Candidate
    "CandidateCreate",
    "CandidateUpdate",
    "CandidateResponse",
    "CandidateWithApplicationsResponse",
    "CandidateApplicationSummary",
    # Activity
    "ActivityEventType",
    "ActorType",
    "ActivityChannel",
    "ActivityCreate",
    "ActivityResponse",
    "TimelineResponse",
]
