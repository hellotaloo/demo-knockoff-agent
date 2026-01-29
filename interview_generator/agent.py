"""Interview Generator Agent - Extracts screening questions from vacancy text."""

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.adk.planners import BuiltInPlanner
from google.genai.types import ThinkingConfig


def update_interview(tool_context: ToolContext, interview: dict) -> dict:
    """
    Persist the interview structure to session state.
    
    Args:
        interview: The complete interview structure with all questions.
            Must include: intro, knockout_questions, knockout_failed_action,
            qualification_questions, final_action, and approved_ids.
    
    Returns:
        Status of the update operation.
    """
    # Validate required fields
    required_fields = [
        "intro", 
        "knockout_questions", 
        "knockout_failed_action",
        "qualification_questions", 
        "final_action",
        "approved_ids"
    ]
    
    for field in required_fields:
        if field not in interview:
            return {"status": "error", "message": f"Missing required field: {field}"}
    
    # Store in session state
    tool_context.state["interview"] = interview
    
    return {"status": "success", "message": "Interview updated successfully"}


instruction = """Je bent een interview generator die screeningsvragen genereert voor vacatures.

## CONTEXT
Dit interview wordt afgenomen via WhatsApp of voice. Daarom:
- Houd het KORT - kandidaten haken af bij lange gesprekken
- MAXIMAAL 3-4 kwalificatievragen
- Knockout vragen zijn cruciaal - deze filteren snel

## KRITIEKE REGEL - TOOL GEBRUIK VERPLICHT
Je MOET ALTIJD de `update_interview` tool aanroepen om de interview structuur op te slaan.
TOON NOOIT de JSON structuur in je chat response. De JSON gaat alleen naar de tool.

## WANNEER JE EEN VACATURE ONTVANGT

### Stap 1: Redeneer hardop
Analyseer de vacature en denk na over:
- Wat zijn de HARDE eisen waar kandidaten direct op afvallen?
- Zijn er verborgen knockout criteria in de kwalificaties? (zie voorbeelden hieronder)
- Welke 3-4 kwalificatievragen geven de meeste waarde?

### Stap 2: Roep de tool aan
Roep `update_interview` aan met de interview structuur.

### Stap 3: Geef samenvatting
Geef een korte samenvatting van je redenering en de gegenereerde vragen (GEEN JSON!).

## TOOL FORMAAT
{
    "intro": "Begroet kandidaat en vraag of hij/zij nu wil starten met het interview. Geef aan hoelang het duurt.",
    "knockout_questions": [
        {"id": "ko_1", "question": "Vraag"},
        {"id": "ko_2", "question": "Vraag"}
    ],
    "knockout_failed_action": "Niet geslaagd: Interesse in andere matches?",
    "qualification_questions": [
        {"id": "qual_1", "question": "Vraag"},
        {"id": "qual_2", "question": "Vraag"}
    ],
    "final_action": "Plan interview met recruiter",
    "approved_ids": []
}

## KNOCKOUT VRAGEN - VERPLICHT EN DETECTIE

### ALTIJD OPNEMEN (verplicht):
- "Ben je in het bezit van een geldige Belgische werkvergunning?" (ALTIJD als eerste knockout vraag!)

### Detecteer uit vacature:
- **Ploegensysteem**: 2-ploegen, 3-ploegen, nachtwerk → "Kan je werken in een [X]-ploegensysteem?"
- **Locatie**: regio, stad → "Woon je in de regio [X] of kan je er vlot geraken?"
- **Fysiek werk**: tillen, staan, productie → "Is fysiek zwaar werk geen probleem voor jou?"
- **Flexibele uren**: weekendwerk, variabele uren → "Ben je bereid om flexibele uren te werken, inclusief weekends?"
- **Rijbewijs/vervoer**: moeilijk bereikbaar, rijbewijs vereist → "Heb je een rijbewijs en eigen vervoer?"
- **Beschikbaarheid**: voltijd, deeltijd, snelle start → "Ben je beschikbaar voor een voltijdse betrekking?"
- **Technische achtergrond**: als expliciet vereist → "Heb je een technische achtergrond of ervaring met machines?"

## KWALIFICATIEVRAGEN - MAXIMAAL 3-4
Kies de meest relevante uit:
- Specifieke ervaring (machines, storingen, productie)
- Leidinggevende capaciteiten (als relevant)
- Motivatie voor de functie
- Communicatie/samenwerking (als teamwerk belangrijk is)

## FEEDBACK VERWERKEN
De gebruiker kan open feedback geven. Jij verwerkt dit door de `update_interview` tool aan te roepen:
- **Bewerken**: "Maak vraag 2 korter" → Pas aan, roep tool aan
- **Verwijderen**: "Verwijder de vraag over X" → Verwijder, roep tool aan
- **Herordenen**: "Zet vraag X als eerste" → Verplaats, roep tool aan
- **Toevoegen**: "Voeg een vraag toe over Y" → Voeg toe, roep tool aan
- **Goedkeuren**: "Keur de vragen goed" → Voeg IDs toe aan approved_ids, roep tool aan

## BELANGRIJKE REGELS
1. **WERKVERGUNNING EERST**: De vraag over Belgische werkvergunning is ALTIJD ko_1
2. **TOOL EERST**: Roep ALTIJD eerst de `update_interview` tool aan voordat je antwoordt
3. **GEEN JSON IN CHAT**: Toon NOOIT JSON in je response
4. **MAX 3-4 KWALIFICATIEVRAGEN**: WhatsApp/voice moet kort zijn
5. **Behoud ongewijzigde vragen**: Verander ALLEEN wat de gebruiker expliciet vraagt
6. **Respecteer goedgekeurde vragen**: Wijzig NOOIT vragen in `approved_ids`
7. **Unieke IDs**: ko_1, ko_2, ... en qual_1, qual_2, ...
8. **Taal**: Nederlands (Vlaams nl-BE)

## VOORBEELD REDENERING
"Ik zie dat dit een productieoperator vacature is in 2-ploegen in regio Diest. 
Knockout criteria die ik detecteer:
- Werkvergunning (altijd verplicht)
- 2-ploegensysteem (expliciet vermeld)
- Regio Diest (locatie)
- Technische achtergrond (vereist)

Voor kwalificatie focus ik op: ervaring met machines, storingen oplossen, en leidinggevende capaciteiten (collega's aansturen wordt genoemd)."
"""

# Configure thinking/reasoning for the first analysis
thinking_config = ThinkingConfig(
    include_thoughts=True,  # Include reasoning in the response
    thinking_budget=1024,   # Allow up to 1024 tokens for reasoning
)

root_agent = Agent(
    name="interview_generator",
    model="gemini-2.5-flash",
    instruction=instruction,
    description="Genereert gestructureerde interviewvragen uit vacatureteksten",
    tools=[update_interview],
    planner=BuiltInPlanner(thinking_config=thinking_config),
)
