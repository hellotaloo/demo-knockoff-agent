"""
Candidacy models — tracks a candidate's position in a vacancy pipeline.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class CandidacyStage(str, Enum):
    NEW = "new"
    PRE_SCREENING = "pre_screening"
    QUALIFIED = "qualified"
    INTERVIEW_PLANNED = "interview_planned"
    INTERVIEW_DONE = "interview_done"
    OFFER = "offer"
    PLACED = "placed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# ---------------------------------------------------------------------------
# Nested objects (embedded in list/detail responses)
# ---------------------------------------------------------------------------

class CandidacyCandidateInfo(BaseModel):
    id: str
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None


class CandidacyVacancyInfo(BaseModel):
    id: str
    title: str
    company: Optional[str] = None
    is_open_application: bool = False


class CandidacyVacancyLink(BaseModel):
    """A vacancy this candidate is actively linked to (shown as chips on the Kanban card)."""
    candidacy_id: str
    vacancy_id: str
    vacancy_title: str
    stage: CandidacyStage


class CandidacyApplicationSummary(BaseModel):
    id: str
    channel: str                              # voice | whatsapp | cv
    status: str = "active"                    # active | completed
    qualified: Optional[bool] = None
    open_questions_score: Optional[int] = None  # 0–100
    knockout_passed: int = 0
    knockout_total: int = 0
    completed_at: Optional[datetime] = None
    interview_scheduled_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Main response model
# ---------------------------------------------------------------------------

class CandidacyResponse(BaseModel):
    id: str
    candidate_id: str
    stage: CandidacyStage
    source: Optional[str] = None
    stage_updated_at: datetime
    created_at: datetime
    updated_at: datetime

    candidate: CandidacyCandidateInfo
    vacancy: Optional[CandidacyVacancyInfo] = None
    latest_application: Optional[CandidacyApplicationSummary] = None
    linked_vacancies: list[CandidacyVacancyLink] = []

    recruiter_verification: bool = False
    recruiter_verification_reason: Optional[str] = None
    contract_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CandidacyCreate(BaseModel):
    vacancy_id: Optional[str] = None
    candidate_id: str
    stage: CandidacyStage = CandidacyStage.NEW
    source: Optional[str] = None


class CandidacyUpdate(BaseModel):
    stage: Optional[CandidacyStage] = None
    source: Optional[str] = None
