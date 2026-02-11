"""
ElevenLabs Voice Agent integration for outbound phone call screenings.

The voice agent is managed in the ElevenLabs dashboard (ELEVENLABS_AGENT_ID).
This module only handles initiating outbound calls via Twilio.
"""

from .agent import (
    get_elevenlabs_client,
    initiate_outbound_call,
    get_dutch_greeting,
)

__all__ = [
    "get_elevenlabs_client",
    "initiate_outbound_call",
    "get_dutch_greeting",
]
