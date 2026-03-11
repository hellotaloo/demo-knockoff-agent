"""
Transcript Processor Agent for analyzing ElevenLabs voice call transcripts.

This agent processes voice call transcripts and evaluates candidate responses
against pre-screening interview questions.
"""

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.planners import BuiltInPlanner
from google.genai import types
from dataclasses import dataclass
from typing import Optional
import json
import logging
import re

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class KnockoutResult:
    """Result for a knockout question evaluation."""
    id: str
    question_text: str
    answer: str
    status: str  # "passed", "failed", "needs_review"
    passed: Optional[bool]  # True, False, or None (needs review)
    score: int  # 100 if passed, 0 if failed, 50 if needs_review
    rating: str  # "excellent", "weak", or "needs_review"


@dataclass
class QualificationResult:
    """Result for a qualification question evaluation."""
    id: str
    question_text: str
    answer: str
    score: int  # 0-100
    rating: str  # weak, below_average, average, good, excellent
    motivation: str  # Explanation of score: what was good/bad, what's missing for 100%


# Rating labels mapped to score ranges
RATING_LABELS = {
    "weak": (0, 20),
    "below_average": (21, 40),
    "average": (41, 60),
    "good": (61, 80),
    "excellent": (81, 100),
}


def score_to_rating(score: int) -> str:
    """Convert a numeric score (0-100) to a rating label."""
    if score <= 20:
        return "weak"
    elif score <= 40:
        return "below_average"
    elif score <= 60:
        return "average"
    elif score <= 80:
        return "good"
    else:
        return "excellent"


@dataclass
class TranscriptProcessorResult:
    """Complete result from transcript processing."""
    knockout_results: list[KnockoutResult]
    qualification_results: list[QualificationResult]
    overall_passed: bool
    needs_human_review: bool  # True if ANY knockout has status "needs_review"
    notes: str
    summary: str = ""  # One-sentence executive summary for recruiter
    interview_slot: Optional[str] = None  # Selected interview date/time, or "none_fit" if no option worked
    raw_response: Optional[str] = None


# =============================================================================
# Agent Instruction
# =============================================================================

INSTRUCTION = """Je bent een expert in het analyseren van telefonische sollicitatiegesprekken.

Je taak is om een transcript van een voice screening te analyseren en de antwoorden van de kandidaat te evalueren.

## INPUT FORMAAT
Je ontvangt:
1. Een transcript van het gesprek (agent en user berichten)
2. Een lijst met KNOCKOUT vragen (ja/nee vragen, verplichte eisen)
3. Een lijst met KWALIFICATIE vragen (met ideaal antwoord voor scoring)

## KNOCKOUT VRAGEN EVALUATIE
Voor elke knockout vraag:
- Zoek in het transcript waar deze vraag gesteld werd
- Identificeer het antwoord van de kandidaat (role: "user")
- Bepaal of het antwoord BEVESTIGEND, ONTKENNEND, of ONDUIDELIJK is

BELANGRIJK: Antwoorden die duidelijk bevestigend of ontkennend zijn, tellen als ja of neen.
Interpreteer de BETEKENIS, niet alleen exacte woorden.

### STATUS: "passed" (bevestigend)
- Expliciete ja: "ja", "ja hoor", "jawel", "ja zeker"
- Informele bevestigingen: "zeker", "tuurlijk", "absoluut", "uiteraard", "natuurlijk"
- Korte positieve reacties: "goed", "oké", "prima", "akkoord", "in orde", "top"
- Probleemloze bevestigingen: "dat is geen probleem", "geen issue", "geen probleem"
- Bevestigende uitspraken: "dat klopt", "klopt", "correct"
- Capaciteitsbevestigingen: "ik kan daar geraken", "ik heb...", "ik kan...", "ik ben..."

### STATUS: "failed" (ontkennend)
- Expliciete nee: "nee", "nee sorry", "helaas niet", "nog niet"
- Onmogelijkheid: "dat gaat niet", "ik kan daar niet geraken", "ik mag niet werken"
- Negatieve uitspraken: "ik heb geen...", "ik kan niet...", "ik ben niet..."
- Kandidaat bevestigt expliciet dat hij/zij NIET aan de eis voldoet

### STATUS: "needs_review" (onduidelijk - menselijke controle nodig)
Gebruik dit ALLEEN wanneer:
- Het antwoord is vaag of dubbelzinnig (bijv. "misschien", "soms", "het hangt ervan af")
- Het antwoord gaat niet direct over de vraag
- De kandidaat geeft een lang antwoord zonder duidelijke ja of nee
- Je bent oprecht onzeker over de intentie van de kandidaat
- Het transcript is onduidelijk of incompleet op dit punt

CONTEXT IS BELANGRIJK:
- Als de voice agent de vraag accepteerde en doorging naar de volgende vraag,
  dan was het antwoord waarschijnlijk bevestigend → "passed"
- Als de voice agent vroeg om bevestiging en de kandidaat werd afgewezen → "failed"
- Alleen bij ECHTE onduidelijkheid → "needs_review"

## KWALIFICATIE VRAGEN EVALUATIE
Voor elke kwalificatie vraag:
- Zoek in het transcript waar deze vraag gesteld werd
- Identificeer het antwoord van de kandidaat
- Vergelijk het antwoord met het IDEAAL ANTWOORD
- Geef een rating, score EN motivatie:

RATINGS (van laag naar hoog):
- "weak" (score 0-20): Geen relevant antwoord of sterk afwijkend
- "below_average" (score 21-40): Minimaal relevant, mist belangrijke punten
- "average" (score 41-60): Gedeeltelijk relevant, mist enkele punten
- "good" (score 61-80): Goed antwoord, dekt meeste belangrijke punten
- "excellent" (score 81-100): Uitstekend antwoord, voldoet aan of overtreft ideaal

MOTIVATIE:
Schrijf een korte motivatie (2-3 zinnen) die uitlegt:
- Wat was goed aan het antwoord (positieve punten)
- Wat was minder goed of ontbrak (negatieve punten)
- Wat had de kandidaat moeten noemen voor een perfecte score van 100%

## OUTPUT FORMAAT
Antwoord ALLEEN met een JSON object in dit exacte formaat:

```json
{
  "knockout_results": [
    {
      "id": "ko_1",
      "question_text": "de originele vraag",
      "answer": "het antwoord van de kandidaat uit het transcript",
      "status": "passed"
    },
    {
      "id": "ko_2",
      "question_text": "andere vraag",
      "answer": "vaag antwoord",
      "status": "needs_review"
    }
  ],
  "qualification_results": [
    {
      "id": "qual_1",
      "question_text": "de originele vraag",
      "answer": "het antwoord van de kandidaat uit het transcript",
      "score": 75,
      "rating": "good",
      "motivation": "Kandidaat toont relevante ervaring met magazijnwerk en noemt concrete voorbeelden. Mist echter specifieke ervaring met inventory management systemen. Voor een perfecte score had de kandidaat ook kunnen noemen: ervaring met WMS software, certificeringen, of voorbeelden van procesverbetering."
    }
  ],
  "overall_passed": true,
  "needs_human_review": true,
  "notes": "Korte samenvatting van de evaluatie",
  "summary": "Eén zin executive summary voor de recruiter over deze kandidaat"
}
```

## BELANGRIJKE REGELS
1. overall_passed = true als ALLE knockout vragen status "passed" of "needs_review" hebben (geen "failed")
2. overall_passed = false als MINSTENS ÉÉN knockout vraag status "failed" heeft
3. needs_human_review = true als MINSTENS ÉÉN knockout vraag status "needs_review" heeft
4. Als een vraag niet in het transcript voorkomt, gebruik answer="[Vraag niet beantwoord]" en status="needs_review"
5. Citeer het antwoord zo letterlijk mogelijk uit het transcript
6. Wees eerlijk in je evaluatie - gebruik "needs_review" bij twijfel, niet "failed"
7. De notes moeten kort en zakelijk zijn (max 2 zinnen)
8. De summary is een bondige, professionele zin voor recruiters die de essentie van de kandidaat samenvat (bijv. "Ervaren magazijnmedewerker met rijbewijs en flexibele beschikbaarheid, maar beperkte ervaring met reachtruck.")
9. Antwoord ALLEEN met JSON, geen andere tekst
"""


# =============================================================================
# Agent and Runner Setup
# =============================================================================

# Create the transcript processor agent with thinking enabled for better reasoning
transcript_processor_agent = Agent(
    name="transcript_processor",
    model="gemini-3-pro-preview",
    instruction=INSTRUCTION,
    description="Agent for analyzing voice call transcripts and evaluating candidate responses",
    planner=BuiltInPlanner(
        thinking_config=types.ThinkingConfig(
            include_thoughts=True,
            thinking_budget=1024,
        )
    ),
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=8192,  # Ensure enough tokens for full JSON response
        temperature=0.1,  # Low temperature for consistent structured output
    ),
)

# Session service for running the agent
_session_service = InMemorySessionService()

# Runner for executing the agent
_runner = Runner(
    agent=transcript_processor_agent,
    app_name="transcript_processor_app",
    session_service=_session_service,
)


# =============================================================================
# Transcript Processing Functions
# =============================================================================

def format_transcript_for_analysis(transcript: list[dict]) -> str:
    """
    Format ElevenLabs transcript array into readable text for analysis.
    
    Args:
        transcript: List of transcript entries with role, message, time_in_call_secs
        
    Returns:
        Formatted transcript string
    """
    lines = []
    for entry in transcript:
        role = entry.get("role", "unknown").upper()
        message = entry.get("message", "")
        time_secs = entry.get("time_in_call_secs", 0)
        
        # Format time as mm:ss
        minutes = int(time_secs // 60)
        seconds = int(time_secs % 60)
        timestamp = f"[{minutes:02d}:{seconds:02d}]"
        
        lines.append(f"{timestamp} {role}: {message}")
    
    return "\n".join(lines)


def format_questions_for_analysis(
    knockout_questions: list[dict],
    qualification_questions: list[dict]
) -> str:
    """
    Format questions for the agent to analyze.
    
    Args:
        knockout_questions: List of knockout questions with id, question_text
        qualification_questions: List of qualification questions with id, question_text, ideal_answer
        
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


async def process_transcript(
    transcript: list[dict],
    knockout_questions: list[dict],
    qualification_questions: list[dict],
    call_date: Optional[str] = None,
) -> TranscriptProcessorResult:
    """
    Process a voice call transcript and evaluate candidate responses.
    
    Args:
        transcript: ElevenLabs transcript array with role, message, time_in_call_secs
        knockout_questions: List of knockout questions to evaluate
        qualification_questions: List of qualification questions to evaluate
        call_date: ISO date string of when the call happened (for interview slot calculation)
        
    Returns:
        TranscriptProcessorResult with evaluation results
    """
    import uuid
    from datetime import datetime
    
    # Use provided call_date or default to today
    if call_date:
        call_date_str = call_date
    else:
        call_date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Format the input for the agent
    formatted_transcript = format_transcript_for_analysis(transcript)
    formatted_questions = format_questions_for_analysis(
        knockout_questions, 
        qualification_questions
    )
    
    # Build the prompt
    prompt = f"""Analyseer het volgende transcript en evalueer de antwoorden.

## GESPREKSDATUM
{call_date_str}

## TRANSCRIPT
{formatted_transcript}

{formatted_questions}

Geef je evaluatie als JSON."""

    logger.info("=" * 60)
    logger.info("TRANSCRIPT PROCESSOR: Starting analysis")
    logger.info("=" * 60)
    logger.info(f"Transcript entries: {len(transcript)}")
    logger.info(f"Knockout questions: {len(knockout_questions)}")
    logger.info(f"Qualification questions: {len(qualification_questions)}")
    logger.info("-" * 40)
    
    # Generate a unique session ID for this processing
    session_id = f"transcript_{uuid.uuid4().hex[:8]}"
    
    # Create session before running the agent
    await _session_service.create_session(
        app_name="transcript_processor_app",
        user_id="system",
        session_id=session_id
    )
    
    # Run the agent
    response_text = ""
    content = types.Content(
        role="user",
        parts=[types.Part(text=prompt)]
    )
    
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
        return TranscriptProcessorResult(
            knockout_results=[],
            qualification_results=[],
            overall_passed=False,
            needs_human_review=True,  # Flag for review when parsing fails
            notes="Fout bij het verwerken van het transcript",
            raw_response=response_text
        )
    
    # Convert to result objects
    knockout_results = []
    for kr in parsed.get("knockout_results", []):
        status = kr.get("status", "needs_review")
        # Derive passed and score from status
        if status == "passed":
            passed = True
            score = 100
            rating = "excellent"
        elif status == "failed":
            passed = False
            score = 0
            rating = "weak"
        else:  # needs_review
            passed = None
            score = 50
            rating = "needs_review"

        knockout_results.append(KnockoutResult(
            id=kr.get("id", ""),
            question_text=kr.get("question_text", ""),
            answer=kr.get("answer", ""),
            status=status,
            passed=passed,
            score=score,
            rating=rating
        ))
    
    qualification_results = []
    for qr in parsed.get("qualification_results", []):
        score = qr.get("score", 0)
        # Use rating from response, or derive from score
        rating = qr.get("rating") or score_to_rating(score)
        qualification_results.append(QualificationResult(
            id=qr.get("id", ""),
            question_text=qr.get("question_text", ""),
            answer=qr.get("answer", ""),
            score=score,
            rating=rating,
            motivation=qr.get("motivation", "")
        ))
    
    # Compute overall_passed and needs_human_review from knockout results
    # overall_passed = true if no knockout has status "failed"
    # needs_human_review = true if any knockout has status "needs_review"
    has_failed = any(kr.status == "failed" for kr in knockout_results)
    has_needs_review = any(kr.status == "needs_review" for kr in knockout_results)

    # Use parsed value as fallback, but prefer computed logic
    overall_passed = not has_failed if knockout_results else parsed.get("overall_passed", False)
    needs_human_review = has_needs_review

    result = TranscriptProcessorResult(
        knockout_results=knockout_results,
        qualification_results=qualification_results,
        overall_passed=overall_passed,
        needs_human_review=needs_human_review,
        notes=parsed.get("notes", ""),
        summary=parsed.get("summary", ""),
        interview_slot=parsed.get("interview_slot"),
        raw_response=response_text
    )
    
    logger.info(f"Processing complete: overall_passed={result.overall_passed}, needs_human_review={result.needs_human_review}")
    logger.info(f"Knockout results: {len(knockout_results)} (passed: {sum(1 for kr in knockout_results if kr.status == 'passed')}, failed: {sum(1 for kr in knockout_results if kr.status == 'failed')}, needs_review: {sum(1 for kr in knockout_results if kr.status == 'needs_review')})")
    logger.info(f"Qualification results: {len(qualification_results)}")
    logger.info("=" * 60)
    
    return result
