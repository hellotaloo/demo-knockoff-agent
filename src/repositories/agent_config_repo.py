"""
Agent config repository - versioned JSONB config for all agent types.
"""
import asyncpg
import uuid
from typing import Optional


class AgentConfigRepository:
    """Repository for versioned agent configuration (agents.agent_config)."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_active(
        self, workspace_id: uuid.UUID, config_type: str
    ) -> Optional[asyncpg.Record]:
        """Get the active config for a workspace + config_type."""
        return await self.pool.fetchrow(
            """
            SELECT id, workspace_id, config_type, version, settings, is_active, created_by, created_at
            FROM agents.agent_config
            WHERE workspace_id = $1 AND config_type = $2 AND is_active = true
            LIMIT 1
            """,
            workspace_id,
            config_type,
        )

    async def get_history(
        self, workspace_id: uuid.UUID, config_type: str, limit: int = 20
    ) -> list[asyncpg.Record]:
        """Get version history for a config type, newest first."""
        return await self.pool.fetch(
            """
            SELECT id, version, settings, is_active, created_by, created_at
            FROM agents.agent_config
            WHERE workspace_id = $1 AND config_type = $2
            ORDER BY version DESC
            LIMIT $3
            """,
            workspace_id,
            config_type,
            limit,
        )

    async def save(
        self,
        workspace_id: uuid.UUID,
        config_type: str,
        settings: dict,
        created_by: Optional[uuid.UUID] = None,
    ) -> asyncpg.Record:
        """
        Save a new config version. Deactivates the previous active version.

        Returns the newly created config record.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Get current max version
                current_version = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(version), 0)
                    FROM agents.agent_config
                    WHERE workspace_id = $1 AND config_type = $2
                    """,
                    workspace_id,
                    config_type,
                )

                # Deactivate all previous versions
                await conn.execute(
                    """
                    UPDATE agents.agent_config
                    SET is_active = false
                    WHERE workspace_id = $1 AND config_type = $2 AND is_active = true
                    """,
                    workspace_id,
                    config_type,
                )

                # Insert new version
                import json
                return await conn.fetchrow(
                    """
                    INSERT INTO agents.agent_config (workspace_id, config_type, version, settings, is_active, created_by)
                    VALUES ($1, $2, $3, $4::jsonb, true, $5)
                    RETURNING id, workspace_id, config_type, version, settings, is_active, created_by, created_at
                    """,
                    workspace_id,
                    config_type,
                    current_version + 1,
                    json.dumps(settings),
                    created_by,
                )

    async def rollback_to_version(
        self, workspace_id: uuid.UUID, config_type: str, version: int
    ) -> Optional[asyncpg.Record]:
        """
        Rollback to a specific version by copying its settings as a new version.

        Returns the newly created config record, or None if the source version doesn't exist.
        """
        source = await self.pool.fetchrow(
            """
            SELECT settings FROM agents.agent_config
            WHERE workspace_id = $1 AND config_type = $2 AND version = $3
            """,
            workspace_id,
            config_type,
            version,
        )
        if not source:
            return None

        import json
        settings = json.loads(source["settings"]) if isinstance(source["settings"], str) else source["settings"]
        return await self.save(workspace_id, config_type, settings)
