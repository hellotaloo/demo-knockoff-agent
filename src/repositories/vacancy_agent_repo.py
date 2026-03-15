"""
Repository for ats.vacancy_agents - agent registration per vacancy.
"""
import asyncpg
import uuid
from typing import Optional


class VacancyAgentRepository:
    """CRUD operations for ats.vacancy_agents."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get(
        self, vacancy_id: uuid.UUID, agent_type: str
    ) -> Optional[asyncpg.Record]:
        """Get a vacancy agent registration."""
        return await self.pool.fetchrow(
            """
            SELECT id, vacancy_id, agent_type, is_online, created_at
            FROM ats.vacancy_agents
            WHERE vacancy_id = $1 AND agent_type = $2
            """,
            vacancy_id, agent_type,
        )

    async def set_online(
        self, vacancy_id: uuid.UUID, agent_type: str, is_online: bool
    ) -> Optional[asyncpg.Record]:
        """Toggle the is_online flag for a vacancy agent."""
        return await self.pool.fetchrow(
            """
            UPDATE ats.vacancy_agents
            SET is_online = $1
            WHERE vacancy_id = $2 AND agent_type = $3
            RETURNING id, vacancy_id, agent_type, is_online, created_at
            """,
            is_online, vacancy_id, agent_type,
        )
