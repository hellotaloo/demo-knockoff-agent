"""
Pydantic models for the Ontology API.

The ontology system provides reference data entities (document types, job functions, etc.)
with parent-child hierarchies and category grouping.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Any
from enum import Enum


class ScanMode(str, Enum):
    single = "single"
    front_back = "front_back"
    multi_page = "multi_page"


class EntityType(str, Enum):
    """Supported ontology entity types."""
    document_type = "document_type"
    # job_function = "job_function"  # future
    # skill = "skill"               # future


class OntologyChild(BaseModel):
    """A child entity within a parent."""

    id: str
    slug: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0
    metadata: Optional[dict[str, Any]] = None
    sync_with: List["SyncWithEntry"] = Field(default_factory=list)


class OntologyEntity(BaseModel):
    """A parent entity with optional nested children."""

    id: str
    type: str
    slug: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0
    parent_id: Optional[str] = None
    is_verifiable: bool = False
    metadata: Optional[dict[str, Any]] = None
    scan_mode: ScanMode = ScanMode.single
    verification_config: Optional[dict[str, Any]] = None
    ai_hint: Optional[str] = None
    children: List[OntologyChild] = Field(default_factory=list)
    children_count: int = 0
    sync_with: List["SyncWithEntry"] = Field(default_factory=list)


class DocumentTypeCreateRequest(BaseModel):
    """Request body for creating a document type."""

    slug: str
    name: str
    description: Optional[str] = None
    category: str = "identity"
    icon: Optional[str] = None
    is_default: bool = False
    is_verifiable: bool = False
    requires_front_back: bool = False
    sort_order: int = 0
    parent_id: Optional[str] = None
    scan_mode: ScanMode = ScanMode.single
    verification_config: Optional[dict[str, Any]] = None


class DocumentTypeUpdateRequest(BaseModel):
    """Request body for updating a document type (all fields optional)."""

    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    is_verifiable: Optional[bool] = None
    requires_front_back: Optional[bool] = None
    sort_order: Optional[int] = None
    scan_mode: Optional[ScanMode] = None
    verification_config: Optional[dict[str, Any]] = None
    ai_hint: Optional[str] = None


class VerificationFieldSchema(BaseModel):
    """Schema definition for a single extractable field — used by the frontend to render config UI."""

    key: str
    label: str
    description: str
    type: str = "string"


class VerificationSchema(BaseModel):
    """Full schema returned to the frontend for building the verification config UI."""

    extract_fields: List[VerificationFieldSchema]
    config_fields: List[VerificationFieldSchema]


class AttributeFieldsSchema(BaseModel):
    """Schema returned to the frontend for building the attribute fields config UI."""

    field_types: List[VerificationFieldSchema]


class OntologyListResponse(BaseModel):
    """Response for listing ontology entities."""

    type: str
    items: List[OntologyEntity]
    total: int
    categories: List[str] = Field(
        default_factory=list,
        description="Available categories for this entity type"
    )


class OntologyTypeInfo(BaseModel):
    """Info about an available ontology entity type."""

    type: str
    label: str
    description: str
    total: int = 0
    categories: List[str] = Field(default_factory=list)


class OntologyOverviewResponse(BaseModel):
    """Overview of all available ontology types."""

    types: List[OntologyTypeInfo]


class OntologyStatCard(BaseModel):
    """A single stat card for the overview dashboard."""

    key: str
    label: str
    value: int
    icon: Optional[str] = None


class OntologyOverviewStatsResponse(BaseModel):
    """Rich overview stats for the ontology dashboard."""

    stats: List[OntologyStatCard]


# ─── Integrations & Sync ─────────────────────────────────────────────────────


class IntegrationResponse(BaseModel):
    """A registered integration vendor."""

    id: str
    slug: str
    name: str
    vendor: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True


class SyncWithEntry(BaseModel):
    """A sync_with link on a types record."""

    id: str
    integration_id: str
    integration_slug: str
    integration_name: str
    external_id: Optional[str] = None
    external_metadata: Optional[dict[str, Any]] = None


class SyncWithAddRequest(BaseModel):
    """Request to add a sync_with link."""

    integration_id: str
    external_id: Optional[str] = None
    external_metadata: Optional[dict[str, Any]] = None
