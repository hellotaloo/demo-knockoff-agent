"""
ElevenLabs API models for agent configuration.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class VoiceConfigRequest(BaseModel):
    """Request model for saving voice configuration settings."""

    voice_id: str = Field(..., description="The ElevenLabs voice ID to use")
    model_id: str = Field(
        default="eleven_v3_conversational",
        description="The TTS model (e.g., eleven_turbo_v2, eleven_multilingual_v2, eleven_flash_v2_5, eleven_v3_conversational)"
    )
    stability: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Voice stability (0-1). Higher = more consistent, lower = more expressive"
    )
    similarity_boost: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Similarity boost (0-1). Higher = more similar to original voice"
    )


class VoiceConfigResponse(BaseModel):
    """Response model for voice configuration settings."""

    id: str
    agent_id: str
    voice_id: str
    model_id: str
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class UpdateAgentVoiceConfigRequest(BaseModel):
    """Request model for updating ElevenLabs agent voice configuration."""

    voice_id: str = Field(..., description="The ElevenLabs voice ID to use")
    model_id: str = Field(
        ...,
        description="The TTS model (e.g., eleven_turbo_v2, eleven_multilingual_v2, eleven_flash_v2_5, eleven_v3_conversational)"
    )
    stability: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Voice stability (0-1). Higher = more consistent, lower = more expressive"
    )
    similarity_boost: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Similarity boost (0-1). Higher = more similar to original voice"
    )


class UpdateAgentVoiceConfigResponse(BaseModel):
    """Response model for updating ElevenLabs agent voice configuration."""

    success: bool
    message: str
    agent_id: str
    voice_id: str
    model_id: str
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
