"""
Interview generation and management models.
"""
from typing import Optional
from pydantic import BaseModel


class GenerateInterviewRequest(BaseModel):
    vacancy_id: str  # UUID of the vacancy to generate questions for
    session_id: str | None = None  # Optional: reuse session for feedback


class FeedbackRequest(BaseModel):
    session_id: str
    message: str


class ReorderRequest(BaseModel):
    session_id: str
    knockout_order: list[str] | None = None  # List of question IDs in new order
    qualification_order: list[str] | None = None


class DeleteQuestionRequest(BaseModel):
    session_id: str
    question_id: str  # ID of question to delete (e.g., "ko_1" or "qual_2")


class AddQuestionRequest(BaseModel):
    session_id: str
    question_type: str  # "knockout" or "qualification"
    question: str
    ideal_answer: str | None = None  # Required for qualification questions
    vacancy_snippet: str | None = None  # Text from vacancy this question relates to


class RestoreSessionRequest(BaseModel):
    vacancy_id: str
