"""
Simple Pre-screening Agent with code-controlled flow.

Flow is managed by Python code, not LLM routing decisions.
LLM only generates conversational responses.

Phases:
1. HELLO - Welcome, wait for confirmation
2. KNOCKOUT - Ask knockout questions, evaluate pass/fail
3. OPEN - Ask open questions, record answers
4. SCHEDULE - Get slots, let user pick, book interview
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.services.scheduling_service import scheduling_service

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class AgentConfig:
    """Configuration settings for the pre-screening agent."""
    # Models
    model_generate: str = "gemini-2.5-flash"  # For response generation
    model_evaluate: str = "gemini-2.0-flash-lite"  # Fast model for JSON evaluations

    # Exit thresholds
    max_unrelated_answers: int = 2  # Exit after this many irrelevant answers

    # Scheduling
    schedule_days_ahead: int = 3  # How many days of slots to show
    schedule_start_offset: int = 3  # Start from X days in the future

    # Alternate intake (when knockout fails)
    alternate_questions: list[str] = field(default_factory=lambda: [
        "Wat voor soort werk doe je het liefst?",
        "Heb je specifieke diploma's, certificaten of vaardigheden?",
        "Vanaf wanneer ben je beschikbaar en hoeveel uren per week zou je willen werken?",
    ])


# Default config instance
DEFAULT_CONFIG = AgentConfig()


class Phase(str, Enum):
    HELLO = "hello"
    KNOCKOUT = "knockout"
    CONFIRM_FAIL = "confirm_fail"  # Ask if interested in other jobs
    ALTERNATE = "alternate"  # Ask 3 open questions for other opportunities
    OPEN = "open"
    SCHEDULE = "schedule"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ConversationState:
    """Simple state tracking - managed by our code, not LLM."""
    phase: Phase = Phase.HELLO

    # Candidate & vacancy info
    candidate_name: str = "kandidaat"
    vacancy_title: str = ""
    company_name: str = ""

    # Knockout questions
    knockout_questions: list[dict] = field(default_factory=list)
    knockout_index: int = 0
    knockout_results: list[dict] = field(default_factory=list)

    # Open questions
    open_questions: list[str] = field(default_factory=list)
    open_index: int = 0
    open_results: list[dict] = field(default_factory=list)

    # Alternate intake (when knockout fails but interested in other jobs)
    alternate_questions: list[str] = field(default_factory=list)  # Set from config
    alternate_index: int = 0
    alternate_results: list[dict] = field(default_factory=list)

    # Knockout failure tracking
    failed_requirement: str = ""

    # Unrelated answer tracking
    unrelated_count: int = 0

    # Scheduling
    available_slots: list[dict] = field(default_factory=list)
    scheduled_time: str = ""

    # Outcome
    outcome: str = ""


# =============================================================================
# PROMPTS - Simple, focused prompts for each phase
# =============================================================================

HELLO_PROMPT = """Je bent een vriendelijke recruiter van {company_name}.

Verwelkom {candidate_name} kort en leg uit dat je een paar vragen hebt voor de functie {vacancy_title}.
Vraag of ze klaar zijn om te beginnen.

Houd het kort (2-3 zinnen max). Spreek Nederlands (Vlaams)."""

INTENT_READY_PROMPT = """Bepaal of de kandidaat klaar is om te beginnen met het gesprek.

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"ready": true/false}}

- ready=true als de kandidaat instemt, bevestigt, of aangeeft klaar te zijn (ja, ok, yes, sure, prima, etc.)
- ready=false als de kandidaat twijfelt, een vraag stelt, of nog niet wil beginnen"""

KNOCKOUT_ASK_PROMPT = """Je bent een recruiter die een screeningsvraag stelt.

Kandidaat: {candidate_name}
Vacature: {vacancy_title}

Stel deze vraag op een vriendelijke manier:
"{question}"

Houd het kort (1-2 zinnen). Gebruik de voornaam."""

KNOCKOUT_EVAL_PROMPT = """Evalueer of dit antwoord voldoet aan de vereiste.

VEREISTE: {requirement}
ANTWOORD: "{answer}"

Antwoord ALLEEN met JSON: {{"passed": true/false, "summary": "samenvatting"}}

passed=true als de kandidaat bevestigend of positief antwoordt (in elke taal of stijl).
passed=false ALLEEN als de kandidaat expliciet ontkent of aangeeft NIET te voldoen.

Bij twijfel: passed=true."""

KNOCKOUT_PASS_NEXT_PROMPT = """Bevestig kort en stel de volgende vraag.

Antwoord: "{answer}"
Volgende vraag: "{next_question}"

Begin met een korte, informele bevestiging (bv. erkenning dat je het gehoord hebt) en stel dan de vraag.
Max 2 zinnen."""

KNOCKOUT_PASS_DONE_PROMPT = """De kandidaat heeft alle basisvragen goed beantwoord. Reageer kort positief EN stel de eerste open vraag.

Kandidaat: {candidate_name}
Hun antwoord: "{answer}"
Open vraag: "{next_question}"

Reageer met een korte positieve bevestiging gevolgd door de open vraag.
Max 2 zinnen totaal."""

KNOCKOUT_FAIL_PROMPT = """De kandidaat voldoet niet aan een vereiste voor deze specifieke vacature.

Kandidaat: {candidate_name}
Vereiste: {requirement}
Hun antwoord: "{answer}"

Leg empathisch uit dat dit helaas een vereiste is voor DEZE functie.
Vraag dan of ze interesse hebben in andere vacatures bij ons.
Houd het kort (2-3 zinnen). Eindig met de vraag over andere vacatures."""

CONFIRM_INTEREST_PROMPT = """Bepaal of de kandidaat interesse heeft in andere vacatures.

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"interested": true/false}}

- interested=true als ze ja zeggen, interesse tonen, of openstaan voor andere opties
- interested=false als ze nee zeggen of geen interesse hebben"""

ALTERNATE_INTRO_PROMPT = """De kandidaat wil graag info geven voor andere vacatures.

Kandidaat: {candidate_name}

Bedank kort voor hun interesse en leg uit dat je 3 korte vragen hebt om te kijken welke vacatures passen.
Stel dan direct de eerste vraag: "{first_question}"

Max 3 zinnen totaal."""

ALTERNATE_GOODBYE_PROMPT = """De kandidaat heeft info gegeven voor andere vacatures.

Kandidaat: {candidate_name}

Bedank ze hartelijk. Zeg dat een recruiter contact opneemt als er een passende vacature is.
Wens ze succes. Max 2 zinnen. GEEN handtekening."""

NO_INTEREST_GOODBYE_PROMPT = """De kandidaat heeft geen interesse in andere vacatures.

Kandidaat: {candidate_name}

Bedank kort voor hun tijd en wens succes met de zoektocht.
Max 2 zinnen. GEEN handtekening."""

OPEN_RECORD_NEXT_PROMPT = """De kandidaat heeft een vraag beantwoord. Reageer kort positief EN stel de volgende vraag.

Vraag: "{question}"
Antwoord: "{answer}"
Volgende vraag: "{next_question}"

Reageer met een korte positieve reactie (1-3 woorden) gevolgd door de volgende vraag.
Max 2 zinnen totaal."""

OPEN_RECORD_DONE_PROMPT = """De kandidaat heeft de laatste open vraag beantwoord. Reageer kort positief EN presenteer de beschikbare tijdsloten.

Antwoord: "{answer}"
Tijdsloten: {slots_text}

Feliciteer kort en presenteer de tijdsloten. Vraag welk moment past.
Max 3 zinnen. GEEN handtekening."""

SCHEDULE_CONFIRM_PROMPT = """Bevestig de afspraak in een WhatsApp chat.

Kandidaat: {candidate_name}
Ingepland: {scheduled_time}

Bevestig kort, zeg dat ze een bevestiging krijgen. Max 2 zinnen. GEEN handtekening."""

SLOT_EXTRACT_PROMPT = """Extraheer de gekozen dag en tijd uit het bericht van de kandidaat.

BESCHIKBARE SLOTS:
{available_slots}

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"day": "maandag/dinsdag/woensdag/donderdag/vrijdag", "time": "10u/11u/14u/16u", "date": "YYYY-MM-DD"}}

- Zoek de dag (ook afkortingen: ma=maandag, di=dinsdag, woe=woensdag, do=donderdag, vrij=vrijdag)
- Zoek de tijd (10u, 11u, 14u, 16u, of "ochtend"=10u, "middag"=14u)
- Geef de bijbehorende date uit de beschikbare slots
- Als onduidelijk: {{"day": null, "time": null, "date": null}}"""

UNRELATED_CHECK_PROMPT = """Is dit antwoord een poging om de vraag te beantwoorden?

VRAAG: "{question}"
ANTWOORD: "{answer}"

Antwoord ALLEEN met JSON: {{"unrelated": true/false}}

unrelated=false als het antwoord de vraag probeert te beantwoorden (ook korte/informele antwoorden).
unrelated=true ALLEEN voor spam, willekeurige tekst, of compleet andere onderwerpen.

Bij twijfel: unrelated=false."""

UNRELATED_EXIT_PROMPT = """De kandidaat heeft meerdere keren irrelevant geantwoord.

Kandidaat: {candidate_name}

Bedank vriendelijk voor hun tijd. Zeg dat ze later contact kunnen opnemen als ze serieus geïnteresseerd zijn.
Max 2 zinnen. GEEN handtekening."""


# =============================================================================
# SIMPLE AGENT CLASS
# =============================================================================

class SimplePreScreeningAgent:
    """
    Pre-screening agent with code-controlled flow.

    Usage:
        agent = SimplePreScreeningAgent(state, config)
        response = await agent.process_message(user_message)
    """

    def __init__(self, state: ConversationState, config: AgentConfig = None):
        self.state = state
        self.config = config or DEFAULT_CONFIG

    async def process_message(self, user_message: str) -> str:
        """
        Process a user message and return agent response.

        The phase logic is handled here in Python, not by the LLM.
        """
        phase = self.state.phase

        if phase == Phase.HELLO:
            return await self._handle_hello(user_message)
        elif phase == Phase.KNOCKOUT:
            return await self._handle_knockout(user_message)
        elif phase == Phase.CONFIRM_FAIL:
            return await self._handle_confirm_fail(user_message)
        elif phase == Phase.ALTERNATE:
            return await self._handle_alternate(user_message)
        elif phase == Phase.OPEN:
            return await self._handle_open(user_message)
        elif phase == Phase.SCHEDULE:
            return await self._handle_schedule(user_message)
        else:
            return "Bedankt voor je tijd!"

    async def get_initial_message(self) -> str:
        """Get the initial welcome message."""
        prompt = HELLO_PROMPT.format(
            company_name=self.state.company_name,
            candidate_name=self.state.candidate_name,
            vacancy_title=self.state.vacancy_title,
        )
        return await self._generate(prompt)

    # -------------------------------------------------------------------------
    # Phase handlers
    # -------------------------------------------------------------------------

    async def _handle_hello(self, user_message: str) -> str:
        """Handle hello phase - wait for confirmation to start."""
        question = f"Ben je klaar om te beginnen met de screening voor {self.state.vacancy_title}?"

        # Run unrelated check and ready check in parallel
        unrelated_task = self._is_unrelated(question, user_message)
        ready_task = self._evaluate_ready(user_message)
        is_unrelated, is_ready = await asyncio.gather(unrelated_task, ready_task)

        # Check for unrelated answer first
        if is_unrelated:
            self.state.unrelated_count += 1
            if self.state.unrelated_count >= self.config.max_unrelated_answers:
                return await self._handle_unrelated_exit()
            # Ask again
            prompt = f"""De kandidaat gaf een irrelevant antwoord: "{user_message}"

Vraag vriendelijk om bij het onderwerp te blijven. We willen weten of ze klaar zijn voor de screening.
Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

        if is_ready:
            self.state.unrelated_count = 0  # Reset on valid answer
            self.state.phase = Phase.KNOCKOUT
            return await self._ask_knockout_question()
        else:
            # Ask again with a friendly prompt
            prompt = f"""De kandidaat heeft geantwoord: "{user_message}"

Ze zijn nog niet klaar om te beginnen of hadden een vraag.
Reageer kort en vriendelijk, en vraag opnieuw of ze klaar zijn.
Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

    async def _handle_knockout(self, user_message: str) -> str:
        """Handle knockout phase - evaluate answer, move to next or fail."""
        current_q = self.state.knockout_questions[self.state.knockout_index]

        # Run unrelated check and knockout eval in parallel
        unrelated_task = self._is_unrelated(current_q["question"], user_message)
        knockout_task = self._evaluate_knockout(user_message, current_q)
        is_unrelated, eval_result = await asyncio.gather(unrelated_task, knockout_task)

        # Check for unrelated answer
        if is_unrelated:
            self.state.unrelated_count += 1
            if self.state.unrelated_count >= self.config.max_unrelated_answers:
                return await self._handle_unrelated_exit()
            # Ask the question again
            prompt = f"""De kandidaat gaf een irrelevant antwoord: "{user_message}"

Vraag vriendelijk om bij het onderwerp te blijven en herhaal de vraag:
"{current_q["question"]}"

Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

        if eval_result["passed"]:
            self.state.unrelated_count = 0  # Reset on valid answer
            # Record result
            self.state.knockout_results.append({
                "question": current_q["question"],
                "answer": eval_result["summary"],
                "passed": True,
            })

            # Move to next question or next phase
            self.state.knockout_index += 1

            if self.state.knockout_index >= len(self.state.knockout_questions):
                # All knockout questions passed - move to open questions
                self.state.phase = Phase.OPEN
                next_q = self.state.open_questions[self.state.open_index]
                prompt = KNOCKOUT_PASS_DONE_PROMPT.format(
                    candidate_name=self.state.candidate_name,
                    answer=eval_result["summary"],
                    next_question=next_q,
                )
                return await self._generate(prompt)
            else:
                # More knockout questions - combined positive + next question
                next_q = self.state.knockout_questions[self.state.knockout_index]
                prompt = KNOCKOUT_PASS_NEXT_PROMPT.format(
                    candidate_name=self.state.candidate_name,
                    answer=eval_result["summary"],
                    next_question=next_q["question"],
                )
                return await self._generate(prompt)
        else:
            # Knockout failed - ask about alternative opportunities
            self.state.phase = Phase.CONFIRM_FAIL
            self.state.failed_requirement = current_q["requirement"]
            return await self._generate_fail_response(current_q, user_message)

    async def _handle_open(self, user_message: str) -> str:
        """Handle open questions phase - record answer, move to next."""
        current_q = self.state.open_questions[self.state.open_index]

        # Check for unrelated answer
        if await self._is_unrelated(current_q, user_message):
            self.state.unrelated_count += 1
            if self.state.unrelated_count >= self.config.max_unrelated_answers:
                return await self._handle_unrelated_exit()
            # Ask the question again
            prompt = f"""De kandidaat gaf een irrelevant antwoord: "{user_message}"

Vraag vriendelijk om bij het onderwerp te blijven en herhaal de vraag:
"{current_q}"

Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

        self.state.unrelated_count = 0  # Reset on valid answer
        # Record answer
        self.state.open_results.append({
            "question": current_q,
            "answer": user_message,
        })

        # Move to next question or scheduling
        self.state.open_index += 1

        if self.state.open_index >= len(self.state.open_questions):
            # All open questions done - move to scheduling
            self.state.phase = Phase.SCHEDULE
            # Get slots and combine with positive response
            slot_data = scheduling_service.get_available_slots(
                days_ahead=self.config.schedule_days_ahead,
                start_offset_days=self.config.schedule_start_offset,
            )
            self.state.available_slots = [s.model_dump() for s in slot_data.slots]
            prompt = OPEN_RECORD_DONE_PROMPT.format(
                answer=user_message,
                slots_text=slot_data.formatted_text,
            )
            return await self._generate(prompt)
        else:
            # More open questions - combined positive + next question
            next_q = self.state.open_questions[self.state.open_index]
            prompt = OPEN_RECORD_NEXT_PROMPT.format(
                question=current_q,
                answer=user_message,
                next_question=next_q,
            )
            return await self._generate(prompt)

    async def _handle_schedule(self, user_message: str) -> str:
        """Handle scheduling phase - use LLM to extract slot choice, book it."""
        # Use LLM to extract slot choice
        slot_info = await self._extract_slot_choice(user_message)

        if slot_info and slot_info.get("day") and slot_info.get("time"):
            # Build slot text
            day = slot_info["day"]
            time = slot_info["time"]
            slot_text = f"{day} om {time}"

            # Book the slot
            result = scheduling_service.schedule_slot(
                slot=slot_text,
                conversation_id="test",
            )
            self.state.scheduled_time = result.slot
            self.state.phase = Phase.DONE
            self.state.outcome = f"Scheduled: {result.slot}"

            return await self._generate_confirm(result.slot)
        else:
            # LLM couldn't extract - ask to clarify
            prompt = f"""De kandidaat zei: "{user_message}"

Je begreep niet welk tijdslot ze willen. Vraag vriendelijk om te verduidelijken.
Noem de beschikbare dagen kort. Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

    async def _handle_confirm_fail(self, user_message: str) -> str:
        """Handle confirm_fail phase - check if interested in other opportunities."""
        # Use LLM to evaluate interest
        is_interested = await self._evaluate_interest(user_message)

        if is_interested:
            # Start alternate intake
            self.state.phase = Phase.ALTERNATE
            self.state.alternate_index = 0
            first_q = self.state.alternate_questions[0]

            prompt = ALTERNATE_INTRO_PROMPT.format(
                candidate_name=self.state.candidate_name,
                first_question=first_q,
            )
            return await self._generate(prompt)
        else:
            # Not interested - say goodbye
            self.state.phase = Phase.FAILED
            self.state.outcome = f"Knockout failed, no interest in alternatives"

            prompt = NO_INTEREST_GOODBYE_PROMPT.format(
                candidate_name=self.state.candidate_name,
            )
            return await self._generate(prompt)

    async def _handle_alternate(self, user_message: str) -> str:
        """Handle alternate phase - collect info for other opportunities."""
        current_q = self.state.alternate_questions[self.state.alternate_index]

        # Check for unrelated answer
        if await self._is_unrelated(current_q, user_message):
            self.state.unrelated_count += 1
            if self.state.unrelated_count >= self.config.max_unrelated_answers:
                return await self._handle_unrelated_exit()
            # Ask the question again
            prompt = f"""De kandidaat gaf een irrelevant antwoord: "{user_message}"

Vraag vriendelijk om bij het onderwerp te blijven en herhaal de vraag:
"{current_q}"

Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

        self.state.unrelated_count = 0  # Reset on valid answer
        # Record answer
        self.state.alternate_results.append({
            "question": current_q,
            "answer": user_message,
        })

        # Move to next question
        self.state.alternate_index += 1

        if self.state.alternate_index >= len(self.state.alternate_questions):
            # All alternate questions done - say goodbye
            self.state.phase = Phase.DONE
            self.state.outcome = "Alternate intake completed"

            prompt = ALTERNATE_GOODBYE_PROMPT.format(
                candidate_name=self.state.candidate_name,
            )
            return await self._generate(prompt)
        else:
            # More questions - combine positive response with next question
            next_q = self.state.alternate_questions[self.state.alternate_index]
            prompt = f"""De kandidaat heeft een vraag beantwoord. Reageer kort positief EN stel de volgende vraag.

Vraag: "{current_q}"
Antwoord: "{user_message}"
Volgende vraag: "{next_q}"

Reageer met een korte positieve reactie (1-3 woorden) gevolgd door de volgende vraag.
Max 2 zinnen totaal."""
            return await self._generate(prompt)

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _parse_json_response(self, response: str, default: dict) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        try:
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            return json.loads(response)
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Failed to parse JSON: {response[:100]}")
            return default

    async def _ask_knockout_question(self) -> str:
        """Generate knockout question prompt."""
        q = self.state.knockout_questions[self.state.knockout_index]
        prompt = KNOCKOUT_ASK_PROMPT.format(
            candidate_name=self.state.candidate_name,
            vacancy_title=self.state.vacancy_title,
            question=q["question"],
        )
        return await self._generate(prompt)

    async def _evaluate_ready(self, message: str) -> bool:
        """Use LLM to evaluate if user is ready to start."""
        prompt = INTENT_READY_PROMPT.format(message=message)
        response = await self._evaluate(prompt)
        result = self._parse_json_response(response, {"ready": True})
        return result.get("ready", True)

    async def _evaluate_interest(self, message: str) -> bool:
        """Use LLM to evaluate if user is interested in other opportunities."""
        prompt = CONFIRM_INTEREST_PROMPT.format(message=message)
        response = await self._evaluate(prompt)
        result = self._parse_json_response(response, {"interested": True})
        return result.get("interested", True)

    async def _is_unrelated(self, question: str, answer: str) -> bool:
        """Use LLM to check if answer is unrelated to the conversation."""
        prompt = UNRELATED_CHECK_PROMPT.format(question=question, answer=answer)
        response = await self._evaluate(prompt)
        result = self._parse_json_response(response, {"unrelated": False})
        return result.get("unrelated", False)

    async def _handle_unrelated_exit(self) -> str:
        """Generate exit message when too many unrelated answers."""
        self.state.phase = Phase.FAILED
        self.state.outcome = "Exited due to unrelated answers"

        prompt = UNRELATED_EXIT_PROMPT.format(
            candidate_name=self.state.candidate_name,
        )
        return await self._generate(prompt)

    async def _evaluate_knockout(self, answer: str, question: dict) -> dict:
        """Evaluate if knockout answer passes."""
        prompt = KNOCKOUT_EVAL_PROMPT.format(
            requirement=question.get("requirement", question["question"]),
            answer=answer,
        )
        response = await self._evaluate(prompt)
        return self._parse_json_response(response, {"passed": True, "summary": answer[:100]})

    async def _generate_fail_response(self, question: dict, answer: str) -> str:
        """Generate knockout fail response."""
        prompt = KNOCKOUT_FAIL_PROMPT.format(
            candidate_name=self.state.candidate_name,
            requirement=question.get("requirement", question["question"]),
            answer=answer,
        )
        return await self._generate(prompt)

    async def _generate_confirm(self, scheduled_time: str) -> str:
        """Generate scheduling confirmation."""
        prompt = SCHEDULE_CONFIRM_PROMPT.format(
            candidate_name=self.state.candidate_name,
            scheduled_time=scheduled_time,
        )
        return await self._generate(prompt)

    async def _extract_slot_choice(self, message: str) -> Optional[dict]:
        """Use LLM to extract slot choice from message."""
        slots_text = [
            f"- {slot['dutch_date']} ({slot['date']}): {slot['morning']}, {slot['afternoon']}"
            for slot in self.state.available_slots
        ]
        prompt = SLOT_EXTRACT_PROMPT.format(
            available_slots="\n".join(slots_text),
            message=message,
        )
        response = await self._evaluate(prompt)
        result = self._parse_json_response(response, {})
        if result.get("day") and result.get("time"):
            return result
        return None

    async def _generate(self, prompt: str) -> str:
        """Generate text using LLM."""
        from google import genai

        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=self.config.model_generate,
            contents=prompt,
        )
        return response.text

    async def _evaluate(self, prompt: str) -> str:
        """Fast evaluation using lightweight model for JSON responses."""
        from google import genai

        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=self.config.model_evaluate,
            contents=prompt,
        )
        return response.text


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_simple_agent(
    candidate_name: str,
    vacancy_title: str,
    company_name: str,
    knockout_questions: list[dict],
    open_questions: list[str],
    config: AgentConfig = None,
) -> SimplePreScreeningAgent:
    """
    Create a simple pre-screening agent.

    Args:
        candidate_name: Name of the candidate
        vacancy_title: Job title
        company_name: Company name
        knockout_questions: List of {"question": "...", "requirement": "..."}
        open_questions: List of question strings
        config: Optional AgentConfig for customization

    Returns:
        SimplePreScreeningAgent ready to use
    """
    config = config or DEFAULT_CONFIG
    state = ConversationState(
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        company_name=company_name,
        knockout_questions=knockout_questions,
        open_questions=open_questions,
        alternate_questions=list(config.alternate_questions),
    )
    return SimplePreScreeningAgent(state, config)
