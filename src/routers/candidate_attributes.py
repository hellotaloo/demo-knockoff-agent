"""
Candidate attributes router.

Two resource types:
1. Attribute types catalog (workspace-scoped) — CRUD for managing the available attribute definitions
2. Candidate attributes (per candidate) — set/remove attribute values on a candidate
"""
import json
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Path, Query, HTTPException
import asyncpg

from src.database import get_db_pool
from src.auth.dependencies import get_current_user, UserProfile
from src.exceptions import parse_uuid
from src.models.common import PaginatedResponse
from src.repositories.candidate_attribute_type_repo import CandidateAttributeTypeRepository
from src.repositories.candidate_attribute_repo import CandidateAttributeRepository
from src.repositories.candidate_repo import CandidateRepository
from src.models.candidate_attribute import (
    AttributeTypeCreate,
    AttributeTypeUpdate,
    AttributeTypeResponse,
    CandidateAttributeSet,
    CandidateAttributeBulkSet,
    CandidateAttributeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Candidate Attributes"])


# =============================================================================
# Helpers
# =============================================================================

def _parse_options(raw):
    """Parse options field — may be a list, a JSON string, or None."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _build_type_response(record: asyncpg.Record) -> AttributeTypeResponse:
    """Convert a DB record to an AttributeTypeResponse."""
    return AttributeTypeResponse(
        id=str(record["id"]),
        workspace_id=str(record["workspace_id"]),
        slug=record["slug"],
        name=record["name"],
        description=record["description"],
        category=record["category"],
        data_type=record["data_type"],
        options=_parse_options(record["options"]),
        icon=record["icon"],
        is_default=record["is_default"],
        is_active=record["is_active"],
        sort_order=record["sort_order"],
        collected_by=record["collected_by"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


def _build_attribute_response(record: asyncpg.Record, include_type: bool = False) -> CandidateAttributeResponse:
    """Convert a DB record to a CandidateAttributeResponse."""
    attr_type = None
    if include_type and "type_slug" in record.keys():
        attr_type = AttributeTypeResponse(
            id=str(record["attribute_type_id"]),
            workspace_id=str(record["type_workspace_id"]),
            slug=record["type_slug"],
            name=record["type_name"],
            description=record["type_description"],
            category=record["type_category"],
            data_type=record["type_data_type"],
            options=_parse_options(record["type_options"]),
            icon=record["type_icon"],
            is_default=record["type_is_default"],
            is_active=record["type_is_active"],
            sort_order=record["type_sort_order"],
            collected_by=record["type_collected_by"],
            created_at=record["type_created_at"],
            updated_at=record["type_updated_at"],
        )

    return CandidateAttributeResponse(
        id=str(record["id"]),
        candidate_id=str(record["candidate_id"]),
        attribute_type_id=str(record["attribute_type_id"]),
        attribute_type=attr_type,
        value=record["value"],
        source=record["source"],
        source_session_id=record["source_session_id"],
        verified=record["verified"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


# =============================================================================
# Attribute Types Catalog (workspace-scoped)
# =============================================================================

@router.get(
    "/workspaces/{workspace_id}/candidate-attribute-types",
    response_model=PaginatedResponse[AttributeTypeResponse],
)
async def list_attribute_types(
    workspace_id: str = Path(...),
    category: Optional[str] = Query(None, description="Filter by category (legal, transport, availability, etc.)"),
    collected_by: Optional[str] = Query(None, description="Filter by collecting phase (pre_screening, contract, etc.)"),
    is_active: Optional[bool] = Query(True, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=200, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    user: UserProfile = Depends(get_current_user),
):
    """List all candidate attribute types for a workspace."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    pool = await get_db_pool()
    repo = CandidateAttributeTypeRepository(pool)
    records = await repo.list_for_workspace(ws_uuid, category=category, collected_by=collected_by, is_active=is_active)
    items = [_build_type_response(r) for r in records]
    total = len(items)
    page = items[offset:offset + limit]
    return PaginatedResponse(items=page, total=total, limit=limit, offset=offset)


@router.post(
    "/workspaces/{workspace_id}/candidate-attribute-types",
    response_model=AttributeTypeResponse,
    status_code=201,
)
async def create_attribute_type(
    data: AttributeTypeCreate,
    workspace_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
):
    """Create a new candidate attribute type."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    pool = await get_db_pool()
    repo = CandidateAttributeTypeRepository(pool)
    record = await repo.create(
        ws_uuid,
        slug=data.slug,
        name=data.name,
        description=data.description,
        category=data.category,
        data_type=data.data_type.value if data.data_type else "text",
        options=data.options,
        icon=data.icon,
        is_default=data.is_default,
        sort_order=data.sort_order,
        collected_by=data.collected_by,
    )
    return _build_type_response(record)


@router.patch(
    "/workspaces/{workspace_id}/candidate-attribute-types/{attr_type_id}",
    response_model=AttributeTypeResponse,
)
async def update_attribute_type(
    data: AttributeTypeUpdate,
    workspace_id: str = Path(...),
    attr_type_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
):
    """Update a candidate attribute type."""
    parse_uuid(workspace_id, field="workspace_id")
    type_uuid = parse_uuid(attr_type_id, field="attr_type_id")
    pool = await get_db_pool()
    repo = CandidateAttributeTypeRepository(pool)

    existing = await repo.get_by_id(type_uuid)
    if not existing:
        raise HTTPException(status_code=404, detail="Attribute type not found")

    update_data = data.model_dump(exclude_unset=True)
    if "data_type" in update_data and update_data["data_type"] is not None:
        update_data["data_type"] = update_data["data_type"].value

    record = await repo.update(type_uuid, **update_data)
    return _build_type_response(record)


@router.delete(
    "/workspaces/{workspace_id}/candidate-attribute-types/{attr_type_id}",
    status_code=204,
)
async def delete_attribute_type(
    workspace_id: str = Path(...),
    attr_type_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
):
    """Soft-delete a candidate attribute type."""
    parse_uuid(workspace_id, field="workspace_id")
    type_uuid = parse_uuid(attr_type_id, field="attr_type_id")
    pool = await get_db_pool()
    repo = CandidateAttributeTypeRepository(pool)

    deleted = await repo.soft_delete(type_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Attribute type not found")


# =============================================================================
# Candidate Attributes (values per candidate)
# =============================================================================

@router.get(
    "/candidates/{candidate_id}/attributes",
    response_model=PaginatedResponse[CandidateAttributeResponse],
)
async def list_candidate_attributes(
    candidate_id: str = Path(...),
    category: Optional[str] = Query(None, description="Filter by attribute category"),
    source: Optional[str] = Query(None, description="Filter by source (pre_screening, contract, manual, etc.)"),
    limit: int = Query(50, ge=1, le=200, description="Number of items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Get all attribute values for a candidate."""
    cand_uuid = parse_uuid(candidate_id, field="candidate_id")
    pool = await get_db_pool()
    repo = CandidateAttributeRepository(pool)
    records = await repo.list_for_candidate(cand_uuid, category=category, source=source)
    items = [_build_attribute_response(r, include_type=True) for r in records]
    total = len(items)
    page = items[offset:offset + limit]
    return PaginatedResponse(items=page, total=total, limit=limit, offset=offset)


@router.put(
    "/candidates/{candidate_id}/attributes",
    response_model=CandidateAttributeResponse,
)
async def set_candidate_attribute(
    data: CandidateAttributeSet,
    candidate_id: str = Path(...),
):
    """Set (create or update) a single attribute value for a candidate."""
    cand_uuid = parse_uuid(candidate_id, field="candidate_id")
    type_uuid = parse_uuid(data.attribute_type_id, field="attribute_type_id")

    pool = await get_db_pool()

    # Verify candidate exists
    cand_repo = CandidateRepository(pool)
    candidate = await cand_repo.get_by_id(cand_uuid)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Verify attribute type exists
    type_repo = CandidateAttributeTypeRepository(pool)
    attr_type = await type_repo.get_by_id(type_uuid)
    if not attr_type:
        raise HTTPException(status_code=404, detail="Attribute type not found")

    repo = CandidateAttributeRepository(pool)
    record = await repo.upsert(
        candidate_id=cand_uuid,
        attribute_type_id=type_uuid,
        value=data.value,
        source=data.source,
        source_session_id=data.source_session_id,
        verified=data.verified,
    )

    # Re-fetch with type info
    full_record = await repo.get_by_id(record["id"])
    return _build_attribute_response(full_record, include_type=True)


@router.put(
    "/candidates/{candidate_id}/attributes/bulk",
    response_model=List[CandidateAttributeResponse],
)
async def bulk_set_candidate_attributes(
    data: CandidateAttributeBulkSet,
    candidate_id: str = Path(...),
):
    """Bulk set multiple attribute values for a candidate."""
    cand_uuid = parse_uuid(candidate_id, field="candidate_id")
    pool = await get_db_pool()

    # Verify candidate exists
    cand_repo = CandidateRepository(pool)
    candidate = await cand_repo.get_by_id(cand_uuid)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    repo = CandidateAttributeRepository(pool)
    results = []

    for attr in data.attributes:
        type_uuid = parse_uuid(attr.attribute_type_id, field="attribute_type_id")
        record = await repo.upsert(
            candidate_id=cand_uuid,
            attribute_type_id=type_uuid,
            value=attr.value,
            source=attr.source,
            source_session_id=attr.source_session_id,
            verified=attr.verified,
        )
        full_record = await repo.get_by_id(record["id"])
        results.append(_build_attribute_response(full_record, include_type=True))

    return results


@router.delete(
    "/candidates/{candidate_id}/attributes/{attribute_id}",
    status_code=204,
)
async def delete_candidate_attribute(
    candidate_id: str = Path(...),
    attribute_id: str = Path(...),
):
    """Remove an attribute value from a candidate."""
    parse_uuid(candidate_id, field="candidate_id")
    attr_uuid = parse_uuid(attribute_id, field="attribute_id")
    pool = await get_db_pool()
    repo = CandidateAttributeRepository(pool)

    deleted = await repo.delete_by_id(attr_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Candidate attribute not found")
