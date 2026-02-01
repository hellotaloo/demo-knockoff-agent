"""
ElevenLabs Voice Agent for outbound phone call screenings.

This module provides functionality to:
1. Create/update ElevenLabs conversational AI agents with dynamic interview scripts
2. Initiate outbound phone calls via Twilio integration
"""

import os
import logging
from typing import Optional
from elevenlabs import ElevenLabs

logger = logging.getLogger(__name__)


# =============================================================================
# ElevenLabs Client
# =============================================================================

_client: Optional[ElevenLabs] = None


def get_elevenlabs_client() -> ElevenLabs:
    """
    Get or create the ElevenLabs client.
    
    Returns:
        ElevenLabs: The ElevenLabs client instance.
        
    Raises:
        RuntimeError: If ELEVENLABS_API_KEY is not set.
    """
    global _client
    
    if _client is None:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY environment variable is required")
        
        _client = ElevenLabs(api_key=api_key)
        logger.info("Created ElevenLabs client")
    
    return _client


# =============================================================================
# Dynamic Vacancy-Specific Agent Creation
# =============================================================================

def build_voice_prompt(config: dict, vacancy_title: str = None) -> str:
    """
    Build a dynamic Dutch voice interview script from pre-screening configuration.
    
    Uses explicit STAP (step) format with flow control to ensure the LLM follows
    all steps in order, including qualification questions.
    
    Args:
        config: Dictionary containing:
            - intro: Introduction message
            - knockout_questions: List of knockout questions
            - knockout_failed_action: Message when knockout fails
            - qualification_questions: List of qualification questions
            - final_action: Final success message
        vacancy_title: Optional vacancy title to mention
    
    Returns:
        str: Complete voice interview script in Dutch with explicit step flow
    """
    from datetime import datetime, timedelta
    
    # Dutch day names for voice (more natural to speak)
    DUTCH_DAYS = {
        0: "maandag",
        1: "dinsdag", 
        2: "woensdag",
        3: "donderdag",
        4: "vrijdag",
        5: "zaterdag",
        6: "zondag"
    }
    
    def get_dutch_day(date):
        """Get Dutch day name for a date."""
        return DUTCH_DAYS[date.weekday()]
    
    # Generate dynamic timestamp
    now = datetime.now()
    timestamp = f"{get_dutch_day(now)} {now.strftime('%d %B %Y, %H:%M')}"
    
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
    # Use Dutch day names only (more natural for voice)
    slot1 = get_dutch_day(next_days[0]) + " om 10 uur"
    slot2 = get_dutch_day(next_days[0]) + " om 14 uur"
    slot3 = get_dutch_day(next_days[1]) + " om 11 uur"
    
    # Extract config values with defaults
    knockout_questions = config.get("knockout_questions", [])
    knockout_failed_action = config.get("knockout_failed_action", "Helaas lijkt deze functie niet bij je te passen. Veel succes!")
    qualification_questions = config.get("qualification_questions", [])
    final_action = config.get("final_action", "Geweldig! Je profiel past goed bij wat we zoeken.")
    
    # Calculate estimated interview duration
    num_knockout = len(knockout_questions)
    num_qualification = len(qualification_questions)
    
    # Knockout questions: ~10 sec (quick yes/no)
    # Qualification questions: ~25 sec (short answers expected)
    # Overhead: ~60 sec for intro + closing + scheduling
    knockout_time = num_knockout * 10
    qualification_time = num_qualification * 25
    overhead = 60
    total_seconds = knockout_time + qualification_time + overhead
    estimated_minutes = max(1, round(total_seconds / 60))
    
    # Vacancy title header
    vacancy_header = f"\nVacature: {vacancy_title}" if vacancy_title else ""
    
    # Build step-by-step script with explicit flow control
    # Step numbering:
    # STAP 1: Opening (wacht op antwoord)
    # STAP 2 to 2+num_knockout-1: Knockout questions
    # STAP 2+num_knockout to 2+num_knockout+num_qualification-1: Qualification questions
    # STAP NIET-GESLAAGD: Failure path
    # STAP INTERVIEW PLANNEN: Schedule interview
    # STAP AFSLUITING: Close conversation
    
    current_step = 1
    steps = []
    
    # =========================================================================
    # STAP 1: Opening
    # =========================================================================
    first_question_step = 2 if num_knockout > 0 else (2 if num_qualification > 0 else "INTERVIEW PLANNEN")
    
    steps.append(f"""=== STAP {current_step}: WACHT OP ANTWOORD ===
Dit is een uitgaand gesprek. Wacht tot de kandidaat opneemt en iets zegt zoals "Hallo".
Stel jezelf dan voor: "Hallo! Met Izy, de digitale assistent van ITZU. Ik bel je over je sollicitatie. Het duurt maar {estimated_minutes} {"minuutje" if estimated_minutes == 1 else "minuutjes"}. Past dat nu?"
- Als NEE: Vraag wanneer je kunt terugbellen en sluit af.
- Als JA: Ga naar STAP {first_question_step}.""")
    
    current_step += 1
    
    # =========================================================================
    # Knockout question steps
    # =========================================================================
    knockout_start_step = current_step
    
    for i, q in enumerate(knockout_questions):
        question_text = q.get("question_text") or q.get("question", "")
        is_last_knockout = (i == num_knockout - 1)
        
        if is_last_knockout:
            # Last knockout: go to first qualification or interview planning
            if num_qualification > 0:
                next_step = current_step + 1
                next_step_desc = f"STAP {next_step}"
            else:
                next_step_desc = "STAP INTERVIEW PLANNEN"
        else:
            next_step = current_step + 1
            next_step_desc = f"STAP {next_step}"
        
        steps.append(f"""=== STAP {current_step}: KNOCKOUT VRAAG {i + 1} ===
Vraag: "{question_text}"
- Als NEE: Ga naar STAP NIET-GESLAAGD.
- Als JA: Ga naar {next_step_desc}.""")
        
        current_step += 1
    
    # =========================================================================
    # Qualification question steps
    # =========================================================================
    qualification_start_step = current_step
    
    if num_qualification > 0 and num_knockout > 0:
        # Add transition to qualification questions
        steps.append(f"""=== STAP {current_step}: START KWALIFICATIEVRAGEN ===
Zeg: "Top! Dan ga ik je nu een paar vragen stellen over je ervaring."
Ga direct naar STAP {current_step + 1}.""")
        current_step += 1
    
    for i, q in enumerate(qualification_questions):
        question_text = q.get("question_text") or q.get("question", "")
        is_last_qual = (i == num_qualification - 1)
        
        if is_last_qual:
            next_step_desc = "STAP INTERVIEW PLANNEN"
        else:
            next_step = current_step + 1
            next_step_desc = f"STAP {next_step}"
        
        steps.append(f"""=== STAP {current_step}: KWALIFICATIEVRAAG {i + 1} ===
Vraag: "{question_text}"
Wacht op antwoord, ga dan naar {next_step_desc}.""")
        
        current_step += 1
    
    # =========================================================================
    # STAP NIET-GESLAAGD: Failure path
    # =========================================================================
    steps.append(f"""=== STAP NIET-GESLAAGD ===
Zeg: "Ik begrijp het. {knockout_failed_action}"
Vraag: "Zou je interesse hebben in andere vacatures die beter bij jouw situatie passen?"
- Als JA: Zeg "Super! Dan neemt een collega contact op om te kijken wat er mogelijk is. Bedankt voor je tijd!"
- Als NEE: Zeg "Geen probleem! Bedankt voor je tijd en veel succes!"
BEËINDIG HET GESPREK.""")
    
    # =========================================================================
    # STAP INTERVIEW PLANNEN: Schedule interview
    # =========================================================================
    steps.append(f"""=== STAP INTERVIEW PLANNEN ===
Zeg: "Dat klinkt allemaal goed. Ik plan graag direct een gesprek in met de recruiter."
Zeg: "Ik heb drie mogelijkheden: {slot1}, {slot2}, of {slot3}. Welke past het beste?"
Wacht op keuze. Bevestig: "Perfect, ik heb je ingepland voor [gekozen moment]. Je krijgt een bevestiging per SMS."
Ga naar STAP AFSLUITING.""")
    
    # =========================================================================
    # STAP AFSLUITING: Close conversation
    # =========================================================================
    steps.append("""=== STAP AFSLUITING ===
Zeg: "Heel fijn! Bedankt voor dit gesprek en tot snel!"
BEËINDIG HET GESPREK.""")
    
    # =========================================================================
    # Combine all into final prompt
    # =========================================================================
    steps_text = "\n\n".join(steps)
    
    prompt = f"""Je bent een vriendelijke digitale recruiter van ITZU. Je voert een telefonische screening uit.

Huidige datum en tijd: {timestamp}{vacancy_header}

BELANGRIJK: Volg dit script STAP VOOR STAP in exact deze volgorde. Sla GEEN stappen over.

{steps_text}

=== STIJLREGELS ===
- Spreek Vlaams Nederlands (nl-BE)
- Als de kandidaat in een andere taal antwoordt, schakel dan direct over naar die taal
- Korte, natuurlijke zinnen - dit is een telefoongesprek
- Wacht altijd op antwoord voor de volgende vraag
- Wees warm en professioneel
- Gebruik NOOIT de naam van de kandidaat (namen worden vaak verkeerd uitgesproken)
- Spreek duidelijk en niet te snel
- Verzin GEEN extra vragen - stel ALLEEN de vragen die hierboven staan
"""
    
    return prompt


def create_or_update_voice_agent(
    vacancy_id: str, 
    config: dict, 
    existing_agent_id: Optional[str] = None,
    vacancy_title: Optional[str] = None
) -> str:
    """
    Create or update an ElevenLabs voice agent for a vacancy.
    
    If existing_agent_id is provided, updates that agent.
    Otherwise, creates a new agent.
    
    Args:
        vacancy_id: The vacancy UUID
        config: Pre-screening configuration containing questions and messages
        existing_agent_id: If provided, update this agent instead of creating new
        vacancy_title: Optional vacancy title to include in the prompt
        
    Returns:
        str: The agent_id (same as existing if updated, new if created)
    """
    client = get_elevenlabs_client()
    prompt = build_voice_prompt(config, vacancy_title=vacancy_title)
    
    # Log the interview configuration (same as knockout_agent)
    logger.info("=" * 60)
    logger.info(f"VOICE AGENT {'UPDATED' if existing_agent_id else 'CREATED'}: vacancy-{vacancy_id[:8]}")
    logger.info("=" * 60)
    logger.info("INTERVIEW CONFIGURATION:")
    logger.info("-" * 40)
    logger.info(f"Vacancy: {vacancy_title or 'N/A'}")
    logger.info(f"Intro: {config.get('intro', 'N/A')}")
    logger.info("-" * 40)
    logger.info("KNOCKOUT QUESTIONS:")
    for i, q in enumerate(config.get('knockout_questions', []), 1):
        question_text = q.get("question_text") or q.get("question", "")
        logger.info(f"  {i}. {question_text}")
    logger.info("-" * 40)
    logger.info(f"Knockout Failed Action: {config.get('knockout_failed_action', 'N/A')}")
    logger.info("-" * 40)
    logger.info("QUALIFICATION QUESTIONS:")
    for i, q in enumerate(config.get('qualification_questions', []), 1):
        question_text = q.get("question_text") or q.get("question", "")
        logger.info(f"  {i}. {question_text}")
    logger.info("-" * 40)
    logger.info(f"Final Action: {config.get('final_action', 'N/A')}")
    logger.info("=" * 60)
    logger.info("FULL SYSTEM PROMPT:")
    logger.info("=" * 60)
    for line in prompt.split('\n'):
        logger.info(line)
    logger.info("=" * 60)
    
    conversation_config = {
        "agent": {
            "prompt": {
                "prompt": prompt,
                "llm": "qwen3-30b-a3b",
            },
            "first_message": "",
            "language": "nl",
        },
        "conversation": {
            "text_only": False,
        },
        "tts": {
            "model_id": "eleven_turbo_v2_5",
            "voice_id": os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        },
        "asr": {
            "user_input_audio_format": "ulaw_8000",
        },
    }
    
    platform_settings = {
        "twilio": {
            "enabled": True,
        },
    }
    
    if existing_agent_id:
        # Update existing agent
        client.conversational_ai.agents.update(
            agent_id=existing_agent_id,
            conversation_config=conversation_config,
            platform_settings=platform_settings,
        )
        logger.info(f"Updated voice agent for vacancy {vacancy_id}: {existing_agent_id}")
        return existing_agent_id
    else:
        # Create new agent
        agent_name = f"vacancy-{vacancy_id[:8]}"
        response = client.conversational_ai.agents.create(
            name=agent_name,
            conversation_config=conversation_config,
            platform_settings=platform_settings,
        )
        logger.info(f"Created voice agent for vacancy {vacancy_id}: {response.agent_id}")
        return response.agent_id


# =============================================================================
# Outbound Calling
# =============================================================================

def initiate_outbound_call(
    to_number: str,
    agent_id: str,
) -> dict:
    """
    Initiate an outbound phone call to a candidate using ElevenLabs + Twilio.
    
    Note: We intentionally don't pass candidate names to avoid mispronunciation issues.
    The agent uses "je/jij" instead of the candidate's name.
    
    Args:
        to_number: The phone number to call (E.164 format, e.g., "+31612345678")
        agent_id: The ElevenLabs agent ID (from published pre-screening)
        
    Returns:
        dict: Response containing:
            - success: bool
            - message: str
            - conversation_id: str (if successful)
            - call_sid: str (if successful)
            
    Raises:
        RuntimeError: If ELEVENLABS_PHONE_NUMBER_ID is not set.
        ValueError: If agent_id is not provided.
    """
    if not agent_id:
        raise ValueError("agent_id is required. Use the agent_id from a published pre-screening.")
    
    phone_number_id = os.environ.get("ELEVENLABS_PHONE_NUMBER_ID")
    if not phone_number_id:
        raise RuntimeError("ELEVENLABS_PHONE_NUMBER_ID environment variable is required")
    
    client = get_elevenlabs_client()
    
    logger.info(f"Initiating outbound call to {to_number} with agent {agent_id}")
    
    # Make the outbound call via Twilio
    # Note: No dynamic variables passed - agent doesn't use candidate names
    response = client.conversational_ai.twilio.outbound_call(
        agent_id=agent_id,
        agent_phone_number_id=phone_number_id,
        to_number=to_number,
    )
    
    result = {
        "success": response.success,
        "message": response.message,
        "conversation_id": response.conversation_id,
        "call_sid": response.call_sid,
    }
    
    logger.info(f"Outbound call initiated: {result}")
    
    return result


# =============================================================================
# Utility Functions
# =============================================================================

def delete_voice_agent(agent_id: str) -> bool:
    """
    Delete an ElevenLabs voice agent.
    
    Args:
        agent_id: The agent ID to delete
        
    Returns:
        bool: True if deleted successfully
    """
    try:
        client = get_elevenlabs_client()
        client.conversational_ai.agents.delete(agent_id=agent_id)
        logger.info(f"Deleted voice agent: {agent_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete voice agent {agent_id}: {e}")
        return False


def list_voice_agents() -> list[dict]:
    """
    List all ElevenLabs voice agents.
    
    Returns:
        list[dict]: List of agent info dicts with 'agent_id' and 'name' keys
    """
    try:
        client = get_elevenlabs_client()
        agents = []
        cursor = None
        
        # Paginate through all agents
        while True:
            response = client.conversational_ai.agents.list(
                page_size=100,
                cursor=cursor
            )
            
            for agent in response.agents:
                agents.append({
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                })
            
            if not response.has_more:
                break
            cursor = response.next_cursor
        
        logger.info(f"Listed {len(agents)} voice agents")
        return agents
    except Exception as e:
        logger.error(f"Failed to list voice agents: {e}")
        return []
