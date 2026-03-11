"""
Repository for document collection configs and requirements.
"""
import asyncpg
import uuid
from typing import Optional


class DocumentCollectionConfigRepository:
    """CRUD operations for agents.document_collection_configs + agents.document_collection_requirements."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # Configs
    # =========================================================================

    async def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        vacancy_id: Optional[uuid.UUID] = None,
    ) -> list[asyncpg.Record]:
        """List configs for a workspace, optionally filtered by vacancy."""
        if vacancy_id is not None:
            return await self.pool.fetch(
                """
                SELECT id, workspace_id, vacancy_id, name, intro_message,
                       status, is_online, whatsapp_enabled, created_at, updated_at
                FROM agents.document_collection_configs
                WHERE workspace_id = $1 AND vacancy_id = $2
                ORDER BY created_at DESC
                """,
                workspace_id, vacancy_id,
            )
        return await self.pool.fetch(
            """
            SELECT id, workspace_id, vacancy_id, name, intro_message,
                   status, is_online, whatsapp_enabled, created_at, updated_at
            FROM agents.document_collection_configs
            WHERE workspace_id = $1
            ORDER BY created_at DESC
            """,
            workspace_id,
        )

    async def get_by_id(self, config_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a config by ID."""
        return await self.pool.fetchrow(
            """
            SELECT id, workspace_id, vacancy_id, name, intro_message,
                   status, is_online, whatsapp_enabled, created_at, updated_at
            FROM agents.document_collection_configs
            WHERE id = $1
            """,
            config_id,
        )

    async def get_for_vacancy(self, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get config for a specific vacancy."""
        return await self.pool.fetchrow(
            """
            SELECT id, workspace_id, vacancy_id, name, intro_message,
                   status, is_online, whatsapp_enabled, created_at, updated_at
            FROM agents.document_collection_configs
            WHERE vacancy_id = $1
            """,
            vacancy_id,
        )

    async def get_workspace_default(self, workspace_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get the workspace default config (vacancy_id IS NULL)."""
        return await self.pool.fetchrow(
            """
            SELECT id, workspace_id, vacancy_id, name, intro_message,
                   status, is_online, whatsapp_enabled, created_at, updated_at
            FROM agents.document_collection_configs
            WHERE workspace_id = $1 AND vacancy_id IS NULL
            """,
            workspace_id,
        )

    async def create(
        self,
        workspace_id: uuid.UUID,
        vacancy_id: Optional[uuid.UUID],
        name: Optional[str],
        intro_message: Optional[str],
        document_type_ids: list[uuid.UUID],
    ) -> asyncpg.Record:
        """Create a config with its requirements in a transaction."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO agents.document_collection_configs
                        (workspace_id, vacancy_id, name, intro_message, status, is_online, whatsapp_enabled)
                    VALUES ($1, $2, $3, $4, 'draft', false, true)
                    RETURNING id, workspace_id, vacancy_id, name, intro_message,
                              status, is_online, whatsapp_enabled, created_at, updated_at
                    """,
                    workspace_id, vacancy_id, name, intro_message,
                )
                config_id = row["id"]

                # Insert requirements
                for position, dt_id in enumerate(document_type_ids):
                    await conn.execute(
                        """
                        INSERT INTO agents.document_collection_requirements
                            (config_id, document_type_id, position, is_required)
                        VALUES ($1, $2, $3, true)
                        """,
                        config_id, dt_id, position,
                    )

                return row

    async def update(self, config_id: uuid.UUID, **kwargs) -> Optional[asyncpg.Record]:
        """Partial update of a config."""
        updates = []
        params = []
        idx = 1

        for field in ["name", "intro_message", "status", "is_online", "whatsapp_enabled"]:
            if field in kwargs and kwargs[field] is not None:
                updates.append(f"{field} = ${idx}")
                params.append(kwargs[field])
                idx += 1

        if not updates:
            return await self.get_by_id(config_id)

        updates.append("updated_at = NOW()")
        params.append(config_id)

        return await self.pool.fetchrow(
            f"""
            UPDATE agents.document_collection_configs
            SET {", ".join(updates)}
            WHERE id = ${idx}
            RETURNING id, workspace_id, vacancy_id, name, intro_message,
                      status, is_online, whatsapp_enabled, created_at, updated_at
            """,
            *params,
        )

    async def delete(self, config_id: uuid.UUID) -> bool:
        """Delete a config (requirements cascade)."""
        result = await self.pool.execute(
            "DELETE FROM agents.document_collection_configs WHERE id = $1",
            config_id,
        )
        return result == "DELETE 1"

    # =========================================================================
    # Requirements
    # =========================================================================

    async def get_requirements(self, config_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get requirements for a config, joined with document type info."""
        return await self.pool.fetch(
            """
            SELECT
                r.id, r.config_id, r.document_type_id, r.position, r.is_required, r.notes,
                dt.workspace_id AS dt_workspace_id, dt.slug AS dt_slug, dt.name AS dt_name,
                dt.description AS dt_description, dt.category AS dt_category,
                dt.requires_front_back AS dt_requires_front_back,
                dt.is_verifiable AS dt_is_verifiable, dt.icon AS dt_icon,
                dt.is_default AS dt_is_default, dt.is_active AS dt_is_active,
                dt.sort_order AS dt_sort_order,
                dt.created_at AS dt_created_at, dt.updated_at AS dt_updated_at
            FROM agents.document_collection_requirements r
            JOIN ats.document_types dt ON dt.id = r.document_type_id
            WHERE r.config_id = $1
            ORDER BY r.position
            """,
            config_id,
        )

    async def replace_requirements(
        self,
        config_id: uuid.UUID,
        requirements: list[dict],
    ) -> None:
        """Replace all requirements for a config (delete + insert)."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM agents.document_collection_requirements WHERE config_id = $1",
                    config_id,
                )
                for req in requirements:
                    await conn.execute(
                        """
                        INSERT INTO agents.document_collection_requirements
                            (config_id, document_type_id, position, is_required, notes)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        config_id,
                        uuid.UUID(req["document_type_id"]),
                        req.get("position", 0),
                        req.get("is_required", True),
                        req.get("notes"),
                    )
