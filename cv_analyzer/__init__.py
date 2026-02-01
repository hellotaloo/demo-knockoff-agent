"""
CV Analyzer Agent for processing PDF CVs against interview questions.

This module provides functionality to:
1. Process PDF CVs (as base64 or bytes)
2. Compare CV content against knockout and qualification questions
3. Identify gaps where the CV doesn't provide sufficient information
4. Generate clarification questions to ask the candidate
"""

from .agent import (
    analyze_cv,
    analyze_cv_base64,
    CVAnalysisResult,
    QuestionAnalysis,
)

__all__ = [
    "analyze_cv",
    "analyze_cv_base64",
    "CVAnalysisResult",
    "QuestionAnalysis",
]
