"""
Agent vacancy repository - handles vacancy listing by agent status.
"""
import asyncpg
from typing import Optional, Tuple, Literal

AgentStatus = Literal["new", "generated", "published", "archived"]


class AgentVacancyRepository:
    """Repository for agent-filtered vacancy queries."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_prescreening_vacancies(
        self,
        status: AgentStatus,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List vacancies filtered by pre-screening agent status.

        Status logic:
        - new: No pre_screening record (questions not generated yet)
        - generated: Has pre_screening record (questions exist, can be online/offline)
        - archived: Vacancy status is 'closed' or 'filled'
        """
        # Build status-specific conditions
        if status == "archived":
            status_condition = "v.status IN ('closed', 'filled')"
        elif status == "published":
            status_condition = """
                v.status NOT IN ('closed', 'filled')
                AND ps.id IS NOT NULL
                AND ps.published_at IS NOT NULL
            """
        elif status == "generated":
            status_condition = """
                v.status NOT IN ('closed', 'filled')
                AND ps.id IS NOT NULL
                AND ps.published_at IS NULL
            """
        else:  # new
            status_condition = """
                v.status NOT IN ('closed', 'filled')
                AND ps.id IS NULL
            """

        # Count query
        count_query = f"""
            SELECT COUNT(*)
            FROM ats.vacancies v
            LEFT JOIN ats.pre_screenings ps ON ps.vacancy_id = v.id
            WHERE {status_condition}
        """
        total = await self.pool.fetchval(count_query)

        # Data query with stats
        query = f"""
            SELECT
                v.id, v.title, v.company, v.location, v.description, v.status, v.created_at,
                v.source, v.source_id, v.archived_at,
                v.prescreening_agent_enabled, v.preonboarding_agent_enabled, v.insights_agent_enabled,
                v.recruiter_id, v.client_id,
                r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
                r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
                c.id as c_id, c.name as c_name, c.location as c_location,
                c.industry as c_industry, c.logo as c_logo,
                (ps.id IS NOT NULL) as has_screening,
                ps.published_at,
                ps.is_online,
                COALESCE(ps.voice_enabled, false) as voice_enabled,
                COALESCE(ps.whatsapp_enabled, false) as whatsapp_enabled,
                COALESCE(ps.cv_enabled, false) as cv_enabled,
                COALESCE(app_stats.candidates_count, 0) as candidates_count,
                COALESCE(app_stats.completed_count, 0) as completed_count,
                COALESCE(app_stats.qualified_count, 0) as qualified_count,
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
                    MAX(COALESCE(completed_at, started_at)) as last_activity_at
                FROM ats.applications a
                WHERE a.vacancy_id = v.id
            ) app_stats ON true
            WHERE {status_condition}
            ORDER BY v.created_at DESC
            LIMIT $1 OFFSET $2
        """

        rows = await self.pool.fetch(query, limit, offset)
        return rows, total

    async def list_preonboarding_vacancies(
        self,
        status: AgentStatus,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List vacancies filtered by pre-onboarding agent status.

        Status logic:
        - new: preonboarding_agent_enabled = false or NULL
        - generated: preonboarding_agent_enabled = true
        - archived: Vacancy status is 'closed' or 'filled'
        """
        # Build status-specific conditions
        if status == "archived":
            status_condition = "v.status IN ('closed', 'filled')"
        elif status == "generated":
            status_condition = """
                v.status NOT IN ('closed', 'filled')
                AND v.preonboarding_agent_enabled = true
            """
        else:  # new
            status_condition = """
                v.status NOT IN ('closed', 'filled')
                AND (v.preonboarding_agent_enabled IS NULL OR v.preonboarding_agent_enabled = false)
            """

        # Count query
        count_query = f"""
            SELECT COUNT(*)
            FROM ats.vacancies v
            WHERE {status_condition}
        """
        total = await self.pool.fetchval(count_query)

        # Data query
        query = f"""
            SELECT
                v.id, v.title, v.company, v.location, v.description, v.status, v.created_at,
                v.source, v.source_id, v.archived_at,
                v.prescreening_agent_enabled, v.preonboarding_agent_enabled, v.insights_agent_enabled,
                v.recruiter_id, v.client_id,
                r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
                r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
                c.id as c_id, c.name as c_name, c.location as c_location,
                c.industry as c_industry, c.logo as c_logo,
                (ps.id IS NOT NULL) as has_screening,
                ps.published_at,
                ps.is_online,
                COALESCE(ps.voice_enabled, false) as voice_enabled,
                COALESCE(ps.whatsapp_enabled, false) as whatsapp_enabled,
                COALESCE(ps.cv_enabled, false) as cv_enabled,
                COALESCE(app_stats.candidates_count, 0) as candidates_count,
                COALESCE(app_stats.completed_count, 0) as completed_count,
                COALESCE(app_stats.qualified_count, 0) as qualified_count,
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
                    MAX(COALESCE(completed_at, started_at)) as last_activity_at
                FROM ats.applications a
                WHERE a.vacancy_id = v.id
            ) app_stats ON true
            WHERE {status_condition}
            ORDER BY v.created_at DESC
            LIMIT $1 OFFSET $2
        """

        rows = await self.pool.fetch(query, limit, offset)
        return rows, total

    async def get_counts(self) -> dict:
        """
        Get all agent vacancy counts in a single lightweight query.
        Used for navigation counters - no LATERAL joins or full data fetching.
        """
        query = """
            SELECT
                -- Pre-screening counts
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND ps.id IS NULL) as prescreening_new,
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND ps.id IS NOT NULL AND ps.published_at IS NULL) as prescreening_generated,
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND ps.id IS NOT NULL AND ps.published_at IS NOT NULL) as prescreening_published,
                COUNT(*) FILTER (WHERE v.status IN ('closed', 'filled')) as prescreening_archived,
                -- Pre-onboarding counts
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND (v.preonboarding_agent_enabled IS NULL OR v.preonboarding_agent_enabled = false)) as preonboarding_new,
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND v.preonboarding_agent_enabled = true) as preonboarding_generated,
                COUNT(*) FILTER (WHERE v.status IN ('closed', 'filled')) as preonboarding_archived
            FROM ats.vacancies v
            LEFT JOIN ats.pre_screenings ps ON ps.vacancy_id = v.id
        """
        return await self.pool.fetchrow(query)
