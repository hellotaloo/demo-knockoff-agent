"""
Playground models — shared request/response schemas for playground endpoints.
"""
from typing import Optional
from pydantic import BaseModel


class PlaygroundChatRequest(BaseModel):
    """Unified chat request for all playground agent types."""
    agent_type: str  # "pre_screening" | "document_collection"
    message: str  # User message or "START" for new conversation
    session_id: Optional[str] = None  # None = new conversation
    # Agent-specific context (only needed on START)
    vacancy_id: Optional[str] = None  # Required for pre_screening
    collection_id: Optional[str] = None  # Required for document_collection
    candidate_name: Optional[str] = None  # Optional — random if missing
    # Image upload (base64-encoded)
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    # Live mode — persist collected data to candidate records & transition candidacy
    live_mode: bool = False
