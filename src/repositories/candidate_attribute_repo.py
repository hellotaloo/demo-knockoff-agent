"""
Repository for candidate attributes - actual values per candidate.
"""
import asyncpg
import uuid
from typing import Optional


_COLUMNS = """
    id, candidate_id, attribute_type_id, value,
    source, source_session_id, verified,
    created_at, updated_at
"""

_COLUMNS_WITH_TYPE = """
    ca.id, ca.candidate_id, ca.attribute_type_id, ca.value,
    ca.source, ca.source_session_id, ca.verified,
    ca.created_at, ca.updated_at,
    cat.slug AS type_slug, cat.name AS type_name, cat.description AS type_description,
    cat.category AS type_category, cat.data_type AS type_data_type,
    cat.options AS type_options, cat.icon AS type_icon,
    cat.is_default AS type_is_default, cat.is_active AS type_is_active,
    cat.sort_order AS type_sort_order, cat.collected_by AS type_collected_by,
    cat.workspace_id AS type_workspace_id,
    cat.created_at AS type_created_at, cat.updated_at AS type_updated_at
"""


class CandidateAttributeRepository:
    """CRUD operations for ats.candidate_attributes."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_for_candidate(
        self,
        candidate_id: uuid.UUID,
        category: Optional[str] = None,
        source: Optional[str] = None,
    ) -> list[asyncpg.Record]:
        """Get all attributes for a candidate, joined with attribute type info."""
        conditions = ["ca.candidate_id = $1", "cat.is_active = true"]
        params: list = [candidate_id]
        idx = 2

        if category is not None:
            conditions.append(f"cat.category = ${idx}")
            params.append(category)
            idx += 1

        if source is not None:
            conditions.append(f"ca.source = ${idx}")
            params.append(source)
            idx += 1

        where = " AND ".join(conditions)
        return await self.pool.fetch(
            f"""
            SELECT {_COLUMNS_WITH_TYPE}
            FROM ats.candidate_attributes ca
            JOIN ats.types_attributes cat ON cat.id = ca.attribute_type_id
            WHERE {where}
            ORDER BY cat.sort_order, cat.name
            """,
            *params,
        )

    async def list_for_candidates(
        self,
        candidate_ids: list[uuid.UUID],
    ) -> list[asyncpg.Record]:
        """Batch load attributes for multiple candidates."""
        if not candidate_ids:
            return []
        return await self.pool.fetch(
            f"""
            SELECT {_COLUMNS_WITH_TYPE}
            FROM ats.candidate_attributes ca
            JOIN ats.types_attributes cat ON cat.id = ca.attribute_type_id
            WHERE ca.candidate_id = ANY($1) AND cat.is_active = true
            ORDER BY ca.candidate_id, cat.sort_order, cat.name
            """,
            candidate_ids,
        )

    async def get_by_id(self, attr_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single candidate attribute by ID."""
        return await self.pool.fetchrow(
            f"""
            SELECT {_COLUMNS_WITH_TYPE}
            FROM ats.candidate_attributes ca
            JOIN ats.types_attributes cat ON cat.id = ca.attribute_type_id
            WHERE ca.id = $1
            """,
            attr_id,
        )

    async def upsert(
        self,
        candidate_id: uuid.UUID,
        attribute_type_id: uuid.UUID,
        value: Optional[str] = None,
        source: Optional[str] = None,
        source_session_id: Optional[str] = None,
        verified: bool = False,
    ) -> asyncpg.Record:
        """Set an attribute value for a candidate (upsert)."""
        return await self.pool.fetchrow(
            f"""
            INSERT INTO ats.candidate_attributes
                (candidate_id, attribute_type_id, value, source, source_session_id, verified)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (candidate_id, attribute_type_id) DO UPDATE SET
                value = EXCLUDED.value,
                source = EXCLUDED.source,
                source_session_id = EXCLUDED.source_session_id,
                verified = EXCLUDED.verified,
                updated_at = NOW()
            RETURNING {_COLUMNS}
            """,
            candidate_id, attribute_type_id, value, source, source_session_id, verified,
        )

    async def delete(self, candidate_id: uuid.UUID, attribute_type_id: uuid.UUID) -> bool:
        """Remove an attribute value from a candidate."""
        result = await self.pool.execute(
            "DELETE FROM ats.candidate_attributes WHERE candidate_id = $1 AND attribute_type_id = $2",
            candidate_id, attribute_type_id,
        )
        return result == "DELETE 1"

    async def delete_by_id(self, attr_id: uuid.UUID) -> bool:
        """Remove an attribute value by its own ID."""
        result = await self.pool.execute(
            "DELETE FROM ats.candidate_attributes WHERE id = $1",
            attr_id,
        )
        return result == "DELETE 1"
