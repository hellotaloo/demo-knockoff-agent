"""
FastAPI dependency injection factories.

This module provides dependency factories for repositories, services,
and other shared resources used across routers.
"""
import asyncpg
from typing import Optional
from fastapi import Depends

from src.database import get_db_pool
from src.repositories import (
    VacancyRepository,
    ApplicationRepository,
    PreScreeningRepository,
    ConversationRepository
)
from src.services import (
    SessionManager,
    VacancyService,
    ApplicationService,
    PreScreeningService,
    InterviewService,
    DemoService
)


# Global session manager instance (set during app startup)
_session_manager: Optional[SessionManager] = None


def set_session_manager(manager: SessionManager):
    """Set the global session manager instance."""
    global _session_manager
    _session_manager = manager


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    if _session_manager is None:
        raise RuntimeError("SessionManager not initialized. Call set_session_manager() during app startup.")
    return _session_manager


# =============================================================================
# Database Dependencies
# =============================================================================

async def get_pool() -> asyncpg.Pool:
    """Get the database connection pool."""
    return await get_db_pool()


# =============================================================================
# Repository Dependencies
# =============================================================================

async def get_vacancy_repo(
    pool: asyncpg.Pool = Depends(get_pool)
) -> VacancyRepository:
    """Get a VacancyRepository instance."""
    return VacancyRepository(pool)


async def get_application_repo(
    pool: asyncpg.Pool = Depends(get_pool)
) -> ApplicationRepository:
    """Get an ApplicationRepository instance."""
    return ApplicationRepository(pool)


async def get_pre_screening_repo(
    pool: asyncpg.Pool = Depends(get_pool)
) -> PreScreeningRepository:
    """Get a PreScreeningRepository instance."""
    return PreScreeningRepository(pool)


async def get_conversation_repo(
    pool: asyncpg.Pool = Depends(get_pool)
) -> ConversationRepository:
    """Get a ConversationRepository instance."""
    return ConversationRepository(pool)


# =============================================================================
# Service Dependencies
# =============================================================================

async def get_vacancy_service(
    pool: asyncpg.Pool = Depends(get_pool)
) -> VacancyService:
    """Get a VacancyService instance."""
    return VacancyService(pool)


async def get_application_service(
    pool: asyncpg.Pool = Depends(get_pool)
) -> ApplicationService:
    """Get an ApplicationService instance."""
    return ApplicationService(pool)


async def get_pre_screening_service(
    pool: asyncpg.Pool = Depends(get_pool)
) -> PreScreeningService:
    """Get a PreScreeningService instance."""
    return PreScreeningService(pool)


async def get_interview_service(
    session_manager: SessionManager = Depends(get_session_manager)
) -> InterviewService:
    """Get an InterviewService instance."""
    return InterviewService(session_manager)


async def get_demo_service(
    pool: asyncpg.Pool = Depends(get_pool)
) -> DemoService:
    """Get a DemoService instance."""
    return DemoService(pool)
