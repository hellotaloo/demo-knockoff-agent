"""
Repository for document types - workspace-scoped reference data.
"""
import asyncpg
import uuid
from typing import Optional


# All columns we select in document_type queries
_COLUMNS = """
    id, workspace_id, slug, name, description, category,
    requires_front_back, is_verifiable, icon, is_default,
    is_active, sort_order, parent_id,
    prato_flex_type_id, prato_flex_detail_type_id,
    scan_mode, verification_config, ai_hint,
    created_at, updated_at
"""


class DocumentTypeRepository:
    """CRUD operations for ats.types_documents."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
        parents_only: bool = False,
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

        if parents_only:
            conditions.append("parent_id IS NULL")

        where = " AND ".join(conditions)
        return await self.pool.fetch(
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
            WHERE {where}
            ORDER BY sort_order, name
            """,
            *params,
        )

    async def list_children(
        self,
        parent_id: uuid.UUID,
        is_active: Optional[bool] = True,
    ) -> list[asyncpg.Record]:
        """List child document types for a given parent."""
        conditions = ["parent_id = $1"]
        params: list = [parent_id]
        idx = 2

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1

        where = " AND ".join(conditions)
        return await self.pool.fetch(
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
            WHERE {where}
            ORDER BY sort_order, name
            """,
            *params,
        )

    async def list_parents_with_children(
        self,
        workspace_id: uuid.UUID,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> list[asyncpg.Record]:
        """
        Get parent document types with their children in a single query.

        The category filter only applies to parents. Children are included
        based on parent match (a child may have a different category than
        its parent, e.g. identity parent with certificate children).
        """
        parent_conditions = ["workspace_id = $1", "parent_id IS NULL"]
        params: list = [workspace_id]
        idx = 2

        if category is not None:
            parent_conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1

        if is_active is not None:
            parent_conditions.append(f"is_active = ${idx}")
            params.append(is_active)

        parent_where = " AND ".join(parent_conditions)

        # Children join on parent_id; is_active filter applies to children too
        child_active = ""
        if is_active is not None:
            child_active = f"AND is_active = ${idx}"

        return await self.pool.fetch(
            f"""
            WITH matched_parents AS (
                SELECT id FROM ats.types_documents
                WHERE {parent_where}
            )
            SELECT {_COLUMNS}
            FROM ats.types_documents
            WHERE (
                id IN (SELECT id FROM matched_parents)
                OR
                (parent_id IN (SELECT id FROM matched_parents) {child_active})
            )
            ORDER BY
                COALESCE(parent_id, id),
                parent_id IS NOT NULL,
                sort_order, name
            """,
            *params,
        )

    async def get_by_id(self, doc_type_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single document type by ID."""
        return await self.pool.fetchrow(
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
            WHERE id = $1
            """,
            doc_type_id,
        )

    async def get_by_slug(self, workspace_id: uuid.UUID, slug: str) -> Optional[asyncpg.Record]:
        """Get a document type by workspace + slug."""
        return await self.pool.fetchrow(
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
            WHERE workspace_id = $1 AND slug = $2
            """,
            workspace_id, slug,
        )

    async def get_defaults(self, workspace_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all default document types for a workspace."""
        return await self.pool.fetch(
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
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
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
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
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_documents
            WHERE id = ANY($1)
            ORDER BY sort_order, name
            """,
            ids,
        )

    async def create(self, workspace_id: uuid.UUID, **kwargs) -> asyncpg.Record:
        """Create a new document type."""
        import json
        config = kwargs.get("verification_config")
        return await self.pool.fetchrow(
            f"""
            INSERT INTO ats.types_documents
                (workspace_id, slug, name, description, category,
                 requires_front_back, is_verifiable, icon, is_default, sort_order,
                 parent_id, prato_flex_type_id, prato_flex_detail_type_id,
                 scan_mode, verification_config)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING {_COLUMNS}
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
            kwargs.get("parent_id"),
            kwargs.get("prato_flex_type_id"),
            kwargs.get("prato_flex_detail_type_id"),
            kwargs.get("scan_mode", "single"),
            json.dumps(config) if config is not None else None,
        )

    async def update(self, doc_type_id: uuid.UUID, **kwargs) -> Optional[asyncpg.Record]:
        """Partial update of a document type."""
        updates = []
        params = []
        idx = 1

        for field in [
            "name", "description", "category", "requires_front_back",
            "is_verifiable", "icon", "is_default", "is_active", "sort_order",
            "scan_mode", "ai_hint",
        ]:
            if field in kwargs and kwargs[field] is not None:
                updates.append(f"{field} = ${idx}")
                params.append(kwargs[field])
                idx += 1

        if "verification_config" in kwargs:
            import json
            updates.append(f"verification_config = ${idx}")
            val = kwargs["verification_config"]
            params.append(json.dumps(val) if val is not None else None)
            idx += 1

        if not updates:
            return await self.get_by_id(doc_type_id)

        updates.append("updated_at = NOW()")
        params.append(doc_type_id)

        return await self.pool.fetchrow(
            f"""
            UPDATE ats.types_documents
            SET {", ".join(updates)}
            WHERE id = ${idx}
            RETURNING {_COLUMNS}
            """,
            *params,
        )

    async def soft_delete(self, doc_type_id: uuid.UUID) -> bool:
        """Soft-delete a document type (set is_active=false)."""
        result = await self.pool.execute(
            "UPDATE ats.types_documents SET is_active = false, updated_at = NOW() WHERE id = $1",
            doc_type_id,
        )
        return result == "UPDATE 1"
