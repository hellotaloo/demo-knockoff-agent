"""
Pydantic models for candidate attribute types and candidate attributes.

Attribute types are the catalog of possible attributes (workspace-scoped).
Candidate attributes are the actual values stored per candidate.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class AttributeDataType(str, Enum):
    """Supported data types for attribute values."""
    TEXT = "text"
    BOOLEAN = "boolean"
    DATE = "date"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    NUMBER = "number"
    STRUCTURED = "structured"


class AttributeFieldDefinition(BaseModel):
    """A sub-field within a structured attribute type (e.g. noodcontact → naam + telefoonnummer)."""
    key: str = Field(..., description="Unique key for this field (e.g. 'name', 'phone')")
    label: str = Field(..., description="Display label (e.g. 'Naam', 'Telefoonnummer')")
    type: str = Field(default="text", description="Field type: text, date, number, boolean, select")
    required: bool = Field(default=True, description="Whether this field is required")
    placeholder: Optional[str] = Field(default=None, description="Placeholder text for the input")
    options: Optional[List[str]] = Field(default=None, description="Options for select-type fields")


# =============================================================================
# Attribute Types (catalog)
# =============================================================================

class AttributeTypeCreate(BaseModel):
    """Create a new candidate attribute type."""
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: str = Field(default="general")
    data_type: AttributeDataType = AttributeDataType.TEXT
    options: Optional[List[dict[str, Any]]] = None
    fields: Optional[List[AttributeFieldDefinition]] = Field(default=None, description="Sub-fields for structured attributes (e.g. noodcontact → naam + telefoon)")
    icon: Optional[str] = None
    is_default: bool = False
    sort_order: int = 0
    collected_by: Optional[str] = None
    ai_hint: Optional[str] = None


class AttributeTypeUpdate(BaseModel):
    """Partial update for a candidate attribute type."""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    data_type: Optional[AttributeDataType] = None
    options: Optional[List[dict[str, Any]]] = None
    fields: Optional[List[AttributeFieldDefinition]] = None
    icon: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    collected_by: Optional[str] = None
    ai_hint: Optional[str] = None


class SyncWithEntryCompact(BaseModel):
    """A sync_with link on a types record (used in attribute type responses)."""
    id: str
    integration_id: str
    integration_slug: str
    integration_name: str
    external_id: Optional[str] = None
    external_metadata: Optional[dict[str, Any]] = None


class AttributeTypeResponse(BaseModel):
    """Response model for a candidate attribute type."""
    id: str
    workspace_id: str
    slug: str
    name: str
    description: Optional[str] = None
    category: str
    data_type: str
    options: Optional[List[dict[str, Any]]] = None
    fields: Optional[List[AttributeFieldDefinition]] = None
    icon: Optional[str] = None
    is_default: bool
    is_active: bool
    sort_order: int
    collected_by: Optional[str] = None
    ai_hint: Optional[str] = None
    sync_with: List[SyncWithEntryCompact] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Candidate Attributes (values per candidate)
# =============================================================================

class CandidateAttributeSet(BaseModel):
    """Set (create or update) an attribute value for a candidate."""
    attribute_type_id: str
    value: Optional[str] = None
    source: Optional[str] = None
    source_session_id: Optional[str] = None
    verified: bool = False


class CandidateAttributeBulkSet(BaseModel):
    """Bulk set multiple attribute values for a candidate."""
    attributes: List[CandidateAttributeSet]


class CandidateAttributeResponse(BaseModel):
    """Response model for a candidate attribute value."""
    id: str
    candidate_id: str
    attribute_type_id: str
    attribute_type: Optional[AttributeTypeResponse] = None
    value: Optional[str] = None
    source: Optional[str] = None
    source_session_id: Optional[str] = None
    verified: bool
    created_at: datetime
    updated_at: datetime
