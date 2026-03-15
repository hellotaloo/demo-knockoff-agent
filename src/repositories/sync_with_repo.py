"""
Repository for types_sync_with junction table and integrations.
"""
import json
import asyncpg
import uuid
from typing import Optional


class SyncWithRepository:
    """CRUD operations for ats.types_sync_with and system.integrations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ─── Integrations ─────────────────────────────────────────────────────────

    async def list_integrations(self, is_active: Optional[bool] = True) -> list[asyncpg.Record]:
        """List all registered integrations."""
        conditions = []
        params: list = []
        idx = 1

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return await self.pool.fetch(
            f"SELECT id, slug, name, vendor, description, icon, is_active, created_at, updated_at "
            f"FROM system.integrations {where} ORDER BY name",
            *params,
        )

    async def get_integration_by_id(self, integration_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single integration by ID."""
        return await self.pool.fetchrow(
            "SELECT id, slug, name, vendor, description, icon, is_active FROM system.integrations WHERE id = $1",
            integration_id,
        )

    # ─── Sync With (junction) ─────────────────────────────────────────────────

    async def list_for_record(self, table_name: str, record_id: uuid.UUID) -> list[asyncpg.Record]:
        """List all sync_with entries for a specific types record."""
        return await self.pool.fetch(
            """
            SELECT sw.id, sw.integration_id, sw.external_id, sw.external_metadata,
                   i.slug AS integration_slug, i.name AS integration_name
            FROM ats.types_sync_with sw
            JOIN system.integrations i ON i.id = sw.integration_id
            WHERE sw.table_name = $1 AND sw.record_id = $2
            ORDER BY i.name
            """,
            table_name, record_id,
        )

    async def list_for_records(self, table_name: str, record_ids: list[uuid.UUID]) -> list[asyncpg.Record]:
        """Batch-load sync_with entries for multiple records."""
        if not record_ids:
            return []
        return await self.pool.fetch(
            """
            SELECT sw.id, sw.record_id, sw.integration_id, sw.external_id, sw.external_metadata,
                   i.slug AS integration_slug, i.name AS integration_name
            FROM ats.types_sync_with sw
            JOIN system.integrations i ON i.id = sw.integration_id
            WHERE sw.table_name = $1 AND sw.record_id = ANY($2)
            ORDER BY i.name
            """,
            table_name, record_ids,
        )

    async def add(
        self,
        table_name: str,
        record_id: uuid.UUID,
        integration_id: uuid.UUID,
        external_id: Optional[str] = None,
        external_metadata: Optional[dict] = None,
    ) -> asyncpg.Record:
        """Add a sync_with link."""
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.types_sync_with (table_name, record_id, integration_id, external_id, external_metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, table_name, record_id, integration_id, external_id, external_metadata, created_at
            """,
            table_name,
            record_id,
            integration_id,
            external_id,
            json.dumps(external_metadata) if external_metadata is not None else None,
        )

    async def remove(self, sync_with_id: uuid.UUID) -> bool:
        """Remove a sync_with link by its ID."""
        result = await self.pool.execute(
            "DELETE FROM ats.types_sync_with WHERE id = $1",
            sync_with_id,
        )
        return result == "DELETE 1"

    async def remove_by_record_and_integration(
        self, table_name: str, record_id: uuid.UUID, integration_id: uuid.UUID
    ) -> bool:
        """Remove a sync_with link by record + integration combo."""
        result = await self.pool.execute(
            "DELETE FROM ats.types_sync_with WHERE table_name = $1 AND record_id = $2 AND integration_id = $3",
            table_name, record_id, integration_id,
        )
        return result == "DELETE 1"
