"""
Pydantic models for the document collection system (v2).

Covers: document types, collection configs, requirements,
document collections, messages, uploads, and candidate documents.
"""
from datetime import datetime, date
from typing import Any, Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# Document Types
# =============================================================================

class DocumentTypeCreate(BaseModel):
    """Create a new document type for a workspace."""
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: str = Field(default="identity")
    requires_front_back: bool = False
    is_verifiable: bool = False
    icon: Optional[str] = None
    is_default: bool = False
    sort_order: int = 0


class DocumentTypeUpdate(BaseModel):
    """Partial update for a document type."""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    requires_front_back: Optional[bool] = None
    is_verifiable: Optional[bool] = None
    icon: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class DocumentTypeResponse(BaseModel):
    """Document type response."""
    id: str
    workspace_id: str
    slug: str
    name: str
    description: Optional[str] = None
    category: str
    requires_front_back: bool
    is_verifiable: bool
    icon: Optional[str] = None
    is_default: bool
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Document Resolution
# =============================================================================

class ResolveDocumentsResponse(BaseModel):
    """Result of resolving which documents are needed."""
    documents: List[DocumentTypeResponse]
    source: str  # "default", "vacancy", "merged"


# =============================================================================
# Document Collections
# =============================================================================

class StartCollectionRequest(BaseModel):
    """Start a document collection."""
    candidate_name: str = Field(..., min_length=1)
    candidate_lastname: str = Field(..., min_length=1)
    whatsapp_number: str = Field(..., pattern=r"^\+?[1-9]\d{1,14}$")
    vacancy_id: Optional[str] = None
    application_id: Optional[str] = None
    candidate_id: Optional[str] = None


class StartCollectionResponse(BaseModel):
    """Response after starting a collection."""
    collection_id: str
    config_id: str
    candidate_name: str
    whatsapp_number: str
    documents_required: List[DocumentTypeResponse]
    source: str  # "default", "vacancy", "merged"


class DocumentCollectionResponse(BaseModel):
    """Document collection summary.

    Status values (general lifecycle):
      active       — collection is ongoing
      completed    — all documents collected
      needs_review — documents need manual review
      abandoned    — collection was abandoned

    Progress values (derived from messages, only relevant when status=active):
      pending     — no messages sent yet
      started     — agent sent first message, awaiting user response
      in_progress — user is actively engaging
    """
    id: str
    config_id: str
    workspace_id: str
    vacancy_id: Optional[str] = None
    vacancy_title: Optional[str] = None
    application_id: Optional[str] = None
    candidacy_stage: Optional[str] = None
    goal: str = "collect_basic"  # collect_basic | collect_and_sign | document_renewal
    candidate_name: str
    candidate_phone: Optional[str] = None
    status: str
    progress: str = "pending"
    channel: str
    retry_count: int
    message_count: int
    documents_collected: int = 0
    documents_total: int = 0
    started_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class CollectionMessageResponse(BaseModel):
    """A message within a document collection."""
    role: str
    message: str
    created_at: datetime


class CollectionUploadResponse(BaseModel):
    """A document upload within a collection."""
    id: str
    document_type_id: Optional[str] = None
    document_side: str
    verification_passed: Optional[bool] = None
    status: str
    uploaded_at: datetime


class DocumentCollectionDetailResponse(DocumentCollectionResponse):
    """Document collection with messages, uploads, and required documents."""
    messages: List[CollectionMessageResponse] = Field(default_factory=list)
    uploads: List[CollectionUploadResponse] = Field(default_factory=list)
    documents_required: List[DocumentTypeResponse] = Field(default_factory=list)


# =============================================================================
# Full Detail (enriched view for detail panel)
# =============================================================================

class CollectionPlanDocumentResponse(BaseModel):
    """A document from the collection plan."""
    slug: str
    name: str
    reason: Optional[str] = None
    priority: str = "required"


class CollectionPlanStepResponse(BaseModel):
    """A single conversation step from the collection plan."""
    step: int
    topic: str
    items: List[str] = Field(default_factory=list)
    message: str


class CollectionPlanResponse(BaseModel):
    """Structured planner output for the frontend."""
    summary: Optional[str] = None
    deadline_note: Optional[str] = None
    intro_message: Optional[str] = None
    documents_to_collect: List[CollectionPlanDocumentResponse] = Field(default_factory=list)
    attributes_to_collect: List[dict] = Field(default_factory=list)
    conversation_steps: List[CollectionPlanStepResponse] = Field(default_factory=list)
    agent_managed_tasks: List[dict] = Field(default_factory=list)
    already_complete: List[str] = Field(default_factory=list)
    final_step: Optional[dict] = None


class CollectionItemStatusResponse(BaseModel):
    """Unified status for a collected item (document, attribute, or task)."""
    slug: str
    name: str
    type: str  # "document" | "attribute" | "task"
    priority: str  # "required" | "recommended" | "conditional"
    status: str  # pending | asked | received | verified | failed | skipped | scheduled
    value: Optional[Any] = None  # For attributes: string or dict for structured values
    upload_id: Optional[str] = None
    verification_passed: Optional[bool] = None
    uploaded_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None  # For tasks: when the task is scheduled to execute
    group: Optional[str] = None  # Visual grouping key (e.g. "identity" for id_card/passport/work_permit)


class WorkflowStepResponse(BaseModel):
    """A single step in a workflow progress bar."""
    id: str
    label: str
    status: str  # completed | current | pending | failed


class DocumentCollectionFullDetailResponse(DocumentCollectionResponse):
    """Enriched detail for the collection detail panel."""
    messages: List[CollectionMessageResponse] = Field(default_factory=list)
    uploads: List[CollectionUploadResponse] = Field(default_factory=list)
    documents_required: List[DocumentTypeResponse] = Field(default_factory=list)
    # Plan summary (recruiter-facing, not the full agent script)
    summary: Optional[str] = None
    deadline_note: Optional[str] = None
    # Unified checklist: documents + attributes with current status
    collection_items: List[CollectionItemStatusResponse] = Field(default_factory=list)
    # Conversation step progress (horizontal stepper)
    conversation_steps: List[dict] = Field(default_factory=list)
    # Links
    candidacy_id: Optional[str] = None
    candidate_id: Optional[str] = None
    # Workflow progress
    workflow_steps: List[WorkflowStepResponse] = Field(default_factory=list)


# =============================================================================
# Candidate Documents (Portfolio)
# =============================================================================

class CandidateDocumentResponse(BaseModel):
    """A candidate's verified document record."""
    id: str
    candidate_id: str
    document_type_id: str
    document_type: Optional[DocumentTypeResponse] = None
    workspace_id: str
    document_number: Optional[str] = None
    metadata: Optional[dict] = None
    expiration_date: Optional[date] = None
    status: str
    verification_passed: Optional[bool] = None
    storage_path: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CandidateDocumentCreate(BaseModel):
    """Manually add a candidate document record."""
    document_type_id: str
    document_number: Optional[str] = None
    metadata: Optional[dict] = None
    expiration_date: Optional[date] = None
    notes: Optional[str] = None


class CandidateDocumentUpdate(BaseModel):
    """Update a candidate document record."""
    document_number: Optional[str] = None
    metadata: Optional[dict] = None
    expiration_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None


