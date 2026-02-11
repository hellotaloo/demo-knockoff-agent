"""
Activity models for candidate timeline tracking.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class ActivityEventType(str, Enum):
    """Types of activities that can be logged."""

    # Screening lifecycle
    SCREENING_STARTED = "screening_started"
    SCREENING_COMPLETED = "screening_completed"
    SCREENING_ABANDONED = "screening_abandoned"

    # Messages
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"

    # Voice calls
    CALL_INITIATED = "call_initiated"
    CALL_COMPLETED = "call_completed"
    CALL_FAILED = "call_failed"

    # Documents
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_VERIFIED = "document_verified"
    DOCUMENT_REJECTED = "document_rejected"
    CV_UPLOADED = "cv_uploaded"
    CV_ANALYZED = "cv_analyzed"

    # Application status
    STATUS_CHANGED = "status_changed"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"

    # Interview scheduling
    INTERVIEW_SCHEDULED = "interview_scheduled"
    INTERVIEW_CONFIRMED = "interview_confirmed"
    INTERVIEW_CANCELLED = "interview_cancelled"
    INTERVIEW_RESCHEDULED = "interview_rescheduled"
    INTERVIEW_COMPLETED = "interview_completed"
    INTERVIEW_NO_SHOW = "interview_no_show"

    # Recruiter actions
    NOTE_ADDED = "note_added"
    APPLICATION_VIEWED = "application_viewed"
    CANDIDATE_CONTACTED = "candidate_contacted"

    # System events
    APPLICATION_SYNCED = "application_synced"


class ActorType(str, Enum):
    """Who performed the activity."""
    CANDIDATE = "candidate"
    AGENT = "agent"
    RECRUITER = "recruiter"
    SYSTEM = "system"


class ActivityChannel(str, Enum):
    """Channel where activity occurred."""
    VOICE = "voice"
    WHATSAPP = "whatsapp"
    CV = "cv"
    WEB = "web"


class ActivityCreate(BaseModel):
    """Request model for creating an activity."""
    candidate_id: str
    event_type: ActivityEventType
    application_id: Optional[str] = None
    vacancy_id: Optional[str] = None
    channel: Optional[ActivityChannel] = None
    actor_type: ActorType = ActorType.SYSTEM
    actor_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None


class ActivityResponse(BaseModel):
    """Response model for an activity."""
    id: str
    candidate_id: str
    application_id: Optional[str] = None
    vacancy_id: Optional[str] = None
    event_type: str
    channel: Optional[str] = None
    actor_type: str
    actor_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineResponse(BaseModel):
    """Response model for a candidate's activity timeline."""
    candidate_id: str
    activities: list[ActivityResponse]
    total: int
