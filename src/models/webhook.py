"""
Webhook payload models.
"""
from typing import Optional
from pydantic import BaseModel


class ElevenLabsWebhookData(BaseModel):
    """Data object from ElevenLabs post-call webhook."""
    agent_id: str
    conversation_id: str
    status: Optional[str] = None
    transcript: list[dict] = []
    metadata: Optional[dict] = None
    analysis: Optional[dict] = None


class ElevenLabsWebhookPayload(BaseModel):
    """Full payload from ElevenLabs post-call webhook."""
    type: str  # "post_call_transcription", "post_call_audio", "call_initiation_failure"
    event_timestamp: int
    data: ElevenLabsWebhookData
