"""
Pre-screening Voice Agent.

Voice-based candidate screening via VAPI/ElevenLabs.
"""

from pre_screening_voice_agent.calendar_helpers import (
    get_time_slots_for_voice,
    schedule_interview,
)

__all__ = [
    "get_time_slots_for_voice",
    "schedule_interview",
]
