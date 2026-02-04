"""
Data query models.
"""
from typing import Optional
from pydantic import BaseModel


class DataQueryRequest(BaseModel):
    question: str
    session_id: str | None = None  # Optional: reuse session for context
