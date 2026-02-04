"""
Data query endpoints - natural language querying of recruitment data.
"""
import json
import uuid
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from google.genai import types
from sqlalchemy.exc import InterfaceError, OperationalError, IntegrityError

from src.models.data_query import DataQueryRequest
from data_query_agent.agent import set_db_pool as set_data_query_db_pool
from recruiter_analyst.agent import root_agent as recruiter_analyst_agent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Data Query"])

# Global session manager (set by main app)
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager


async def stream_analyst_query(question: str, session_id: str) -> AsyncGenerator[str, None]:
    """Stream SSE events during analyst query processing."""
    global session_manager

    async def get_or_create_analyst_session():
        """Helper to get existing session or create new one, handling race conditions."""
        existing = await session_manager.analyst_session_service.get_session(
            app_name="recruiter_analyst", user_id="web", session_id=session_id
        )
        if existing:
            return
        try:
            await session_manager.analyst_session_service.create_session(
                app_name="recruiter_analyst",
                user_id="web",
                session_id=session_id
            )
        except IntegrityError:
            # Session was created by another request, that's fine
            logger.info(f"Analyst session {session_id} already exists")

    await session_manager.with_session_retry(
        get_or_create_analyst_session,
        lambda: session_manager.create_analyst_session_service(recruiter_analyst_agent),
        "create analyst session"
    )

    # Send initial status
    yield f"data: {json.dumps({'type': 'status', 'status': 'thinking', 'message': 'Vraag analyseren...'})}\n\n"

    # Run the agent
    content = types.Content(role="user", parts=[types.Part(text=question)])

    try:
        async for event in session_manager.analyst_runner.run_async(
            user_id="web",
            session_id=session_id,
            new_message=content
        ):
            # Check for tool calls or sub-agent delegation
            if hasattr(event, 'tool_calls') and event.tool_calls:
                yield f"data: {json.dumps({'type': 'status', 'status': 'tool_call', 'message': 'Data ophalen...'})}\n\n"

            # Check for thinking/reasoning content
            if hasattr(event, 'content') and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'thought') and part.thought:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': part.text})}\n\n"

            # Final response
            if event.is_final_response() and event.content and event.content.parts:
                response_text = event.content.parts[0].text
                yield f"data: {json.dumps({'type': 'complete', 'message': response_text, 'session_id': session_id})}\n\n"
    except Exception as e:
        logger.error(f"Error during analyst query: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/data-query")
async def analyst_query(request: DataQueryRequest):
    """Query the recruiter analyst using natural language with SSE streaming."""
    session_id = request.session_id or str(uuid.uuid4())

    return StreamingResponse(
        stream_analyst_query(request.question, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/data-query/session/{session_id}")
async def get_analyst_session(session_id: str):
    """Get the current session state for an analyst session."""
    global session_manager

    try:
        session = await session_manager.analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating analyst session service: {e}")
        session_manager.create_analyst_session_service(recruiter_analyst_agent)
        session = await session_manager.analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "state": session.state
    }


@router.delete("/data-query/session/{session_id}")
async def delete_analyst_session(session_id: str):
    """Delete an analyst session to start fresh."""
    global session_manager

    try:
        session = await session_manager.analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )
    except (InterfaceError, OperationalError) as e:
        logger.warning(f"Database connection error, recreating analyst session service: {e}")
        session_manager.create_analyst_session_service(recruiter_analyst_agent)
        session = await session_manager.analyst_session_service.get_session(
            app_name="recruiter_analyst",
            user_id="web",
            session_id=session_id
        )

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await session_manager.analyst_session_service.delete_session(
        app_name="recruiter_analyst",
        user_id="web",
        session_id=session_id
    )

    return {"status": "success", "message": "Session deleted"}
