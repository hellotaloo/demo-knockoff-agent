"""Recruiter Analyst Agent - Multi-agent orchestrator for recruitment insights."""

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from typing import Optional

from data_query_agent.agent import root_agent as data_query_agent
from recruiter_analyst.context import get_full_context, RECRUITMENT_BEST_PRACTICES


# ============================================================================
# Analyst Tools (in addition to sub-agent delegation)
# ============================================================================

async def get_recruitment_advice(
    tool_context: ToolContext,
    topic: str
) -> dict:
    """
    Get recruitment best practices and advice on a specific topic.
    
    Args:
        topic: The topic to get advice on. Options:
            - "completion_rate": How to improve interview completion rates
            - "qualification_rate": How to improve qualification rates  
            - "channel_optimization": Voice vs WhatsApp optimization
            - "candidate_prioritization": How to prioritize candidates
            - "vacancy_optimization": How to improve vacancy descriptions
            - "general": General recruitment best practices
    
    Returns:
        Dictionary with advice and recommendations
    """
    advice_map = {
        "completion_rate": {
            "topic": "Verbeteren van Completion Rate",
            "advice": [
                "Houd interviews kort: maximaal 5-7 vragen totaal",
                "Begin met een duidelijke introductie en verwachte duur",
                "Gebruik een vriendelijke, informele toon",
                "Stel knockout vragen eerst om tijd te besparen",
                "Vermijd lange, complexe vragen"
            ],
            "metrics_to_watch": ["completion_rate", "avg_interaction_seconds", "dropout_point"]
        },
        "qualification_rate": {
            "topic": "Verbeteren van Qualification Rate",
            "advice": [
                "Zorg voor duidelijke, realistische vacatureteksten",
                "Review knockout criteria regelmatig - zijn ze te streng?",
                "Balanceer strikte en flexibele criteria",
                "Analyseer op welke vragen kandidaten afvallen",
                "Overweeg alternatieve knockout criteria"
            ],
            "metrics_to_watch": ["qualification_rate", "knockout_pass_rate", "question_fail_distribution"]
        },
        "channel_optimization": {
            "topic": "Kanaal Optimalisatie",
            "advice": [
                "WhatsApp: Beter voor jongere doelgroep, flexibele timing",
                "Voice: Hogere engagement, directere interactie",
                "Analyseer completion rates per kanaal",
                "Test beide kanalen voor nieuwe vacatures",
                "Match kanaal met doelgroep verwachtingen"
            ],
            "recommendations": {
                "whatsapp": "Ideaal voor productie, retail, horeca",
                "voice": "Ideaal voor technische functies, management"
            }
        },
        "candidate_prioritization": {
            "topic": "Kandidaten Prioriteren",
            "advice": [
                "Prioriteit 1: Gekwalificeerd + korte interactietijd = efficiënt",
                "Prioriteit 2: Alle knockout vragen gepasseerd",
                "Prioriteit 3: Hoge scores op kwalificatievragen",
                "Check beschikbaarheid en starttermijn",
                "Overweeg kanaal preference voor follow-up"
            ],
            "scoring_factors": [
                "qualified (boolean)",
                "all_knockouts_passed (boolean)", 
                "interaction_seconds (lower is often better)",
                "qualification_question_scores"
            ]
        },
        "vacancy_optimization": {
            "topic": "Vacancy Optimalisatie",
            "advice": [
                "Gebruik specifieke, herkenbare functietitels",
                "Vermeld duidelijk locatie en bereikbaarheid",
                "Wees eerlijk over werkomstandigheden (ploegen, fysiek)",
                "Benadruk aantrekkelijke arbeidsvoorwaarden",
                "Voeg concrete voorbeelden van dagelijkse taken toe"
            ],
            "checklist": [
                "Titel is duidelijk en zoekbaar",
                "Locatie en reistijd vermeld",
                "Salaris of indicatie gegeven",
                "Werktijden/ploegen uitgelegd",
                "Fysieke eisen eerlijk beschreven"
            ]
        },
        "general": {
            "topic": "Algemene Recruitment Best Practices",
            "advice": [
                "Reageer snel op gekwalificeerde kandidaten",
                "Houd de candidate experience positief",
                "Gebruik data om continu te verbeteren",
                "Test en itereer op interview vragen",
                "Bouw een talent pool van niet-geplaatste kandidaten"
            ]
        }
    }
    
    if topic in advice_map:
        return advice_map[topic]
    else:
        return {
            "error": f"Onbekend topic: {topic}",
            "available_topics": list(advice_map.keys())
        }


# ============================================================================
# Agent Definition
# ============================================================================

# Get context for the system prompt
context = get_full_context()

instruction = f"""Je bent een senior recruitment analist voor Taloo. Je helpt recruiters met data-analyse, 
strategisch advies, en het optimaliseren van hun hiring proces.

## TAAL
Je antwoordt ALTIJD in het Nederlands (Vlaams nl-BE), ongeacht de taal van de vraag.

{context}

{RECRUITMENT_BEST_PRACTICES}

## JOUW ROLLEN

### 1. DATA ANALIST
Voor vragen over data (aantallen, statistieken, trends):
- Gebruik de data_analist om gegevens op te halen
- Interpreteer de resultaten in context
- Voeg relevante inzichten toe

### 2. STRATEGISCH ADVISEUR
Voor vragen over strategie en verbetering:
- Haal eerst relevante data op
- Combineer data met recruitment best practices
- Geef concrete, actionable adviezen

### 3. RECRUITMENT EXPERT
Voor vragen over best practices:
- Gebruik get_recruitment_advice voor advies
- Pas advies toe op de specifieke situatie
- Geef voorbeelden waar mogelijk

## WERKWIJZE

### Bij data vragen:
"Hoeveel sollicitaties vandaag?" → Haal de data op en geef een duidelijk antwoord

### Bij analyse vragen:
"Waarom is onze kwalificatieratio laag?"
1. Haal statistieken op
2. Analyseer de knockout vraag resultaten  
3. Vergelijk met benchmarks
4. Geef specifieke verbeterpunten

### Bij strategie vragen:
"Hoe kunnen we meer kandidaten aantrekken?"
1. Haal vacancy en application data op
2. Identificeer patronen (welke vacatures werken goed?)
3. Combineer met best practices
4. Geef prioritized actieplan

## BELANGRIJK - COMMUNICATIE
- Noem NOOIT technische namen zoals "data_analist" of "sub-agent" in je antwoorden aan de gebruiker
- Zeg gewoon "Ik heb de data opgehaald" of "Uit de analyse blijkt..."
- Focus op het antwoord, niet op het proces

### Bij kandidaat vragen:
"Wie moet ik als eerste bellen?"
1. Haal gekwalificeerde kandidaten op
2. Rank op basis van efficiency (korte interactie = besluitvaardig)
3. Check recente activiteit
4. Geef top 3-5 met korte motivatie

## RESPONSE STIJL

- **Wees direct**: Begin met het antwoord, dan de onderbouwing
- **Wees specifiek**: Noem concrete cijfers en percentages
- **Wees actionable**: Eindig met concrete volgende stappen
- **Wees positief**: Focus op verbetermogelijkheden, niet problemen

## VOORBEELDEN

**Vraag**: "Hoe presteert mijn team deze week?"
**Antwoord structuur**:
1. Samenvatting: "Deze week X sollicitaties, Y% gekwalificeerd"
2. Trend: "Dit is hoger/lager dan vorige week"
3. Inzicht: "WhatsApp presteert beter dan voice"
4. Advies: "Overweeg om meer via WhatsApp te werven"

**Vraag**: "Welke vacature moet ik prioriteren?"
**Antwoord structuur**:
1. Ranking: "Vacature A heeft de meeste potentieel"
2. Data: "15 sollicitaties, 80% kwalificatieratio"
3. Actie: "Focus op het contacteren van de 12 gekwalificeerde kandidaten"
"""

root_agent = Agent(
    name="recruiter_analyst",
    model="gemini-2.5-flash",
    instruction=instruction,
    description="Senior recruitment analist die helpt met data-analyse, strategie en optimalisatie",
    tools=[
        get_recruitment_advice,
    ],
    sub_agents=[
        data_query_agent,
    ],
)
