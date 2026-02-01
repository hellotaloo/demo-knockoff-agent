"""
Candidate Simulator Agent - Generates realistic candidate responses for interview testing.

This module allows recruiters to simulate interviews with different candidate personas
to test their pre-screening configuration before going live.
"""

import re
import logging
import json
import uuid
from enum import Enum
from typing import Optional, AsyncGenerator

from google.adk.agents import Agent
from google.genai import types

logger = logging.getLogger(__name__)


class SimulationPersona(str, Enum):
    """Available candidate personas for simulation."""
    QUALIFIED = "qualified"           # Passes all questions
    BORDERLINE = "borderline"         # Uncertain, asks clarifications
    UNQUALIFIED = "unqualified"       # Fails knockout questions
    RUSHED = "rushed"                 # Short answers, seems busy
    ENTHUSIASTIC = "enthusiastic"     # Very eager, detailed answers
    CUSTOM = "custom"                 # Custom persona description


# Persona behavior descriptions (Dutch) - KEEP ANSWERS SHORT!
PERSONA_BEHAVIORS = {
    SimulationPersona.QUALIFIED: """Je bent een IDEALE kandidaat.
- Antwoord HEEL KORT: max 1-2 zinnen!
- "Ja hoor!" / "Zeker, geen probleem" / "Ja, 3 jaar ervaring"
- Voldoe aan alle vereisten
- Positief maar bondig""",

    SimulationPersona.BORDERLINE: """Je bent een TWIJFELGEVAL.
- Antwoord KORT maar met twijfel
- "Hmm, ik denk het wel..." / "Dat zou moeten lukken"
- Stel af en toe een tegenvraag
- Max 1-2 zinnen per antwoord""",

    SimulationPersona.UNQUALIFIED: """Je VOLDOET NIET aan de vereisten.
- Kies EEN reden: geen werkvergunning / kan niet in ploegen / te ver weg
- Antwoord KORT en eerlijk: "Nee helaas, ik heb nog geen werkvergunning"
- Max 1-2 zinnen""",

    SimulationPersona.RUSHED: """Je bent GEHAAST.
- ULTRA KORT: 1-5 woorden max
- "ja" / "nee" / "ok" / "kan wel" / "2 jaar"
- Geen emoji's, geen uitleg
- Voldoe aan de vereisten""",

    SimulationPersona.ENTHUSIASTIC: """Je bent ENTHOUSIAST.
- Kort maar met energie: max 2 zinnen
- Gebruik 1-2 emoji's 🎉👍
- "Ja zeker!! Ik heb 3 jaar ervaring 💪"
- Voldoe aan alle vereisten""",
}


def build_simulator_instruction(
    config: dict, 
    persona: SimulationPersona,
    custom_persona: Optional[str] = None,
    vacancy_title: Optional[str] = None
) -> str:
    """
    Build instruction for the candidate simulator agent.
    
    Args:
        config: Pre-screening configuration with questions
        persona: The persona type to simulate
        custom_persona: Custom persona description (if persona is CUSTOM)
        vacancy_title: Optional vacancy title for context
    
    Returns:
        str: Complete instruction for the simulator agent
    """
    # Get persona behavior
    if persona == SimulationPersona.CUSTOM and custom_persona:
        persona_behavior = custom_persona
    else:
        persona_behavior = PERSONA_BEHAVIORS.get(persona, PERSONA_BEHAVIORS[SimulationPersona.QUALIFIED])
    
    # Extract questions for context
    knockout_questions = config.get("knockout_questions", [])
    qualification_questions = config.get("qualification_questions", [])
    
    knockout_list = []
    for q in knockout_questions:
        text = q.get("question_text") or q.get("question", "")
        knockout_list.append(f"- {text}")
    
    qual_list = []
    for q in qualification_questions:
        text = q.get("question_text") or q.get("question", "")
        ideal = q.get("ideal_answer", "")
        qual_list.append(f"- {text}")
        if ideal and persona in [SimulationPersona.QUALIFIED, SimulationPersona.ENTHUSIASTIC]:
            qual_list.append(f"  (Gewenst antwoord: {ideal})")
    
    vacancy_context = f"\nVACATURE: {vacancy_title}" if vacancy_title else ""
    
    instruction = f"""Je simuleert een kandidaat via WhatsApp. ANTWOORD ALTIJD HEEL KORT!
{vacancy_context}

## JOUW PERSONA
{persona_behavior}

## KRITISCH: KORTE ANTWOORDEN
- MAX 1-2 ZINNEN per antwoord!
- WhatsApp = kort en bondig
- Geen lange uitleg of verhalen
- Gewoon antwoord geven op de vraag

## VOORBEELDEN VAN GOEDE (KORTE) ANTWOORDEN
- "Ja hoor!" 
- "Zeker, geen probleem 👍"
- "Ja, 3 jaar ervaring"
- "Nee helaas, dat lukt niet"
- "Maandag 10u past perfect!"

## VOORBEELDEN VAN SLECHTE (TE LANGE) ANTWOORDEN
- "Goede vraag! Ik heb veel ervaring met..." (TE LANG)
- "Laat me even uitleggen..." (TE LANG)

## KNOCKOUT VRAGEN
{chr(10).join(knockout_list) if knockout_list else "(geen)"}

## KWALIFICATIEVRAGEN  
{chr(10).join(qual_list) if qual_list else "(geen)"}

## REGELS
1. MAX 1-2 ZINNEN - dit is WhatsApp, niet een sollicitatiebrief!
2. Antwoord alleen op de gestelde vraag
3. Bij tijdslot-vraag: kies er gewoon één
"""
    
    return instruction


def create_simulator_agent(
    config: dict,
    persona: SimulationPersona,
    custom_persona: Optional[str] = None,
    vacancy_title: Optional[str] = None
) -> Agent:
    """
    Create a candidate simulator agent for testing interviews.
    
    Args:
        config: Pre-screening configuration
        persona: The persona to simulate
        custom_persona: Custom persona description
        vacancy_title: Optional vacancy title
    
    Returns:
        Agent: Configured simulator agent
    """
    instruction = build_simulator_instruction(
        config=config,
        persona=persona,
        custom_persona=custom_persona,
        vacancy_title=vacancy_title
    )
    
    agent = Agent(
        name=f"simulator_{persona.value}",
        model="gemini-2.5-flash",  # Fast model for quick responses
        instruction=instruction,
        description=f"Candidate simulator with {persona.value} persona",
    )
    
    logger.info(f"✅ Created simulator agent with persona: {persona.value}")
    return agent


# Patterns that indicate conversation is ending (goodbye messages)
CLOSING_PATTERNS = [
    r"tot (ziens|snel|gauw|dan|dinsdag|woensdag|donderdag|vrijdag|maandag)",
    r"bedankt",
    r"dank je",
    r"fijn(e dag)?",
    r"succes",
    r"doei",
    r"dag!?$",
    r"👋",
    r"🙌",
    r"✅",
    r"ingepland",  # Interview scheduled
    r"staat genoteerd",
    r"afspraak.*(bevestigd|gemaakt)",
]


def is_closing_message(message: str) -> bool:
    """Check if a message is a closing/goodbye message."""
    message_lower = message.lower().strip()
    # Very short messages with closing patterns
    if len(message_lower) < 50:
        for pattern in CLOSING_PATTERNS:
            if re.search(pattern, message_lower):
                return True
    return False


async def run_simulation(
    screening_agent: Agent,
    simulator_agent: Agent,
    candidate_name: str,
    max_turns: int = 20
) -> AsyncGenerator[dict, None]:
    """
    Run a simulated interview between the screening agent and simulator.
    
    This orchestrates a conversation between two agents:
    1. Screening agent (the interviewer)
    2. Simulator agent (the candidate)
    
    IMPORTANT: Both agents use fresh in-memory sessions to ensure
    no state leakage from real conversations.
    
    Args:
        screening_agent: The screening Agent instance (not runner - we create fresh runner)
        simulator_agent: The candidate simulator agent
        candidate_name: Name to use for the simulated candidate
        max_turns: Maximum conversation turns to prevent infinite loops
    
    Yields:
        dict: Events with type 'agent', 'candidate', 'qa_pair', or 'complete'
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    
    # Create FRESH in-memory sessions for BOTH agents
    # This ensures no state leakage from real conversations
    screening_session_service = InMemorySessionService()
    simulator_session_service = InMemorySessionService()
    
    # Create fresh runners with isolated session services
    screening_runner = Runner(
        agent=screening_agent,
        app_name="simulation_screening",
        session_service=screening_session_service
    )
    simulator_runner = Runner(
        agent=simulator_agent,
        app_name="simulation_candidate",
        session_service=simulator_session_service
    )
    
    # Create unique sessions
    session_suffix = str(uuid.uuid4())[:8]
    screening_session_id = f"sim_screening_{session_suffix}"
    simulator_session_id = f"sim_candidate_{session_suffix}"
    
    await screening_session_service.create_session(
        app_name="simulation_screening",
        user_id="simulator",
        session_id=screening_session_id
    )
    await simulator_session_service.create_session(
        app_name="simulation_candidate",
        user_id="simulator", 
        session_id=simulator_session_id
    )
    
    logger.info(f"🎭 Simulation started with fresh in-memory sessions: {screening_session_id}")
    
    qa_pairs = []
    conversation_complete = False
    current_question = None
    closing_count = 0  # Track consecutive closing messages
    
    # Start with trigger message to screening agent
    trigger_message = f"START_SCREENING name={candidate_name}"
    candidate_response = ""
    
    for turn in range(max_turns):
        # === SCREENING AGENT TURN ===
        if turn == 0:
            user_message = trigger_message
        else:
            # Use candidate's last response
            user_message = candidate_response
        
        content = types.Content(role="user", parts=[types.Part(text=user_message)])
        
        agent_response = ""
        async for event in screening_runner.run_async(
            user_id="simulator",
            session_id=screening_session_id,
            new_message=content
        ):
            if hasattr(event, 'content') and event.content:
                parts = getattr(event.content, 'parts', None)
                if parts:
                    for part in parts:
                        if hasattr(part, 'text') and part.text:
                            agent_response += part.text
            
            # Check for conversation_complete tool call
            if hasattr(event, 'actions') and event.actions:
                actions_list = getattr(event.actions, 'actions', None)
                if actions_list:
                    for action in actions_list:
                        if hasattr(action, 'name') and action.name == 'conversation_complete':
                            conversation_complete = True
        
        if agent_response:
            # Clean up any tool call artifacts
            from knockout_agent.agent import clean_response_text
            agent_response = clean_response_text(agent_response)
            
            yield {
                "type": "agent",
                "message": agent_response,
                "turn": turn
            }
            
            # Track as current question (simplified - could be smarter)
            if "?" in agent_response:
                current_question = agent_response
            
            # Check for closing pattern
            if is_closing_message(agent_response):
                closing_count += 1
        
        # STOP immediately if conversation_complete tool was called
        if conversation_complete:
            logger.info(f"🏁 Simulation ended: conversation_complete tool called at turn {turn}")
            break
        
        # STOP if we've had 2+ consecutive closing messages (goodbye loop detected)
        if closing_count >= 2:
            logger.info(f"🏁 Simulation ended: goodbye loop detected at turn {turn}")
            conversation_complete = True
            break
        
        # Skip candidate turn if agent response is empty
        if not agent_response or not agent_response.strip():
            logger.warning(f"⚠️ Empty agent response at turn {turn}, skipping candidate turn")
            continue
        
        # === CANDIDATE SIMULATOR TURN ===
        # Feed agent's message to simulator
        simulator_content = types.Content(
            role="user", 
            parts=[types.Part(text=f"[Recruiter zegt]: {agent_response}")]
        )
        
        candidate_response = ""
        async for event in simulator_runner.run_async(
            user_id="simulator",
            session_id=simulator_session_id,
            new_message=simulator_content
        ):
            if hasattr(event, 'content') and event.content:
                parts = getattr(event.content, 'parts', None)
                if parts:
                    for part in parts:
                        if hasattr(part, 'text') and part.text:
                            candidate_response += part.text
        
        if candidate_response:
            # Detect confused simulator (waiting for message = something went wrong)
            if "wacht op" in candidate_response.lower() and "bericht" in candidate_response.lower():
                logger.warning(f"⚠️ Simulator confused at turn {turn}, ending simulation")
                conversation_complete = True
                break
            
            yield {
                "type": "candidate", 
                "message": candidate_response,
                "turn": turn
            }
            
            # Record Q&A pair if we have a question
            if current_question:
                qa_pair = {
                    "question": current_question,
                    "answer": candidate_response,
                    "turn": turn
                }
                qa_pairs.append(qa_pair)
                yield {
                    "type": "qa_pair",
                    "data": qa_pair
                }
                current_question = None
            
            # Check for closing pattern from candidate
            if is_closing_message(candidate_response):
                closing_count += 1
            else:
                # Reset if we get a non-closing message
                closing_count = 0
    
    # Determine outcome based on conversation
    outcome = "completed" if conversation_complete else "max_turns_reached"
    
    yield {
        "type": "complete",
        "outcome": outcome,
        "qa_pairs": qa_pairs,
        "total_turns": turn + 1
    }
