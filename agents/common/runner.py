"""
Shared agent runner utilities.

Provides a helper for single-shot agent execution, eliminating boilerplate
for session creation, runner setup, and response collection that was
duplicated across cv_analyzer, interview_analyzer, transcript_processor,
and document_detector agents.
"""
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


async def run_agent_once(
    agent,
    app_name: str,
    content: types.Content,
    session_id_prefix: str = "agent",
) -> str:
    """
    Run an agent with a single message and return the final response text.

    Creates a fresh InMemorySessionService and Runner per invocation,
    so there is no shared state between calls.

    Args:
        agent: The ADK Agent instance to run.
        app_name: The app_name to use for session/runner.
        content: The message content (types.Content) to send.
        session_id_prefix: Prefix for the generated session ID.

    Returns:
        The concatenated text from the agent's final response.
    """
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)

    session_id = f"{session_id_prefix}_{uuid.uuid4().hex[:8]}"
    await session_service.create_session(
        app_name=app_name,
        user_id="system",
        session_id=session_id,
    )

    response_text = ""
    async for event in runner.run_async(
        user_id="system",
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text

    return response_text
