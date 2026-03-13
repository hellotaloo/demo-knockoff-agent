"""
Repository for candidate attribute types - workspace-scoped catalog.
"""
import json
import asyncpg
import uuid
from typing import Optional


_COLUMNS = """
    id, workspace_id, slug, name, description, category,
    data_type, options, icon, is_default, is_active, sort_order,
    collected_by,
    created_at, updated_at
"""


class CandidateAttributeTypeRepository:
    """CRUD operations for ats.types_attributes."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        category: Optional[str] = None,
        collected_by: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> list[asyncpg.Record]:
        """List attribute types for a workspace with optional filters."""
        conditions = ["workspace_id = $1"]
        params: list = [workspace_id]
        idx = 2

        if category is not None:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1

        if collected_by is not None:
            conditions.append(f"collected_by = ${idx}")
            params.append(collected_by)
            idx += 1

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            params.append(is_active)
            idx += 1

        where = " AND ".join(conditions)
        return await self.pool.fetch(
            f"""
            SELECT {_COLUMNS}
            FROM ats.types_attributes
            WHERE {where}
            ORDER BY sort_order, name
            """,
            *params,
        )

    async def get_by_id(self, attr_type_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single attribute type by ID."""
        return await self.pool.fetchrow(
            f"SELECT {_COLUMNS} FROM ats.types_attributes WHERE id = $1",
            attr_type_id,
        )

    async def get_by_slug(self, workspace_id: uuid.UUID, slug: str) -> Optional[asyncpg.Record]:
        """Get an attribute type by workspace + slug."""
        return await self.pool.fetchrow(
            f"SELECT {_COLUMNS} FROM ats.types_attributes WHERE workspace_id = $1 AND slug = $2",
            workspace_id, slug,
        )

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[asyncpg.Record]:
        """Get multiple attribute types by their IDs."""
        if not ids:
            return []
        return await self.pool.fetch(
            f"SELECT {_COLUMNS} FROM ats.types_attributes WHERE id = ANY($1) ORDER BY sort_order, name",
            ids,
        )

    async def create(self, workspace_id: uuid.UUID, **kwargs) -> asyncpg.Record:
        """Create a new attribute type."""
        options = kwargs.get("options")
        return await self.pool.fetchrow(
            f"""
            INSERT INTO ats.types_attributes
                (workspace_id, slug, name, description, category,
                 data_type, options, icon, is_default, sort_order,
                 collected_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING {_COLUMNS}
            """,
            workspace_id,
            kwargs["slug"],
            kwargs["name"],
            kwargs.get("description"),
            kwargs.get("category", "general"),
            kwargs.get("data_type", "text"),
            json.dumps(options) if options is not None else None,
            kwargs.get("icon"),
            kwargs.get("is_default", False),
            kwargs.get("sort_order", 0),
            kwargs.get("collected_by"),
        )

    async def update(self, attr_type_id: uuid.UUID, **kwargs) -> Optional[asyncpg.Record]:
        """Partial update of an attribute type."""
        updates = []
        params = []
        idx = 1

        for field in [
            "name", "description", "category", "data_type",
            "icon", "is_default", "is_active", "sort_order",
            "collected_by",
        ]:
            if field in kwargs and kwargs[field] is not None:
                updates.append(f"{field} = ${idx}")
                params.append(kwargs[field])
                idx += 1

        if "options" in kwargs:
            updates.append(f"options = ${idx}")
            val = kwargs["options"]
            params.append(json.dumps(val) if val is not None else None)
            idx += 1

        if not updates:
            return await self.get_by_id(attr_type_id)

        updates.append("updated_at = NOW()")
        params.append(attr_type_id)

        return await self.pool.fetchrow(
            f"""
            UPDATE ats.types_attributes
            SET {", ".join(updates)}
            WHERE id = ${idx}
            RETURNING {_COLUMNS}
            """,
            *params,
        )

    async def soft_delete(self, attr_type_id: uuid.UUID) -> bool:
        """Soft-delete an attribute type (set is_active=false)."""
        result = await self.pool.execute(
            "UPDATE ats.types_attributes SET is_active = false, updated_at = NOW() WHERE id = $1",
            attr_type_id,
        )
        return result == "UPDATE 1"
