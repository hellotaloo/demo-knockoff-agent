"""
Interview Analysis Agent for evaluating pre-screening interview quality.

Analyzes interview questions from a candidate perspective and returns:
- Per-question metrics (clarity, drop-off risk, time estimate, tips)
- Overall summary with verdict and one-liner
- Funnel data starting at 200 simulated candidates
"""

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
import json
import logging
import re
import uuid

logger = logging.getLogger(__name__)


# =============================================================================
# Agent Instruction
# =============================================================================

INSTRUCTION = """Je bent een expert in het analyseren van pre-screening interviews voor recruitment.

Je taak is om een set interviewvragen te evalueren vanuit het perspectief van een kandidaat. Je beoordeelt elke vraag op helderheid, verwachte invultijd, en het risico dat kandidaten afhaken.

## INPUT
Je ontvangt:
1. Een lijst interviewvragen met type (knockout of qualifying) en volgorde
2. Context over de vacature (titel en beschrijving)

## ANALYSE PER VRAAG

Evalueer elke vraag op basis van:

### 1. Helderheid (clarityScore: 0-100)
- Is de vraag ondubbelzinnig?
- Zou een kandidaat direct begrijpen wat er gevraagd wordt?
- Knockout-vragen moeten simpele ja/nee-vragen zijn
- Kwalificatievragen mogen complexer zijn maar niet vaag
- Score >= 85: helder, < 85: verbetering nodig

### 2. Knockout-vragen: Ambiguïteitscheck
Knockout-vragen MOETEN ondubbelzinnige ja/nee-vragen zijn. Controleer specifiek:
- Kan de kandidaat het verwachte antwoord anders interpreteren?
- Bevat de vraag vage termen die per persoon verschillen?
  Voorbeeld: "Ben je flexibel?" is AMBIGU — flexibel in uren? in taken? in locatie?
  Voorbeeld: "Heb je een rijbewijs B?" is HELDER — eenduidig ja of nee
- Als een knockout-vraag ambigu is: clarityScore flink verlagen (< 70) en een specifieke tip genereren die uitlegt WAAROM het ambigu is en HOE het concreter kan

### 3. Cognitieve belasting & Invultijd (avgTimeSeconds)
- Ja/nee knockout-vragen: 5-15 seconden
- Eenvoudige kwalificatievragen: 15-30 seconden
- Complexe/open kwalificatievragen: 30-60 seconden
- Zeer vage of moeilijke vragen: 45-90 seconden

### 4. Drop-off risico (dropOffRisk: "low" | "medium" | "high")
- Houd rekening met de POSITIE in het interview (latere vragen = hoger risico)
- Open vragen aan het einde versterken drop-off
- Onduidelijke vragen verhogen het risico
- Knockout-vragen met simpele ja/nee = laag risico
- "low": < 5% drop-off bij deze vraag
- "medium": 5-15% drop-off
- "high": > 15% drop-off

### 5. Completion rate per vraag (completionRate: 0-100)
- Dit is CUMULATIEF — het houdt rekening met eerdere drop-off
- Start bij 100% (of 200 kandidaten)
- Elke vraag kan een percentage kandidaten verliezen
- De completionRate van vraag N = completionRate van vraag N-1 * (1 - drop-off%)

### 6. Tips
- Genereer ALLEEN een tip als clarityScore < 85 OF dropOffRisk is "medium" of "high"
- Tips moeten in het Nederlands zijn
- Tips moeten specifiek en actionable zijn (verwijs naar de eigenlijke vraag)
- Maximaal 1-2 zinnen
- Als de vraag goed is: tip = null

## SAMENVATTING

### completionRate (overall)
- Het percentage van de 200 startende kandidaten dat het volledige interview zou afronden
- Gebaseerd op de cumulatieve drop-off

### avgTimeSeconds (overall)
- De totale geschatte invultijd voor het hele interview

### verdict
Bepaal het verdict op basis van deze regels:
- "excellent": ALLE vragen hebben clarityScore >= 85 EN completionRate >= 80%
- "good": Overall completionRate >= 50% EN maximaal 2 vragen met dropOffRisk "high"
- "needs_work": Overall completionRate >= 30% OF 3+ vragen met medium/high risico
- "poor": Overall completionRate < 30% OF meerderheid van vragen onduidelijk

### verdictHeadline
- Korte Nederlandse kop voor de UI banner
- Voorbeelden: "Dit interview is uitstekend opgebouwd", "Dit interview is goed opgebouwd", "Dit interview kan beter", "Dit interview heeft werk nodig"

### verdictDescription
- 1-2 zinnen in het Nederlands met actionable advies
- Verwijs naar specifieke probleemvragen als die er zijn

### oneLiner
- Eén enkele zin in het Nederlands die de kwaliteit samenvat
- Geschikt voor een Teams-notificatie of korte melding
- Beknopt maar informatief, bijv.: "Sterk interview met 6 heldere vragen, let op de open vraag over motivatie."
- Of bij problemen: "3 van de 5 knockout-vragen zijn te vaag geformuleerd — herformuleren aanbevolen."

## FUNNEL
- Begint ALTIJD bij 200 kandidaten
- Eerste stap is altijd {"step": "Start", "candidates": 200}
- Dan voor elke vraag op volgorde: {"step": "<question_id>", "candidates": <remaining>}
- Laatste stap: {"step": "Voltooid", "candidates": <final>}
- candidates moeten gehele getallen zijn

## OUTPUT FORMAAT
Antwoord ALLEEN met een JSON object in dit exacte formaat:

```json
{
  "summary": {
    "completionRate": 64,
    "avgTimeSeconds": 107,
    "verdict": "good",
    "verdictHeadline": "Dit interview is goed opgebouwd",
    "verdictDescription": "De knockout-vragen zijn helder...",
    "oneLiner": "Goed interview met heldere knockout-vragen, let op bij de open kwalificatievragen."
  },
  "questions": [
    {
      "questionId": "ko_1",
      "completionRate": 98,
      "avgTimeSeconds": 8,
      "dropOffRisk": "low",
      "clarityScore": 95,
      "tip": null
    }
  ],
  "funnel": [
    {"step": "Start", "candidates": 200},
    {"step": "ko_1", "candidates": 196},
    {"step": "Voltooid", "candidates": 128}
  ]
}
```

## BELANGRIJKE REGELS
1. Antwoord ALLEEN met JSON, geen andere tekst
2. Alle tekst (tips, verdict, headline, description, oneLiner) in het Nederlands
3. Wees realistisch maar constructief — niet te streng, niet te mild
4. De funnel start ALTIJD bij 200 kandidaten
5. completionRate per vraag is cumulatief
6. tip mag ALLEEN null zijn als de vraag goed genoeg is (clarityScore >= 85 EN dropOffRisk = "low")
7. Knockout-vragen met ambigue formulering MOETEN geflagd worden met lage clarityScore en specifieke tip
"""


# =============================================================================
# Agent and Runner Setup
# =============================================================================

generate_config = types.GenerateContentConfig(temperature=0)

interview_analysis_agent = Agent(
    name="interview_analysis",
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    description="Agent voor het analyseren van pre-screening interviewkwaliteit",
    generate_content_config=generate_config,
)

_session_service = InMemorySessionService()

_runner = Runner(
    agent=interview_analysis_agent,
    app_name="interview_analysis_app",
    session_service=_session_service,
)


# =============================================================================
# Helper Functions
# =============================================================================

def format_questions_for_analysis(questions: list[dict]) -> str:
    """Format questions list into a readable string for the agent prompt."""
    lines = ["## INTERVIEWVRAGEN (in volgorde)"]
    for i, q in enumerate(questions, 1):
        q_type = q.get("type", "qualifying")
        q_text = q.get("text", "")
        q_id = q.get("id", f"q{i}")
        lines.append(f"{i}. [{q_type.upper()}] (id: {q_id}) {q_text}")
    return "\n".join(lines)


def parse_agent_response(response_text: str) -> dict:
    """Parse JSON response from the agent, handling markdown code blocks."""
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
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

async def analyze_interview(
    questions: list[dict],
    vacancy_title: str,
    vacancy_description: str = "",
) -> dict:
    """
    Analyze interview questions and return structured analytics.

    Args:
        questions: List of dicts with id, text, type
        vacancy_title: Title of the vacancy
        vacancy_description: Full vacancy description for context

    Returns:
        Dict with summary, questions, and funnel data
    """
    formatted_questions = format_questions_for_analysis(questions)

    prompt_text = f"""Analyseer het volgende pre-screening interview voor de vacature "{vacancy_title}".

## VACATURE CONTEXT
Titel: {vacancy_title}
{f"Beschrijving: {vacancy_description}" if vacancy_description else ""}

{formatted_questions}

Geef je analyse als JSON."""

    logger.info(f"[INTERVIEW ANALYSIS] Starting — vacancy: {vacancy_title}, questions: {len(questions)}")

    session_id = f"interview_analysis_{uuid.uuid4().hex[:8]}"

    await _session_service.create_session(
        app_name="interview_analysis_app",
        user_id="system",
        session_id=session_id,
    )

    content = types.Content(
        role="user",
        parts=[types.Part(text=prompt_text)],
    )

    response_text = ""
    async for event in _runner.run_async(
        user_id="system",
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text

    logger.info("[INTERVIEW ANALYSIS] Agent response received")
    logger.debug(f"Raw response: {response_text[:500]}...")

    parsed = parse_agent_response(response_text)

    if not parsed:
        logger.error("[INTERVIEW ANALYSIS] Failed to parse agent response")
        return _fallback_response(questions)

    return parsed


def _fallback_response(questions: list[dict]) -> dict:
    """Return a safe fallback response if agent parsing fails."""
    return {
        "summary": {
            "completionRate": 0,
            "avgTimeSeconds": 0,
            "verdict": "poor",
            "verdictHeadline": "Analyse mislukt",
            "verdictDescription": "De analyse kon niet worden uitgevoerd. Probeer het opnieuw.",
            "oneLiner": "Analyse mislukt — probeer het opnieuw.",
        },
        "questions": [
            {
                "questionId": q.get("id", f"q{i}"),
                "completionRate": 0,
                "avgTimeSeconds": 0,
                "dropOffRisk": "medium",
                "clarityScore": 50,
                "tip": None,
            }
            for i, q in enumerate(questions, 1)
        ],
        "funnel": [
            {"step": "Start", "candidates": 200},
            {"step": "Voltooid", "candidates": 0},
        ],
    }
