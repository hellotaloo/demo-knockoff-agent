"""
VAPI webhook payload models.

VAPI is a voice AI platform that handles outbound calls with multi-assistant squads.
These models define the structure of webhook events sent by VAPI after calls complete.
"""
from typing import Optional, List, Union
from pydantic import BaseModel


class VapiTranscriptMessage(BaseModel):
    """Single message in VAPI transcript."""
    role: str  # "user" or "assistant" or "bot"
    message: Optional[str] = None  # May be empty for some message types
    content: Optional[str] = None  # Alternative field name used by VAPI
    time: Optional[float] = None  # seconds into call
    endTime: Optional[float] = None
    secondsFromStart: Optional[float] = None
    # Squad-specific fields - which assistant spoke
    assistantId: Optional[str] = None
    assistantName: Optional[str] = None
    # Additional fields VAPI might include
    name: Optional[str] = None  # Assistant name in some formats

    @property
    def text(self) -> str:
        """Get message text from either 'message' or 'content' field."""
        return self.message or self.content or ""


class VapiCallObject(BaseModel):
    """VAPI call object included in webhooks."""
    id: str
    orgId: Optional[str] = None
    type: Optional[str] = None  # "outboundPhoneCall", "inboundPhoneCall", etc.
    status: Optional[str] = None  # "queued", "ringing", "in-progress", "ended"
    endedReason: Optional[str] = None
    phoneNumberId: Optional[str] = None
    squadId: Optional[str] = None
    assistantId: Optional[str] = None
    customer: Optional[dict] = None  # {"number": "+1234567890"}
    startedAt: Optional[Union[str, int, float]] = None  # ISO string or Unix ms
    endedAt: Optional[Union[str, int, float]] = None  # ISO string or Unix ms
    cost: Optional[float] = None
    # Duration fields - VAPI may send these directly
    durationSeconds: Optional[float] = None
    duration: Optional[float] = None  # Alias used by some VAPI versions
    # Cost breakdown may contain duration info
    costBreakdown: Optional[dict] = None
    # Custom metadata passed via assistantOverrides.variableValues
    metadata: Optional[dict] = None


class VapiArtifact(BaseModel):
    """Artifact containing transcript and recording info."""
    transcript: Optional[str] = None  # Full transcript text
    messages: Optional[List[VapiTranscriptMessage]] = None
    recordingUrl: Optional[str] = None
    stereoRecordingUrl: Optional[str] = None


class VapiEndOfCallReportPayload(BaseModel):
    """Payload for end-of-call-report webhook event."""
    type: str = "end-of-call-report"
    endedReason: Optional[str] = None
    call: VapiCallObject
    artifact: Optional[VapiArtifact] = None
    # Analysis results if configured
    analysis: Optional[dict] = None
    # Metadata
    timestamp: Optional[Union[str, int, float]] = None  # Can be string or Unix ms


class VapiStatusUpdatePayload(BaseModel):
    """Payload for status-update webhook event."""
    type: str = "status-update"
    status: str  # "queued", "ringing", "in-progress", "ended"
    call: VapiCallObject
    timestamp: Optional[Union[str, int, float]] = None  # Can be string or Unix ms


class VapiMessagePayload(BaseModel):
    """Real-time message event during call."""
    role: Optional[str] = None
    message: Optional[str] = None
    timestamp: Optional[Union[str, int, float]] = None  # Can be string or Unix ms
    secondsFromStart: Optional[float] = None
    # Additional fields VAPI might send
    type: Optional[str] = None  # "transcript", etc.
    transcriptType: Optional[str] = None  # "partial", "final"


class VapiWebhookPayload(BaseModel):
    """Generic VAPI webhook payload - use type to determine specific structure.

    VAPI sends various event types:
    - type="status-update": Call state changes
    - type="end-of-call-report": Final transcript and call data
    - type="transcript": Partial/final transcripts
    - message={...}: Real-time messages during call (no top-level type!)
    """
    type: Optional[str] = None  # May be absent for message events
    call: Optional[VapiCallObject] = None
    artifact: Optional[VapiArtifact] = None
    endedReason: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[Union[str, int, float]] = None  # Can be string or Unix ms
    # Real-time message events have a "message" field instead of "type"
    message: Optional[VapiMessagePayload] = None


class VapiCreateCallRequest(BaseModel):
    """Request model for creating VAPI outbound call."""
    phone_number: str  # E.164 format
    candidate_id: str
    vacancy_id: str
    first_name: str
    pre_screening_id: Optional[str] = None


class VapiCreateCallResponse(BaseModel):
    """Response from VAPI create call API."""
    id: str  # VAPI call ID
    status: str
    phoneNumberId: Optional[str] = None
    squadId: Optional[str] = None


class VapiWebCallRequest(BaseModel):
    """Request model for creating VAPI web call session (browser-based simulation)."""
    vacancy_id: str
    candidate_name: str = "Test Kandidaat"  # Dummy default for simulation
    first_name: Optional[str] = None  # Extracted from candidate_name if not provided


class VapiWebCallResponse(BaseModel):
    """Response with config for frontend to start web call via VAPI SDK."""
    success: bool
    squad_id: str
    vapi_public_key: str
    assistant_overrides: dict  # Contains variableValues with questions
