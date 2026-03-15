"""
Document collection router (v2) - workspace-scoped CRUD for document collection system.

Handles: document types, collection configs, requirements, document collections, and resolution.
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Path, Query
import asyncpg

from src.database import get_db_pool
from src.services.document_collection_service import DocumentCollectionService
from src.auth.dependencies import get_current_user, UserProfile
from src.exceptions import parse_uuid
from src.models.common import PaginatedResponse
from src.models.document_collection_v2 import (
    DocumentTypeCreate,
    DocumentTypeUpdate,
    DocumentTypeResponse,
    ResolveDocumentsResponse,
    StartCollectionRequest,
    StartCollectionResponse,
    DocumentCollectionResponse,
    DocumentCollectionDetailResponse,
    DocumentCollectionFullDetailResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/document-collection",
    tags=["Document Collection"],
)


# =============================================================================
# Dependencies
# =============================================================================

async def get_dc_service(pool: asyncpg.Pool = Depends(get_db_pool)) -> DocumentCollectionService:
    """Get DocumentCollectionService instance."""
    return DocumentCollectionService(pool)


# =============================================================================
# Document Types
# =============================================================================

@router.get("/document-types", response_model=List[DocumentTypeResponse])
async def list_document_types(
    workspace_id: str = Path(...),
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(True),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """List all document types for a workspace."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.list_document_types(ws_uuid, user.id, category, is_active)


@router.post("/document-types", response_model=DocumentTypeResponse, status_code=201)
async def create_document_type(
    data: DocumentTypeCreate,
    workspace_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Create a new document type."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    return await service.create_document_type(
        ws_uuid, user.id,
        slug=data.slug,
        name=data.name,
        description=data.description,
        category=data.category,
        requires_front_back=data.requires_front_back,
        is_verifiable=data.is_verifiable,
        icon=data.icon,
        is_default=data.is_default,
        sort_order=data.sort_order,
    )


@router.patch("/document-types/{doc_type_id}", response_model=DocumentTypeResponse)
async def update_document_type(
    data: DocumentTypeUpdate,
    workspace_id: str = Path(...),
    doc_type_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Update a document type."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    dt_uuid = parse_uuid(doc_type_id, field="doc_type_id")
    return await service.update_document_type(
        ws_uuid, user.id, dt_uuid,
        name=data.name,
        description=data.description,
        category=data.category,
        requires_front_back=data.requires_front_back,
        is_verifiable=data.is_verifiable,
        icon=data.icon,
        is_default=data.is_default,
        is_active=data.is_active,
        sort_order=data.sort_order,
    )


@router.delete("/document-types/{doc_type_id}")
async def delete_document_type(
    workspace_id: str = Path(...),
    doc_type_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Soft-delete a document type (set is_active=false)."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    dt_uuid = parse_uuid(doc_type_id, field="doc_type_id")
    await service.delete_document_type(ws_uuid, user.id, dt_uuid)
    return {"success": True}


# =============================================================================
# Document Resolution
# =============================================================================

@router.get("/resolve", response_model=ResolveDocumentsResponse)
async def resolve_documents(
    workspace_id: str = Path(...),
    vacancy_id: Optional[str] = Query(None),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Resolve which documents are needed for a candidate."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    v_uuid = parse_uuid(vacancy_id, field="vacancy_id") if vacancy_id else None
    return await service.resolve_documents(ws_uuid, user.id, v_uuid)


# =============================================================================
# Document Collections
# =============================================================================

@router.get("/collections", response_model=PaginatedResponse[DocumentCollectionResponse])
async def list_collections(
    workspace_id: str = Path(...),
    vacancy_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """List document collections with filtering."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    v_uuid = parse_uuid(vacancy_id, field="vacancy_id") if vacancy_id else None
    items, total = await service.list_collections(ws_uuid, user.id, v_uuid, status, limit, offset)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/collections/{collection_id}", response_model=DocumentCollectionDetailResponse)
async def get_collection(
    workspace_id: str = Path(...),
    collection_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Get a document collection with messages and uploads."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    coll_uuid = parse_uuid(collection_id, field="collection_id")
    return await service.get_collection(ws_uuid, user.id, coll_uuid)


@router.get("/collections/{collection_id}/detail", response_model=DocumentCollectionFullDetailResponse)
async def get_collection_full_detail(
    workspace_id: str = Path(...),
    collection_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Get enriched collection detail with plan, document statuses, and workflow progress."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    coll_uuid = parse_uuid(collection_id, field="collection_id")
    return await service.get_collection_full_detail(ws_uuid, user.id, coll_uuid)


@router.post("/collections/{collection_id}/abandon")
async def abandon_collection(
    workspace_id: str = Path(...),
    collection_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Mark a document collection as abandoned."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    coll_uuid = parse_uuid(collection_id, field="collection_id")
    await service.abandon_collection(ws_uuid, user.id, coll_uuid)
    return {"success": True}


@router.post("/collections/{collection_id}/tasks/{task_slug}/trigger")
async def trigger_task_now(
    workspace_id: str = Path(...),
    collection_id: str = Path(...),
    task_slug: str = Path(..., description="Slug of the task to trigger immediately"),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """Trigger a scheduled task immediately (e.g. send a day contract now instead of waiting)."""
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    coll_uuid = parse_uuid(collection_id, field="collection_id")
    await service.trigger_task_now(ws_uuid, user.id, coll_uuid, task_slug)
    return {"success": True}


# =============================================================================
# Start Collection
# =============================================================================

@router.post("/start", response_model=StartCollectionResponse, status_code=201)
async def start_collection(
    data: StartCollectionRequest,
    workspace_id: str = Path(...),
    user: UserProfile = Depends(get_current_user),
    service: DocumentCollectionService = Depends(get_dc_service),
):
    """
    Start a document collection.

    Creates database records and resolves documents.
    Does NOT send WhatsApp messages yet (agent integration is a later phase).
    """
    ws_uuid = parse_uuid(workspace_id, field="workspace_id")
    v_uuid = parse_uuid(data.vacancy_id, field="vacancy_id") if data.vacancy_id else None
    app_uuid = parse_uuid(data.application_id, field="application_id") if data.application_id else None
    cand_uuid = parse_uuid(data.candidate_id, field="candidate_id") if data.candidate_id else None

    return await service.start_collection(
        ws_uuid, user.id,
        candidate_name=data.candidate_name,
        candidate_lastname=data.candidate_lastname,
        whatsapp_number=data.whatsapp_number,
        vacancy_id=v_uuid,
        application_id=app_uuid,
        candidate_id=cand_uuid,
    )
