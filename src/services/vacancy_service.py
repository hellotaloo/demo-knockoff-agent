"""
Vacancy service - handles vacancy listing, details, and statistics.
"""
import uuid
from typing import Optional, Tuple
import asyncpg
from src.repositories import VacancyRepository
from src.models import VacancyResponse, ChannelsResponse, VacancyStatsResponse, DashboardStatsResponse


class VacancyService:
    """Service for vacancy operations."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = VacancyRepository(pool)
    
    @staticmethod
    def build_vacancy_response(row: asyncpg.Record) -> VacancyResponse:
        """
        Build a VacancyResponse model from a database row.
        
        Calculates effective channel states and is_online status based on
        published state and active channels.
        """
        # Calculate effective channel states
        voice_active = row["voice_enabled"] or False
        whatsapp_active = row["whatsapp_enabled"] or False
        cv_active = row["cv_enabled"] or False
        
        # is_online is only true if at least one channel is active
        any_channel_active = voice_active or whatsapp_active or cv_active
        effective_is_online = row["is_online"] and any_channel_active
        
        return VacancyResponse(
            id=str(row["id"]),
            title=row["title"],
            company=row["company"],
            location=row["location"],
            description=row["description"],
            status=row["status"],
            created_at=row["created_at"],
            archived_at=row["archived_at"],
            source=row["source"],
            source_id=row["source_id"],
            has_screening=row["has_screening"],
            is_online=effective_is_online,
            channels=ChannelsResponse(
                voice=voice_active,
                whatsapp=whatsapp_active,
                cv=cv_active
            ),
            candidates_count=row["candidates_count"],
            completed_count=row["completed_count"],
            qualified_count=row["qualified_count"],
            last_activity_at=row["last_activity_at"]
        )
    
    async def list_vacancies(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[VacancyResponse], int]:
        """
        List vacancies with optional filtering.
        
        Returns:
            Tuple of (vacancy list, total count)
        """
        rows, total = await self.repo.list_with_stats(status, source, limit, offset)
        vacancies = [self.build_vacancy_response(row) for row in rows]
        return vacancies, total
    
    async def get_vacancy(self, vacancy_id: uuid.UUID) -> Optional[VacancyResponse]:
        """Get a single vacancy by ID with stats."""
        row = await self.repo.get_by_id(vacancy_id)
        if not row:
            return None
        return self.build_vacancy_response(row)
    
    async def get_vacancy_stats(self, vacancy_id: uuid.UUID) -> Optional[VacancyStatsResponse]:
        """Get detailed statistics for a vacancy."""
        stats = await self.repo.get_stats(vacancy_id)
        if not stats:
            return None
        
        return VacancyStatsResponse(
            total=stats["total"],
            completed_count=stats["completed_count"],
            qualified_count=stats["qualified_count"],
            voice_count=stats["voice_count"],
            whatsapp_count=stats["whatsapp_count"],
            avg_duration_seconds=int(stats["avg_seconds"]),
            last_application=stats["last_application"]
        )
    
    async def get_dashboard_stats(self) -> DashboardStatsResponse:
        """Get dashboard-level aggregate statistics."""
        stats = await self.repo.get_dashboard_stats()
        
        return DashboardStatsResponse(
            total_applications=stats["total"],
            this_week=stats["this_week"],
            completed=stats["completed_count"],
            qualified=stats["qualified_count"],
            voice_count=stats["voice_count"],
            whatsapp_count=stats["whatsapp_count"],
            cv_count=stats["cv_count"]
        )
