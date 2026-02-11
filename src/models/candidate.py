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


class CandidateListResponse(CandidateResponse):
    """Response model for candidate list (includes computed fields)."""
    skills: List[CandidateSkillResponse] = []
    vacancy_count: int = 0
    last_activity: Optional[datetime] = None


class CandidateWithApplicationsResponse(CandidateResponse):
    """Response model for a candidate with their applications."""
    applications: List["CandidateApplicationSummary"] = []
    skills: List[CandidateSkillResponse] = []
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


# Import ActivityResponse for type hints (imported here to avoid circular imports)
from src.models.activity import ActivityResponse

# Rebuild models to resolve forward references
CandidateWithApplicationsResponse.model_rebuild()
