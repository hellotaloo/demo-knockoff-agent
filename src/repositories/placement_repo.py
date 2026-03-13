"""
Placement repository — data access for ats.placements.
"""
import uuid
from typing import Optional
import asyncpg


class PlacementRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(
        self,
        workspace_id: uuid.UUID,
        candidate_id: uuid.UUID,
        vacancy_id: uuid.UUID,
        application_id: Optional[uuid.UUID] = None,
        client_id: Optional[uuid.UUID] = None,
        start_date=None,
        regime: Optional[str] = None,
        contract_id: Optional[str] = None,
    ) -> asyncpg.Record:
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.placements (workspace_id, candidate_id, vacancy_id, application_id, client_id, start_date, regime, contract_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            workspace_id, candidate_id, vacancy_id, application_id, client_id, start_date, regime, contract_id,
        )

    async def get_by_id(self, placement_id: uuid.UUID) -> Optional[asyncpg.Record]:
        return await self.pool.fetchrow(
            "SELECT * FROM ats.placements WHERE id = $1",
            placement_id,
        )

    async def get_by_candidacy(self, candidate_id: uuid.UUID, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        return await self.pool.fetchrow(
            "SELECT * FROM ats.placements WHERE candidate_id = $1 AND vacancy_id = $2 ORDER BY created_at DESC LIMIT 1",
            candidate_id, vacancy_id,
        )
