"""
Pre-screening WhatsApp Agent

A code-controlled agent for conducting candidate pre-screening conversations.
Flow is managed by Python code, not LLM routing decisions.

Usage:
    from pre_screening_whatsapp_agent import create_simple_agent, Phase

    agent = create_simple_agent(
        candidate_name="Jan",
        vacancy_title="Magazijnmedewerker",
        company_name="ITZU",
        knockout_questions=[{"question": "...", "requirement": "..."}],
        open_questions=["..."],
    )

    # Get initial welcome message
    message = await agent.get_initial_message()

    # Process user responses
    response = await agent.process_message(user_input)

    # Save state for persistence
    state_json = agent.state.to_json()

    # Restore agent from state
    agent = restore_agent_from_state(state_json)
"""

from .agent import (
    # Main classes
    SimplePreScreeningAgent,
    ConversationState,
    AgentConfig,
    Phase,
    # Factory functions
    create_simple_agent,
    restore_agent_from_state,
    # Helper functions
    is_conversation_complete,
    get_conversation_outcome,
    # Default config
    DEFAULT_CONFIG,
)

__all__ = [
    # Main classes
    "SimplePreScreeningAgent",
    "ConversationState",
    "AgentConfig",
    "Phase",
    # Factory functions
    "create_simple_agent",
    "restore_agent_from_state",
    # Helper functions
    "is_conversation_complete",
    "get_conversation_outcome",
    # Default config
    "DEFAULT_CONFIG",
]
