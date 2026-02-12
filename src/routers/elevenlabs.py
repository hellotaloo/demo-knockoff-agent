"""
ElevenLabs Router - Agent configuration management.
"""
import os
import httpx
from fastapi import APIRouter, HTTPException

from src.models.elevenlabs import (
    VoiceConfigRequest,
    VoiceConfigResponse,
    UpdateAgentVoiceConfigRequest,
    UpdateAgentVoiceConfigResponse,
)
from src.database import get_db_pool
from src.config import logger

router = APIRouter(prefix="/elevenlabs", tags=["ElevenLabs"])


def _get_api_key() -> str:
    """Get ElevenLabs API key from environment."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="ELEVENLABS_API_KEY environment variable is required"
        )
    return api_key


@router.patch(
    "/agent/{agent_id}/config",
    response_model=UpdateAgentVoiceConfigResponse,
    summary="Update ElevenLabs agent voice configuration",
    description="""
    Update the voice and TTS model configuration for an ElevenLabs conversational AI agent.

    This endpoint calls the ElevenLabs API to update the agent's TTS settings,
    allowing users to change the voice, model, stability, and similarity boost
    before starting a conversation.

    **Available TTS models:**
    - `eleven_turbo_v2` - Fast, low-latency model
    - `eleven_multilingual_v2` - Multilingual support
    - `eleven_flash_v2_5` - Ultra-fast streaming
    - `eleven_v3_conversational` - Latest conversational model (recommended)
    """
)
async def update_agent_voice_config(
    agent_id: str,
    request: UpdateAgentVoiceConfigRequest,
) -> UpdateAgentVoiceConfigResponse:
    """
    Update the voice configuration for an ElevenLabs agent.

    This patches the agent's TTS settings including voice_id, model_id,
    stability, and similarity_boost.
    """
    api_key = _get_api_key()

    # Build the TTS config object
    tts_config = {
        "voice_id": request.voice_id,
        "model_id": request.model_id,
    }

    # Add optional parameters if provided
    if request.stability is not None:
        tts_config["stability"] = request.stability
    if request.similarity_boost is not None:
        tts_config["similarity_boost"] = request.similarity_boost

    # Build the PATCH request body
    patch_body = {
        "conversation_config": {
            "tts": tts_config
        }
    }

    logger.info(f"Updating ElevenLabs agent {agent_id} with config: {patch_body}")

    # Call ElevenLabs API
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}",
                json=patch_body,
                headers={
                    "Content-Type": "application/json",
                    "xi-api-key": api_key,
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Successfully updated ElevenLabs agent {agent_id}")

                # Extract the TTS config from the response
                tts_response = result.get("conversation_config", {}).get("tts", {})

                return UpdateAgentVoiceConfigResponse(
                    success=True,
                    message="Agent voice configuration updated successfully",
                    agent_id=agent_id,
                    voice_id=tts_response.get("voice_id", request.voice_id),
                    model_id=tts_response.get("model_id", request.model_id),
                    stability=tts_response.get("stability"),
                    similarity_boost=tts_response.get("similarity_boost"),
                )
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Agent not found: {agent_id}"
                )
            elif response.status_code == 422:
                error_detail = response.json()
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation error: {error_detail}"
                )
            else:
                error_text = response.text
                logger.error(f"ElevenLabs API error: {response.status_code} - {error_text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"ElevenLabs API error: {error_text}"
                )

        except httpx.TimeoutException:
            logger.error(f"Timeout calling ElevenLabs API for agent {agent_id}")
            raise HTTPException(
                status_code=504,
                detail="Timeout connecting to ElevenLabs API"
            )
        except httpx.RequestError as e:
            logger.error(f"Error calling ElevenLabs API: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error connecting to ElevenLabs API: {str(e)}"
            )


@router.get(
    "/voice-config/{agent_id}",
    response_model=VoiceConfigResponse,
    summary="Get saved voice configuration",
    description="Retrieve the saved voice configuration settings for an ElevenLabs agent."
)
async def get_voice_config(agent_id: str) -> VoiceConfigResponse:
    """
    Get the saved voice configuration for an agent.

    Returns the stored voice_id, model_id, stability, and similarity_boost settings.
    """
    pool = await get_db_pool()

    row = await pool.fetchrow(
        """
        SELECT id, agent_id, voice_id, model_id, stability, similarity_boost, created_at, updated_at
        FROM agents.voice_config
        WHERE agent_id = $1
        """,
        agent_id
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Voice configuration not found for agent: {agent_id}"
        )

    return VoiceConfigResponse(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        voice_id=row["voice_id"],
        model_id=row["model_id"],
        stability=float(row["stability"]) if row["stability"] is not None else None,
        similarity_boost=float(row["similarity_boost"]) if row["similarity_boost"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.put(
    "/voice-config/{agent_id}",
    response_model=VoiceConfigResponse,
    summary="Save voice configuration",
    description="Save or update the voice configuration settings for an ElevenLabs agent."
)
async def save_voice_config(
    agent_id: str,
    request: VoiceConfigRequest,
) -> VoiceConfigResponse:
    """
    Save or update the voice configuration for an agent.

    Creates a new record if one doesn't exist, or updates the existing record.
    """
    pool = await get_db_pool()

    # Upsert the voice config
    row = await pool.fetchrow(
        """
        INSERT INTO agents.voice_config (agent_id, voice_id, model_id, stability, similarity_boost)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (agent_id)
        DO UPDATE SET
            voice_id = EXCLUDED.voice_id,
            model_id = EXCLUDED.model_id,
            stability = EXCLUDED.stability,
            similarity_boost = EXCLUDED.similarity_boost,
            updated_at = NOW()
        RETURNING id, agent_id, voice_id, model_id, stability, similarity_boost, created_at, updated_at
        """,
        agent_id,
        request.voice_id,
        request.model_id,
        request.stability,
        request.similarity_boost,
    )

    logger.info(f"Saved voice config for agent {agent_id}: voice_id={request.voice_id}, model_id={request.model_id}")

    return VoiceConfigResponse(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        voice_id=row["voice_id"],
        model_id=row["model_id"],
        stability=float(row["stability"]) if row["stability"] is not None else None,
        similarity_boost=float(row["similarity_boost"]) if row["similarity_boost"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
