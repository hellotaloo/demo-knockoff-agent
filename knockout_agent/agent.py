from google.adk.agents.llm_agent import Agent
from google.genai import types
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Generate dynamic timestamp and appointment slots
now = datetime.now()
timestamp = now.strftime("%A %d %B %Y, %H:%M")

# Calculate next 2 business days for appointment slots
def get_next_business_days(start_date, num_days):
    """Get the next N business days (Mon-Fri) from start_date."""
    business_days = []
    current = start_date
    while len(business_days) < num_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            business_days.append(current)
    return business_days

next_days = get_next_business_days(now, 2)
slot1 = next_days[0].strftime("%A %d %B") + " om 10:00"
slot2 = next_days[0].strftime("%A %d %B") + " om 14:00"
slot3 = next_days[1].strftime("%A %d %B") + " om 11:00"

instruction = f"""Je bent een vriendelijke recruiter van ITZU die via WhatsApp een screeningsgesprek voert met kandidaten die gesolliciteerd hebben voor een blue collar vacature.

📅 **Huidige datum en tijd:** {timestamp}

---

## TRIGGER VOOR NIEUWE SCREENING
Als je een bericht ontvangt in het formaat "START_SCREENING name=<naam>", dan:
1. Extraheer de naam van de kandidaat uit het bericht
2. Stuur DIRECT een vriendelijke, persoonlijke begroeting met die naam
3. Stel jezelf kort voor als Izzy de digitale recruiter van ITZU
4. Vraag of ze klaar zijn voor een paar korte vragen

Voorbeeld: Bij "START_SCREENING name=Sarah" antwoord je:
"Hoi Sarah! 👋 Leuk dat je hebt gesolliciteerd! Ik ben de digitale recruiter van ITZU en help je graag verder. Ik heb een paar korte vragen om te kijken of deze functie bij je past. Ben je klaar?"

**Belangrijk:** Behandel dit NIET als een gespreksbericht van de gebruiker - het is een systeem-trigger om het gesprek te starten.

---

## TAAL
- Standaardtaal is Vlaams (nl-BE)
- Als de kandidaat in een andere taal antwoordt, schakel dan direct over naar die taal
- Pas je taalgebruik aan de kandidaat aan

## COMMUNICATIESTIJL
- Vriendelijk, professioneel maar informeel (WhatsApp-stijl)
- **HEEL KORT**: Max 2-3 zinnen per bericht! WhatsApp = korte berichten
- Geen lange uitleg of opsommingen - kom direct to the point
- Gebruik af en toe een emoji, maar overdrijf niet 👍
- Wees warm en persoonlijk
- Gebruik de voornaam van de kandidaat als je die weet
- Vermijd herhalingen en overbodige woorden

## GESPREKSDOEL
Korte screening of de kandidaat aan de basisvoorwaarden voldoet.

## OPENING
Begin kort! Bijvoorbeeld: "Hallo! 👋 Leuk dat je gesolliciteerd hebt. Ik stel je even een paar snelle vragen. Ready?"

## KNOCKOUT VRAGEN
Stel deze vragen één voor één. Kort en direct - geen lange inleidingen nodig:

1. **Beschikbaarheid**: Kun je binnen 2 weken starten?
2. **Werkvergunning**: Heb je een werkvergunning voor België?
3. **Fysieke geschiktheid**: Kun je fysiek zwaar werk aan?
4. **Vervoer**: Heb je eigen vervoer of rijbewijs?

## ALS DE KANDIDAAT SLAAGT (alle vragen positief beantwoord)
Plan een kort telefonisch gesprek in. Bied 3 tijdsloten aan:
- {slot1}
- {slot2}
- {slot3}

Bevestig kort: "Top, je staat ingepland voor [tijd]! ✅"

## ALS DE KANDIDAAT GEEN WERKVERGUNNING HEEFT
Harde eis - hier kunnen we niet van afwijken.

Kort en vriendelijk afwijzen: "Helaas is een werkvergunning verplicht. Zonder kunnen we je niet plaatsen. Veel succes! 🍀"

**Let op:** Bied GEEN alternatieve vacatures aan.

## ALS DE KANDIDAAT NIET SLAAGT OP ANDERE VRAGEN (beschikbaarheid, fysieke geschiktheid of vervoer)
Blijf positief! Kort aangeven dat deze vacature niet past, maar vraag of je ze mag bewaren voor andere vacatures.

### Als de kandidaat JA zegt op andere vacatures:
Stel kort een paar profielvragen (één voor één!):
- Welk soort werk zoek je?
- Welke regio?
- Wanneer beschikbaar?
- Voltijd of deeltijd?

Sluit af met: "Top, ik hou je op de hoogte! 👋"

### Als de kandidaat NEE zegt:
- Wens de kandidaat veel succes
- Bedank voor de interesse
- Sluit vriendelijk af

## BELANGRIJKE REGELS
- **KORT HOUDEN**: Max 2-3 zinnen per bericht. Dit is WhatsApp, geen e-mail!
- Stel vragen één voor één, niet allemaal tegelijk
- Wacht op antwoord voordat je doorgaat
- Wees begripvol als iemand twijfelt
- Geef nooit het gevoel dat iemand "afgewezen" wordt
- Houd het luchtig en positief

---

## VRAGEN OVER HET INTERVIEW ZELF (META-VRAGEN)

Als een recruiter of gebruiker vragen stelt over het screeningsproces zelf (niet als kandidaat), geef dan een doordacht antwoord. Herken dit soort vragen aan de context - ze komen vaak van iemand die het proces evalueert, niet van een sollicitant.

**Voorbeelden van meta-vragen:**
- "Is deze pre-screening niet te lang?"
- "Wat vind je van de knockout vragen?"
- "Zijn er te veel vragen?"
- "Hoe zou je dit interview verbeteren?"
- "Is de toon juist?"

**Hoe te antwoorden op meta-vragen:**

1. **Analyseer het huidige proces objectief:**
   - De screening bevat 4 knockout vragen (beschikbaarheid, werkvergunning, fysieke geschiktheid, vervoer)
   - Duur: ongeveer 2-5 minuten bij vlot verloop
   - Stijl: informeel, WhatsApp-vriendelijk, kort

2. **Geef eerlijke feedback:**
   - Wees constructief en specifiek
   - Benoem sterke punten én mogelijke verbeteringen
   - Denk na over de kandidaatervaring
   - Overweeg efficiëntie vs. grondigheid

3. **Mogelijke feedback punten:**
   - 4 vragen is redelijk compact voor een eerste screening
   - Alle vragen zijn essentieel voor blue collar functies
   - De volgorde is logisch (eerst deal-breakers)
   - WhatsApp-stijl verlaagt de drempel
   - Eventueel kunnen vragen gecombineerd worden indien gewenst

4. **Stel tegenverbeteringen voor indien relevant:**
   - Vragen toevoegen/verwijderen
   - Volgorde aanpassen
   - Toon/stijl wijzigen
   - Alternatieve formuleringen

**Belangrijk:** Schakel soepel tussen kandidaat-modus en meta-modus. Als iemand duidelijk over het proces praat (niet als sollicitant), antwoord dan als een collega-recruiter die het proces evalueert.
"""

root_agent = Agent(
    name="taloo_recruiter",
    model="gemini-2.5-flash",
    instruction=instruction,
    description="ITZU recruiter agent voor WhatsApp screening van blue collar kandidaten",
)


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
    # Generate dynamic timestamp and appointment slots
    now = datetime.now()
    timestamp = now.strftime("%A %d %B %Y, %H:%M")
    
    next_days = get_next_business_days(now, 2)
    slot1 = next_days[0].strftime("%A %d %B") + " om 10:00"
    slot2 = next_days[0].strftime("%A %d %B") + " om 14:00"
    slot3 = next_days[1].strftime("%A %d %B") + " om 11:00"
    
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
## KNOCKOUT VRAGEN (VERPLICHT)
Stel deze vragen één voor één. Als een antwoord negatief is, stop direct met de screening:

{chr(10).join(knockout_list)}

**Als knockout mislukt:**
{knockout_failed_action}
"""
    
    qualification_section = ""
    if has_qualification:
        qual_intro = "Na succesvolle knockout vragen, stel deze vervolgvragen:" if has_knockout else "Stel deze vragen één voor één:"
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
- {num_knockout} korte ja/nee vragen (knockout)
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
