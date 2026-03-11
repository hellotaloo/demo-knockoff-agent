"""
Ontology Router

Generic reference data system for entity types (document types, job functions, etc.)
with parent-child hierarchies and category grouping.

Endpoints:
  GET /ontology                — overview of available entity types
  GET /ontology/entities       — list entities by type
  GET /ontology/entities/{id}  — get single entity with children
"""
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from src.models.ontology import (
    EntityType,
    OntologyChild,
    OntologyEntity,
    OntologyListResponse,
    OntologyTypeInfo,
    OntologyOverviewResponse,
    DocumentTypeCreateRequest,
    DocumentTypeUpdateRequest,
    VerificationSchema,
    VerificationFieldSchema,
)
from src.repositories.document_type_repo import DocumentTypeRepository
from src.dependencies import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ontology", tags=["Ontology"])


def _get_doc_type_repo(pool=Depends(get_pool)) -> DocumentTypeRepository:
    return DocumentTypeRepository(pool)


# ─── document_type helpers ────────────────────────────────────────────────────


def _doc_record_to_entity(record) -> OntologyEntity:
    """Convert a document_type DB record to an OntologyEntity."""
    import json as _json
    metadata = {}
    if record["prato_flex_type_id"]:
        metadata["prato_flex_type_id"] = record["prato_flex_type_id"]
    if record.get("requires_front_back"):
        metadata["requires_front_back"] = True

    vc = record["verification_config"]
    if isinstance(vc, str):
        vc = _json.loads(vc)

    return OntologyEntity(
        id=str(record["id"]),
        type="document_type",
        slug=record["slug"],
        name=record["name"],
        description=record["description"],
        category=record["category"],
        icon=record["icon"],
        is_default=record["is_default"],
        is_active=record["is_active"],
        sort_order=record["sort_order"],
        parent_id=str(record["parent_id"]) if record["parent_id"] else None,
        is_verifiable=record["is_verifiable"],
        metadata=metadata or None,
        scan_mode=record["scan_mode"],
        verification_config=vc,
    )


def _doc_record_to_child(record) -> OntologyChild:
    """Convert a document_type child DB record to an OntologyChild."""
    metadata = {}
    if record["prato_flex_type_id"]:
        metadata["prato_flex_type_id"] = record["prato_flex_type_id"]
    if record.get("prato_flex_detail_type_id"):
        metadata["prato_flex_detail_type_id"] = record["prato_flex_detail_type_id"]

    return OntologyChild(
        id=str(record["id"]),
        slug=record["slug"],
        name=record["name"],
        description=record["description"],
        category=record["category"],
        is_default=record["is_default"],
        is_active=record["is_active"],
        sort_order=record["sort_order"],
        metadata=metadata or None,
    )


async def _list_document_types(
    workspace_id: uuid.UUID,
    category: Optional[str],
    include_children: bool,
    include_inactive: bool,
    repo: DocumentTypeRepository,
) -> OntologyListResponse:
    """Build ontology list response for document_type entities."""
    is_active = None if include_inactive else True

    rows = await repo.list_parents_with_children(
        workspace_id=workspace_id,
        category=category,
        is_active=is_active,
    )

    parents: dict[str, OntologyEntity] = {}
    parent_order: list[str] = []

    for row in rows:
        row_id = str(row["id"])
        parent_id = row["parent_id"]

        if parent_id is None:
            entity = _doc_record_to_entity(row)
            parents[row_id] = entity
            parent_order.append(row_id)
        elif include_children:
            pid = str(parent_id)
            if pid in parents:
                parents[pid].children.append(_doc_record_to_child(row))

    items = []
    for pid in parent_order:
        parent = parents[pid]
        parent.children_count = len(parent.children)
        items.append(parent)

    items.sort(key=lambda x: (x.children_count == 0, x.name.lower()))

    categories = sorted({item.category for item in items if item.category})

    return OntologyListResponse(
        type="document_type",
        items=items,
        total=len(items),
        categories=categories,
    )


async def _get_document_type_overview(
    workspace_id: uuid.UUID,
    repo: DocumentTypeRepository,
) -> OntologyTypeInfo:
    """Build overview info for document_type."""
    rows = await repo.list_for_workspace(workspace_id, is_active=True, parents_only=True)
    categories = sorted({r["category"] for r in rows if r["category"]})
    return OntologyTypeInfo(
        type="document_type",
        label="Documenttypes",
        description="Document- en certificaattypes voor kandidaten",
        total=len(rows),
        categories=categories,
    )


# ─── endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=OntologyOverviewResponse)
async def get_ontology_overview(
    workspace_id: uuid.UUID = Query(..., description="Workspace ID"),
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
):
    """
    Overview of all available ontology entity types.

    Returns the list of supported types with counts and available categories.
    """
    types = [
        await _get_document_type_overview(workspace_id, repo),
        # Future: await _get_job_function_overview(workspace_id, ...),
    ]

    return OntologyOverviewResponse(types=types)


@router.get("/entities", response_model=OntologyListResponse)
async def list_entities(
    type: EntityType = Query(..., description="Entity type to list"),
    workspace_id: uuid.UUID = Query(..., description="Workspace ID"),
    category: Optional[str] = Query(None, description="Filter by category"),
    include_children: bool = Query(True, description="Nest children under parents"),
    include_inactive: bool = Query(False, description="Include inactive entities"),
    limit: int = Query(200, ge=1, le=1000, description="Max items to return"),
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
):
    """
    List ontology entities by type.

    Supports parent-child hierarchies with optional nested children.
    """
    if type == EntityType.document_type:
        return await _list_document_types(
            workspace_id, category, include_children, include_inactive, repo
        )

    raise HTTPException(status_code=400, detail=f"Unsupported entity type: {type}")


@router.get("/entities/{entity_id}", response_model=OntologyEntity)
async def get_entity(
    entity_id: uuid.UUID,
    include_children: bool = Query(True, description="Include children"),
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
):
    """
    Get a single ontology entity by ID with optional children.

    Currently looks up document_type entities. Will auto-detect type when
    more entity types are added.
    """
    record = await repo.get_by_id(entity_id)
    if not record:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity = _doc_record_to_entity(record)

    if include_children:
        children = await repo.list_children(entity_id)
        entity.children = [_doc_record_to_child(c) for c in children]
        entity.children_count = len(entity.children)

    return entity


_EXTRACT_FIELDS = [
    VerificationFieldSchema(key="expiry_date", label="Vervaldatum", description="Datum waarop het document vervalt", type="date"),
    VerificationFieldSchema(key="issuing_date", label="Datum van uitgifte", description="Datum waarop het document werd uitgegeven", type="date"),
    VerificationFieldSchema(key="document_number", label="Documentnummer", description="Uniek identificatienummer van het document", type="string"),
    VerificationFieldSchema(key="holder_name", label="Naam houder", description="Volledige naam vermeld op het document", type="string"),
    VerificationFieldSchema(key="date_of_birth", label="Geboortedatum", description="Geboortedatum van de documenthouder", type="date"),
    VerificationFieldSchema(key="nationality", label="Nationaliteit", description="Nationaliteit vermeld op het document", type="string"),
    VerificationFieldSchema(key="issuing_country", label="Uitgevend land", description="Land dat het document heeft uitgegeven", type="string"),
    VerificationFieldSchema(key="issuing_authority", label="Uitgevende instantie", description="Organisatie die het document heeft uitgegeven", type="string"),
    VerificationFieldSchema(key="license_categories", label="Categorieën", description="Klassen of categorieën op het document (bv. rijbewijs B, C)", type="list"),
    VerificationFieldSchema(key="certificate_level", label="Niveau", description="Niveau of graad van het certificaat", type="string"),
    VerificationFieldSchema(key="certificate_type", label="Type certificaat", description="Specifiek type of variant van het certificaat", type="string"),
]

_CONFIG_FIELDS = [
    VerificationFieldSchema(key="check_expiry", label="Controleer vervaldatum", description="Markeer het document als ongeldig als de vervaldatum verstreken is", type="boolean"),
    VerificationFieldSchema(key="check_name", label="Controleer naam", description="Controleer of de naam op het document overeenkomt met de kandidaat", type="boolean"),
    VerificationFieldSchema(key="additional_instructions", label="Instructies voor de AI", description="Vrije tekst met aanvullende instructies voor de AI verificatie", type="text"),
]


@router.get("/verification-schema", response_model=VerificationSchema)
async def get_verification_schema():
    """
    Returns the available fields and config options for building a verification_config UI.

    - `extract_fields`: fields the LLM can extract from a document
    - `config_fields`: toggles/options that control verification behaviour
    """
    return VerificationSchema(extract_fields=_EXTRACT_FIELDS, config_fields=_CONFIG_FIELDS)


@router.post("/entities", response_model=OntologyEntity, status_code=201)
async def create_entity(
    workspace_id: uuid.UUID = Query(..., description="Workspace ID"),
    body: DocumentTypeCreateRequest = ...,
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
):
    """Create a new document type entity."""
    parent_id = uuid.UUID(body.parent_id) if body.parent_id else None
    record = await repo.create(
        workspace_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        category=body.category,
        icon=body.icon,
        is_default=body.is_default,
        is_verifiable=body.is_verifiable,
        requires_front_back=body.requires_front_back,
        sort_order=body.sort_order,
        parent_id=parent_id,
        scan_mode=body.scan_mode.value,
        verification_config=body.verification_config,
    )
    return _doc_record_to_entity(record)


@router.patch("/entities/{entity_id}", response_model=OntologyEntity)
async def update_entity(
    entity_id: uuid.UUID,
    body: DocumentTypeUpdateRequest,
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
):
    """
    Partially update a document type entity.

    Only provided fields are updated. Use `custom_field_extraction: null` to clear it.
    """
    record = await repo.get_by_id(entity_id)
    if not record:
        raise HTTPException(status_code=404, detail="Entity not found")

    updated = await repo.update(entity_id, **body.model_dump(exclude_unset=True))
    entity = _doc_record_to_entity(updated)

    children = await repo.list_children(entity_id)
    entity.children = [_doc_record_to_child(c) for c in children]
    entity.children_count = len(entity.children)

    return entity


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    entity_id: uuid.UUID,
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
):
    """Soft-delete a document type entity (sets is_active=false)."""
    record = await repo.get_by_id(entity_id)
    if not record:
        raise HTTPException(status_code=404, detail="Entity not found")

    await repo.soft_delete(entity_id)
