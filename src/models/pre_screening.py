"""
Pre-screening configuration models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PreScreeningQuestionRequest(BaseModel):
    """Request model for a pre-screening question."""
    id: str  # Client-provided ID (e.g., "ko_1", "qual_2")
    question: str
    ideal_answer: Optional[str] = None  # Scoring guidance for qualification questions
    vacancy_snippet: Optional[str] = None  # Exact text from vacancy this question is based on


class PreScreeningQuestionResponse(BaseModel):
    """Response model for a pre-screening question."""
    id: str  # Database UUID
    question_type: str  # "knockout" or "qualification"
    position: int
    question_text: str
    ideal_answer: Optional[str] = None  # Scoring guidance for qualification questions
    vacancy_snippet: Optional[str] = None  # Exact text from vacancy this question is based on
    is_approved: bool


class PreScreeningRequest(BaseModel):
    """Request model for saving pre-screening configuration."""
    intro: str
    knockout_questions: list[PreScreeningQuestionRequest]
    knockout_failed_action: str
    qualification_questions: list[PreScreeningQuestionRequest]
    final_action: str
    approved_ids: list[str] = []


class PreScreeningResponse(BaseModel):
    """Response model for pre-screening configuration."""
    id: str  # Pre-screening UUID
    vacancy_id: str
    intro: str
    knockout_questions: list[PreScreeningQuestionResponse]
    knockout_failed_action: str
    qualification_questions: list[PreScreeningQuestionResponse]
    final_action: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Publishing fields
    published_at: Optional[datetime] = None
    is_online: bool = False
    elevenlabs_agent_id: Optional[str] = None
    whatsapp_agent_id: Optional[str] = None


class PublishPreScreeningRequest(BaseModel):
    """Request model for publishing a pre-screening."""
    enable_voice: bool = True      # Create ElevenLabs agent
    enable_whatsapp: bool = True   # Create WhatsApp agent
    enable_cv: bool = False        # Enable CV analysis channel


class PublishPreScreeningResponse(BaseModel):
    """Response model for publish operation."""
    published_at: datetime
    elevenlabs_agent_id: Optional[str] = None
    whatsapp_agent_id: Optional[str] = None
    is_online: bool


class StatusUpdateRequest(BaseModel):
    """Request model for updating pre-screening status and channel toggles."""
    is_online: Optional[bool] = None
    voice_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    cv_enabled: Optional[bool] = None
