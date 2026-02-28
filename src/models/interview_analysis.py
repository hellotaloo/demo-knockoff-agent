"""
Interview analysis models.
"""
from typing import Optional, Literal
from pydantic import BaseModel


# =============================================================================
# Request Models
# =============================================================================

class AnalysisQuestionInput(BaseModel):
    """A question to analyze."""
    id: str
    text: str
    type: Literal["knockout", "qualifying"]


class AnalysisVacancyInput(BaseModel):
    """Vacancy context for the analysis."""
    id: str
    title: str
    description: Optional[str] = None


class InterviewAnalysisRequest(BaseModel):
    """Request model for interview analysis.

    Questions and vacancy can be provided in the body,
    or omitted to load from database via the path parameter.
    """
    questions: Optional[list[AnalysisQuestionInput]] = None
    vacancy: Optional[AnalysisVacancyInput] = None


# =============================================================================
# Response Models (camelCase to match frontend contract)
# =============================================================================

class AnalysisSummary(BaseModel):
    """Overall interview analysis summary."""
    completionRate: int
    avgTimeSeconds: int
    verdict: Literal["excellent", "good", "needs_work", "poor"]
    verdictHeadline: str
    verdictDescription: str
    oneLiner: str


class AnalysisQuestionResult(BaseModel):
    """Per-question analysis result."""
    questionId: str
    completionRate: int
    avgTimeSeconds: int
    dropOffRisk: Literal["low", "medium", "high"]
    clarityScore: int
    tip: Optional[str] = None


class AnalysisFunnelStep(BaseModel):
    """Single step in the funnel visualization."""
    step: str
    candidates: int


class InterviewAnalysisResponse(BaseModel):
    """Full interview analysis response."""
    summary: AnalysisSummary
    questions: list[AnalysisQuestionResult]
    funnel: list[AnalysisFunnelStep]
