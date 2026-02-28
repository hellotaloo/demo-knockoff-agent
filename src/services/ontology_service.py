"""
Ontology service - handles ontology management operations.
"""
import json
import logging
from typing import Optional, Any
from uuid import UUID

import asyncpg

from src.auth.exceptions import WorkspaceAccessDenied, InsufficientRoleError
from src.exceptions import NotFoundError, ValidationError
from src.repositories.ontology_repo import OntologyRepository
from src.repositories.membership_repo import WorkspaceMembershipRepository
from src.models.ontology import (
    OntologyTypeResponse,
    OntologyEntityResponse,
    OntologyEntityDetailResponse,
    OntologyRelationTypeResponse,
    OntologyRelationResponse,
    OntologyGraphNode,
    OntologyGraphEdge,
    OntologyGraphResponse,
    OntologyOverviewResponse,
)

logger = logging.getLogger(__name__)


class OntologyService:
    """Service for ontology operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = OntologyRepository(pool)
        self.membership_repo = WorkspaceMembershipRepository(pool)

    # =========================================================================
    # Access Control
    # =========================================================================

    async def _check_read_access(self, workspace_id: UUID, user_id: UUID) -> dict:
        """Verify user has read access (any workspace member)."""
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))
        return membership

    async def _check_write_access(self, workspace_id: UUID, user_id: UUID) -> dict:
        """Verify user has write access (owner or admin)."""
        membership = await self._check_read_access(workspace_id, user_id)
        if membership["role"] not in ("owner", "admin"):
            raise InsufficientRoleError("admin", membership["role"])
        return membership

    # =========================================================================
    # Types
    # =========================================================================

    async def list_types(self, workspace_id: UUID, user_id: UUID) -> list[OntologyTypeResponse]:
        """List all ontology types for a workspace."""
        await self._check_read_access(workspace_id, user_id)
        rows = await self.repo.list_types(workspace_id)
        return [self._build_type_response(row) for row in rows]

    async def create_type(
        self, workspace_id: UUID, user_id: UUID, **kwargs
    ) -> OntologyTypeResponse:
        """Create a new ontology type."""
        await self._check_write_access(workspace_id, user_id)

        # Check slug uniqueness
        existing = await self.repo.get_type_by_slug(workspace_id, kwargs["slug"])
        if existing:
            raise ValidationError(f"Type with slug '{kwargs['slug']}' already exists", field="slug")

        row = await self.repo.create_type(workspace_id, **kwargs)
        return self._build_type_response(row, entity_count=0)

    async def update_type(
        self, workspace_id: UUID, user_id: UUID, type_id: UUID, **kwargs
    ) -> OntologyTypeResponse:
        """Update an ontology type."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.repo.get_type_by_id(type_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology type", str(type_id))

        row = await self.repo.update_type(type_id, **kwargs)
        # Re-fetch with entity count
        row = await self.repo.get_type_by_id(type_id)
        return self._build_type_response(row)

    async def delete_type(self, workspace_id: UUID, user_id: UUID, type_id: UUID) -> bool:
        """Delete an ontology type. Blocked for system types."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.repo.get_type_by_id(type_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology type", str(type_id))

        if existing["is_system"]:
            raise ValidationError("Cannot delete system ontology types")

        return await self.repo.delete_type(type_id)

    # =========================================================================
    # Entities
    # =========================================================================

    async def list_entities(
        self,
        workspace_id: UUID,
        user_id: UUID,
        type_slug: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OntologyEntityResponse], int]:
        """List entities with optional filtering."""
        await self._check_read_access(workspace_id, user_id)
        rows, total = await self.repo.list_entities(
            workspace_id, type_slug=type_slug, search=search,
            is_active=is_active, limit=limit, offset=offset,
        )
        entities = [self._build_entity_response(row) for row in rows]
        return entities, total

    async def get_entity(
        self, workspace_id: UUID, user_id: UUID, entity_id: UUID
    ) -> OntologyEntityDetailResponse:
        """Get a single entity with its relations."""
        await self._check_read_access(workspace_id, user_id)

        row = await self.repo.get_entity_by_id(entity_id)
        if not row or row["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology entity", str(entity_id))

        # Get relations for this entity
        relation_rows = await self.repo.get_entity_relations(entity_id)
        relations = [self._build_relation_response(r) for r in relation_rows]

        entity = self._build_entity_response(row)
        return OntologyEntityDetailResponse(
            **entity.model_dump(),
            relations=relations,
        )

    async def create_entity(
        self, workspace_id: UUID, user_id: UUID, type_slug: str, **kwargs
    ) -> OntologyEntityResponse:
        """Create a new ontology entity."""
        await self._check_write_access(workspace_id, user_id)

        # Resolve type_slug to type_id
        entity_type = await self.repo.get_type_by_slug(workspace_id, type_slug)
        if not entity_type:
            raise ValidationError(f"Unknown entity type: '{type_slug}'", field="type_slug")

        row = await self.repo.create_entity(workspace_id, entity_type["id"], **kwargs)
        # Re-fetch with joins
        row = await self.repo.get_entity_by_id(row["id"])
        return self._build_entity_response(row)

    async def update_entity(
        self, workspace_id: UUID, user_id: UUID, entity_id: UUID, **kwargs
    ) -> OntologyEntityResponse:
        """Update an ontology entity."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.repo.get_entity_by_id(entity_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology entity", str(entity_id))

        row = await self.repo.update_entity(entity_id, **kwargs)
        return self._build_entity_response(row)

    async def delete_entity(self, workspace_id: UUID, user_id: UUID, entity_id: UUID) -> bool:
        """Soft-delete an entity (set is_active=false)."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.repo.get_entity_by_id(entity_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology entity", str(entity_id))

        return await self.repo.soft_delete_entity(entity_id)

    # =========================================================================
    # Relation Types
    # =========================================================================

    async def list_relation_types(
        self, workspace_id: UUID, user_id: UUID
    ) -> list[OntologyRelationTypeResponse]:
        """List all relation types for a workspace."""
        await self._check_read_access(workspace_id, user_id)
        rows = await self.repo.list_relation_types(workspace_id)
        return [self._build_relation_type_response(row) for row in rows]

    async def create_relation_type(
        self,
        workspace_id: UUID,
        user_id: UUID,
        slug: str,
        name: str,
        source_type_slug: Optional[str] = None,
        target_type_slug: Optional[str] = None,
    ) -> OntologyRelationTypeResponse:
        """Create a new relation type."""
        await self._check_write_access(workspace_id, user_id)

        # Check slug uniqueness
        existing = await self.repo.get_relation_type_by_slug(workspace_id, slug)
        if existing:
            raise ValidationError(f"Relation type with slug '{slug}' already exists", field="slug")

        # Resolve type slugs to IDs
        source_type_id = None
        target_type_id = None

        if source_type_slug:
            source_type = await self.repo.get_type_by_slug(workspace_id, source_type_slug)
            if not source_type:
                raise ValidationError(f"Unknown source type: '{source_type_slug}'", field="source_type_slug")
            source_type_id = source_type["id"]

        if target_type_slug:
            target_type = await self.repo.get_type_by_slug(workspace_id, target_type_slug)
            if not target_type:
                raise ValidationError(f"Unknown target type: '{target_type_slug}'", field="target_type_slug")
            target_type_id = target_type["id"]

        row = await self.repo.create_relation_type(
            workspace_id, slug, name, source_type_id, target_type_id
        )
        return self._build_relation_type_response(row)

    # =========================================================================
    # Relations
    # =========================================================================

    async def list_relations(
        self,
        workspace_id: UUID,
        user_id: UUID,
        source_entity_id: Optional[UUID] = None,
        target_entity_id: Optional[UUID] = None,
        relation_type_slug: Optional[str] = None,
    ) -> list[OntologyRelationResponse]:
        """List relations with optional filtering."""
        await self._check_read_access(workspace_id, user_id)
        rows = await self.repo.list_relations(
            workspace_id, source_entity_id, target_entity_id, relation_type_slug
        )
        return [self._build_relation_response(row) for row in rows]

    async def create_relation(
        self,
        workspace_id: UUID,
        user_id: UUID,
        source_entity_id: UUID,
        target_entity_id: UUID,
        relation_type_slug: str,
        metadata: Optional[dict] = None,
    ) -> OntologyRelationResponse:
        """Create a new relation between entities."""
        await self._check_write_access(workspace_id, user_id)

        # Validate source entity
        source = await self.repo.get_entity_by_id(source_entity_id)
        if not source or source["workspace_id"] != workspace_id:
            raise NotFoundError("Source entity", str(source_entity_id))

        # Validate target entity
        target = await self.repo.get_entity_by_id(target_entity_id)
        if not target or target["workspace_id"] != workspace_id:
            raise NotFoundError("Target entity", str(target_entity_id))

        # Resolve relation type
        rel_type = await self.repo.get_relation_type_by_slug(workspace_id, relation_type_slug)
        if not rel_type:
            raise ValidationError(f"Unknown relation type: '{relation_type_slug}'", field="relation_type_slug")

        # Validate type constraints
        if rel_type["source_type_id"] and source["type_id"] != rel_type["source_type_id"]:
            raise ValidationError(
                f"Relation type '{relation_type_slug}' requires source of type '{rel_type['source_type_slug']}'",
                field="source_entity_id",
            )

        if rel_type["target_type_id"] and target["type_id"] != rel_type["target_type_id"]:
            raise ValidationError(
                f"Relation type '{relation_type_slug}' requires target of type '{rel_type['target_type_slug']}'",
                field="target_entity_id",
            )

        row = await self.repo.create_relation(
            workspace_id, source_entity_id, target_entity_id, rel_type["id"], metadata
        )
        return self._build_relation_response(row)

    async def update_relation(
        self,
        workspace_id: UUID,
        user_id: UUID,
        relation_id: UUID,
        metadata: dict,
    ) -> OntologyRelationResponse:
        """Update a relation's metadata."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.repo.get_relation_by_id(relation_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology relation", str(relation_id))

        row = await self.repo.update_relation(relation_id, metadata)
        return self._build_relation_response(row)

    async def delete_relation(self, workspace_id: UUID, user_id: UUID, relation_id: UUID) -> bool:
        """Delete a relation."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.repo.get_relation_by_id(relation_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Ontology relation", str(relation_id))

        return await self.repo.delete_relation(relation_id)

    # =========================================================================
    # Graph & Overview
    # =========================================================================

    async def get_graph(self, workspace_id: UUID, user_id: UUID) -> OntologyGraphResponse:
        """Get the full ontology graph for visualization."""
        await self._check_read_access(workspace_id, user_id)

        nodes_rows = await self.repo.get_graph_nodes(workspace_id)
        edges_rows = await self.repo.get_graph_edges(workspace_id)
        type_rows = await self.repo.list_types(workspace_id)

        nodes = [
            OntologyGraphNode(
                id=str(row["id"]),
                name=row["name"],
                type_slug=row["type_slug"],
                type_name=row["type_name"],
                icon=row["icon"],
                color=row["color"],
                description=row["description"],
                metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {}),
                external_id=row["external_id"],
            )
            for row in nodes_rows
        ]

        edges = [
            OntologyGraphEdge(
                id=str(row["id"]),
                source=str(row["source_entity_id"]),
                target=str(row["target_entity_id"]),
                relation_type=row["relation_type"],
                relation_label=row["relation_label"],
                metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {}),
            )
            for row in edges_rows
        ]

        types = [self._build_type_response(row) for row in type_rows]

        # Build stats: entity count per type slug
        stats = {}
        for t in type_rows:
            stats[t["slug"]] = t["entity_count"] if "entity_count" in t.keys() else 0

        return OntologyGraphResponse(nodes=nodes, edges=edges, types=types, stats=stats)

    async def get_overview(self, workspace_id: UUID, user_id: UUID) -> OntologyOverviewResponse:
        """Get ontology overview with type counts and totals."""
        await self._check_read_access(workspace_id, user_id)

        type_rows = await self.repo.list_types(workspace_id)
        stats = await self.repo.get_stats(workspace_id)

        types = [self._build_type_response(row) for row in type_rows]

        return OntologyOverviewResponse(
            types=types,
            total_entities=stats["total_entities"],
            total_relations=stats["total_relations"],
        )

    # =========================================================================
    # Seeding
    # =========================================================================

    async def seed_workspace(self, workspace_id: UUID) -> None:
        """Seed default ontology types and relation types for a workspace."""
        has_types = await self.repo.has_types(workspace_id)
        if not has_types:
            await self.repo.seed_defaults(workspace_id)
            logger.info(f"Seeded ontology defaults for workspace {workspace_id}")

    # =========================================================================
    # Response Builders
    # =========================================================================

    @staticmethod
    def _build_type_response(row: asyncpg.Record, entity_count: Optional[int] = None) -> OntologyTypeResponse:
        """Build an OntologyTypeResponse from a database row."""
        return OntologyTypeResponse(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            slug=row["slug"],
            name=row["name"],
            name_plural=row.get("name_plural"),
            description=row.get("description"),
            icon=row.get("icon"),
            color=row.get("color"),
            sort_order=row["sort_order"],
            is_system=row["is_system"],
            entity_count=entity_count if entity_count is not None else row.get("entity_count", 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _build_entity_response(row: asyncpg.Record) -> OntologyEntityResponse:
        """Build an OntologyEntityResponse from a database row."""
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return OntologyEntityResponse(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            type_id=str(row["type_id"]),
            type_slug=row["type_slug"],
            type_name=row["type_name"],
            name=row["name"],
            description=row.get("description"),
            icon=row.get("icon"),
            color=row.get("color"),
            external_id=row.get("external_id"),
            metadata=metadata or {},
            sort_order=row["sort_order"],
            is_active=row["is_active"],
            relation_count=row.get("relation_count", 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _build_relation_type_response(row: asyncpg.Record) -> OntologyRelationTypeResponse:
        """Build an OntologyRelationTypeResponse from a database row."""
        return OntologyRelationTypeResponse(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            slug=row["slug"],
            name=row["name"],
            source_type_id=str(row["source_type_id"]) if row.get("source_type_id") else None,
            source_type_slug=row.get("source_type_slug"),
            target_type_id=str(row["target_type_id"]) if row.get("target_type_id") else None,
            target_type_slug=row.get("target_type_slug"),
            is_system=row["is_system"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _build_relation_response(row: asyncpg.Record) -> OntologyRelationResponse:
        """Build an OntologyRelationResponse from a database row."""
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return OntologyRelationResponse(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            source_entity_id=str(row["source_entity_id"]),
            source_entity_name=row["source_entity_name"],
            source_type_slug=row["source_type_slug"],
            target_entity_id=str(row["target_entity_id"]),
            target_entity_name=row["target_entity_name"],
            target_type_slug=row["target_type_slug"],
            relation_type_id=str(row["relation_type_id"]),
            relation_type_slug=row["relation_type_slug"],
            relation_type_name=row["relation_type_name"],
            metadata=metadata or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
