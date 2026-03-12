"""
Candidacy repository — data access for ats.candidacies.
"""
import asyncpg
import uuid
from typing import Optional

# Reusable lateral join that fetches the latest completed application
# with computed score summary from pre_screening_answers.
# Knockout answers have passed IS NOT NULL; qualification answers have passed IS NULL + score.
_LATEST_APP_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT
            a.id,
            a.channel,
            a.qualified,
            a.completed_at,
            (
                SELECT COUNT(*)::int
                FROM agents.pre_screening_answers
                WHERE application_id = a.id AND passed IS NOT NULL
            ) AS knockout_total,
            (
                SELECT COUNT(*)::int
                FROM agents.pre_screening_answers
                WHERE application_id = a.id AND passed = true
            ) AS knockout_passed,
            (
                SELECT AVG(score)::int
                FROM agents.pre_screening_answers
                WHERE application_id = a.id AND passed IS NULL AND score IS NOT NULL
            ) AS open_questions_score
        FROM ats.applications a
        WHERE a.candidacy_id = c.id
          AND a.status = 'completed'
        ORDER BY a.completed_at DESC
        LIMIT 1
    ) app ON true
"""

_LINKED_VACANCIES_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT COALESCE(json_agg(json_build_object(
            'candidacy_id', c2.id,
            'vacancy_id',   v2.id,
            'vacancy_title', v2.title,
            'stage',        c2.stage
        ) ORDER BY c2.created_at), '[]'::json) AS linked_vacancies
        FROM ats.candidacies c2
        JOIN ats.vacancies v2 ON v2.id = c2.vacancy_id
        WHERE c2.candidate_id = c.candidate_id
          AND c2.vacancy_id IS NOT NULL
    ) lv ON true
"""

_SELECT_COLS = """
    c.id,
    c.vacancy_id,
    c.candidate_id,
    c.stage,
    c.source,
    c.stage_updated_at,
    c.created_at,
    c.updated_at,

    cand.id        AS cand_id,
    cand.full_name AS cand_full_name,
    cand.phone     AS cand_phone,
    cand.email     AS cand_email,

    v.id                    AS vac_id,
    v.title                 AS vac_title,
    v.company               AS vac_company,
    v.is_open_application   AS vac_is_open_application,

    app.id                   AS app_id,
    app.channel              AS app_channel,
    app.qualified            AS app_qualified,
    app.open_questions_score AS app_score,
    app.knockout_passed      AS app_ko_passed,
    app.knockout_total       AS app_ko_total,
    app.completed_at         AS app_completed_at,

    lv.linked_vacancies
"""


class CandidacyRepository:
    """Repository for candidacy database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list(
        self,
        workspace_id: uuid.UUID,
        vacancy_id: Optional[uuid.UUID] = None,
        candidate_id: Optional[uuid.UUID] = None,
        stage: Optional[str] = None,
    ) -> list[asyncpg.Record]:
        """
        List candidacies with nested candidate, vacancy, and latest application summary.

        Filters:
          - vacancy_id: scope to one vacancy (Kanban view)
          - workspace_id: required (Kandidaten view uses this without vacancy_id)
          - stage: optional stage filter
        """
        conditions = ["c.workspace_id = $1"]
        params: list = [workspace_id]
        idx = 2

        if vacancy_id is not None:
            conditions.append(f"c.vacancy_id = ${idx}")
            params.append(vacancy_id)
            idx += 1

        if candidate_id is not None:
            conditions.append(f"c.candidate_id = ${idx}")
            params.append(candidate_id)
            idx += 1

        if stage is not None:
            conditions.append(f"c.stage = ${idx}")
            params.append(stage)
            idx += 1

        where = " AND ".join(conditions)

        return await self.pool.fetch(
            f"""
            SELECT {_SELECT_COLS}
            FROM ats.candidacies c
            JOIN ats.candidates cand ON cand.id = c.candidate_id
            LEFT JOIN ats.vacancies v ON v.id = c.vacancy_id
            {_LATEST_APP_LATERAL}
            {_LINKED_VACANCIES_LATERAL}
            WHERE {where}
            ORDER BY c.stage_updated_at DESC
            """,
            *params,
        )

    async def get_by_id(self, candidacy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single candidacy by ID with nested info."""
        return await self.pool.fetchrow(
            f"""
            SELECT {_SELECT_COLS}
            FROM ats.candidacies c
            JOIN ats.candidates cand ON cand.id = c.candidate_id
            LEFT JOIN ats.vacancies v ON v.id = c.vacancy_id
            {_LATEST_APP_LATERAL}
            {_LINKED_VACANCIES_LATERAL}
            WHERE c.id = $1
            """,
            candidacy_id,
        )

    async def create(
        self,
        workspace_id: uuid.UUID,
        candidate_id: uuid.UUID,
        vacancy_id: Optional[uuid.UUID],
        stage: str,
        source: Optional[str],
    ) -> asyncpg.Record:
        """Insert a new candidacy and return the inserted row."""
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.candidacies
                (workspace_id, candidate_id, vacancy_id, stage, source)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, vacancy_id, candidate_id, stage, source,
                      stage_updated_at, created_at, updated_at
            """,
            workspace_id,
            candidate_id,
            vacancy_id,
            stage,
            source,
        )

    async def update_stage(
        self, candidacy_id: uuid.UUID, stage: str
    ) -> Optional[asyncpg.Record]:
        """Update stage and reset stage_updated_at. Returns None if not found."""
        return await self.pool.fetchrow(
            """
            UPDATE ats.candidacies
            SET stage = $1, stage_updated_at = NOW()
            WHERE id = $2
            RETURNING id, vacancy_id, candidate_id, stage, source,
                      stage_updated_at, created_at, updated_at
            """,
            stage,
            candidacy_id,
        )

    async def find_by_candidate_and_vacancy(
        self, candidate_id: uuid.UUID, vacancy_id: uuid.UUID
    ) -> Optional[asyncpg.Record]:
        """Return the candidacy row for a given candidate+vacancy pair, or None."""
        return await self.pool.fetchrow(
            """
            SELECT id, stage, candidate_id, vacancy_id, workspace_id
            FROM ats.candidacies
            WHERE candidate_id = $1 AND vacancy_id = $2
            """,
            candidate_id,
            vacancy_id,
        )

    async def exists_for_vacancy(
        self, candidate_id: uuid.UUID, vacancy_id: uuid.UUID
    ) -> bool:
        """Check if a candidacy already exists for this candidate+vacancy pair."""
        row = await self.pool.fetchrow(
            "SELECT 1 FROM ats.candidacies WHERE candidate_id = $1 AND vacancy_id = $2",
            candidate_id,
            vacancy_id,
        )
        return row is not None
