"""
CV analysis models.
"""
from typing import Optional
from pydantic import BaseModel


class CVQuestionRequest(BaseModel):
    """A question to analyze against the CV."""
    id: str  # e.g., "ko_1" or "qual_1"
    question: str  # The question text
    ideal_answer: Optional[str] = None  # For qualification questions


class CVAnalyzeRequest(BaseModel):
    """Request model for CV analysis."""
    pdf_base64: str  # Base64-encoded PDF
    knockout_questions: list[CVQuestionRequest]
    qualification_questions: list[CVQuestionRequest]


class CVQuestionAnalysisResponse(BaseModel):
    """Analysis result for a single question."""
    id: str
    question_text: str
    cv_evidence: str
    is_answered: bool
    clarification_needed: Optional[str] = None


class CVAnalyzeResponse(BaseModel):
    """Response model for CV analysis."""
    knockout_analysis: list[CVQuestionAnalysisResponse]
    qualification_analysis: list[CVQuestionAnalysisResponse]
    cv_summary: str
    clarification_questions: list[str]
