"""
Candidate models.
"""
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class CandidateStatus(str, Enum):
    """Candidate lifecycle status."""
    NEW = "new"
    QUALIFIED = "qualified"
    ACTIVE = "active"
    PLACED = "placed"
    INACTIVE = "inactive"


class AvailabilityStatus(str, Enum):
    """Candidate availability status."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CandidateBase(BaseModel):
    """Base candidate fields."""
    phone: Optional[str] = Field(None, description="Phone number in E.164 format")
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str


class CandidateCreate(CandidateBase):
    """Request model for creating a candidate."""
    status: CandidateStatus = CandidateStatus.NEW
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    available_from: Optional[date] = None
    rating: Optional[float] = Field(None, ge=0, le=5)


class CandidateUpdate(BaseModel):
    """Request model for updating a candidate."""
    phone: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    status: Optional[CandidateStatus] = None
    availability: Optional[AvailabilityStatus] = None
    available_from: Optional[date] = None
    rating: Optional[float] = Field(None, ge=0, le=5)


class CandidateResponse(CandidateBase):
    """Response model for a candidate."""
    id: str
    source: Optional[str] = None
    status: CandidateStatus = CandidateStatus.NEW
    status_updated_at: Optional[datetime] = None
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    available_from: Optional[date] = None
    rating: Optional[float] = None
    is_test: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CandidateSkillResponse(BaseModel):
    """Response model for a candidate skill."""
    id: str
    skill_name: str
    skill_code: Optional[str] = None
    skill_category: Optional[str] = None
    score: Optional[float] = None
    evidence: Optional[str] = None
    source: str = "manual"
    created_at: datetime

    class Config:
        from_attributes = True


class CandidateVacancyLink(BaseModel):
    """A vacancy linked to a candidate via candidacy."""
    id: str
    title: str
    company: Optional[str] = None
    is_open_application: bool = False


class CandidateListResponse(CandidateResponse):
    """Response model for candidate list (includes computed fields)."""
    skills: List[CandidateSkillResponse] = []
    vacancies: List[CandidateVacancyLink] = []
    vacancy_count: int = 0
    last_activity: Optional[datetime] = None


class CandidateAttributeSummary(BaseModel):
    """Summary of a candidate attribute value (for candidate detail)."""
    id: str
    attribute_type_id: str
    slug: str
    name: str
    category: str
    data_type: str
    options: Optional[List[dict]] = None
    icon: Optional[str] = None
    value: Optional[str] = None
    source: Optional[str] = None
    verified: bool = False
    created_at: datetime


class CandidateDocumentSummary(BaseModel):
    """Summary of a candidate document (for candidate detail)."""
    id: str
    document_type_id: str
    document_type_name: str
    document_type_slug: Optional[str] = None
    document_number: Optional[str] = None
    expiration_date: Optional[date] = None
    status: str = "pending_review"
    verification_passed: Optional[bool] = None
    storage_path: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CandidacySummary(BaseModel):
    """Candidacy summary embedded in candidate detail."""
    id: str
    vacancy_id: Optional[str] = None
    stage: str
    source: Optional[str] = None
    stage_updated_at: datetime
    created_at: datetime
    vacancy_title: Optional[str] = None
    vacancy_company: Optional[str] = None
    is_open_application: bool = False
    latest_application: Optional["CandidacyApplicationBrief"] = None
    screening_result: Optional["ScreeningResult"] = None
    document_collection: Optional["DocumentCollectionSummary"] = None


class CandidacyApplicationBrief(BaseModel):
    """Brief application info nested in candidacy summary."""
    id: str
    channel: str
    status: str = "active"
    qualified: Optional[bool] = None
    open_questions_score: Optional[int] = None
    knockout_passed: int = 0
    knockout_total: int = 0
    completed_at: Optional[datetime] = None


class ScreeningResult(BaseModel):
    """Full pre-screening result with Q&A, embedded in candidacy summary."""
    application_id: str
    channel: str
    status: str
    qualified: Optional[bool] = None
    summary: Optional[str] = None
    interaction_seconds: int = 0
    knockout_passed: int = 0
    knockout_total: int = 0
    open_questions_score: Optional[int] = None
    open_questions_total: int = 0
    completed_at: Optional[datetime] = None
    answers: List["QuestionAnswerResponse"] = []


class DocumentCollectionItem(BaseModel):
    """Per-document status within a collection."""
    document_type_id: str
    document_type_name: str
    icon: Optional[str] = None
    status: str = "pending"
    uploaded_at: Optional[datetime] = None


class DocumentCollectionSummary(BaseModel):
    """Lightweight document collection status per candidacy."""
    collection_id: str
    status: str
    progress: str
    documents_collected: int = 0
    documents_total: int = 0
    documents: List[DocumentCollectionItem] = []


class CandidateWithApplicationsResponse(CandidateResponse):
    """Response model for a candidate with their applications."""
    applications: List["CandidateApplicationSummary"] = []
    skills: List[CandidateSkillResponse] = []
    attributes: List[CandidateAttributeSummary] = []
    candidacies: List[CandidacySummary] = []
    documents: List[CandidateDocumentSummary] = []
    timeline: List["ActivityResponse"] = []


class CandidateApplicationSummary(BaseModel):
    """Summary of an application for a candidate."""
    id: str
    vacancy_id: str
    vacancy_title: str
    vacancy_company: str
    channel: str
    status: str
    qualified: Optional[bool] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class CandidateSkillCreate(BaseModel):
    """Request model for adding a skill to a candidate."""
    skill_name: str
    skill_code: Optional[str] = None
    skill_category: Optional[str] = None
    score: Optional[float] = Field(None, ge=0, le=1)
    evidence: Optional[str] = None
    source: str = "manual"


class CandidateSkillBulkCreate(BaseModel):
    """Request model for bulk adding skills (e.g., from CV analysis)."""
    skills: List[CandidateSkillCreate]


# Import for forward references (avoid circular imports)
from src.models.activity import ActivityResponse
from src.models.application import QuestionAnswerResponse

# Rebuild models to resolve forward references
ScreeningResult.model_rebuild()
CandidacySummary.model_rebuild()
CandidateWithApplicationsResponse.model_rebuild()
