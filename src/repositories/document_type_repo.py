"""
Repository for document types - workspace-scoped reference data.
"""
import asyncpg
import uuid
from typing import Optional


class DocumentTypeRepository:
    """CRUD operations for ats.document_types."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> list[asyncpg.Record]:
        """List document types for a workspace with optional filters."""
        conditions = ["workspace_id = $1"]
        params: list = [workspace_id]
        idx = 2

        if category is not None:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1

        where = " AND ".join(conditions)
        return await self.pool.fetch(
            f"""
            SELECT id, workspace_id, slug, name, description, category,
                   requires_front_back, is_verifiable, icon, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM ats.document_types
            WHERE {where}
            ORDER BY sort_order, name
            """,
            *params,
        )

    async def get_by_id(self, doc_type_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single document type by ID."""
        return await self.pool.fetchrow(
            """
            SELECT id, workspace_id, slug, name, description, category,
                   requires_front_back, is_verifiable, icon, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM ats.document_types
            WHERE id = $1
            """,
            doc_type_id,
        )

    async def get_by_slug(self, workspace_id: uuid.UUID, slug: str) -> Optional[asyncpg.Record]:
        """Get a document type by workspace + slug."""
        return await self.pool.fetchrow(
            """
            SELECT id, workspace_id, slug, name, description, category,
                   requires_front_back, is_verifiable, icon, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM ats.document_types
            WHERE workspace_id = $1 AND slug = $2
            """,
            workspace_id, slug,
        )

    async def get_defaults(self, workspace_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all default document types for a workspace."""
        return await self.pool.fetch(
            """
            SELECT id, workspace_id, slug, name, description, category,
                   requires_front_back, is_verifiable, icon, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM ats.document_types
            WHERE workspace_id = $1 AND is_default = true AND is_active = true
            ORDER BY sort_order, name
            """,
            workspace_id,
        )

    async def get_by_slugs(self, workspace_id: uuid.UUID, slugs: list[str]) -> list[asyncpg.Record]:
        """Get document types by workspace + slug list."""
        if not slugs:
            return []
        return await self.pool.fetch(
            """
            SELECT id, workspace_id, slug, name, description, category,
                   requires_front_back, is_verifiable, icon, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM ats.document_types
            WHERE workspace_id = $1 AND slug = ANY($2) AND is_active = true
            ORDER BY sort_order, name
            """,
            workspace_id, slugs,
        )

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[asyncpg.Record]:
        """Get multiple document types by their IDs."""
        if not ids:
            return []
        return await self.pool.fetch(
            """
            SELECT id, workspace_id, slug, name, description, category,
                   requires_front_back, is_verifiable, icon, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM ats.document_types
            WHERE id = ANY($1)
            ORDER BY sort_order, name
            """,
            ids,
        )

    async def create(self, workspace_id: uuid.UUID, **kwargs) -> asyncpg.Record:
        """Create a new document type."""
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.document_types
                (workspace_id, slug, name, description, category,
                 requires_front_back, is_verifiable, icon, is_default, sort_order)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id, workspace_id, slug, name, description, category,
                      requires_front_back, is_verifiable, icon, is_default,
                      is_active, sort_order, created_at, updated_at
            """,
            workspace_id,
            kwargs["slug"],
            kwargs["name"],
            kwargs.get("description"),
            kwargs.get("category", "identity"),
            kwargs.get("requires_front_back", False),
            kwargs.get("is_verifiable", False),
            kwargs.get("icon"),
            kwargs.get("is_default", False),
            kwargs.get("sort_order", 0),
        )

    async def update(self, doc_type_id: uuid.UUID, **kwargs) -> Optional[asyncpg.Record]:
        """Partial update of a document type."""
        updates = []
        params = []
        idx = 1

        for field in [
            "name", "description", "category", "requires_front_back",
            "is_verifiable", "icon", "is_default", "is_active", "sort_order",
        ]:
            if field in kwargs and kwargs[field] is not None:
                updates.append(f"{field} = ${idx}")
                params.append(kwargs[field])
                idx += 1

        if not updates:
            return await self.get_by_id(doc_type_id)

        updates.append("updated_at = NOW()")
        params.append(doc_type_id)

        return await self.pool.fetchrow(
            f"""
            UPDATE ats.document_types
            SET {", ".join(updates)}
            WHERE id = ${idx}
            RETURNING id, workspace_id, slug, name, description, category,
                      requires_front_back, is_verifiable, icon, is_default,
                      is_active, sort_order, created_at, updated_at
            """,
            *params,
        )

    async def soft_delete(self, doc_type_id: uuid.UUID) -> bool:
        """Soft-delete a document type (set is_active=false)."""
        result = await self.pool.execute(
            "UPDATE ats.document_types SET is_active = false, updated_at = NOW() WHERE id = $1",
            doc_type_id,
        )
        return result == "UPDATE 1"
