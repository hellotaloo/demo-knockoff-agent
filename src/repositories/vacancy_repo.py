"""
Vacancy repository - handles all vacancy-related database operations.
"""
import asyncpg
import uuid
from typing import Optional, Tuple
from datetime import datetime


class VacancyRepository:
    """Repository for vacancy database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_with_stats(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List vacancies with application stats, with optional filtering.

        Returns:
            Tuple of (vacancy rows, total count)
        """
        # Build query with optional filters
        conditions = []
        params = []
        param_idx = 1

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if source:
            conditions.append(f"source = ${param_idx}")
            params.append(source)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Get total count
        count_query = f"SELECT COUNT(*) FROM ats.vacancies {where_clause}"
        total = await self.pool.fetchval(count_query, *params)

        # Get vacancies with application stats, recruiter info, and client info
        query = f"""
            SELECT v.id, v.title, v.company, v.location, v.description, v.status,
                   v.created_at, v.archived_at, v.source, v.source_id,
                   v.prescreening_agent_enabled, v.preonboarding_agent_enabled, v.insights_agent_enabled,
                   v.recruiter_id,
                   r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
                   r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
                   v.client_id,
                   c.id as c_id, c.name as c_name, c.location as c_location,
                   c.industry as c_industry, c.logo as c_logo,
                   (ps.id IS NOT NULL) as has_screening,
                   ps.published_at,
                   CASE
                       WHEN ps.published_at IS NULL THEN NULL
                       ELSE ps.is_online
                   END as is_online,
                   COALESCE(ps.voice_enabled, false) as voice_enabled,
                   COALESCE(ps.whatsapp_enabled, false) as whatsapp_enabled,
                   COALESCE(ps.cv_enabled, false) as cv_enabled,
                   COALESCE(app_stats.candidates_count, 0) as candidates_count,
                   COALESCE(app_stats.completed_count, 0) as completed_count,
                   COALESCE(app_stats.qualified_count, 0) as qualified_count,
                   app_stats.avg_score,
                   app_stats.last_activity_at
            FROM ats.vacancies v
            LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
            LEFT JOIN ats.clients c ON c.id = v.client_id
            LEFT JOIN ats.pre_screenings ps ON ps.vacancy_id = v.id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) as candidates_count,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                    COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
                    MAX(COALESCE(completed_at, started_at)) as last_activity_at,
                    (
                        SELECT ROUND(AVG(ans.score)::numeric, 1)
                        FROM ats.application_answers ans
                        JOIN ats.applications app ON app.id = ans.application_id
                        WHERE app.vacancy_id = v.id AND ans.score IS NOT NULL
                    ) as avg_score
                FROM ats.applications a
                WHERE a.vacancy_id = v.id
            ) app_stats ON true
            {where_clause}
            ORDER BY v.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)

        return rows, total

    async def get_by_id(self, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single vacancy by ID with stats, recruiter info, and client info."""
        query = """
            SELECT v.id, v.title, v.company, v.location, v.description, v.status,
                   v.created_at, v.archived_at, v.source, v.source_id,
                   v.prescreening_agent_enabled, v.preonboarding_agent_enabled, v.insights_agent_enabled,
                   v.recruiter_id,
                   r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
                   r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
                   v.client_id,
                   c.id as c_id, c.name as c_name, c.location as c_location,
                   c.industry as c_industry, c.logo as c_logo,
                   (ps.id IS NOT NULL) as has_screening,
                   ps.published_at,
                   CASE
                       WHEN ps.published_at IS NULL THEN NULL
                       ELSE ps.is_online
                   END as is_online,
                   COALESCE(ps.voice_enabled, false) as voice_enabled,
                   COALESCE(ps.whatsapp_enabled, false) as whatsapp_enabled,
                   COALESCE(ps.cv_enabled, false) as cv_enabled,
                   COALESCE(app_stats.candidates_count, 0) as candidates_count,
                   COALESCE(app_stats.completed_count, 0) as completed_count,
                   COALESCE(app_stats.qualified_count, 0) as qualified_count,
                   app_stats.avg_score,
                   app_stats.last_activity_at
            FROM ats.vacancies v
            LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
            LEFT JOIN ats.clients c ON c.id = v.client_id
            LEFT JOIN ats.pre_screenings ps ON ps.vacancy_id = v.id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) as candidates_count,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                    COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
                    MAX(COALESCE(completed_at, started_at)) as last_activity_at,
                    (
                        SELECT ROUND(AVG(ans.score)::numeric, 1)
                        FROM ats.application_answers ans
                        JOIN ats.applications app ON app.id = ans.application_id
                        WHERE app.vacancy_id = v.id AND ans.score IS NOT NULL
                    ) as avg_score
                FROM ats.applications a
                WHERE a.vacancy_id = v.id
            ) app_stats ON true
            WHERE v.id = $1
        """

        return await self.pool.fetchrow(query, vacancy_id)

    async def exists(self, vacancy_id: uuid.UUID) -> bool:
        """Check if a vacancy exists."""
        result = await self.pool.fetchval(
            "SELECT 1 FROM ats.vacancies WHERE id = $1",
            vacancy_id
        )
        return result is not None

    async def get_basic_info(self, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get basic vacancy information without stats."""
        return await self.pool.fetchrow(
            """
            SELECT id, title, company, location, description, status,
                   created_at, archived_at, source, source_id
            FROM ats.vacancies
            WHERE id = $1
            """,
            vacancy_id
        )

    async def get_stats(self, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get aggregated statistics for a vacancy."""
        stats_query = """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
                COUNT(*) FILTER (WHERE channel = 'voice') as voice_count,
                COUNT(*) FILTER (WHERE channel = 'whatsapp') as whatsapp_count,
                COALESCE(AVG(interaction_seconds), 0) as avg_seconds,
                MAX(started_at) as last_application
            FROM ats.applications
            WHERE vacancy_id = $1
        """

        return await self.pool.fetchrow(stats_query, vacancy_id)

    async def get_dashboard_stats(self) -> Optional[asyncpg.Record]:
        """Get dashboard-level aggregate statistics across all vacancies."""
        stats_query = """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '7 days') as this_week,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
                COUNT(*) FILTER (WHERE channel = 'voice') as voice_count,
                COUNT(*) FILTER (WHERE channel = 'whatsapp') as whatsapp_count,
                COUNT(*) FILTER (WHERE channel = 'cv') as cv_count
            FROM ats.applications
        """

        return await self.pool.fetchrow(stats_query)

    async def get_applicants_by_vacancy_ids(
        self, vacancy_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[asyncpg.Record]]:
        """
        Fetch applicants for multiple vacancies in a single query.
        Returns a dict mapping vacancy_id -> list of applicant records.
        """
        if not vacancy_ids:
            return {}

        query = """
            SELECT
                a.id,
                a.vacancy_id,
                a.candidate_name as name,
                a.candidate_phone as phone,
                a.channel,
                a.status,
                a.qualified,
                a.started_at,
                a.completed_at,
                (
                    SELECT ROUND(AVG(ans.score)::numeric, 1)
                    FROM ats.application_answers ans
                    WHERE ans.application_id = a.id AND ans.score IS NOT NULL
                ) as score
            FROM ats.applications a
            WHERE a.vacancy_id = ANY($1)
              AND a.is_test = false
            ORDER BY a.started_at DESC
        """

        rows = await self.pool.fetch(query, vacancy_ids)

        # Group by vacancy_id
        result: dict[uuid.UUID, list[asyncpg.Record]] = {vid: [] for vid in vacancy_ids}
        for row in rows:
            result[row["vacancy_id"]].append(row)

        return result
