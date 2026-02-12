"""
Pre-screening Voice Agent for outbound phone call screenings.

This module provides functionality to initiate outbound phone calls via ElevenLabs + Twilio.
The agent is managed in the ElevenLabs dashboard - we only trigger calls and pass dynamic variables.
"""

import os
import logging
from datetime import datetime
from typing import Optional
from elevenlabs import ElevenLabs

logger = logging.getLogger(__name__)


def get_dutch_greeting() -> str:
    """
    Get appropriate Dutch greeting based on current time.

    Returns:
        str: "Goedemorgen" (6-12), "Goeiemiddag" (12-18), or "Goeieavond" (18-6)
    """
    hour = datetime.now().hour

    if 6 <= hour < 12:
        return "Goedemorgen"
    elif 12 <= hour < 18:
        return "Goeiemiddag"
    else:
        return "Goeieavond"


# =============================================================================
# ElevenLabs Client
# =============================================================================

_client: Optional[ElevenLabs] = None


def get_elevenlabs_client() -> ElevenLabs:
    """
    Get or create the ElevenLabs client.

    Returns:
        ElevenLabs: The ElevenLabs client instance.

    Raises:
        RuntimeError: If ELEVENLABS_API_KEY is not set.
    """
    global _client

    if _client is None:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY environment variable is required")

        _client = ElevenLabs(api_key=api_key)
        logger.info("Created ElevenLabs client")

    return _client


# =============================================================================
# Outbound Calling
# =============================================================================

def initiate_outbound_call(
    to_number: str,
    agent_id: str,
    first_name: Optional[str] = None,
    pre_screening_id: Optional[str] = None,
    vacancy_id: Optional[str] = None,
) -> dict:
    """
    Initiate an outbound phone call to a candidate using ElevenLabs + Twilio.

    Args:
        to_number: The phone number to call (E.164 format, e.g., "+31612345678")
        agent_id: The ElevenLabs agent ID (from ELEVENLABS_AGENT_ID env var)
        first_name: Candidate's first name (passed to agent as dynamic variable)
        pre_screening_id: Optional pre-screening ID for correlation
        vacancy_id: Optional vacancy ID for correlation

    Returns:
        dict: Response containing:
            - success: bool
            - message: str
            - conversation_id: str (if successful)
            - call_sid: str (if successful)

    Raises:
        RuntimeError: If ELEVENLABS_PHONE_NUMBER_ID is not set.
        ValueError: If agent_id is not provided.
    """
    if not agent_id:
        raise ValueError("agent_id is required. Use ELEVENLABS_AGENT_ID from environment.")

    phone_number_id = os.environ.get("ELEVENLABS_PHONE_NUMBER_ID")
    if not phone_number_id:
        raise RuntimeError("ELEVENLABS_PHONE_NUMBER_ID environment variable is required")

    client = get_elevenlabs_client()

    logger.info(f"Initiating outbound call to {to_number} with agent {agent_id}")

    # Build dynamic variables for the agent
    dynamic_variables = {
        "greeting": get_dutch_greeting(),  # Always include time-based greeting
    }
    if first_name:
        dynamic_variables["first_name"] = first_name
    if pre_screening_id:
        dynamic_variables["pre_screening_id"] = pre_screening_id
    if vacancy_id:
        dynamic_variables["vacancy_id"] = vacancy_id

    conversation_initiation_client_data = None
    if dynamic_variables:
        conversation_initiation_client_data = {"dynamic_variables": dynamic_variables}
        logger.info(f"Passing dynamic_variables: {dynamic_variables}")

    # Make the outbound call via Twilio
    response = client.conversational_ai.twilio.outbound_call(
        agent_id=agent_id,
        agent_phone_number_id=phone_number_id,
        to_number=to_number,
        conversation_initiation_client_data=conversation_initiation_client_data,
    )

    result = {
        "success": response.success,
        "message": response.message,
        "conversation_id": response.conversation_id,
        "call_sid": response.call_sid,
    }

    logger.info(f"Outbound call initiated: {result}")

    return result
