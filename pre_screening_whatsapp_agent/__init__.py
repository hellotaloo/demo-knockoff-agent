"""
Pre-screening WhatsApp Agent

A multi-agent system for conducting candidate pre-screening conversations.

Usage with ADK Web:
    cd taloo-backend
    adk web . --port 8001

Then select "pre_screening_whatsapp_agent" from the dropdown.
"""

from .agent import (
    root_agent,
    create_pre_screening_agent,
    get_test_state,
    DEFAULT_TEST_STATE,
)

from .tools import (
    evaluate_knockout_answer,
    knockout_failed,
    confirm_knockout_result,
    evaluate_open_answer,
    complete_alternate_intake,
    exit_interview,
    get_available_slots,
    schedule_interview,
    conversation_complete,
)

__all__ = [
    # Main agent
    "root_agent",

    # Factory function
    "create_pre_screening_agent",

    # Test utilities
    "get_test_state",
    "DEFAULT_TEST_STATE",

    # Tools (for custom implementations)
    "evaluate_knockout_answer",
    "knockout_failed",
    "confirm_knockout_result",
    "evaluate_open_answer",
    "complete_alternate_intake",
    "exit_interview",
    "get_available_slots",
    "schedule_interview",
    "conversation_complete",
]
