"""
Repository for ontology database operations.
"""
import json
import logging
import uuid
from typing import Optional, List, Tuple

import asyncpg

logger = logging.getLogger(__name__)


class OntologyRepository:
    """Repository for ontology CRUD operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # Types
    # =========================================================================

    async def list_types(self, workspace_id: uuid.UUID) -> List[asyncpg.Record]:
        """List all ontology types for a workspace with entity counts."""
        return await self.pool.fetch("""
            SELECT t.*,
                   COALESCE(ec.cnt, 0) as entity_count
            FROM ats.ontology_types t
            LEFT JOIN (
                SELECT type_id, COUNT(*) as cnt
                FROM ats.ontology_entities
                WHERE workspace_id = $1 AND is_active = true
                GROUP BY type_id
            ) ec ON ec.type_id = t.id
            WHERE t.workspace_id = $1
            ORDER BY t.sort_order, t.name
        """, workspace_id)

    async def get_type_by_id(self, type_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single ontology type by ID."""
        return await self.pool.fetchrow("""
            SELECT t.*,
                   COALESCE(ec.cnt, 0) as entity_count
            FROM ats.ontology_types t
            LEFT JOIN (
                SELECT type_id, COUNT(*) as cnt
                FROM ats.ontology_entities
                WHERE is_active = true
                GROUP BY type_id
            ) ec ON ec.type_id = t.id
            WHERE t.id = $1
        """, type_id)

    async def get_type_by_slug(self, workspace_id: uuid.UUID, slug: str) -> Optional[asyncpg.Record]:
        """Get an ontology type by workspace and slug."""
        return await self.pool.fetchrow("""
            SELECT * FROM ats.ontology_types
            WHERE workspace_id = $1 AND slug = $2
        """, workspace_id, slug)

    async def create_type(
        self,
        workspace_id: uuid.UUID,
        slug: str,
        name: str,
        name_plural: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        sort_order: int = 0,
    ) -> asyncpg.Record:
        """Create a new ontology type."""
        return await self.pool.fetchrow("""
            INSERT INTO ats.ontology_types
                (workspace_id, slug, name, name_plural, description, icon, color, sort_order)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """, workspace_id, slug, name, name_plural, description, icon, color, sort_order)

    async def update_type(self, type_id: uuid.UUID, **kwargs) -> Optional[asyncpg.Record]:
        """Update an ontology type. Only updates provided fields."""
        allowed_fields = {"name", "name_plural", "description", "icon", "color", "sort_order"}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        if not updates:
            return await self.get_type_by_id(type_id)

        set_clauses = []
        params = [type_id]
        for i, (field, value) in enumerate(updates.items(), start=2):
            set_clauses.append(f"{field} = ${i}")
            params.append(value)

        set_clauses.append("updated_at = NOW()")
        query = f"""
            UPDATE ats.ontology_types
            SET {', '.join(set_clauses)}
            WHERE id = $1
            RETURNING *
        """
        return await self.pool.fetchrow(query, *params)

    async def delete_type(self, type_id: uuid.UUID) -> bool:
        """Delete an ontology type. Returns False if it was a system type."""
        result = await self.pool.execute("""
            DELETE FROM ats.ontology_types
            WHERE id = $1 AND is_system = false
        """, type_id)
        return result == "DELETE 1"

    # =========================================================================
    # Entities
    # =========================================================================

    async def list_entities(
        self,
        workspace_id: uuid.UUID,
        type_slug: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[asyncpg.Record], int]:
        """List entities with optional filtering. Returns (rows, total_count)."""
        where_clauses = ["e.workspace_id = $1"]
        params: list = [workspace_id]
        param_idx = 2

        if type_slug:
            where_clauses.append(f"t.slug = ${param_idx}")
            params.append(type_slug)
            param_idx += 1

        if search:
            where_clauses.append(f"e.name ILIKE ${param_idx}")
            params.append(f"%{search}%")
            param_idx += 1

        if is_active is not None:
            where_clauses.append(f"e.is_active = ${param_idx}")
            params.append(is_active)
            param_idx += 1

        where_sql = " AND ".join(where_clauses)

        # Count query
        count_query = f"""
            SELECT COUNT(*)
            FROM ats.ontology_entities e
            JOIN ats.ontology_types t ON t.id = e.type_id
            WHERE {where_sql}
        """
        total = await self.pool.fetchval(count_query, *params)

        # Data query with relation count
        params.append(limit)
        limit_idx = param_idx
        param_idx += 1
        params.append(offset)
        offset_idx = param_idx

        data_query = f"""
            SELECT e.*,
                   t.slug as type_slug,
                   t.name as type_name,
                   COALESCE(rc.cnt, 0) as relation_count
            FROM ats.ontology_entities e
            JOIN ats.ontology_types t ON t.id = e.type_id
            LEFT JOIN (
                SELECT entity_id, COUNT(*) as cnt FROM (
                    SELECT source_entity_id as entity_id FROM ats.ontology_relations WHERE workspace_id = $1
                    UNION ALL
                    SELECT target_entity_id as entity_id FROM ats.ontology_relations WHERE workspace_id = $1
                ) sub
                GROUP BY entity_id
            ) rc ON rc.entity_id = e.id
            WHERE {where_sql}
            ORDER BY t.sort_order, e.sort_order, e.name
            LIMIT ${limit_idx} OFFSET ${offset_idx}
        """
        rows = await self.pool.fetch(data_query, *params)
        return rows, total

    async def get_entity_by_id(self, entity_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single entity by ID with type info and relation count."""
        return await self.pool.fetchrow("""
            SELECT e.*,
                   t.slug as type_slug,
                   t.name as type_name,
                   COALESCE(rc.cnt, 0) as relation_count
            FROM ats.ontology_entities e
            JOIN ats.ontology_types t ON t.id = e.type_id
            LEFT JOIN (
                SELECT entity_id, COUNT(*) as cnt FROM (
                    SELECT source_entity_id as entity_id FROM ats.ontology_relations
                    UNION ALL
                    SELECT target_entity_id as entity_id FROM ats.ontology_relations
                ) sub
                GROUP BY entity_id
            ) rc ON rc.entity_id = e.id
            WHERE e.id = $1
        """, entity_id)

    async def create_entity(
        self,
        workspace_id: uuid.UUID,
        type_id: uuid.UUID,
        name: str,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        external_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        sort_order: int = 0,
    ) -> asyncpg.Record:
        """Create a new ontology entity."""
        return await self.pool.fetchrow("""
            INSERT INTO ats.ontology_entities
                (workspace_id, type_id, name, description, icon, color, external_id, metadata, sort_order)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
        """, workspace_id, type_id, name, description, icon, color, external_id,
             json.dumps(metadata or {}), sort_order)

    async def update_entity(self, entity_id: uuid.UUID, **kwargs) -> Optional[asyncpg.Record]:
        """Update an ontology entity. Only updates provided fields."""
        allowed_fields = {"name", "description", "icon", "color", "external_id", "sort_order", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        # Handle metadata separately (can be set to empty dict)
        if "metadata" in kwargs and kwargs["metadata"] is not None:
            updates["metadata"] = json.dumps(kwargs["metadata"])

        if not updates:
            return await self.get_entity_by_id(entity_id)

        set_clauses = []
        params = [entity_id]
        for i, (field, value) in enumerate(updates.items(), start=2):
            set_clauses.append(f"{field} = ${i}")
            params.append(value)

        set_clauses.append("updated_at = NOW()")
        query = f"""
            UPDATE ats.ontology_entities
            SET {', '.join(set_clauses)}
            WHERE id = $1
            RETURNING *
        """
        row = await self.pool.fetchrow(query, *params)
        if row:
            return await self.get_entity_by_id(entity_id)
        return None

    async def soft_delete_entity(self, entity_id: uuid.UUID) -> bool:
        """Soft-delete an entity by setting is_active=false."""
        result = await self.pool.execute("""
            UPDATE ats.ontology_entities
            SET is_active = false, updated_at = NOW()
            WHERE id = $1
        """, entity_id)
        return result == "UPDATE 1"

    # =========================================================================
    # Relation Types
    # =========================================================================

    async def list_relation_types(self, workspace_id: uuid.UUID) -> List[asyncpg.Record]:
        """List all relation types for a workspace."""
        return await self.pool.fetch("""
            SELECT rt.*,
                   st.slug as source_type_slug,
                   tt.slug as target_type_slug
            FROM ats.ontology_relation_types rt
            LEFT JOIN ats.ontology_types st ON st.id = rt.source_type_id
            LEFT JOIN ats.ontology_types tt ON tt.id = rt.target_type_id
            WHERE rt.workspace_id = $1
            ORDER BY rt.slug
        """, workspace_id)

    async def get_relation_type_by_slug(
        self, workspace_id: uuid.UUID, slug: str
    ) -> Optional[asyncpg.Record]:
        """Get a relation type by workspace and slug."""
        return await self.pool.fetchrow("""
            SELECT rt.*,
                   st.slug as source_type_slug,
                   tt.slug as target_type_slug
            FROM ats.ontology_relation_types rt
            LEFT JOIN ats.ontology_types st ON st.id = rt.source_type_id
            LEFT JOIN ats.ontology_types tt ON tt.id = rt.target_type_id
            WHERE rt.workspace_id = $1 AND rt.slug = $2
        """, workspace_id, slug)

    async def create_relation_type(
        self,
        workspace_id: uuid.UUID,
        slug: str,
        name: str,
        source_type_id: Optional[uuid.UUID] = None,
        target_type_id: Optional[uuid.UUID] = None,
    ) -> asyncpg.Record:
        """Create a new relation type."""
        row = await self.pool.fetchrow("""
            INSERT INTO ats.ontology_relation_types
                (workspace_id, slug, name, source_type_id, target_type_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """, workspace_id, slug, name, source_type_id, target_type_id)
        # Re-fetch with joins
        return await self.get_relation_type_by_slug(workspace_id, slug)

    # =========================================================================
    # Relations
    # =========================================================================

    async def list_relations(
        self,
        workspace_id: uuid.UUID,
        source_entity_id: Optional[uuid.UUID] = None,
        target_entity_id: Optional[uuid.UUID] = None,
        relation_type_slug: Optional[str] = None,
    ) -> List[asyncpg.Record]:
        """List relations with optional filtering."""
        where_clauses = ["r.workspace_id = $1"]
        params: list = [workspace_id]
        param_idx = 2

        if source_entity_id:
            where_clauses.append(f"r.source_entity_id = ${param_idx}")
            params.append(source_entity_id)
            param_idx += 1

        if target_entity_id:
            where_clauses.append(f"r.target_entity_id = ${param_idx}")
            params.append(target_entity_id)
            param_idx += 1

        if relation_type_slug:
            where_clauses.append(f"rt.slug = ${param_idx}")
            params.append(relation_type_slug)
            param_idx += 1

        where_sql = " AND ".join(where_clauses)

        return await self.pool.fetch(f"""
            SELECT r.*,
                   se.name as source_entity_name,
                   st.slug as source_type_slug,
                   te.name as target_entity_name,
                   tt.slug as target_type_slug,
                   rt.slug as relation_type_slug,
                   rt.name as relation_type_name
            FROM ats.ontology_relations r
            JOIN ats.ontology_entities se ON se.id = r.source_entity_id
            JOIN ats.ontology_types st ON st.id = se.type_id
            JOIN ats.ontology_entities te ON te.id = r.target_entity_id
            JOIN ats.ontology_types tt ON tt.id = te.type_id
            JOIN ats.ontology_relation_types rt ON rt.id = r.relation_type_id
            WHERE {where_sql}
            ORDER BY r.created_at
        """, *params)

    async def get_relation_by_id(self, relation_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single relation by ID with denormalized names."""
        return await self.pool.fetchrow("""
            SELECT r.*,
                   se.name as source_entity_name,
                   st.slug as source_type_slug,
                   te.name as target_entity_name,
                   tt.slug as target_type_slug,
                   rt.slug as relation_type_slug,
                   rt.name as relation_type_name
            FROM ats.ontology_relations r
            JOIN ats.ontology_entities se ON se.id = r.source_entity_id
            JOIN ats.ontology_types st ON st.id = se.type_id
            JOIN ats.ontology_entities te ON te.id = r.target_entity_id
            JOIN ats.ontology_types tt ON tt.id = te.type_id
            JOIN ats.ontology_relation_types rt ON rt.id = r.relation_type_id
            WHERE r.id = $1
        """, relation_id)

    async def create_relation(
        self,
        workspace_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        relation_type_id: uuid.UUID,
        metadata: Optional[dict] = None,
    ) -> asyncpg.Record:
        """Create a new relation between entities."""
        row = await self.pool.fetchrow("""
            INSERT INTO ats.ontology_relations
                (workspace_id, source_entity_id, target_entity_id, relation_type_id, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """, workspace_id, source_entity_id, target_entity_id, relation_type_id,
             json.dumps(metadata or {}))
        return await self.get_relation_by_id(row["id"])

    async def update_relation(self, relation_id: uuid.UUID, metadata: dict) -> Optional[asyncpg.Record]:
        """Update a relation's metadata."""
        await self.pool.execute("""
            UPDATE ats.ontology_relations
            SET metadata = $2, updated_at = NOW()
            WHERE id = $1
        """, relation_id, json.dumps(metadata))
        return await self.get_relation_by_id(relation_id)

    async def delete_relation(self, relation_id: uuid.UUID) -> bool:
        """Hard-delete a relation."""
        result = await self.pool.execute("""
            DELETE FROM ats.ontology_relations WHERE id = $1
        """, relation_id)
        return result == "DELETE 1"

    # =========================================================================
    # Graph
    # =========================================================================

    async def get_graph_nodes(self, workspace_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all active entities for the graph visualization."""
        return await self.pool.fetch("""
            SELECT e.id, e.name, e.description, e.metadata, e.external_id,
                   t.slug as type_slug, t.name as type_name,
                   COALESCE(e.color, t.color) as color,
                   COALESCE(e.icon, t.icon) as icon
            FROM ats.ontology_entities e
            JOIN ats.ontology_types t ON t.id = e.type_id
            WHERE e.workspace_id = $1 AND e.is_active = true
            ORDER BY t.sort_order, e.sort_order, e.name
        """, workspace_id)

    async def get_graph_edges(self, workspace_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all relations for the graph visualization (only between active entities)."""
        return await self.pool.fetch("""
            SELECT r.id, r.source_entity_id, r.target_entity_id, r.metadata,
                   rt.slug as relation_type, rt.name as relation_label
            FROM ats.ontology_relations r
            JOIN ats.ontology_relation_types rt ON rt.id = r.relation_type_id
            JOIN ats.ontology_entities se ON se.id = r.source_entity_id AND se.is_active = true
            JOIN ats.ontology_entities te ON te.id = r.target_entity_id AND te.is_active = true
            WHERE r.workspace_id = $1
            ORDER BY r.created_at
        """, workspace_id)

    async def get_entity_relations(self, entity_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all relations for a specific entity (as source or target)."""
        return await self.pool.fetch("""
            SELECT r.*,
                   se.name as source_entity_name,
                   st.slug as source_type_slug,
                   te.name as target_entity_name,
                   tt.slug as target_type_slug,
                   rt.slug as relation_type_slug,
                   rt.name as relation_type_name
            FROM ats.ontology_relations r
            JOIN ats.ontology_entities se ON se.id = r.source_entity_id
            JOIN ats.ontology_types st ON st.id = se.type_id
            JOIN ats.ontology_entities te ON te.id = r.target_entity_id
            JOIN ats.ontology_types tt ON tt.id = te.type_id
            JOIN ats.ontology_relation_types rt ON rt.id = r.relation_type_id
            WHERE r.source_entity_id = $1 OR r.target_entity_id = $1
            ORDER BY r.created_at
        """, entity_id)

    # =========================================================================
    # Seeding
    # =========================================================================

    async def seed_defaults(self, workspace_id: uuid.UUID) -> None:
        """Seed default ontology types and relation types for a workspace."""
        await self.pool.execute("""
            SELECT ats.seed_ontology_defaults($1)
        """, workspace_id)

    async def has_types(self, workspace_id: uuid.UUID) -> bool:
        """Check if workspace already has ontology types."""
        count = await self.pool.fetchval("""
            SELECT COUNT(*) FROM ats.ontology_types WHERE workspace_id = $1
        """, workspace_id)
        return count > 0

    # =========================================================================
    # Stats
    # =========================================================================

    async def get_stats(self, workspace_id: uuid.UUID) -> dict:
        """Get total entity and relation counts for a workspace."""
        entity_count = await self.pool.fetchval("""
            SELECT COUNT(*) FROM ats.ontology_entities
            WHERE workspace_id = $1 AND is_active = true
        """, workspace_id)

        relation_count = await self.pool.fetchval("""
            SELECT COUNT(*)
            FROM ats.ontology_relations r
            JOIN ats.ontology_entities se ON se.id = r.source_entity_id AND se.is_active = true
            JOIN ats.ontology_entities te ON te.id = r.target_entity_id AND te.is_active = true
            WHERE r.workspace_id = $1
        """, workspace_id)

        return {"total_entities": entity_count, "total_relations": relation_count}
