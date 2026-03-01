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
    ApplicantSummary,
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

# LiveKit models
from .livekit import (
    LiveKitCallResultPayload,
    LiveKitKnockoutAnswerPayload,
    LiveKitOpenAnswerPayload,
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
    GlobalActivityResponse,
    GlobalActivitiesResponse,
)

# Auth models
from .auth import (
    TokenResponse,
    RefreshTokenRequest,
    AuthCallbackResponse,
    AuthMeResponse,
)

# User models
from .user import (
    UserProfileCreate,
    UserProfileUpdate,
    UserProfileResponse,
    UserProfileSummary,
)

# Workspace models
from .workspace import (
    WorkspaceRole,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceSummary,
    WorkspaceWithMembers,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceInvitationCreate,
    WorkspaceInvitationResponse,
)

# Ontology models
from .ontology import (
    RequirementType,
    OntologyTypeCreate,
    OntologyTypeUpdate,
    OntologyTypeResponse,
    OntologyEntityCreate,
    OntologyEntityUpdate,
    OntologyEntityResponse,
    OntologyEntityDetailResponse,
    OntologyRelationTypeCreate,
    OntologyRelationTypeResponse,
    OntologyRelationCreate,
    OntologyRelationUpdate,
    OntologyRelationResponse,
    OntologyGraphNode,
    OntologyGraphEdge,
    OntologyGraphResponse,
    OntologyOverviewResponse,
)

# Interview analysis models
from .interview_analysis import (
    AnalysisQuestionInput,
    AnalysisVacancyInput,
    InterviewAnalysisRequest,
    AnalysisSummary,
    AnalysisQuestionResult,
    AnalysisFunnelStep,
    InterviewAnalysisResponse,
)

# Architecture models
from .architecture import (
    ArchitectureNode,
    ArchitectureEdge,
    ArchitectureGroup,
    ArchitectureStats,
    ArchitectureMetadata,
    ArchitectureResponse,
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
    "ApplicantSummary",
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
    # LiveKit
    "LiveKitCallResultPayload",
    "LiveKitKnockoutAnswerPayload",
    "LiveKitOpenAnswerPayload",
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
    "GlobalActivityResponse",
    "GlobalActivitiesResponse",
    # Auth
    "TokenResponse",
    "RefreshTokenRequest",
    "AuthCallbackResponse",
    "AuthMeResponse",
    # User
    "UserProfileCreate",
    "UserProfileUpdate",
    "UserProfileResponse",
    "UserProfileSummary",
    # Workspace
    "WorkspaceRole",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceResponse",
    "WorkspaceSummary",
    "WorkspaceWithMembers",
    "WorkspaceMemberResponse",
    "WorkspaceMemberUpdate",
    "WorkspaceInvitationCreate",
    "WorkspaceInvitationResponse",
    # Ontology
    "RequirementType",
    "OntologyTypeCreate",
    "OntologyTypeUpdate",
    "OntologyTypeResponse",
    "OntologyEntityCreate",
    "OntologyEntityUpdate",
    "OntologyEntityResponse",
    "OntologyEntityDetailResponse",
    "OntologyRelationTypeCreate",
    "OntologyRelationTypeResponse",
    "OntologyRelationCreate",
    "OntologyRelationUpdate",
    "OntologyRelationResponse",
    "OntologyGraphNode",
    "OntologyGraphEdge",
    "OntologyGraphResponse",
    "OntologyOverviewResponse",
    # Interview Analysis
    "AnalysisQuestionInput",
    "AnalysisVacancyInput",
    "InterviewAnalysisRequest",
    "AnalysisSummary",
    "AnalysisQuestionResult",
    "AnalysisFunnelStep",
    "InterviewAnalysisResponse",
    # Architecture
    "ArchitectureNode",
    "ArchitectureEdge",
    "ArchitectureGroup",
    "ArchitectureStats",
    "ArchitectureMetadata",
    "ArchitectureResponse",
]
