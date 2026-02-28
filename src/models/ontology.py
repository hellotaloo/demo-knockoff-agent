"""
Ontology models for the workspace knowledge graph.

Supports entity types (categories, job functions, document types, skills, requirements),
entities within each type, relation types, and relations between entities.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Any, List
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class RequirementType(str, Enum):
    """Requirement type for document/skill requirements."""
    VERPLICHT = "verplicht"
    VOORWAARDELIJK = "voorwaardelijk"
    GEWENST = "gewenst"


# =============================================================================
# Ontology Types (entity type definitions)
# =============================================================================

class OntologyTypeBase(BaseModel):
    """Base fields for an ontology type."""
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    name: str = Field(..., min_length=1, max_length=100)
    name_plural: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int = 0


class OntologyTypeCreate(OntologyTypeBase):
    """Request model for creating an ontology type."""
    pass


class OntologyTypeUpdate(BaseModel):
    """Request model for updating an ontology type."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    name_plural: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: Optional[int] = None


class OntologyTypeResponse(OntologyTypeBase):
    """Response model for an ontology type."""
    id: str
    workspace_id: str
    is_system: bool = False
    entity_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Ontology Entities
# =============================================================================

class OntologyEntityBase(BaseModel):
    """Base fields for an ontology entity."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")
    external_id: Optional[str] = Field(None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class OntologyEntityCreate(OntologyEntityBase):
    """Request model for creating an ontology entity."""
    type_slug: str = Field(..., description="Entity type slug (e.g., 'job_function', 'document_type')")


class OntologyEntityUpdate(BaseModel):
    """Request model for updating an ontology entity."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")
    external_id: Optional[str] = Field(None, max_length=255)
    metadata: Optional[dict[str, Any]] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class OntologyEntityResponse(OntologyEntityBase):
    """Response model for an ontology entity."""
    id: str
    workspace_id: str
    type_id: str
    type_slug: str
    type_name: str
    is_active: bool = True
    relation_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OntologyEntityDetailResponse(OntologyEntityResponse):
    """Detailed response for a single entity, including its relations."""
    relations: List["OntologyRelationResponse"] = []


# =============================================================================
# Ontology Relation Types
# =============================================================================

class OntologyRelationTypeCreate(BaseModel):
    """Request model for creating a relation type."""
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    name: str = Field(..., min_length=1, max_length=100)
    source_type_slug: Optional[str] = None
    target_type_slug: Optional[str] = None


class OntologyRelationTypeResponse(BaseModel):
    """Response model for a relation type."""
    id: str
    workspace_id: str
    slug: str
    name: str
    source_type_id: Optional[str] = None
    source_type_slug: Optional[str] = None
    target_type_id: Optional[str] = None
    target_type_slug: Optional[str] = None
    is_system: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Ontology Relations
# =============================================================================

class OntologyRelationCreate(BaseModel):
    """Request model for creating a relation."""
    source_entity_id: str
    target_entity_id: str
    relation_type_slug: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyRelationUpdate(BaseModel):
    """Request model for updating a relation's metadata."""
    metadata: dict[str, Any]


class OntologyRelationResponse(BaseModel):
    """Response model for a relation."""
    id: str
    workspace_id: str
    source_entity_id: str
    source_entity_name: str
    source_type_slug: str
    target_entity_id: str
    target_entity_name: str
    target_type_slug: str
    relation_type_id: str
    relation_type_slug: str
    relation_type_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Graph Response (for visualization)
# =============================================================================

class OntologyGraphNode(BaseModel):
    """A node in the ontology graph."""
    id: str
    name: str
    type_slug: str
    type_name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    external_id: Optional[str] = None


class OntologyGraphEdge(BaseModel):
    """An edge in the ontology graph."""
    id: str
    source: str
    target: str
    relation_type: str
    relation_label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyGraphResponse(BaseModel):
    """Complete ontology graph for visualization."""
    nodes: List[OntologyGraphNode]
    edges: List[OntologyGraphEdge]
    types: List[OntologyTypeResponse]
    stats: dict[str, int]


# =============================================================================
# Overview Response
# =============================================================================

class OntologyOverviewResponse(BaseModel):
    """Overview of the ontology for a workspace."""
    types: List[OntologyTypeResponse]
    total_entities: int
    total_relations: int


# Update forward references
OntologyEntityDetailResponse.model_rebuild()
