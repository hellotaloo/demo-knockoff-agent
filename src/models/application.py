"""
Application-related models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class QuestionAnswerResponse(BaseModel):
    question_id: str
    question_text: str
    question_type: Optional[str] = None  # knockout or qualification
    answer: Optional[str] = None
    passed: Optional[bool] = None
    score: Optional[int] = None  # 0-100
    rating: Optional[str] = None  # weak, below_average, average, good, excellent
    motivation: Optional[str] = None  # Explanation of score: what was good/bad, what's missing for 100%


class ApplicationResponse(BaseModel):
    id: str
    vacancy_id: str
    candidate_name: str
    channel: str
    status: str  # Workflow state: 'active', 'processing', 'completed'
    qualified: bool  # Outcome: did applicant pass the screening?
    started_at: datetime
    completed_at: Optional[datetime] = None
    interaction_seconds: int
    answers: list[QuestionAnswerResponse] = []
    synced: bool
    synced_at: Optional[datetime] = None
    # Score summary
    open_questions_score: Optional[int] = None  # Average of all scores (0-100)
    knockout_passed: int = 0  # Number of knockout questions passed
    knockout_total: int = 0  # Total knockout questions
    open_questions_total: int = 0  # Total open/qualification questions
    summary: Optional[str] = None  # AI-generated executive summary
    interview_slot: Optional[str] = None  # Selected interview date/time, or "none_fit"
    is_test: bool = False  # True for internal test conversations


class CVApplicationRequest(BaseModel):
    """Request model for creating an application from a CV."""
    pdf_base64: str
    candidate_name: str
    candidate_phone: Optional[str] = None
    candidate_email: Optional[str] = None
