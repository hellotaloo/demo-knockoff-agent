"""
Vacancy repository - handles all vacancy-related database operations.
"""
import asyncpg
import uuid
from datetime import date
from typing import Optional, Tuple


# Shared SQL fragments for vacancy detail queries
_VACANCY_DETAIL_COLUMNS = """
    v.id, v.title, v.company, v.location, v.description, v.status,
    v.created_at, v.archived_at, v.source, v.source_id, v.start_date,
    v.recruiter_id,
    r.id as r_id, r.name as r_name, r.email as r_email, r.phone as r_phone,
    r.team as r_team, r.role as r_role, r.avatar_url as r_avatar_url,
    v.client_id,
    c.id as c_id, c.name as c_name, c.location as c_location,
    c.industry as c_industry, c.logo as c_logo,
    ol.id as ol_id, ol.name as ol_name, ol.address as ol_address,
    ol.email as ol_email, ol.phone as ol_phone,
    jf.id as jf_id, jf.name as jf_name,
    (ps.id IS NOT NULL) as has_screening,
    ps.published_at,
    COALESCE(va_ps.status, 'new') as agent_status,
    COALESCE(ps.voice_enabled, false) as voice_enabled,
    COALESCE(ps.whatsapp_enabled, false) as whatsapp_enabled,
    COALESCE(ps.cv_enabled, false) as cv_enabled,
    COALESCE(cand_stats.candidacy_count, 0) as candidates_count,
    COALESCE(app_stats.completed_count, 0) as completed_count,
    COALESCE(app_stats.qualified_count, 0) as qualified_count,
    app_stats.avg_score,
    app_stats.last_activity_at,
    COALESCE(
        (SELECT array_agg(va.agent_type) FROM ats.vacancy_agents va WHERE va.vacancy_id = v.id),
        ARRAY[]::text[]
    ) as agent_types"""

_VACANCY_DETAIL_JOINS = """
    FROM ats.vacancies v
    LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
    LEFT JOIN ats.clients c ON c.id = v.client_id
    LEFT JOIN ats.office_locations ol ON ol.id = v.office_location_id
    LEFT JOIN ats.job_functions jf ON jf.id = v.job_function_id
    LEFT JOIN agents.pre_screenings ps ON ps.vacancy_id = v.id
    LEFT JOIN ats.vacancy_agents va_ps ON va_ps.vacancy_id = v.id AND va_ps.agent_type = 'prescreening'
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
            COUNT(*) FILTER (WHERE qualified = true) as qualified_count,
            MAX(COALESCE(completed_at, started_at)) as last_activity_at,
            (
                SELECT ROUND(AVG(ans.score)::numeric, 1)
                FROM agents.pre_screening_answers ans
                JOIN ats.applications app ON app.id = ans.application_id
                WHERE app.vacancy_id = v.id AND ans.score IS NOT NULL
            ) as avg_score
        FROM ats.applications a
        WHERE a.vacancy_id = v.id
    ) app_stats ON true
    LEFT JOIN LATERAL (
        SELECT COUNT(*) as candidacy_count
        FROM ats.candidacies cd
        WHERE cd.vacancy_id = v.id
    ) cand_stats ON true"""


class VacancyRepository:
    """Repository for vacancy database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_with_stats(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List vacancies with application stats, with optional filtering.

        Returns:
            Tuple of (vacancy rows, total count)
        """
        conditions = []
        params = []
        param_idx = 1

        if workspace_id:
            conditions.append(f"v.workspace_id = ${param_idx}")
            params.append(workspace_id)
            param_idx += 1

        if status:
            conditions.append(f"v.status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if source:
            conditions.append(f"v.source = ${param_idx}")
            params.append(source)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_query = f"SELECT COUNT(*) FROM ats.vacancies v {where_clause}"
        total = await self.pool.fetchval(count_query, *params)

        query = f"""
            SELECT {_VACANCY_DETAIL_COLUMNS}
            {_VACANCY_DETAIL_JOINS}
            {where_clause}
            ORDER BY v.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)

        return rows, total

    async def get_by_id(self, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single vacancy by ID with stats, recruiter info, and client info."""
        query = f"""
            SELECT v.workspace_id, {_VACANCY_DETAIL_COLUMNS}
            {_VACANCY_DETAIL_JOINS}
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

    async def update(self, vacancy_id: uuid.UUID, start_date: Optional[date] = None) -> Optional[asyncpg.Record]:
        """Update vacancy fields. Returns the updated row or None if not found."""
        return await self.pool.fetchrow(
            """
            UPDATE ats.vacancies
            SET start_date = $2
            WHERE id = $1
            RETURNING id, start_date
            """,
            vacancy_id, start_date
        )

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

    async def get_dashboard_stats(self, workspace_id: Optional[uuid.UUID] = None) -> Optional[asyncpg.Record]:
        """Get dashboard-level aggregate statistics across all vacancies."""
        ws_join = ""
        ws_filter = ""
        params = []
        if workspace_id:
            ws_join = " JOIN ats.vacancies v ON v.id = a.vacancy_id"
            ws_filter = " WHERE v.workspace_id = $1"
            params.append(workspace_id)

        query = f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE a.started_at >= NOW() - INTERVAL '7 days') as this_week,
                COUNT(*) FILTER (WHERE a.status = 'completed') as completed_count,
                COUNT(*) FILTER (WHERE a.qualified = true) as qualified_count,
                COUNT(*) FILTER (WHERE a.channel = 'voice') as voice_count,
                COUNT(*) FILTER (WHERE a.channel = 'whatsapp') as whatsapp_count,
                COUNT(*) FILTER (WHERE a.channel = 'cv') as cv_count
            FROM ats.applications a{ws_join}{ws_filter}
        """
        return await self.pool.fetchrow(query, *params)

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
                COALESCE(c.first_name || ' ' || c.last_name, a.candidate_name) as name,
                COALESCE(c.phone, a.candidate_phone) as phone,
                a.channel,
                a.status,
                a.qualified,
                a.started_at,
                a.completed_at,
                (
                    SELECT ROUND(AVG(ans.score)::numeric, 1)
                    FROM agents.pre_screening_answers ans
                    WHERE ans.application_id = a.id AND ans.score IS NOT NULL
                ) as score
            FROM ats.applications a
            LEFT JOIN ats.candidates c ON c.id = a.candidate_id
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

    # -------------------------------------------------------------------------
    # Vacancy agent registration (ats.vacancy_agents)
    # -------------------------------------------------------------------------

    async def get_agent(
        self, vacancy_id: uuid.UUID, agent_type: str
    ) -> Optional[asyncpg.Record]:
        """Get a vacancy agent registration."""
        return await self.pool.fetchrow(
            """
            SELECT id, vacancy_id, agent_type, status, created_at
            FROM ats.vacancy_agents
            WHERE vacancy_id = $1 AND agent_type = $2
            """,
            vacancy_id, agent_type,
        )

    async def ensure_agent_registered(
        self, vacancy_id: uuid.UUID, agent_type: str,
        status: str = "new",
        conn: Optional[asyncpg.Connection] = None,
    ) -> asyncpg.Record:
        """Insert or update a vacancy agent registration."""
        executor = conn or self.pool
        return await executor.fetchrow(
            """
            INSERT INTO ats.vacancy_agents (vacancy_id, agent_type, status)
            VALUES ($1, $2, $3)
            ON CONFLICT (vacancy_id, agent_type) DO UPDATE SET status = $3
            RETURNING id, vacancy_id, agent_type, status, created_at
            """,
            vacancy_id, agent_type, status,
        )

    async def set_agent_status(
        self, vacancy_id: uuid.UUID, agent_type: str, status: str,
    ) -> Optional[asyncpg.Record]:
        """Update the lifecycle status for a vacancy agent."""
        return await self.pool.fetchrow(
            """
            UPDATE ats.vacancy_agents
            SET status = $1
            WHERE vacancy_id = $2 AND agent_type = $3
            RETURNING id, vacancy_id, agent_type, status, created_at
            """,
            status, vacancy_id, agent_type,
        )
