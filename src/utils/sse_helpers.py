"""
SSE (Server-Sent Events) formatting helpers.

Provides consistent formatting for SSE event strings used across
streaming endpoints (interviews, screening, data query, playground).
"""
import json


def sse_done() -> str:
    """Terminal SSE event indicating the stream is complete."""
    return "data: [DONE]\n\n"


def sse_error(message: str) -> str:
    """SSE event for an error message."""
    return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"


def sse_status(status: str, message: str) -> str:
    """SSE event for a status update (e.g. 'thinking', 'tool_call')."""
    return f"data: {json.dumps({'type': 'status', 'status': status, 'message': message})}\n\n"


def sse_data(data: dict) -> str:
    """SSE event for arbitrary JSON data."""
    return f"data: {json.dumps(data)}\n\n"
