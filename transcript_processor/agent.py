"""
Transcript Processor Agent for analyzing ElevenLabs voice call transcripts.

This agent processes voice call transcripts and evaluates candidate responses
against pre-screening interview questions.
"""

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
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
    passed: bool
    score: int  # 100 if passed, 0 if failed
    rating: str  # "excellent" if passed, "weak" if failed


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
- Bepaal of het antwoord POSITIEF of NEGATIEF is

POSITIEVE indicatoren (passed=true):
- "ja", "ja hoor", "jawel", "ja zeker", "absoluut"
- "dat klopt", "zeker", "uiteraard", "natuurlijk"
- "ik heb...", "ik kan...", "ik ben..." (bevestigend)

NEGATIEVE indicatoren (passed=false):
- "nee", "nee sorry", "helaas niet", "nog niet"
- "ik heb geen...", "ik kan niet...", "ik ben niet..."
- Twijfelachtige antwoorden zonder duidelijke bevestiging

Bij twijfel: kies voor passed=false (veilige kant)

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

## INTERVIEW SLOT EXTRACTIE
Zoek in het transcript of er een gesprek is ingepland:
- De agent biedt meestal meerdere opties aan (bijv. "maandag om 10 uur, maandag om 14 uur, of dinsdag om 11 uur")
- De kandidaat kiest een optie of geeft aan dat geen enkele optie past

Je krijgt de GESPREKSDATUM mee om relatieve dagen om te zetten naar een echte datum.
Bijvoorbeeld: als het gesprek op vrijdag 31 januari 2025 was en de kandidaat kiest "dinsdag om 11 uur", 
dan is dat dinsdag 4 februari 2025 om 11:00.

Mogelijke waarden voor interview_slot:
- ISO 8601 datetime (bijv. "2025-02-04T11:00:00") als een optie is gekozen
- "none_fit" als de kandidaat aangeeft dat geen enkele optie past
- null als er geen gesprek over inplannen in het transcript staat

## OUTPUT FORMAAT
Antwoord ALLEEN met een JSON object in dit exacte formaat:

```json
{
  "knockout_results": [
    {
      "id": "ko_1",
      "question_text": "de originele vraag",
      "answer": "het antwoord van de kandidaat uit het transcript",
      "passed": true
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
  "notes": "Korte samenvatting van de evaluatie",
  "summary": "Eén zin executive summary voor de recruiter over deze kandidaat",
  "interview_slot": "2025-02-04T11:00:00"
}
```

## BELANGRIJKE REGELS
1. overall_passed = true ALLEEN als ALLE knockout vragen passed=true zijn
2. Als een vraag niet in het transcript voorkomt, gebruik answer="[Vraag niet beantwoord]" en passed=false / score=0
3. Citeer het antwoord zo letterlijk mogelijk uit het transcript
4. Wees strikt maar eerlijk in je evaluatie
5. De notes moeten kort en zakelijk zijn (max 2 zinnen)
6. De summary is een bondige, professionele zin voor recruiters die de essentie van de kandidaat samenvat (bijv. "Ervaren magazijnmedewerker met rijbewijs en flexibele beschikbaarheid, maar beperkte ervaring met reachtruck.")
7. interview_slot moet een ISO 8601 datetime zijn (bijv. "2025-02-04T11:00:00"), bereken de echte datum op basis van de gespreksdatum en de gekozen dag/tijd
8. Als geen optie paste: interview_slot = "none_fit", als niet besproken: interview_slot = null
9. Antwoord ALLEEN met JSON, geen andere tekst
"""


# =============================================================================
# Agent and Runner Setup
# =============================================================================

# Create the transcript processor agent
transcript_processor_agent = Agent(
    name="transcript_processor",
    model="gemini-3-pro-preview",
    instruction=INSTRUCTION,
    description="Agent for analyzing voice call transcripts and evaluating candidate responses",
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
            notes="Fout bij het verwerken van het transcript",
            raw_response=response_text
        )
    
    # Convert to result objects
    knockout_results = []
    for kr in parsed.get("knockout_results", []):
        passed = kr.get("passed", False)
        # Knockout: passed = 100/excellent, failed = 0/weak
        knockout_results.append(KnockoutResult(
            id=kr.get("id", ""),
            question_text=kr.get("question_text", ""),
            answer=kr.get("answer", ""),
            passed=passed,
            score=100 if passed else 0,
            rating="excellent" if passed else "weak"
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
    
    result = TranscriptProcessorResult(
        knockout_results=knockout_results,
        qualification_results=qualification_results,
        overall_passed=parsed.get("overall_passed", False),
        notes=parsed.get("notes", ""),
        summary=parsed.get("summary", ""),
        interview_slot=parsed.get("interview_slot"),
        raw_response=response_text
    )
    
    logger.info(f"Processing complete: overall_passed={result.overall_passed}")
    logger.info(f"Knockout results: {len(knockout_results)}")
    logger.info(f"Qualification results: {len(qualification_results)}")
    logger.info("=" * 60)
    
    return result
