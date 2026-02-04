"""
Screening conversation models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ScreeningChatRequest(BaseModel):
    vacancy_id: str
    message: str
    session_id: Optional[str] = None
    candidate_name: Optional[str] = None  # Optional - if not provided, random name generated
    is_test: bool = False  # True for admin/internal test conversations


class SimulateInterviewRequest(BaseModel):
    """Request model for running an interview simulation."""
    persona: str = "qualified"  # qualified, borderline, unqualified, rushed, enthusiastic, custom
    custom_persona: Optional[str] = None  # Custom persona description when persona="custom"
    candidate_name: Optional[str] = None  # Optional - random name generated if not provided


class ScreeningConversationResponse(BaseModel):
    id: str
    vacancy_id: str
    candidate_name: str
    candidate_email: Optional[str] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    message_count: int
