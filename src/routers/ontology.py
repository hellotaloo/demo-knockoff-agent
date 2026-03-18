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
    OntologyOverviewStatsResponse,
    OntologyStatCard,
    DocumentTypeCreateRequest,
    DocumentTypeUpdateRequest,
    VerificationSchema,
    VerificationFieldSchema,
    AttributeFieldsSchema,
    IntegrationResponse,
    SyncWithEntry,
    SyncWithAddRequest,
)
from src.repositories.document_type_repo import DocumentTypeRepository
from src.repositories.sync_with_repo import SyncWithRepository
from src.dependencies import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ontology", tags=["Ontology"])


def _get_doc_type_repo(pool=Depends(get_pool)) -> DocumentTypeRepository:
    return DocumentTypeRepository(pool)


def _get_sync_repo(pool=Depends(get_pool)) -> SyncWithRepository:
    return SyncWithRepository(pool)


# ─── sync_with helpers ─────────────────────────────────────────────────────


def _build_sync_entry(record) -> SyncWithEntry:
    """Convert a sync_with DB record to a SyncWithEntry."""
    import json as _json
    meta = record["external_metadata"]
    if isinstance(meta, str):
        meta = _json.loads(meta)
    return SyncWithEntry(
        id=str(record["id"]),
        integration_id=str(record["integration_id"]),
        integration_slug=record["integration_slug"],
        integration_name=record["integration_name"],
        external_id=record["external_id"],
        external_metadata=meta,
    )


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
        ai_hint=record["ai_hint"],
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
    sync_repo: SyncWithRepository,
) -> OntologyListResponse:
    """Build ontology list response for document_type entities."""
    is_active = None if include_inactive else True

    rows = await repo.list_parents_with_children(
        workspace_id=workspace_id,
        category=category,
        is_active=is_active,
    )

    # Batch-load sync_with for all records
    all_ids = [row["id"] for row in rows]
    sync_rows = await sync_repo.list_for_records("types_documents", all_ids)
    sync_map: dict[str, list[SyncWithEntry]] = {}
    for sr in sync_rows:
        rid = str(sr["record_id"])
        sync_map.setdefault(rid, []).append(_build_sync_entry(sr))

    parents: dict[str, OntologyEntity] = {}
    parent_order: list[str] = []

    for row in rows:
        row_id = str(row["id"])
        parent_id = row["parent_id"]

        if parent_id is None:
            entity = _doc_record_to_entity(row)
            entity.sync_with = sync_map.get(row_id, [])
            parents[row_id] = entity
            parent_order.append(row_id)
        elif include_children:
            pid = str(parent_id)
            if pid in parents:
                child = _doc_record_to_child(row)
                child.sync_with = sync_map.get(row_id, [])
                parents[pid].children.append(child)

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


@router.get("/stats", response_model=OntologyOverviewStatsResponse)
async def get_ontology_stats(
    workspace_id: uuid.UUID = Query(..., description="Workspace ID"),
    pool=Depends(get_pool),
):
    """
    Dashboard stats for the ontology overview page.

    Dynamically discovers all ontology.types_* tables and computes:
    - object_types: number of registered object types
    - categories: total unique categories across all types
    - total_items: total parent entities across all types
    - subtypes: total child entities across all types
    """
    # Discover all ontology type tables dynamically (only those with required columns)
    type_tables = await pool.fetch("""
        SELECT table_name
        FROM information_schema.tables t
        WHERE table_schema = 'ontology' AND table_name LIKE 'types_%'
          AND EXISTS (SELECT 1 FROM information_schema.columns c WHERE c.table_schema = 'ontology' AND c.table_name = t.table_name AND c.column_name = 'workspace_id')
          AND EXISTS (SELECT 1 FROM information_schema.columns c WHERE c.table_schema = 'ontology' AND c.table_name = t.table_name AND c.column_name = 'is_active')
          AND EXISTS (SELECT 1 FROM information_schema.columns c WHERE c.table_schema = 'ontology' AND c.table_name = t.table_name AND c.column_name = 'category')
        ORDER BY table_name
    """)

    total_items = 0
    total_subtypes = 0
    all_categories: set[str] = set()

    for table in type_tables:
        table_name = table["table_name"]

        # Check if this table has a parent_id column (supports hierarchy)
        has_parent = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'ontology' AND table_name = $1 AND column_name = 'parent_id'
            )
        """, table_name)

        if has_parent:
            # Count parents and subtypes separately
            counts = await pool.fetchrow(f"""
                SELECT
                    COUNT(*) FILTER (WHERE parent_id IS NULL) AS parents,
                    COUNT(*) FILTER (WHERE parent_id IS NOT NULL) AS subtypes
                FROM ontology.{table_name}
                WHERE workspace_id = $1 AND is_active = true
            """, workspace_id)
            total_items += counts["parents"]
            total_subtypes += counts["subtypes"]
        else:
            # Flat table — all rows are top-level items
            count = await pool.fetchval(f"""
                SELECT COUNT(*) FROM ontology.{table_name}
                WHERE workspace_id = $1 AND is_active = true
            """, workspace_id)
            total_items += count

        # Collect categories
        categories = await pool.fetch(f"""
            SELECT DISTINCT category FROM ontology.{table_name}
            WHERE workspace_id = $1 AND is_active = true AND category IS NOT NULL
        """, workspace_id)
        all_categories.update(r["category"] for r in categories)

    stats = [
        OntologyStatCard(key="object_types", label="Objecttypes", value=len(type_tables), icon="boxes"),
        OntologyStatCard(key="total_items", label="Totaal items", value=total_items, icon="layers"),
        OntologyStatCard(key="subtypes", label="Subtypes", value=total_subtypes, icon="git-branch"),
        OntologyStatCard(key="categories", label="Categorieën", value=len(all_categories), icon="tags"),
    ]

    return OntologyOverviewStatsResponse(stats=stats)


@router.get("/entities", response_model=OntologyListResponse)
async def list_entities(
    type: EntityType = Query(..., description="Entity type to list"),
    workspace_id: uuid.UUID = Query(..., description="Workspace ID"),
    category: Optional[str] = Query(None, description="Filter by category"),
    include_children: bool = Query(True, description="Nest children under parents"),
    include_inactive: bool = Query(False, description="Include inactive entities"),
    limit: int = Query(200, ge=1, le=1000, description="Max items to return"),
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
    sync_repo: SyncWithRepository = Depends(_get_sync_repo),
):
    """
    List ontology entities by type.

    Supports parent-child hierarchies with optional nested children.
    """
    if type == EntityType.document_type:
        return await _list_document_types(
            workspace_id, category, include_children, include_inactive, repo, sync_repo
        )

    raise HTTPException(status_code=400, detail=f"Unsupported entity type: {type}")


@router.get("/entities/{entity_id}", response_model=OntologyEntity)
async def get_entity(
    entity_id: uuid.UUID,
    include_children: bool = Query(True, description="Include children"),
    repo: DocumentTypeRepository = Depends(_get_doc_type_repo),
    sync_repo: SyncWithRepository = Depends(_get_sync_repo),
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

    # Load sync_with for this entity
    sync_rows = await sync_repo.list_for_record("types_documents", entity_id)
    entity.sync_with = [_build_sync_entry(sr) for sr in sync_rows]

    if include_children:
        children = await repo.list_children(entity_id)
        child_ids = [c["id"] for c in children]
        child_sync_rows = await sync_repo.list_for_records("types_documents", child_ids)
        child_sync_map: dict[str, list[SyncWithEntry]] = {}
        for sr in child_sync_rows:
            rid = str(sr["record_id"])
            child_sync_map.setdefault(rid, []).append(_build_sync_entry(sr))

        for c in children:
            child = _doc_record_to_child(c)
            child.sync_with = child_sync_map.get(str(c["id"]), [])
            entity.children.append(child)
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
    VerificationFieldSchema(key="national_registry_number", label="Rijksregisternummer", description="Belgisch rijksregisternummer (11 cijfers)", type="string"),
    VerificationFieldSchema(key="iban", label="IBAN", description="IBAN rekeningnummer", type="string"),
    VerificationFieldSchema(key="bic", label="BIC/SWIFT", description="BIC of SWIFT code van de bank", type="string"),
    VerificationFieldSchema(key="permit_type", label="Type vergunning", description="Specifiek type vergunning of arbeidskaart (A/B/C)", type="string"),
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


_ATTRIBUTE_FIELD_TYPES = [
    VerificationFieldSchema(key="text", label="Tekst", description="Vrije tekst (naam, adres, ...)", type="text"),
    VerificationFieldSchema(key="phone", label="Telefoonnummer", description="Telefoonnummer met landcode", type="text"),
    VerificationFieldSchema(key="email", label="E-mailadres", description="E-mailadres", type="text"),
    VerificationFieldSchema(key="date", label="Datum", description="Datumveld (DD/MM/JJJJ)", type="date"),
    VerificationFieldSchema(key="number", label="Nummer", description="Numerieke waarde", type="number"),
    VerificationFieldSchema(key="boolean", label="Ja/Nee", description="Ja of nee keuze", type="boolean"),
    VerificationFieldSchema(key="select", label="Keuzelijst", description="Selectie uit vaste opties", type="select"),
]


@router.get("/attribute-fields-schema", response_model=AttributeFieldsSchema)
async def get_attribute_fields_schema():
    """
    Returns the available field types for building structured attribute fields.

    Used by the frontend to render the fields config UI on attribute type detail panels.
    For example, a "noodcontact" attribute could have fields: naam (text) + telefoon (phone).
    """
    return AttributeFieldsSchema(field_types=_ATTRIBUTE_FIELD_TYPES)


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


# ─── Integrations ─────────────────────────────────────────────────────────────


@router.get("/integrations", response_model=list[IntegrationResponse])
async def list_integrations(
    sync_repo: SyncWithRepository = Depends(_get_sync_repo),
):
    """List all registered integration vendors."""
    rows = await sync_repo.list_integrations()
    return [
        IntegrationResponse(
            id=str(r["id"]),
            slug=r["slug"],
            name=r["name"],
            vendor=r["vendor"],
            description=r["description"],
            icon=r["icon"],
            is_active=r["is_active"],
        )
        for r in rows
    ]


# ─── Sync With CRUD ───────────────────────────────────────────────────────────


@router.get("/entities/{entity_id}/sync-with", response_model=list[SyncWithEntry])
async def list_entity_sync_with(
    entity_id: uuid.UUID,
    table_name: str = Query("types_documents", description="Types table name"),
    sync_repo: SyncWithRepository = Depends(_get_sync_repo),
):
    """List all sync_with links for an entity."""
    rows = await sync_repo.list_for_record(table_name, entity_id)
    return [_build_sync_entry(r) for r in rows]


@router.post("/entities/{entity_id}/sync-with", response_model=SyncWithEntry, status_code=201)
async def add_entity_sync_with(
    entity_id: uuid.UUID,
    body: SyncWithAddRequest,
    table_name: str = Query("types_documents", description="Types table name"),
    sync_repo: SyncWithRepository = Depends(_get_sync_repo),
):
    """Add a sync_with link to an entity."""
    integration_id = uuid.UUID(body.integration_id)

    # Verify integration exists
    integration = await sync_repo.get_integration_by_id(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    try:
        record = await sync_repo.add(
            table_name=table_name,
            record_id=entity_id,
            integration_id=integration_id,
            external_id=body.external_id,
            external_metadata=body.external_metadata,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="This sync_with link already exists")
        raise

    # Re-fetch with integration info
    rows = await sync_repo.list_for_record(table_name, entity_id)
    for r in rows:
        if str(r["id"]) == str(record["id"]):
            return _build_sync_entry(r)

    return _build_sync_entry(record)


@router.delete("/entities/{entity_id}/sync-with/{sync_with_id}", status_code=204)
async def remove_entity_sync_with(
    entity_id: uuid.UUID,
    sync_with_id: uuid.UUID,
    sync_repo: SyncWithRepository = Depends(_get_sync_repo),
):
    """Remove a sync_with link from an entity."""
    deleted = await sync_repo.remove(sync_with_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sync link not found")
