"""
Repository for integration connections.
"""
import asyncpg
from typing import Optional
from uuid import UUID


class IntegrationRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_integrations(self) -> list[asyncpg.Record]:
        """List all available integrations from the catalog."""
        return await self.pool.fetch(
            "SELECT * FROM system.integrations WHERE is_active = true ORDER BY name"
        )

    async def list_connections(self, workspace_id: UUID) -> list[asyncpg.Record]:
        """List all connections for a workspace, joined with integration details."""
        return await self.pool.fetch("""
            SELECT
                ic.id, ic.workspace_id, ic.integration_id, ic.is_active,
                ic.credentials, ic.settings, ic.health_status, ic.last_health_check_at,
                ic.created_at, ic.updated_at,
                i.slug, i.name, i.vendor, i.description, i.icon,
                i.is_active as integration_is_active
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.workspace_id = $1
            ORDER BY i.name
        """, workspace_id)

    async def get_connection(self, connection_id: UUID) -> Optional[asyncpg.Record]:
        """Get a single connection with integration details."""
        return await self.pool.fetchrow("""
            SELECT
                ic.id, ic.workspace_id, ic.integration_id, ic.is_active,
                ic.credentials, ic.settings, ic.health_status, ic.last_health_check_at,
                ic.created_at, ic.updated_at,
                i.slug, i.name, i.vendor, i.description, i.icon,
                i.is_active as integration_is_active
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.id = $1
        """, connection_id)

    async def get_connection_by_provider(self, workspace_id: UUID, provider_slug: str) -> Optional[asyncpg.Record]:
        """Get a connection by workspace and provider slug."""
        return await self.pool.fetchrow("""
            SELECT
                ic.id, ic.workspace_id, ic.integration_id, ic.is_active,
                ic.credentials, ic.settings, ic.health_status, ic.last_health_check_at,
                ic.created_at, ic.updated_at,
                i.slug, i.name, i.vendor, i.description, i.icon,
                i.is_active as integration_is_active
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.workspace_id = $1 AND i.slug = $2
        """, workspace_id, provider_slug)

    async def get_integration_by_slug(self, slug: str) -> Optional[asyncpg.Record]:
        """Get an integration catalog entry by slug."""
        return await self.pool.fetchrow(
            "SELECT * FROM system.integrations WHERE slug = $1", slug
        )

    async def upsert_connection(
        self, workspace_id: UUID, integration_id: UUID,
        credentials: dict, settings: dict, is_active: bool
    ) -> asyncpg.Record:
        """Create or update a connection."""
        return await self.pool.fetchrow("""
            INSERT INTO system.integration_connections
                (workspace_id, integration_id, credentials, settings, is_active)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (workspace_id, integration_id) DO UPDATE SET
                credentials = $3,
                settings = $4,
                is_active = $5,
                updated_at = now()
            RETURNING id
        """, workspace_id, integration_id, credentials, settings, is_active)

    async def update_credentials(self, connection_id: UUID, credentials: dict) -> None:
        """Update only the credentials for a connection."""
        await self.pool.execute("""
            UPDATE system.integration_connections
            SET credentials = $2, updated_at = now()
            WHERE id = $1
        """, connection_id, credentials)

    async def update_settings(self, connection_id: UUID, settings: Optional[str] = None, is_active: Optional[bool] = None) -> None:
        """Update settings and/or is_active."""
        if settings is not None and is_active is not None:
            await self.pool.execute("""
                UPDATE system.integration_connections
                SET settings = $2, is_active = $3, updated_at = now()
                WHERE id = $1
            """, connection_id, settings, is_active)
        elif settings is not None:
            await self.pool.execute("""
                UPDATE system.integration_connections
                SET settings = $2, updated_at = now()
                WHERE id = $1
            """, connection_id, settings)
        elif is_active is not None:
            await self.pool.execute("""
                UPDATE system.integration_connections
                SET is_active = $2, updated_at = now()
                WHERE id = $1
            """, connection_id, is_active)

    async def update_health_status(self, connection_id: UUID, status: str) -> None:
        """Update the health status after a check."""
        await self.pool.execute("""
            UPDATE system.integration_connections
            SET health_status = $2, last_health_check_at = now(), updated_at = now()
            WHERE id = $1
        """, connection_id, status)

    async def delete_connection(self, connection_id: UUID) -> None:
        """Delete a connection."""
        await self.pool.execute(
            "DELETE FROM system.integration_connections WHERE id = $1", connection_id
        )
