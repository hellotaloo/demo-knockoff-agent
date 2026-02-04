"""
CV Analysis Router

Handles CV analysis endpoints including analyzing CVs against pre-screening questions.
"""

from fastapi import APIRouter

from cv_analyzer import analyze_cv_base64
from src.models.cv import (
    CVAnalyzeRequest,
    CVAnalyzeResponse,
    CVQuestionAnalysisResponse,
)
from src.repositories import PreScreeningRepository

router = APIRouter(prefix="/cv", tags=["CV Analysis"])


@router.post("/analyze", response_model=CVAnalyzeResponse)
async def analyze_cv_endpoint(request: CVAnalyzeRequest):
    """
    Analyze a PDF CV against interview questions.

    Takes a base64-encoded PDF and lists of knockout/qualification questions,
    returns analysis of what information is in the CV and what clarification
    questions need to be asked.
    """
    # Convert request questions to dict format
    knockout_questions = [
        {
            "id": q.id,
            "question_text": q.question,
        }
        for q in request.knockout_questions
    ]

    qualification_questions = [
        {
            "id": q.id,
            "question_text": q.question,
            "ideal_answer": q.ideal_answer or "",
        }
        for q in request.qualification_questions
    ]

    # Run the CV analyzer
    result = await analyze_cv_base64(
        pdf_base64=request.pdf_base64,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
    )

    # Convert to response format
    return CVAnalyzeResponse(
        knockout_analysis=[
            CVQuestionAnalysisResponse(
                id=qa.id,
                question_text=qa.question_text,
                cv_evidence=qa.cv_evidence,
                is_answered=qa.is_answered,
                clarification_needed=qa.clarification_needed,
            )
            for qa in result.knockout_analysis
        ],
        qualification_analysis=[
            CVQuestionAnalysisResponse(
                id=qa.id,
                question_text=qa.question_text,
                cv_evidence=qa.cv_evidence,
                is_answered=qa.is_answered,
                clarification_needed=qa.clarification_needed,
            )
            for qa in result.qualification_analysis
        ],
        cv_summary=result.cv_summary,
        clarification_questions=result.clarification_questions,
    )
