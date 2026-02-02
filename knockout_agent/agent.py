from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool
from google.genai import types
from datetime import datetime, timedelta
from typing import Optional
import logging
import re

logger = logging.getLogger(__name__)


# =============================================================================
# Conversation Completion Detection
# =============================================================================

# Tool function for agent to signal conversation completion
def conversation_complete(outcome: str) -> str:
    """
    Roep dit aan wanneer het gesprek afgerond is, net voordat je afscheid neemt.
    
    Args:
        outcome: Korte beschrijving van de uitkomst. Voorbeelden:
                 - "interview ingepland voor maandag 10:00"
                 - "geen match voor deze vacature"
                 - "info verzameld voor andere vacatures"
                 - "kandidaat niet beschikbaar"
    
    Returns:
        str: Bevestiging dat het gesprek is afgerond
    """
    logger.info(f"🏁 CONVERSATION COMPLETE: {outcome}")
    return f"Gesprek afgerond: {outcome}"


# Create the tool for the agent
conversation_complete_tool = FunctionTool(func=conversation_complete)


# Fallback: Closing pattern detection
CLOSING_PATTERNS = [
    r"bedankt voor (je|uw) (tijd|gesprek|interesse|antwoorden)",
    r"tot (ziens|snel|gauw|dan)",
    r"fijne dag",
    r"prettige dag",
    r"je hoort (nog )?van ons",
    r"we nemen contact",
    r"succes (verder|ermee)",
    r"veel succes",
    r"ik wens je",
    # Interview scheduled patterns
    r"je staat ingepland",
    r"je bent ingepland",
    r"afspraak.*(gepland|bevestigd|ingepland)",
    r"gesprek.*(gepland|bevestigd|ingepland)",
]


def is_closing_message(message: str) -> bool:
    """
    Check if an agent message is a closing/goodbye message.
    
    Args:
        message: The agent's response message
        
    Returns:
        bool: True if the message appears to be a closing message
    """
    # TEMPORARILY DISABLED - Testing tool function only
    return False
    # message_lower = message.lower()
    # return any(re.search(pattern, message_lower) for pattern in CLOSING_PATTERNS)


def clean_response_text(message: str) -> str:
    """
    Remove any accidental tool call text from agent responses.
    
    Sometimes the model includes the function call syntax in its response text.
    This strips that out before sending to the user.
    
    Args:
        message: The agent's response message
        
    Returns:
        str: Cleaned message without tool call syntax
    """
    # Remove conversation_complete(...) calls from the text
    cleaned = re.sub(
        r'conversation_complete\s*\([^)]*\)\s*',
        '',
        message,
        flags=re.IGNORECASE
    )
    # Clean up any resulting double newlines or leading/trailing whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

# =============================================================================
# Helper Functions
# =============================================================================

# Dutch day and month names for proper Dutch date formatting
DUTCH_DAYS = {
    0: "maandag",
    1: "dinsdag",
    2: "woensdag",
    3: "donderdag",
    4: "vrijdag",
    5: "zaterdag",
    6: "zondag"
}

DUTCH_MONTHS = {
    1: "januari",
    2: "februari",
    3: "maart",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "augustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "december"
}


def get_dutch_date(date, include_time=False):
    """Format a date in Dutch (e.g., 'maandag 2 februari 2026')."""
    day_name = DUTCH_DAYS[date.weekday()]
    month_name = DUTCH_MONTHS[date.month]
    if include_time:
        return f"{day_name} {date.day} {month_name} {date.year}, {date.strftime('%H:%M')}"
    return f"{day_name} {date.day} {month_name}"


def get_next_business_days(start_date, num_days):
    """Get the next N business days (Mon-Fri) from start_date."""
    business_days = []
    current = start_date
    while len(business_days) < num_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            business_days.append(current)
    return business_days


# =============================================================================
# Dynamic Vacancy-Specific Agent Creation
# =============================================================================

# Registry for vacancy-specific agents (vacancy_id -> Agent)
_vacancy_agents: dict[str, Agent] = {}


def build_screening_instruction(config: dict, vacancy_title: str = None, channel: str = "chat") -> str:
    """
    Build a dynamic screening instruction from pre-screening configuration.
    
    This is the unified instruction builder used by both chat widget and WhatsApp.
    
    Args:
        config: Dictionary containing:
            - intro: Introduction message
            - knockout_questions: List of knockout questions
            - knockout_failed_action: Message when knockout fails
            - qualification_questions: List of qualification questions
            - final_action: Final success message
        vacancy_title: Optional vacancy title to display
        channel: "chat" or "whatsapp" - only affects minor wording
    
    Returns:
        str: Complete screening instruction in Dutch
    """
    # Generate dynamic timestamp and appointment slots (in Dutch)
    now = datetime.now()
    timestamp = get_dutch_date(now, include_time=True)
    
    next_days = get_next_business_days(now, 2)
    slot1 = get_dutch_date(next_days[0]) + " om 10:00"
    slot2 = get_dutch_date(next_days[0]) + " om 14:00"
    slot3 = get_dutch_date(next_days[1]) + " om 11:00"
    
    intro = config.get("intro", "Hallo! Ik zou je graag enkele vragen stellen.")
    knockout_questions = config.get("knockout_questions", [])
    knockout_failed_action = config.get("knockout_failed_action", "Helaas lijkt deze functie niet bij je te passen. Veel succes!")
    qualification_questions = config.get("qualification_questions", [])
    final_action = config.get("final_action", "Geweldig! Je profiel past goed bij wat we zoeken.")
    
    # Calculate estimated interview duration
    num_knockout = len(knockout_questions)
    num_qualification = len(qualification_questions)
    has_knockout = num_knockout > 0
    has_qualification = num_qualification > 0
    
    # Knockout questions: ~10 sec (quick yes/no)
    # Qualification questions: ~25 sec (short answers expected)
    # Overhead: ~60 sec for intro + closing
    knockout_time = num_knockout * 10
    qualification_time = num_qualification * 25
    overhead = 60
    total_seconds = knockout_time + qualification_time + overhead
    estimated_minutes = max(1, round(total_seconds / 60))
    
    # Build knockout questions list (use question_text, fallback to question for backward compat)
    knockout_list = []
    for i, q in enumerate(knockout_questions, 1):
        text = q.get("question_text") or q.get("question", "")
        knockout_list.append(f"{i}. {text}")
    
    # Build qualification questions list
    qual_list = []
    for i, q in enumerate(qualification_questions, 1):
        text = q.get("question_text") or q.get("question", "")
        qual_list.append(f"{i}. {text}")
    
    # Channel-specific wording
    channel_style = "WhatsApp-stijl" if channel == "whatsapp" else "chat-stijl"
    channel_note = "WhatsApp = korte berichten" if channel == "whatsapp" else ""
    
    # Vacancy title header (if provided)
    vacancy_header = f"\n📋 **Vacature:** {vacancy_title}" if vacancy_title else ""
    
    # Build conditional sections
    knockout_section = ""
    if has_knockout:
        knockout_section = f"""
## PRAKTISCHE CHECK (VERPLICHT)
Stel deze korte checkvragen één voor één. Als een antwoord negatief is, ga naar de "ALTERNATIEVE VACATURES" sectie:

{chr(10).join(knockout_list)}

## ALS DE PRAKTISCHE CHECK NIET PAST - ALTERNATIEVE VACATURES
Als de kandidaat niet aan de basisvereisten voldoet voor deze functie:

1. **Empathisch reageren**: Leg kort uit dat deze specifieke functie helaas niet matcht
2. **Vraag naar interesse**: "Zou je interesse hebben in andere vacatures bij ons?"

**Als JA → stel deze 3 vragen (één voor één):**
1. "Wat voor soort werk doe je het liefst?" (bijv. productie, logistiek, administratie, technisch...)
2. "Heb je specifieke diploma's, certificaten of vaardigheden?" (bijv. rijbewijs, VCA, heftruckcertificaat...)
3. "Vanaf wanneer ben je beschikbaar en hoeveel uren per week zou je willen werken?"

Na deze vragen:
- Bedank de kandidaat en zeg dat een recruiter contact opneemt als er een passende vacature is
- Roep `conversation_complete("info verzameld voor andere vacatures")` aan

**Als NEE → vriendelijk afsluiten:**
"Geen probleem! Bedankt voor je tijd en interesse. Veel succes met je zoektocht! 🍀"
- Roep `conversation_complete("geen match, geen interesse in andere vacatures")` aan
"""
    
    qualification_section = ""
    if has_qualification:
        qual_intro = "Na de praktische check, stel deze vervolgvragen:" if has_knockout else "Stel deze vragen één voor één:"
        qualification_section = f"""
## KWALIFICATIEVRAGEN
{qual_intro}

{chr(10).join(qual_list)}
"""
    
    # Determine success condition
    if has_knockout or has_qualification:
        success_condition = "alle vragen positief beantwoord"
    else:
        success_condition = "het gesprek goed verlopen is"
    
    instruction = f"""Je bent een vriendelijke digitale recruiter van ITZU die via {channel} een screeningsgesprek voert met kandidaten.

📅 **Huidige datum en tijd:** {timestamp}{vacancy_header}

---

## TRIGGER VOOR NIEUWE SCREENING
Als je een bericht ontvangt in het formaat "START_SCREENING name=<naam>", dan:
1. Extraheer de naam van de kandidaat uit het bericht
2. Stuur DIRECT een vriendelijke, persoonlijke begroeting met die naam
3. Gebruik deze intro als basis (pas aan naar jouw stijl):
   "{intro}"

**Belangrijk:** Behandel dit NIET als een gespreksbericht van de gebruiker - het is een systeem-trigger om het gesprek te starten.

---

## TAAL
- Standaardtaal is Vlaams (nl-BE)
- Als de kandidaat in een andere taal antwoordt, schakel dan direct over naar die taal
- Pas je taalgebruik aan de kandidaat aan

## COMMUNICATIESTIJL
- Vriendelijk, professioneel maar informeel ({channel_style})
- **HEEL KORT**: Max 2-3 zinnen per bericht! {channel_note}
- Geen lange uitleg of opsommingen - kom direct to the point
- Gebruik af en toe een emoji, maar overdrijf niet 👍
- Wees warm en persoonlijk
- Gebruik de voornaam van de kandidaat als je die weet

## GESPREKSDOEL
Korte screening of de kandidaat aan de basisvoorwaarden voldoet.

## INTERVIEW DUUR
Dit interview duurt ongeveer {estimated_minutes} {"minuut" if estimated_minutes == 1 else "minuten"}.
- {num_knockout} korte praktische checks
- {num_qualification} kwalificatievragen (korte antwoorden verwacht)

## OPENING FORMAAT
Gebruik EXACT dit formaat voor je opening (met lege regels ertussen):

Hey [naam]! 👋
Super leuk dat je solliciteert voor de functie van [vacature]!

Ik heb een paar korte vragen voor je. Dit duurt ongeveer [X] minuten.

Als alles matcht, plannen we direct een gesprek in met de recruiter! 🙌

Ben je klaar om te beginnen?
{knockout_section}{qualification_section}
## ALS DE KANDIDAAT SLAAGT ({success_condition})
{final_action}

## BIJ SUCCES - GESPREK INPLANNEN
Als de kandidaat alle vragen positief beantwoordt:
1. Zeg direct dat ze een goede match lijken en je graag een gesprek met de recruiter wilt inplannen
2. Bied deze 3 tijdsloten aan:
   - {slot1}
   - {slot2}
   - {slot3}
3. Vraag welk tijdslot het beste past
4. Bevestig kort: "Top, je staat ingepland voor [tijd]! ✅"

Voorbeeld: "Je bent precies wat we zoeken! Laten we een gesprek inplannen met de recruiter. Welk tijdslot past jou?"

## BELANGRIJKE REGELS
- **KORT HOUDEN**: Max 2-3 zinnen per bericht
- Stel vragen één voor één, niet allemaal tegelijk
- Wacht op antwoord voordat je doorgaat
- Wees begripvol als iemand twijfelt
- Geef nooit het gevoel dat iemand "afgewezen" wordt
- **BELANGRIJK**: Verzin GEEN extra vragen. Stel ALLEEN de vragen die hierboven zijn gedefinieerd
- Houd het luchtig en positief

## GESPREK AFSLUITEN
Wanneer het gesprek ten einde is (interview ingepland, geen match, of kandidaat stopt):
1. Roep EERST de `conversation_complete` functie aan (dit is een achtergrond-actie, NIET zichtbaar voor de kandidaat)
2. Stuur daarna je normale afscheidsgroet

**BELANGRIJK:** Toon de functie-aanroep NOOIT in je bericht aan de kandidaat. 
De kandidaat ziet alleen je vriendelijke afscheidsbericht, niet de technische functie.

Voorbeeld van correcte uitvoering:
- Intern: conversation_complete("interview ingepland voor dinsdag 10:00")
- Bericht aan kandidaat: "Top! Je staat ingepland voor dinsdag om 10:00. ✅ Tot snel!"
"""
    
    return instruction


# Backward-compatible alias for WhatsApp
def build_whatsapp_instruction(config: dict) -> str:
    """Alias for build_screening_instruction with channel='whatsapp'."""
    return build_screening_instruction(config, channel="whatsapp")


def create_vacancy_whatsapp_agent(vacancy_id: str, config: dict) -> str:
    """
    Create an ADK agent with vacancy-specific questions for WhatsApp screening.
    
    Args:
        vacancy_id: The vacancy UUID
        config: Pre-screening configuration containing questions and messages
        
    Returns:
        str: The vacancy_id (used as agent identifier)
    """
    instruction = build_whatsapp_instruction(config)
    
    # Log the interview configuration transcript
    logger.info("=" * 60)
    logger.info(f"📋 SCREENING AGENT CREATED: whatsapp_{vacancy_id[:8]}")
    logger.info("=" * 60)
    logger.info("INTERVIEW CONFIGURATION:")
    logger.info("-" * 40)
    logger.info(f"Intro: {config.get('intro', 'N/A')}")
    logger.info("-" * 40)
    logger.info("KNOCKOUT QUESTIONS:")
    for i, q in enumerate(config.get('knockout_questions', []), 1):
        question_text = q.get("question") or q.get("question_text", "")
        logger.info(f"  {i}. {question_text}")
    logger.info("-" * 40)
    logger.info(f"Knockout Failed Action: {config.get('knockout_failed_action', 'N/A')}")
    logger.info("-" * 40)
    logger.info("QUALIFICATION QUESTIONS:")
    for i, q in enumerate(config.get('qualification_questions', []), 1):
        question_text = q.get("question") or q.get("question_text", "")
        logger.info(f"  {i}. {question_text}")
    logger.info("-" * 40)
    logger.info(f"Final Action: {config.get('final_action', 'N/A')}")
    logger.info("=" * 60)
    logger.info("FULL SYSTEM PROMPT:")
    logger.info("=" * 60)
    for line in instruction.split('\n'):
        logger.info(line)
    logger.info("=" * 60)
    
    agent = Agent(
        name=f"whatsapp_{vacancy_id[:8]}",
        model="gemini-2.5-flash",
        instruction=instruction,
        description=f"WhatsApp screening agent for vacancy {vacancy_id[:8]}",
        tools=[conversation_complete_tool],
    )
    
    _vacancy_agents[vacancy_id] = agent
    logger.info(f"✅ Agent ready: whatsapp_{vacancy_id[:8]}")
    
    return vacancy_id


def get_vacancy_whatsapp_agent(vacancy_id: str) -> Optional[Agent]:
    """Get the Agent instance for a vacancy, or None if not created."""
    return _vacancy_agents.get(vacancy_id)


def clear_vacancy_whatsapp_agent(vacancy_id: Optional[str] = None):
    """Clear vacancy agent registry. If vacancy_id provided, only clear that one."""
    global _vacancy_agents
    if vacancy_id:
        _vacancy_agents.pop(vacancy_id, None)
        logger.info(f"Cleared vacancy WhatsApp agent for {vacancy_id}")
    else:
        _vacancy_agents = {}
        logger.info("Cleared all vacancy WhatsApp agents")
