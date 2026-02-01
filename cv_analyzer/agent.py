"""
CV Analyzer Agent for processing PDF CVs against interview questions.

This agent analyzes PDF CVs and compares them against pre-screening interview
questions to identify what information is available and what clarification
questions need to be asked.
"""

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from dataclasses import dataclass
from typing import Optional
import base64
import json
import logging
import re
import uuid

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class QuestionAnalysis:
    """Analysis result for a single interview question against the CV."""
    id: str                           # e.g., "ko_1" or "qual_2"
    question_text: str                # The original question
    cv_evidence: str                  # What the CV says about this topic
    is_answered: bool                 # Can we answer from CV?
    clarification_needed: Optional[str]  # Suggested clarification question (if any)


@dataclass
class CVAnalysisResult:
    """Complete result from CV analysis."""
    knockout_analysis: list[QuestionAnalysis]
    qualification_analysis: list[QuestionAnalysis]
    cv_summary: str                   # Brief summary of candidate profile
    clarification_questions: list[str]  # List of questions to ask candidate
    raw_response: Optional[str] = None


# =============================================================================
# Agent Instruction
# =============================================================================

INSTRUCTION = """Je bent een expert in het analyseren van CV's voor screening doeleinden.

Je taak is om een CV (PDF) te analyseren en te vergelijken met de interviewvragen om te bepalen welke informatie al aanwezig is en welke verduidelijkingsvragen gesteld moeten worden.

## INPUT FORMAAT
Je ontvangt:
1. Een PDF CV van de kandidaat
2. Een lijst met KNOCKOUT vragen (ja/nee vragen, verplichte eisen)
3. Een lijst met KWALIFICATIE vragen (met ideaal antwoord voor context)

## ANALYSE INSTRUCTIES

### Voor KNOCKOUT vragen:
- Zoek in het CV naar bewijs dat de vraag beantwoordt
- Bijvoorbeeld: "Heb je een rijbewijs B?" - zoek naar vermelding van rijbewijs
- Als het CV geen duidelijke informatie bevat: clarification_needed = de originele vraag
- is_answered = true alleen als het CV expliciet bewijs bevat

### Voor KWALIFICATIE vragen:
- Zoek in het CV naar relevante ervaring, vaardigheden, opleiding
- Vergelijk met het ideale antwoord om te begrijpen wat belangrijk is
- Als er lacunes zijn: stel een gerichte verduidelijkingsvraag voor
- is_answered = true als het CV voldoende informatie bevat

## OUTPUT FORMAAT
Antwoord ALLEEN met een JSON object in dit exacte formaat:

```json
{
  "knockout_analysis": [
    {
      "id": "ko_1",
      "question_text": "de originele vraag",
      "cv_evidence": "wat het CV zegt over dit onderwerp, of 'Geen informatie gevonden'",
      "is_answered": true,
      "clarification_needed": null
    }
  ],
  "qualification_analysis": [
    {
      "id": "qual_1",
      "question_text": "de originele vraag",
      "cv_evidence": "relevante ervaring/opleiding uit het CV",
      "is_answered": false,
      "clarification_needed": "Specifieke vraag om de lacune te vullen"
    }
  ],
  "cv_summary": "Korte professionele samenvatting van de kandidaat (2-3 zinnen)",
  "clarification_questions": [
    "Vraag 1 om te stellen aan de kandidaat",
    "Vraag 2 om te stellen aan de kandidaat"
  ]
}
```

## BELANGRIJKE REGELS
1. Wees grondig maar realistisch - sommige informatie staat zelden in een CV (bijv. rijbewijs)
2. cv_evidence moet concreet zijn - citeer of parafraseer wat je in het CV vindt
3. clarification_questions is een verzamelde lijst van ALLE vragen die gesteld moeten worden
4. De cv_summary moet professioneel en bondig zijn
5. Antwoord ALLEEN met JSON, geen andere tekst
6. clarification_needed kan null zijn als is_answered=true
7. Formuleer verduidelijkingsvragen vriendelijk en professioneel in het Nederlands
"""


# =============================================================================
# Agent and Runner Setup
# =============================================================================

# Create the CV analyzer agent
cv_analyzer_agent = Agent(
    name="cv_analyzer",
    model="gemini-2.5-flash",  # Supports PDF natively, fast and cost-effective
    instruction=INSTRUCTION,
    description="Agent for analyzing CVs against interview questions to identify clarification needs",
)

# Session service for running the agent
_session_service = InMemorySessionService()

# Runner for executing the agent
_runner = Runner(
    agent=cv_analyzer_agent,
    app_name="cv_analyzer_app",
    session_service=_session_service,
)


# =============================================================================
# Helper Functions
# =============================================================================

def format_questions_for_analysis(
    knockout_questions: list[dict],
    qualification_questions: list[dict]
) -> str:
    """
    Format questions for the agent to analyze.
    
    Args:
        knockout_questions: List of knockout questions with id, question/question_text
        qualification_questions: List of qualification questions with id, question/question_text, ideal_answer
        
    Returns:
        Formatted questions string
    """
    lines = []
    
    if knockout_questions:
        lines.append("## KNOCKOUT VRAGEN")
        for q in knockout_questions:
            qid = q.get("id", "ko_?")
            text = q.get("question_text", q.get("question", ""))
            lines.append(f"- {qid}: {text}")
        lines.append("")
    
    if qualification_questions:
        lines.append("## KWALIFICATIE VRAGEN")
        for q in qualification_questions:
            qid = q.get("id", "qual_?")
            text = q.get("question_text", q.get("question", ""))
            ideal = q.get("ideal_answer", "")
            lines.append(f"- {qid}: {text}")
            if ideal:
                lines.append(f"  IDEAAL ANTWOORD: {ideal}")
        lines.append("")
    
    return "\n".join(lines)


def parse_agent_response(response_text: str) -> dict:
    """
    Parse the JSON response from the agent.
    
    Args:
        response_text: Raw text response from the agent
        
    Returns:
        Parsed JSON dict, or empty result on error
    """
    # Try to extract JSON from the response
    # The agent might wrap it in markdown code blocks
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.error(f"Could not find JSON in response: {response_text[:500]}")
            return {}
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}\nJSON string: {json_str[:500]}")
        return {}


# =============================================================================
# Main Analysis Function
# =============================================================================

async def analyze_cv(
    pdf_data: bytes,
    knockout_questions: list[dict],
    qualification_questions: list[dict],
) -> CVAnalysisResult:
    """
    Analyze a PDF CV against interview questions.
    
    Args:
        pdf_data: Raw PDF bytes (not base64 encoded)
        knockout_questions: List of knockout questions with id, question_text
        qualification_questions: List of qualification questions with id, question_text, ideal_answer
        
    Returns:
        CVAnalysisResult with analysis for each question and clarification questions
    """
    # Format questions for the prompt
    formatted_questions = format_questions_for_analysis(
        knockout_questions, 
        qualification_questions
    )
    
    # Build the text prompt
    prompt_text = f"""Analyseer het bijgevoegde CV en vergelijk het met de volgende interviewvragen.

{formatted_questions}

Geef je analyse als JSON."""

    logger.info("=" * 60)
    logger.info("CV ANALYZER: Starting analysis")
    logger.info("=" * 60)
    logger.info(f"PDF size: {len(pdf_data)} bytes")
    logger.info(f"Knockout questions: {len(knockout_questions)}")
    logger.info(f"Qualification questions: {len(qualification_questions)}")
    logger.info("-" * 40)
    
    # Generate a unique session ID for this processing
    session_id = f"cv_analysis_{uuid.uuid4().hex[:8]}"
    
    # Create session before running the agent
    await _session_service.create_session(
        app_name="cv_analyzer_app",
        user_id="system",
        session_id=session_id
    )
    
    # Build the content with both PDF and text prompt
    # The PDF is passed as inline_data, the prompt as text
    content = types.Content(
        role="user",
        parts=[
            # PDF document
            types.Part(
                inline_data=types.Blob(
                    mime_type="application/pdf",
                    data=pdf_data
                )
            ),
            # Text prompt with questions
            types.Part(text=prompt_text)
        ]
    )
    
    # Run the agent
    response_text = ""
    async for event in _runner.run_async(
        user_id="system",
        session_id=session_id,
        new_message=content
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    response_text += part.text
    
    logger.info("Agent response received")
    logger.debug(f"Raw response: {response_text[:500]}...")
    
    # Parse the response
    parsed = parse_agent_response(response_text)
    
    if not parsed:
        logger.error("Failed to parse agent response, returning empty results")
        return CVAnalysisResult(
            knockout_analysis=[],
            qualification_analysis=[],
            cv_summary="Fout bij het analyseren van het CV",
            clarification_questions=[],
            raw_response=response_text
        )
    
    # Convert to result objects
    knockout_analysis = []
    for ka in parsed.get("knockout_analysis", []):
        knockout_analysis.append(QuestionAnalysis(
            id=ka.get("id", ""),
            question_text=ka.get("question_text", ""),
            cv_evidence=ka.get("cv_evidence", ""),
            is_answered=ka.get("is_answered", False),
            clarification_needed=ka.get("clarification_needed")
        ))
    
    qualification_analysis = []
    for qa in parsed.get("qualification_analysis", []):
        qualification_analysis.append(QuestionAnalysis(
            id=qa.get("id", ""),
            question_text=qa.get("question_text", ""),
            cv_evidence=qa.get("cv_evidence", ""),
            is_answered=qa.get("is_answered", False),
            clarification_needed=qa.get("clarification_needed")
        ))
    
    result = CVAnalysisResult(
        knockout_analysis=knockout_analysis,
        qualification_analysis=qualification_analysis,
        cv_summary=parsed.get("cv_summary", ""),
        clarification_questions=parsed.get("clarification_questions", []),
        raw_response=response_text
    )
    
    logger.info(f"Analysis complete: {len(knockout_analysis)} knockout, {len(qualification_analysis)} qualification")
    logger.info(f"Clarification questions needed: {len(result.clarification_questions)}")
    logger.info("=" * 60)
    
    return result


async def analyze_cv_base64(
    pdf_base64: str,
    knockout_questions: list[dict],
    qualification_questions: list[dict],
) -> CVAnalysisResult:
    """
    Analyze a PDF CV (base64 encoded) against interview questions.
    
    This is a convenience wrapper that decodes base64 before calling analyze_cv.
    
    Args:
        pdf_base64: Base64-encoded PDF data
        knockout_questions: List of knockout questions
        qualification_questions: List of qualification questions
        
    Returns:
        CVAnalysisResult with analysis for each question
    """
    # Decode base64 to bytes
    try:
        pdf_data = base64.b64decode(pdf_base64)
    except Exception as e:
        logger.error(f"Failed to decode base64 PDF: {e}")
        return CVAnalysisResult(
            knockout_analysis=[],
            qualification_analysis=[],
            cv_summary="Fout bij het decoderen van de PDF (ongeldige base64)",
            clarification_questions=[],
            raw_response=None
        )
    
    return await analyze_cv(pdf_data, knockout_questions, qualification_questions)
