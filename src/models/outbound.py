"""
Outbound screening models (voice and WhatsApp).
"""
from typing import Optional
from pydantic import BaseModel
from .enums import InterviewChannel


class OutboundScreeningRequest(BaseModel):
    """Request model for initiating outbound screening (voice or WhatsApp)."""
    vacancy_id: str  # UUID of the vacancy
    channel: InterviewChannel  # "voice" or "whatsapp"
    phone_number: str  # E.164 format, e.g., "+32412345678"
    first_name: str  # Candidate's first name
    last_name: str  # Candidate's last name
    test_conversation_id: Optional[str] = None  # For testing: skip real call, use this ID
    is_test: bool = False  # True for internal test conversations (admin testing)


class OutboundScreeningResponse(BaseModel):
    """Response model for outbound screening initiation."""
    success: bool
    message: str
    channel: InterviewChannel
    conversation_id: Optional[str] = None
    application_id: Optional[str] = None  # UUID of the created/updated application
    # Voice-specific fields
    call_sid: Optional[str] = None
