"""
Ontology router - workspace knowledge graph management.

Provides endpoints for managing entity types, entities, relation types,
relations, and graph visualization within a workspace ontology.
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Path, Query
import asyncpg

from src.database import get_db_pool
from src.services.ontology_service import OntologyService
from src.auth.dependencies import get_current_user, UserProfile
from src.exceptions import parse_uuid
from src.models.common import PaginatedResponse
from src.models.ontology import (
    OntologyTypeCreate,
    OntologyTypeUpdate,
    OntologyTypeResponse,
    OntologyEntityCreate,
    OntologyEntityUpdate,
    OntologyEntityResponse,
    OntologyEntityDetailResponse,
    OntologyRelationTypeCreate,
    OntologyRelationTypeResponse,
    OntologyRelationCreate,
    OntologyRelationUpdate,
    OntologyRelationResponse,
    OntologyGraphResponse,
    OntologyOverviewResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/ontology",
    tags=["Ontology"],
)


# =============================================================================
# Dependencies
# =============================================================================

async def get_ontology_service(pool: asyncpg.Pool = Depends(get_db_pool)) -> OntologyService:
    """Get OntologyService instance."""
    return OntologyService(pool)


# =============================================================================
# Overview & Graph
# =============================================================================

@router.get("", response_model=OntologyOverviewResponse)
async def get_ontology_overview(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Get ontology overview for a workspace.

    Returns all entity types with their counts, plus totals.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.get_overview(workspace_uuid, user.id)


@router.get("/graph", response_model=OntologyGraphResponse)
async def get_ontology_graph(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Get the full ontology graph for visualization.

    Returns all active nodes and edges, plus type definitions for the legend.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.get_graph(workspace_uuid, user.id)


# =============================================================================
# Entity Types
# =============================================================================

@router.get("/types", response_model=List[OntologyTypeResponse])
async def list_ontology_types(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    List all ontology entity types for a workspace.

    Returns types with entity counts, ordered by sort_order.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.list_types(workspace_uuid, user.id)


@router.post("/types", response_model=OntologyTypeResponse, status_code=201)
async def create_ontology_type(
    data: OntologyTypeCreate,
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Create a new ontology entity type.

    Requires admin or owner role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.create_type(
        workspace_uuid,
        user.id,
        slug=data.slug,
        name=data.name,
        name_plural=data.name_plural,
        description=data.description,
        icon=data.icon,
        color=data.color,
        sort_order=data.sort_order,
    )


@router.patch("/types/{type_id}", response_model=OntologyTypeResponse)
async def update_ontology_type(
    data: OntologyTypeUpdate,
    workspace_id: str = Path(..., description="Workspace ID"),
    type_id: str = Path(..., description="Type ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Update an ontology entity type.

    Requires admin or owner role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    type_uuid = parse_uuid(type_id, field="type_id")
    return await service.update_type(
        workspace_uuid,
        user.id,
        type_uuid,
        name=data.name,
        name_plural=data.name_plural,
        description=data.description,
        icon=data.icon,
        color=data.color,
        sort_order=data.sort_order,
    )


@router.delete("/types/{type_id}")
async def delete_ontology_type(
    workspace_id: str = Path(..., description="Workspace ID"),
    type_id: str = Path(..., description="Type ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Delete an ontology entity type.

    Requires admin or owner role. System types cannot be deleted.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    type_uuid = parse_uuid(type_id, field="type_id")
    await service.delete_type(workspace_uuid, user.id, type_uuid)
    return {"success": True}


# =============================================================================
# Entities
# =============================================================================

@router.get("/entities", response_model=PaginatedResponse[OntologyEntityResponse])
async def list_ontology_entities(
    workspace_id: str = Path(..., description="Workspace ID"),
    type: Optional[str] = Query(None, description="Filter by type slug (e.g., 'job_function')"),
    search: Optional[str] = Query(None, description="Search by name"),
    active: Optional[bool] = Query(True, description="Filter by active status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    List ontology entities with optional filtering.

    Filter by type slug, search by name, and filter by active status.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    entities, total = await service.list_entities(
        workspace_uuid, user.id,
        type_slug=type, search=search, is_active=active,
        limit=limit, offset=offset,
    )
    return PaginatedResponse(items=entities, total=total, limit=limit, offset=offset)


@router.post("/entities", response_model=OntologyEntityResponse, status_code=201)
async def create_ontology_entity(
    data: OntologyEntityCreate,
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Create a new ontology entity.

    Requires admin or owner role. Specify the type via type_slug.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.create_entity(
        workspace_uuid,
        user.id,
        type_slug=data.type_slug,
        name=data.name,
        description=data.description,
        icon=data.icon,
        color=data.color,
        external_id=data.external_id,
        metadata=data.metadata,
        sort_order=data.sort_order,
    )


@router.get("/entities/{entity_id}", response_model=OntologyEntityDetailResponse)
async def get_ontology_entity(
    workspace_id: str = Path(..., description="Workspace ID"),
    entity_id: str = Path(..., description="Entity ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Get a single ontology entity with its relations.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    entity_uuid = parse_uuid(entity_id, field="entity_id")
    return await service.get_entity(workspace_uuid, user.id, entity_uuid)


@router.patch("/entities/{entity_id}", response_model=OntologyEntityResponse)
async def update_ontology_entity(
    data: OntologyEntityUpdate,
    workspace_id: str = Path(..., description="Workspace ID"),
    entity_id: str = Path(..., description="Entity ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Update an ontology entity.

    Requires admin or owner role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    entity_uuid = parse_uuid(entity_id, field="entity_id")
    return await service.update_entity(
        workspace_uuid,
        user.id,
        entity_uuid,
        name=data.name,
        description=data.description,
        icon=data.icon,
        color=data.color,
        external_id=data.external_id,
        metadata=data.metadata,
        sort_order=data.sort_order,
        is_active=data.is_active,
    )


@router.delete("/entities/{entity_id}")
async def delete_ontology_entity(
    workspace_id: str = Path(..., description="Workspace ID"),
    entity_id: str = Path(..., description="Entity ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Soft-delete an ontology entity (sets is_active=false).

    Requires admin or owner role. Relations to this entity remain but
    are filtered from graph/list queries.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    entity_uuid = parse_uuid(entity_id, field="entity_id")
    await service.delete_entity(workspace_uuid, user.id, entity_uuid)
    return {"success": True}


# =============================================================================
# Relation Types
# =============================================================================

@router.get("/relation-types", response_model=List[OntologyRelationTypeResponse])
async def list_ontology_relation_types(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    List all ontology relation types for a workspace.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.list_relation_types(workspace_uuid, user.id)


@router.post("/relation-types", response_model=OntologyRelationTypeResponse, status_code=201)
async def create_ontology_relation_type(
    data: OntologyRelationTypeCreate,
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Create a new ontology relation type.

    Requires admin or owner role. Optionally constrain source/target entity types.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.create_relation_type(
        workspace_uuid,
        user.id,
        slug=data.slug,
        name=data.name,
        source_type_slug=data.source_type_slug,
        target_type_slug=data.target_type_slug,
    )


# =============================================================================
# Relations
# =============================================================================

@router.get("/relations", response_model=List[OntologyRelationResponse])
async def list_ontology_relations(
    workspace_id: str = Path(..., description="Workspace ID"),
    source_id: Optional[str] = Query(None, description="Filter by source entity ID"),
    target_id: Optional[str] = Query(None, description="Filter by target entity ID"),
    type: Optional[str] = Query(None, description="Filter by relation type slug"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    List ontology relations with optional filtering.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    source_uuid = parse_uuid(source_id, field="source_id") if source_id else None
    target_uuid = parse_uuid(target_id, field="target_id") if target_id else None
    return await service.list_relations(
        workspace_uuid, user.id,
        source_entity_id=source_uuid,
        target_entity_id=target_uuid,
        relation_type_slug=type,
    )


@router.post("/relations", response_model=OntologyRelationResponse, status_code=201)
async def create_ontology_relation(
    data: OntologyRelationCreate,
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Create a new relation between two entities.

    Requires admin or owner role. Validates type constraints.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    source_uuid = parse_uuid(data.source_entity_id, field="source_entity_id")
    target_uuid = parse_uuid(data.target_entity_id, field="target_entity_id")
    return await service.create_relation(
        workspace_uuid,
        user.id,
        source_entity_id=source_uuid,
        target_entity_id=target_uuid,
        relation_type_slug=data.relation_type_slug,
        metadata=data.metadata,
    )


@router.patch("/relations/{relation_id}", response_model=OntologyRelationResponse)
async def update_ontology_relation(
    data: OntologyRelationUpdate,
    workspace_id: str = Path(..., description="Workspace ID"),
    relation_id: str = Path(..., description="Relation ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Update a relation's metadata (e.g., requirement_type, priority, condition).

    Requires admin or owner role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    relation_uuid = parse_uuid(relation_id, field="relation_id")
    return await service.update_relation(
        workspace_uuid, user.id, relation_uuid, data.metadata
    )


@router.delete("/relations/{relation_id}")
async def delete_ontology_relation(
    workspace_id: str = Path(..., description="Workspace ID"),
    relation_id: str = Path(..., description="Relation ID"),
    user: UserProfile = Depends(get_current_user),
    service: OntologyService = Depends(get_ontology_service),
):
    """
    Delete an ontology relation.

    Requires admin or owner role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    relation_uuid = parse_uuid(relation_id, field="relation_id")
    await service.delete_relation(workspace_uuid, user.id, relation_uuid)
    return {"success": True}
