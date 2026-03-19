"""
Agent vacancy repository - handles vacancy listing by agent status.
"""
import asyncpg
from typing import Optional, Tuple
from uuid import UUID


class AgentVacancyRepository:
    """Repository for agent-filtered vacancy queries."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_prescreening_vacancies(
        self,
        workspace_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List all non-archived vacancies with prescreening agent status and stats.

        Returns agent_status per vacancy:
        - new: No pre_screening record
        - generated: Has pre_screening but not published
        - published: Pre_screening is published
        """
        ws_filter = ""
        params = []
        param_idx = 1

        if workspace_id:
            ws_filter = f" AND v.workspace_id = ${param_idx}"
            params.append(workspace_id)
            param_idx += 1

        count_query = f"""
            SELECT COUNT(*)
            FROM ats.vacancies v
            WHERE v.status NOT IN ('closed', 'filled'){ws_filter}
        """
        total = await self.pool.fetchval(count_query, *params)

        query = f"""
            SELECT
                v.id, v.title, v.company, v.location, v.status, v.created_at,
                CASE
                    WHEN ps.id IS NULL THEN 'new'
                    WHEN ps.published_at IS NULL THEN 'generated'
                    ELSE 'published'
                END as agent_status,
                COALESCE(va_ps.is_online, ps.is_online, false) as agent_online,
                v.recruiter_id, v.client_id,
                r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
                r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
                c.id as c_id, c.name as c_name, c.location as c_location,
                c.industry as c_industry, c.logo as c_logo,
                COALESCE(app_stats.candidates_count, 0) as candidates_count,
                COALESCE(app_stats.completed_count, 0) as completed_count,
                COALESCE(app_stats.qualified_count, 0) as qualified_count,
                app_stats.last_activity_at
            FROM ats.vacancies v
            LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
            LEFT JOIN ats.clients c ON c.id = v.client_id
            LEFT JOIN agents.pre_screenings ps ON ps.vacancy_id = v.id
            LEFT JOIN ats.vacancy_agents va_ps ON va_ps.vacancy_id = v.id AND va_ps.agent_type = 'prescreening'
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) as candidates_count,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                    COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
                    MAX(COALESCE(completed_at, started_at)) as last_activity_at
                FROM ats.applications a
                WHERE a.vacancy_id = v.id
            ) app_stats ON true
            WHERE v.status NOT IN ('closed', 'filled'){ws_filter}
            ORDER BY v.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)
        return rows, total

    async def list_preonboarding_vacancies(
        self,
        workspace_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List all non-archived vacancies with document collection agent status and stats.

        Returns agent_status per vacancy:
        - new: document_collection agent not registered
        - generated: document_collection agent registered
        """
        ws_filter = ""
        params = []
        param_idx = 1

        if workspace_id:
            ws_filter = f" AND v.workspace_id = ${param_idx}"
            params.append(workspace_id)
            param_idx += 1

        count_query = f"""
            SELECT COUNT(*)
            FROM ats.vacancies v
            WHERE v.status NOT IN ('closed', 'filled'){ws_filter}
        """
        total = await self.pool.fetchval(count_query, *params)

        query = f"""
            SELECT
                v.id, v.title, v.company, v.location, v.status, v.created_at,
                CASE
                    WHEN va_dc.id IS NULL THEN 'new'
                    ELSE 'generated'
                END as agent_status,
                va_dc.is_online as agent_online,
                v.recruiter_id, v.client_id,
                r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
                r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
                c.id as c_id, c.name as c_name, c.location as c_location,
                c.industry as c_industry, c.logo as c_logo,
                COALESCE(dc_stats.dc_active, 0) as dc_active,
                COALESCE(dc_stats.dc_completed, 0) as dc_completed,
                COALESCE(dc_stats.dc_needs_review, 0) as dc_needs_review,
                dc_stats.dc_last_activity as last_activity_at
            FROM ats.vacancies v
            LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
            LEFT JOIN ats.clients c ON c.id = v.client_id
            LEFT JOIN ats.vacancy_agents va_dc ON va_dc.vacancy_id = v.id AND va_dc.agent_type = 'document_collection'
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) FILTER (WHERE dc.status = 'active') as dc_active,
                    COUNT(*) FILTER (WHERE dc.status = 'completed') as dc_completed,
                    COUNT(*) FILTER (WHERE dc.status = 'needs_review') as dc_needs_review,
                    MAX(COALESCE(dc.completed_at, dc.updated_at)) as dc_last_activity
                FROM agents.document_collections dc
                WHERE dc.vacancy_id = v.id
            ) dc_stats ON true
            WHERE v.status NOT IN ('closed', 'filled'){ws_filter}
            ORDER BY v.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)
        return rows, total

    async def get_prescreening_dashboard_stats(self, workspace_id: Optional[UUID] = None) -> asyncpg.Record:
        """Get aggregate prescreening stats for the dashboard."""
        ws_filter = ""
        params = []
        if workspace_id:
            ws_filter = " WHERE a.vacancy_id IN (SELECT id FROM ats.vacancies WHERE workspace_id = $1)"
            params.append(workspace_id)

        query = f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE a.started_at >= date_trunc('week', NOW())) as this_week,
                COUNT(*) FILTER (WHERE a.status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE a.qualified = true) as qualified_count,
                COUNT(*) FILTER (WHERE a.channel = 'voice') as voice_count,
                COUNT(*) FILTER (WHERE a.channel = 'whatsapp') as whatsapp_count
            FROM ats.applications a{ws_filter}
        """
        return await self.pool.fetchrow(query, *params)

    async def get_preonboarding_dashboard_stats(self, workspace_id: Optional[UUID] = None) -> asyncpg.Record:
        """Get aggregate document collection stats for the dashboard."""
        ws_filter = ""
        params = []
        if workspace_id:
            ws_filter = " WHERE dc.vacancy_id IN (SELECT id FROM ats.vacancies WHERE workspace_id = $1)"
            params.append(workspace_id)

        query = f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE dc.status = 'active') as active,
                COUNT(*) FILTER (WHERE dc.status = 'completed') as completed,
                COUNT(*) FILTER (WHERE dc.status = 'needs_review') as needs_review
            FROM agents.document_collections dc{ws_filter}
        """
        return await self.pool.fetchrow(query, *params)

    async def get_counts(self, workspace_id: Optional[UUID] = None) -> dict:
        """
        Get all agent vacancy counts in a single lightweight query.
        Used for navigation counters - no LATERAL joins or full data fetching.
        """
        ws_filter = ""
        params = []
        if workspace_id:
            ws_filter = " WHERE v.workspace_id = $1"
            params.append(workspace_id)

        query = f"""
            SELECT
                -- Pre-screening counts
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND ps.id IS NULL) as prescreening_new,
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND ps.id IS NOT NULL AND ps.published_at IS NULL) as prescreening_generated,
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND ps.id IS NOT NULL AND ps.published_at IS NOT NULL) as prescreening_published,
                COUNT(*) FILTER (WHERE v.status IN ('closed', 'filled')) as prescreening_archived,
                -- Pre-onboarding counts (based on document_collection agent registration)
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND NOT EXISTS (SELECT 1 FROM ats.vacancy_agents va WHERE va.vacancy_id = v.id AND va.agent_type = 'document_collection')) as preonboarding_new,
                COUNT(*) FILTER (WHERE v.status NOT IN ('closed', 'filled') AND EXISTS (SELECT 1 FROM ats.vacancy_agents va WHERE va.vacancy_id = v.id AND va.agent_type = 'document_collection')) as preonboarding_generated,
                COUNT(*) FILTER (WHERE v.status IN ('closed', 'filled')) as preonboarding_archived
            FROM ats.vacancies v
            LEFT JOIN agents.pre_screenings ps ON ps.vacancy_id = v.id{ws_filter}
        """
        return await self.pool.fetchrow(query, *params)
