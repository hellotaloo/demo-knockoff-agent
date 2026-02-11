"""
Activity repository - handles all activity-related database operations.
"""
import asyncpg
import uuid
import json
from typing import Optional, Tuple


class ActivityRepository:
    """Repository for candidate activity database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(
        self,
        candidate_id: uuid.UUID,
        event_type: str,
        actor_type: str = "system",
        application_id: Optional[uuid.UUID] = None,
        vacancy_id: Optional[uuid.UUID] = None,
        channel: Optional[str] = None,
        actor_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        summary: Optional[str] = None
    ) -> uuid.UUID:
        """Create a new activity log entry."""
        activity_id = await self.pool.fetchval(
            """
            INSERT INTO ats.candidate_activities
            (candidate_id, application_id, vacancy_id, event_type, channel, actor_type, actor_id, metadata, summary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            candidate_id,
            application_id,
            vacancy_id,
            event_type,
            channel,
            actor_type,
            actor_id,
            json.dumps(metadata) if metadata else "{}",
            summary
        )
        return activity_id

    async def get_by_id(self, activity_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single activity by ID."""
        return await self.pool.fetchrow(
            """
            SELECT id, candidate_id, application_id, vacancy_id, event_type,
                   channel, actor_type, actor_id, metadata, summary, created_at
            FROM ats.candidate_activities
            WHERE id = $1
            """,
            activity_id
        )

    async def list_for_candidate(
        self,
        candidate_id: uuid.UUID,
        event_types: Optional[list[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List activities for a candidate with optional filtering.

        Returns:
            Tuple of (activity rows, total count)
        """
        conditions = ["candidate_id = $1"]
        params = [candidate_id]
        param_idx = 2

        if event_types:
            conditions.append(f"event_type = ANY(${param_idx})")
            params.append(event_types)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        # Get total count
        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM ats.candidate_activities WHERE {where_clause}",
            *params
        )

        # Get activities
        query = f"""
            SELECT id, candidate_id, application_id, vacancy_id, event_type,
                   channel, actor_type, actor_id, metadata, summary, created_at
            FROM ats.candidate_activities
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)
        return rows, total

    async def list_for_application(
        self,
        application_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List activities for an application.

        Returns:
            Tuple of (activity rows, total count)
        """
        total = await self.pool.fetchval(
            "SELECT COUNT(*) FROM ats.candidate_activities WHERE application_id = $1",
            application_id
        )

        rows = await self.pool.fetch(
            """
            SELECT id, candidate_id, application_id, vacancy_id, event_type,
                   channel, actor_type, actor_id, metadata, summary, created_at
            FROM ats.candidate_activities
            WHERE application_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            application_id, limit, offset
        )
        return rows, total

    async def list_for_vacancy(
        self,
        vacancy_id: uuid.UUID,
        event_types: Optional[list[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List activities for a vacancy.

        Returns:
            Tuple of (activity rows, total count)
        """
        conditions = ["vacancy_id = $1"]
        params = [vacancy_id]
        param_idx = 2

        if event_types:
            conditions.append(f"event_type = ANY(${param_idx})")
            params.append(event_types)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM ats.candidate_activities WHERE {where_clause}",
            *params
        )

        query = f"""
            SELECT id, candidate_id, application_id, vacancy_id, event_type,
                   channel, actor_type, actor_id, metadata, summary, created_at
            FROM ats.candidate_activities
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)
        return rows, total

    async def delete_for_candidate(self, candidate_id: uuid.UUID) -> int:
        """Delete all activities for a candidate. Returns count deleted."""
        result = await self.pool.execute(
            "DELETE FROM ats.candidate_activities WHERE candidate_id = $1",
            candidate_id
        )
        # Result format: "DELETE N"
        return int(result.split()[-1])

    async def delete_for_application(self, application_id: uuid.UUID) -> int:
        """Delete all activities for an application. Returns count deleted."""
        result = await self.pool.execute(
            "DELETE FROM ats.candidate_activities WHERE application_id = $1",
            application_id
        )
        return int(result.split()[-1])
