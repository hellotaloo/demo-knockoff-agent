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
    "document_collection_router"
]
