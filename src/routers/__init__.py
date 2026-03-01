"""
API routers for endpoint organization.
"""
from .health import router as health_router
from .vacancies import router as vacancies_router
from .applications import router as applications_router
from .pre_screenings import router as pre_screenings_router
from .interviews import router as interviews_router
from .screening import router as screening_router
from .webhooks import router as webhooks_router
from .data_query import router as data_query_router
from .outbound import router as outbound_router
from .cv import router as cv_router
from .demo import router as demo_router
from .documents import router as documents_router
from .document_collection import router as document_collection_router
from .scheduling import router as scheduling_router
from .candidates import router as candidates_router
from .agents import router as agents_router
from .activities import router as activities_router
from .monitoring import router as monitoring_router
from .elevenlabs import router as elevenlabs_router
from .auth import router as auth_router
from .workspaces import router as workspaces_router
from .vapi import router as vapi_router
from .livekit_webhook import router as livekit_webhook_router
from .teams import router as teams_router
from .architecture import router as architecture_router
from .ontology import router as ontology_router
from .interview_analysis import router as interview_analysis_router
from .ats_simulator import router as ats_simulator_router
from .playground import router as playground_router

__all__ = [
    "health_router",
    "vacancies_router",
    "applications_router",
    "pre_screenings_router",
    "interviews_router",
    "screening_router",
    "webhooks_router",
    "data_query_router",
    "outbound_router",
    "cv_router",
    "demo_router",
    "documents_router",
    "document_collection_router",
    "scheduling_router",
    "candidates_router",
    "agents_router",
    "activities_router",
    "monitoring_router",
    "elevenlabs_router",
    "auth_router",
    "workspaces_router",
    "vapi_router",
    "livekit_webhook_router",
    "teams_router",
    "architecture_router",
    "ontology_router",
    "interview_analysis_router",
    "ats_simulator_router",
    "playground_router",
]
