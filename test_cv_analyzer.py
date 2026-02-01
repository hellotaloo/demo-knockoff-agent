#!/usr/bin/env python3
"""
Test script for the CV Analyzer.

Usage:
    python test_cv_analyzer.py path/to/cv.pdf

Outputs results to cv_analysis_result.md
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from cv_analyzer import analyze_cv, CVAnalysisResult


# Sample interview questions for testing
SAMPLE_KNOCKOUT_QUESTIONS = [
    {"id": "ko_1", "question_text": "Heb je een rijbewijs B?"},
    {"id": "ko_2", "question_text": "Ben je beschikbaar voor weekendwerk?"},
    {"id": "ko_3", "question_text": "Heb je een geldig werkvergunning voor België?"},
]

SAMPLE_QUALIFICATION_QUESTIONS = [
    {
        "id": "qual_1",
        "question_text": "Hoeveel jaar relevante werkervaring heb je?",
        "ideal_answer": "Minstens 2 jaar relevante ervaring in een vergelijkbare functie."
    },
    {
        "id": "qual_2",
        "question_text": "Welke technische vaardigheden of certificaten heb je?",
        "ideal_answer": "Relevante technische certificaten, softwarekennis, of vakspecifieke opleidingen."
    },
    {
        "id": "qual_3",
        "question_text": "Beschrijf je ervaring met teamwerk en samenwerking.",
        "ideal_answer": "Concrete voorbeelden van teamprojecten of leidinggevende ervaring."
    },
]


def format_result_as_markdown(result: CVAnalysisResult, pdf_path: str) -> str:
    """Format the analysis result as a Markdown document."""
    lines = []
    
    # Header
    lines.append("# CV Analyse Resultaat")
    lines.append("")
    lines.append(f"**Geanalyseerd bestand:** `{pdf_path}`")
    lines.append(f"**Analyse datum:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # CV Summary
    lines.append("## Kandidaat Samenvatting")
    lines.append("")
    lines.append(result.cv_summary or "_Geen samenvatting beschikbaar_")
    lines.append("")
    
    # Clarification Questions
    lines.append("## Verduidelijkingsvragen")
    lines.append("")
    if result.clarification_questions:
        lines.append("De volgende vragen moeten nog aan de kandidaat gesteld worden:")
        lines.append("")
        for i, question in enumerate(result.clarification_questions, 1):
            lines.append(f"{i}. {question}")
        lines.append("")
    else:
        lines.append("_Geen verduidelijkingsvragen nodig - alle informatie is beschikbaar in het CV._")
        lines.append("")
    
    # Knockout Questions Analysis
    lines.append("## Knockout Vragen Analyse")
    lines.append("")
    if result.knockout_analysis:
        for qa in result.knockout_analysis:
            status = "✅" if qa.is_answered else "❓"
            lines.append(f"### {status} {qa.id}: {qa.question_text}")
            lines.append("")
            lines.append(f"**CV Bewijs:** {qa.cv_evidence}")
            lines.append("")
            lines.append(f"**Beantwoord vanuit CV:** {'Ja' if qa.is_answered else 'Nee'}")
            if qa.clarification_needed:
                lines.append(f"")
                lines.append(f"**Verduidelijking nodig:** {qa.clarification_needed}")
            lines.append("")
    else:
        lines.append("_Geen knockout vragen geanalyseerd._")
        lines.append("")
    
    # Qualification Questions Analysis
    lines.append("## Kwalificatie Vragen Analyse")
    lines.append("")
    if result.qualification_analysis:
        for qa in result.qualification_analysis:
            status = "✅" if qa.is_answered else "❓"
            lines.append(f"### {status} {qa.id}: {qa.question_text}")
            lines.append("")
            lines.append(f"**CV Bewijs:** {qa.cv_evidence}")
            lines.append("")
            lines.append(f"**Beantwoord vanuit CV:** {'Ja' if qa.is_answered else 'Nee'}")
            if qa.clarification_needed:
                lines.append(f"")
                lines.append(f"**Verduidelijking nodig:** {qa.clarification_needed}")
            lines.append("")
    else:
        lines.append("_Geen kwalificatie vragen geanalyseerd._")
        lines.append("")
    
    # Raw response (for debugging)
    if result.raw_response:
        lines.append("---")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Raw Agent Response (voor debugging)</summary>")
        lines.append("")
        lines.append("```json")
        lines.append(result.raw_response)
        lines.append("```")
        lines.append("")
        lines.append("</details>")
    
    return "\n".join(lines)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_cv_analyzer.py path/to/cv.pdf")
        print("")
        print("This script analyzes a PDF CV and outputs results to cv_analysis_result.md")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    
    if not pdf_path.lower().endswith('.pdf'):
        print(f"Warning: File does not have .pdf extension: {pdf_path}")
    
    print(f"Reading PDF: {pdf_path}")
    
    # Read the PDF file
    with open(pdf_path, 'rb') as f:
        pdf_data = f.read()
    
    print(f"PDF size: {len(pdf_data):,} bytes")
    print("")
    print("Analyzing CV against sample questions...")
    print(f"  - {len(SAMPLE_KNOCKOUT_QUESTIONS)} knockout questions")
    print(f"  - {len(SAMPLE_QUALIFICATION_QUESTIONS)} qualification questions")
    print("")
    
    # Run the analyzer
    result = await analyze_cv(
        pdf_data=pdf_data,
        knockout_questions=SAMPLE_KNOCKOUT_QUESTIONS,
        qualification_questions=SAMPLE_QUALIFICATION_QUESTIONS,
    )
    
    print("Analysis complete!")
    print("")
    
    # Format and save results
    markdown = format_result_as_markdown(result, pdf_path)
    output_path = "cv_analysis_result.md"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown)
    
    print(f"Results saved to: {output_path}")
    print("")
    
    # Print summary
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"CV Summary: {result.cv_summary[:100]}..." if len(result.cv_summary) > 100 else f"CV Summary: {result.cv_summary}")
    print("")
    print(f"Knockout questions answered: {sum(1 for q in result.knockout_analysis if q.is_answered)}/{len(result.knockout_analysis)}")
    print(f"Qualification questions answered: {sum(1 for q in result.qualification_analysis if q.is_answered)}/{len(result.qualification_analysis)}")
    print(f"Clarification questions needed: {len(result.clarification_questions)}")
    
    if result.clarification_questions:
        print("")
        print("Questions to ask:")
        for q in result.clarification_questions:
            print(f"  - {q}")


if __name__ == "__main__":
    asyncio.run(main())
