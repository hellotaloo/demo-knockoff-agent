"""
ElevenLabs Voice Agent integration for outbound phone call screenings.

All voice agents are created dynamically from pre-screening configurations.
Use create_or_update_voice_agent() to create vacancy-specific agents.
"""

from .agent import (
    get_elevenlabs_client,
    initiate_outbound_call,
    # Dynamic vacancy-specific agent creation
    create_or_update_voice_agent,
    build_voice_prompt,
    delete_voice_agent,
    list_voice_agents,
)

__all__ = [
    "get_elevenlabs_client",
    "initiate_outbound_call",
    # Dynamic vacancy-specific agent creation
    "create_or_update_voice_agent",
    "build_voice_prompt",
    "delete_voice_agent",
    "list_voice_agents",
]
