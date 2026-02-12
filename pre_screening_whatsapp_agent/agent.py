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
    # Models - gemini-2.5-flash-lite is fastest based on testing
    model_generate: str = "gemini-2.5-flash-lite"  # Fast model for response generation
    model_evaluate: str = "gemini-2.5-flash-lite"  # Fast model for JSON evaluations

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


# =============================================================================
# FORBIDDEN WORDS FILTER
# =============================================================================

# Dutch and English swear words, slurs, and inappropriate terms
# This list is checked via regex word boundaries to avoid false positives
FORBIDDEN_WORDS = {
    # Dutch swear words
    "kut", "kanker", "tering", "tyfus", "klote", "godverdomme", "godver",
    "hoer", "slet", "lul", "eikel", "klootzak", "sukkel", "mongool",
    "debiel", "achterlijk", "flikker", "mietje", "homo",  # slurs
    "nikker", "neger", "allochtoon",  # racial slurs
    "opflikkeren", "oprotten", "opsodemieteren", "opkankeren",
    "kutwijf", "teringlijer", "kankerjoch", "tyfushoer",

    # English swear words
    "fuck", "fucking", "fucked", "fucker", "shit", "shitty", "bullshit",
    "asshole", "bitch", "bastard", "dick", "dickhead", "cock", "cunt",
    "whore", "slut", "retard", "retarded", "faggot", "fag",
    "nigger", "nigga",  # racial slurs

    # Hate/threat words
    "kill", "murder", "rape", "terrorist", "nazi", "hitler",
    "dood", "vermoord", "verkracht",  # Dutch equivalents
}

# Phrases that indicate hostility (checked as substrings)
FORBIDDEN_PHRASES = [
    "ga dood", "sterf", "rot op", "flikker op", "sodemieter op",
    "kanker op", "val dood", "krijg de", "fuck you", "fuck off",
    "go die", "kill yourself", "i hate you", "ik haat je",
]


def contains_forbidden_content(message: str) -> tuple[bool, str]:
    """
    Check if message contains forbidden words or phrases.

    Returns:
        tuple: (contains_forbidden, matched_term)
        - contains_forbidden: True if forbidden content detected
        - matched_term: The matched word/phrase (for logging)
    """
    import re
    msg_lower = message.lower()

    # Check for forbidden phrases (substring match)
    for phrase in FORBIDDEN_PHRASES:
        if phrase in msg_lower:
            return True, phrase

    # Check for forbidden words (word boundary match to avoid false positives)
    # e.g., "assassin" shouldn't match "ass"
    for word in FORBIDDEN_WORDS:
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, msg_lower):
            return True, word

    return False, ""


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

    # Conversation tracking (for database operations)
    conversation_id: str = ""  # UUID string for linking to screening_conversations

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
    scheduled_time: str = ""  # Human-readable slot text (e.g., "maandag 17 februari om 10u")
    selected_date: str = ""   # ISO date (YYYY-MM-DD) for database storage
    selected_time: str = ""   # Time slot (e.g., "10u") for database storage

    # Outcome
    outcome: str = ""

    def to_dict(self) -> dict:
        """Serialize state to dictionary for JSON storage."""
        return {
            "phase": self.phase.value,
            "conversation_id": self.conversation_id,
            "candidate_name": self.candidate_name,
            "vacancy_title": self.vacancy_title,
            "company_name": self.company_name,
            "knockout_questions": self.knockout_questions,
            "knockout_index": self.knockout_index,
            "knockout_results": self.knockout_results,
            "open_questions": self.open_questions,
            "open_index": self.open_index,
            "open_results": self.open_results,
            "alternate_questions": self.alternate_questions,
            "alternate_index": self.alternate_index,
            "alternate_results": self.alternate_results,
            "failed_requirement": self.failed_requirement,
            "unrelated_count": self.unrelated_count,
            "available_slots": self.available_slots,
            "scheduled_time": self.scheduled_time,
            "selected_date": self.selected_date,
            "selected_time": self.selected_time,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        """Deserialize state from dictionary."""
        return cls(
            phase=Phase(data.get("phase", "hello")),
            conversation_id=data.get("conversation_id", ""),
            candidate_name=data.get("candidate_name", "kandidaat"),
            vacancy_title=data.get("vacancy_title", ""),
            company_name=data.get("company_name", ""),
            knockout_questions=data.get("knockout_questions", []),
            knockout_index=data.get("knockout_index", 0),
            knockout_results=data.get("knockout_results", []),
            open_questions=data.get("open_questions", []),
            open_index=data.get("open_index", 0),
            open_results=data.get("open_results", []),
            alternate_questions=data.get("alternate_questions", []),
            alternate_index=data.get("alternate_index", 0),
            alternate_results=data.get("alternate_results", []),
            failed_requirement=data.get("failed_requirement", ""),
            unrelated_count=data.get("unrelated_count", 0),
            available_slots=data.get("available_slots", []),
            scheduled_time=data.get("scheduled_time", ""),
            selected_date=data.get("selected_date", ""),
            selected_time=data.get("selected_time", ""),
            outcome=data.get("outcome", ""),
        )

    def to_json(self) -> str:
        """Serialize state to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "ConversationState":
        """Deserialize state from JSON string."""
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# PROMPTS - Simple, focused prompts for each phase
# =============================================================================

HELLO_PROMPT = """Schrijf een welkomstbericht. Je MOET dit exacte formaat volgen:

Hey {candidate_name}! 👋
Super leuk dat je interesse hebt in de functie {vacancy_title}!

Ik heb een paar korte vragen voor je. Dit duurt maar een paar minuutjes.
Ben je klaar om te beginnen?

BELANGRIJK: Begin met "Hey {candidate_name}!" en noem de vacature. Schrijf in het Nederlands (Vlaams)."""

INTENT_READY_PROMPT = """Bepaal of de kandidaat klaar is om te beginnen met het gesprek.

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"ready": true/false}}

- ready=true als de kandidaat instemt, bevestigt, of aangeeft klaar te zijn (ja, ok, yes, sure, prima, etc.)
- ready=false als de kandidaat twijfelt, een vraag stelt, of nog niet wil beginnen"""

READY_START_PROMPT = """Reageer positief op de kandidaat en stel direct de eerste vraag.

Context (niet herhalen in je antwoord):
- Kandidaat zei: "{answer}"
- Eerste vraag om te stellen: {first_question}

Schrijf een natuurlijk WhatsApp bericht:
1. Korte positieve reactie (1 zin, bijv. "Top! Daar gaan we." of "Prima, laten we beginnen!")
2. Stel de eerste vraag

Voorbeeld output:
Top! 🚀 Daar gaan we!

Mag je wettelijk werken in België?

BELANGRIJK: Geef ALLEEN het bericht, geen labels zoals "Reactie:" of "Vraag:"."""

KNOCKOUT_ASK_PROMPT = """Je bent een recruiter. Stel deze vraag op een vriendelijke, directe manier:

"{question}"

Voorbeeld: "Nog een snelle check: [vraag]?" of gewoon de vraag zelf.
Houd het kort (1 zin). Geen inleiding nodig."""

KNOCKOUT_EVAL_PROMPT = """Evalueer of dit antwoord voldoet aan de vereiste.

VEREISTE: {requirement}
ANTWOORD: "{answer}"

Antwoord ALLEEN met JSON: {{"passed": true/false, "summary": "samenvatting"}}

passed=true als de kandidaat bevestigend of positief antwoordt (in elke taal of stijl).
passed=false ALLEEN als de kandidaat expliciet ontkent of aangeeft NIET te voldoen.

Bij twijfel: passed=true."""

KNOCKOUT_PASS_NEXT_PROMPT = """Reageer kort en stel de volgende vraag.

Context (niet herhalen):
- Kandidaat zei: "{answer}"
- Volgende vraag: {next_question}

Schrijf een natuurlijk WhatsApp bericht:
1. Korte reactie (bijv. "Oke!" / "Check!" / "Fijn!" / "Top!")
2. Stel de vraag

Voorbeeld:
Check! ✓

Heb je ervaring met X?

GEEN labels zoals "Reactie:" of "Vraag:". Max 2 zinnen."""

KNOCKOUT_PASS_DONE_PROMPT = """Basisvragen zijn klaar! Nu een open vraag.

Context (niet herhalen):
- Kandidaat zei: "{answer}"
- Volgende vraag: {next_question}

Schrijf een natuurlijk WhatsApp bericht:
1. Korte positieve reactie (bijv. "Prima!" / "Mooi!" / "Top!")
2. Stel de open vraag

GEEN labels. Max 2 zinnen."""

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

OPEN_RECORD_NEXT_PROMPT = """De kandidaat heeft een vraag beantwoord. Reageer kort EN stel de volgende vraag.

Vraag: "{question}"
Antwoord: "{answer}"
Volgende vraag: "{next_question}"

VARIATIE IN REACTIES - pas aan op basis van het antwoord:
- Kort antwoord → kort en neutraal: "Oke!" / "Duidelijk." / "Begrepen!"
- Goed antwoord → positief: "Mooi!" / "Fijn!" / "Interessant!"
- Uitgebreid/sterk antwoord → enthousiast: "Klinkt goed!" / "Dat is mooi!" / "Leuk om te horen!"

BELANGRIJK: Varieer! Herhaal NIET dezelfde woorden als in eerdere berichten.
Max 2 zinnen totaal."""

OPEN_RECORD_DONE_PROMPT = """De kandidaat heeft de laatste vraag beantwoord. Reageer kort EN presenteer de beschikbare tijdsloten.

Antwoord: "{answer}"
Tijdsloten: {slots_text}

Reageer passend bij hun antwoord (kort bij kort antwoord, enthousiaster bij uitgebreid antwoord).
Geef dan aan dat je een korte kennismaking wilt inplannen en presenteer de tijdsloten.
Varieer je woordkeuze. Max 3 zinnen. GEEN handtekening."""

SCHEDULE_CONFIRM_PROMPT = """Bevestig de afspraak in een WhatsApp chat.

Ingepland: {scheduled_time}

BELANGRIJK: Spreek de kandidaat DIRECT aan met "je" (niet in derde persoon).
Noem NIET de naam van de kandidaat in je bericht.

Goed: "Top! Je afspraak staat genoteerd voor {scheduled_time}. Je ontvangt nog een reminder."
Fout: "De afspraak voor [naam] staat genoteerd..."

Bevestig kort, zeg dat ze een reminder krijgen. Max 2 zinnen. GEEN handtekening."""

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

INAPPROPRIATE_EXIT_PROMPT = """Het gesprek wordt beëindigd wegens ongepast taalgebruik.

Kandidaat: {candidate_name}

Geef aan dat je het gesprek moet stoppen omdat we respectvolle communicatie verwachten.
Wens ze succes verder. Blijf professioneel en kort.
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
        import time
        t0 = time.perf_counter()

        # Check for forbidden content FIRST (swear words, hate speech, etc.)
        has_forbidden, matched_term = contains_forbidden_content(user_message)
        if has_forbidden:
            logger.warning(f"⚠️ Forbidden content detected: '{matched_term}' in message from {self.state.candidate_name}")
            return await self._handle_inappropriate_exit()

        phase = self.state.phase
        logger.info(f"🔄 Processing message in phase: {phase.value}")

        if phase == Phase.HELLO:
            result = await self._handle_hello(user_message)
        elif phase == Phase.KNOCKOUT:
            result = await self._handle_knockout(user_message)
        elif phase == Phase.CONFIRM_FAIL:
            result = await self._handle_confirm_fail(user_message)
        elif phase == Phase.ALTERNATE:
            result = await self._handle_alternate(user_message)
        elif phase == Phase.OPEN:
            result = await self._handle_open(user_message)
        elif phase == Phase.SCHEDULE:
            result = await self._handle_schedule(user_message)
        else:
            result = "Bedankt voor je tijd!"

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"⏱️ process_message total: {elapsed:.0f}ms (phase: {phase.value})")
        return result

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

        # Check regex first - if it matches, we can skip the LLM calls entirely
        is_ready, regex_matched = self._evaluate_ready_regex(user_message)

        if regex_matched:
            # Clear yes/no is obviously related, skip LLM checks
            is_unrelated = False
            speculative_response = None
            logger.info(f"✅ HELLO: Regex matched, skipping LLM checks")
        else:
            # Ambiguous answer - run eval + speculative response generation in parallel
            import time
            t_parallel = time.perf_counter()
            logger.info(f"🔀 HELLO: No regex match, running PARALLEL eval + speculative generation...")

            ready_task = self._evaluate_ready_llm(user_message)
            unrelated_task = self._is_unrelated(question, user_message)
            speculative_task = self._generate_speculative_hello_ready(user_message)

            is_ready, is_unrelated, speculative_response = await asyncio.gather(
                ready_task, unrelated_task, speculative_task
            )
            parallel_ms = (time.perf_counter() - t_parallel) * 1000
            logger.info(f"⏱️ HELLO parallel (eval + generate): {parallel_ms:.0f}ms")

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
            # Use speculative response if available
            if speculative_response:
                logger.info(f"✅ HELLO: Using speculative response (saved ~2s)")
                return speculative_response
            # Fallback: generate response
            first_q = self.state.knockout_questions[self.state.knockout_index]
            prompt = READY_START_PROMPT.format(
                candidate_name=self.state.candidate_name,
                answer=user_message,
                first_question=first_q["question"],
            )
            return await self._generate(prompt)
        else:
            # Not ready - speculative response is discarded
            logger.info(f"⚠️ HELLO: Not ready, discarding speculative response")
            prompt = f"""De kandidaat heeft geantwoord: "{user_message}"

Ze zijn nog niet klaar om te beginnen of hadden een vraag.
Reageer kort en vriendelijk, en vraag opnieuw of ze klaar zijn.
Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

    async def _handle_knockout(self, user_message: str) -> str:
        """Handle knockout phase - evaluate answer, move to next or fail."""
        current_q = self.state.knockout_questions[self.state.knockout_index]

        # Check regex first - if it matches, we can skip the LLM calls entirely
        eval_result, regex_matched = self._evaluate_knockout_regex(user_message)

        if regex_matched:
            # Clear yes/no is obviously related, skip LLM checks
            is_unrelated = False
            speculative_response = None
            logger.info(f"✅ KNOCKOUT: Regex matched, skipping LLM checks")
        else:
            # Ambiguous answer - run eval + speculative response generation in parallel
            # This is the key optimization: we generate the "pass" response while evaluating
            import time
            t_parallel = time.perf_counter()
            logger.info(f"🔀 KNOCKOUT: No regex match, running PARALLEL eval + speculative generation...")

            eval_task = self._evaluate_knockout_llm(user_message, current_q)
            unrelated_task = self._is_unrelated(current_q["question"], user_message)
            speculative_task = self._generate_speculative_knockout_pass(user_message)

            eval_result, is_unrelated, speculative_response = await asyncio.gather(
                eval_task, unrelated_task, speculative_task
            )
            parallel_ms = (time.perf_counter() - t_parallel) * 1000
            logger.info(f"⏱️ KNOCKOUT parallel (eval + generate): {parallel_ms:.0f}ms")

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
                # Use speculative response if available, otherwise generate
                if speculative_response:
                    logger.info(f"✅ KNOCKOUT: Using speculative response (saved ~2s)")
                    return speculative_response
                next_q = self.state.open_questions[self.state.open_index]
                prompt = KNOCKOUT_PASS_DONE_PROMPT.format(
                    candidate_name=self.state.candidate_name,
                    answer=user_message,
                    next_question=next_q,
                )
                return await self._generate(prompt)
            else:
                # More knockout questions - use speculative or generate
                if speculative_response:
                    logger.info(f"✅ KNOCKOUT: Using speculative response (saved ~2s)")
                    return speculative_response
                next_q = self.state.knockout_questions[self.state.knockout_index]
                prompt = KNOCKOUT_PASS_NEXT_PROMPT.format(
                    candidate_name=self.state.candidate_name,
                    answer=user_message,
                    next_question=next_q["question"],
                )
                return await self._generate(prompt)
        else:
            # Knockout failed - ask about alternative opportunities
            # Speculative response is discarded
            logger.info(f"⚠️ KNOCKOUT: Failed, discarding speculative response")
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
            # Get slots from Google Calendar (uses GOOGLE_CALENDAR_IMPERSONATE_EMAIL from .env)
            import os
            calendar_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
            slot_data = await scheduling_service.get_available_slots_async(
                recruiter_email=calendar_email,
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
        """Handle scheduling phase - use LLM to extract slot choice, store in state."""
        # Use LLM to extract slot choice
        slot_info = await self._extract_slot_choice(user_message)

        if slot_info and slot_info.get("day") and slot_info.get("time"):
            # Build slot text
            day = slot_info["day"]
            time = slot_info["time"]
            date = slot_info.get("date", "")  # ISO format YYYY-MM-DD from available_slots

            # Build human-readable slot text
            # Find the matching slot to get the full dutch_date
            slot_text = f"{day} om {time}"
            for slot in self.state.available_slots:
                if slot.get("date") == date:
                    slot_text = f"{slot.get('dutch_date', day)} om {time}"
                    break

            # Store scheduling info in state (actual DB save happens in webhook handler)
            self.state.scheduled_time = slot_text
            self.state.selected_date = date
            self.state.selected_time = time
            self.state.phase = Phase.DONE
            self.state.outcome = f"Scheduled: {slot_text}"

            logger.info(f"📅 Slot selected: {slot_text} (date={date}, time={time})")

            return await self._generate_confirm(slot_text)
        else:
            # LLM couldn't extract - ask to clarify
            prompt = f"""De kandidaat zei: "{user_message}"

Je begreep niet welk tijdslot ze willen. Vraag vriendelijk om te verduidelijken.
Noem de beschikbare dagen kort. Geef EEN antwoord, geen alternatieven. Max 2 zinnen."""
            return await self._generate(prompt)

    async def _handle_confirm_fail(self, user_message: str) -> str:
        """Handle confirm_fail phase - check if interested in other opportunities."""
        # Evaluate interest (regex first, then LLM if needed)
        is_interested, regex_matched = await self._evaluate_interest(user_message)
        # Note: We don't need _is_unrelated check here since we're asking a direct yes/no question
        # and both regex and LLM are checking for intent

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
            prompt = f"""De kandidaat heeft een vraag beantwoord. Reageer kort EN stel de volgende vraag.

Vraag: "{current_q}"
Antwoord: "{user_message}"
Volgende vraag: "{next_q}"

Pas je reactie aan op het antwoord:
- Kort antwoord → neutraal: "Oke!" / "Duidelijk." / "Begrepen!"
- Goed antwoord → positief: "Fijn!" / "Mooi!" / "Interessant!"
- Uitgebreid antwoord → enthousiast: "Klinkt goed!" / "Leuk om te horen!"

Varieer je woordkeuze! Max 2 zinnen totaal."""
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

    def _evaluate_ready_regex(self, message: str) -> tuple[bool, bool]:
        """
        Check if user is ready to start using regex only (no LLM).

        Returns:
            tuple: (is_ready, regex_matched)
            - is_ready: True if user wants to start, False if not (only valid if regex_matched=True)
            - regex_matched: True if regex matched a clear yes/no pattern
        """
        import re
        msg = message.lower().strip()

        # Obvious YES patterns (Dutch + English)
        yes_patterns = [
            r"^(ja|yes|yep|yeah|ok|oké|oke|prima|sure|zeker|absoluut|natuurlijk|tuurlijk|graag|goed|top|perfect|laten we|let'?s go|go|start|begin|ready|klaar)[\s!.]*$",
            r"^(ja|yes|ok|oké|prima|zeker|absoluut|natuurlijk|tuurlijk|graag|goed|top|perfect)[,!\s]",
            r"^(ja\s*(hoor|graag|zeker|prima)|yes\s*(please|sure))",
            r"^(ik ben (er\s*)?(klaar|ready)|i'?m ready)",
            r"^(geen probleem|no problem)",
        ]

        # Obvious NO patterns (Dutch + English)
        no_patterns = [
            r"^(nee|no|nope|niet nu|later|nog niet|wacht|wait|stop|cancel|annuleer)[\s!.]*$",
            r"^(nee|no|nope)[,!\s]",
            r"^(ik (heb|kan) (geen|niet)|i (don'?t|can'?t))",
            r"^(helaas|sorry).*(niet|no|kan niet|lukt niet)",
        ]

        for pattern in yes_patterns:
            if re.match(pattern, msg):
                logger.debug(f"Regex match YES: '{msg}'")
                return True, True

        for pattern in no_patterns:
            if re.match(pattern, msg):
                logger.debug(f"Regex match NO: '{msg}'")
                return False, True

        return False, False  # No regex match

    async def _evaluate_ready_llm(self, message: str) -> bool:
        """
        Check if user is ready to start using LLM (called when regex doesn't match).

        Returns:
            bool: True if user wants to start
        """
        prompt = INTENT_READY_PROMPT.format(message=message)
        response = await self._evaluate(prompt)
        result = self._parse_json_response(response, {"ready": True})
        return result.get("ready", True)

    async def _evaluate_interest(self, message: str) -> tuple[bool, bool]:
        """
        Check if user is interested in other opportunities. Uses regex for obvious patterns, LLM for ambiguous.

        Returns:
            tuple: (is_interested, regex_matched)
            - is_interested: True if user wants to explore other options
            - regex_matched: True if regex matched (can skip _is_unrelated check)
        """
        import re
        msg = message.lower().strip()

        # Obvious YES patterns
        yes_patterns = [
            # Exact short answers
            r"^(ja|yes|yep|yeah|ok|oké|prima|sure|zeker|graag|goed)[\s!.]*$",
            # Sentences starting with yes-indicators
            r"^(ja|yes|ok|oké|prima|zeker|graag|goed)[,!\s]",
            # Common phrases
            r"^(ja\s*(hoor|graag|zeker))",
            r"(interesseert me|interesse|wil ik wel|lijkt me leuk|klinkt goed)",
        ]

        # Obvious NO patterns
        no_patterns = [
            # Exact short answers
            r"^(nee|no|nope|niet|nee bedankt|no thanks)[\s!.]*$",
            # Sentences starting with no-indicators
            r"^(nee|no|nope)[,!\s]",
            # Common phrases
            r"^(nee\s*(bedankt|dank je|dankje))",
            r"(geen interesse|niet geïnteresseerd|hoeft niet|laat maar)",
        ]

        for pattern in yes_patterns:
            if re.search(pattern, msg):  # Use search for phrases that can appear anywhere
                logger.debug(f"Interest regex match YES: '{msg}'")
                return True, True

        for pattern in no_patterns:
            if re.search(pattern, msg):
                logger.debug(f"Interest regex match NO: '{msg}'")
                return False, True

        # Ambiguous - use LLM
        logger.debug(f"Interest no regex match, using LLM for: '{msg}'")
        prompt = CONFIRM_INTEREST_PROMPT.format(message=message)
        response = await self._evaluate(prompt)
        result = self._parse_json_response(response, {"interested": True})
        return result.get("interested", True), False

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

    async def _handle_inappropriate_exit(self) -> str:
        """Generate exit message when inappropriate language is detected."""
        self.state.phase = Phase.FAILED
        self.state.outcome = "Exited due to inappropriate language"

        prompt = INAPPROPRIATE_EXIT_PROMPT.format(
            candidate_name=self.state.candidate_name,
        )
        return await self._generate(prompt)

    def _evaluate_knockout_regex(self, answer: str) -> tuple[dict, bool]:
        """
        Evaluate if knockout answer passes using regex only (no LLM).

        Returns:
            tuple: (eval_result, regex_matched)
            - eval_result: {"passed": bool, "summary": str} (only valid if regex_matched=True)
            - regex_matched: True if regex matched a clear yes/no pattern
        """
        import re
        msg = answer.lower().strip()

        # Clear YES patterns - candidate confirms they meet requirement
        yes_patterns = [
            r"^(ja|yes|yep|yeah|ok|oké|oke|zeker|absoluut|natuurlijk|tuurlijk|klopt|correct|inderdaad|dat klopt)[\s!.]*$",
            r"^(ja|yes|ok|oké|zeker|absoluut|natuurlijk|tuurlijk|klopt|correct|inderdaad)[,!\s]",
            r"^(ja\s*(hoor|zeker|absoluut|inderdaad|dat|natuurlijk))",
            r"^(dat klopt|dat is correct|dat heb ik|die heb ik)",
            r"^(geen probleem|no problem)",
        ]

        # Clear NO patterns - candidate confirms they DON'T meet requirement
        no_patterns = [
            r"^(nee|no|nope|helaas|jammer)[\s!.]*$",
            r"^(nee|no|nope|helaas|jammer)[,!\s]",
            r"^(nee\s*(helaas|jammer|dat|sorry))",
            r"^(dat heb ik niet|die heb ik niet|ik heb geen)",
            r"(helaas niet|kan ik niet|lukt niet|heb ik niet)",
        ]

        for pattern in yes_patterns:
            if re.match(pattern, msg):
                logger.debug(f"Knockout regex match YES: '{msg}'")
                return {"passed": True, "summary": "Ja, voldoet aan vereiste"}, True

        for pattern in no_patterns:
            if re.search(pattern, msg):
                logger.debug(f"Knockout regex match NO: '{msg}'")
                return {"passed": False, "summary": "Nee, voldoet niet aan vereiste"}, True

        return {"passed": True, "summary": ""}, False  # No regex match

    async def _evaluate_knockout_llm(self, answer: str, question: dict) -> dict:
        """
        Evaluate if knockout answer passes using LLM (called when regex doesn't match).

        Returns:
            dict: {"passed": bool, "summary": str}
        """
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

    async def _generate_speculative_knockout_pass(self, user_message: str) -> str:
        """
        Speculatively generate response assuming user passed the current knockout question.

        This runs in parallel with evaluation - if user actually passed, we use this response.
        If user failed/unrelated, we discard it and generate the appropriate response.

        This optimization saves ~2s on the happy path (most common case).
        """
        # Figure out what the next question will be (assuming pass)
        next_knockout_index = self.state.knockout_index + 1

        if next_knockout_index >= len(self.state.knockout_questions):
            # This was the last knockout - next is open questions
            next_q = self.state.open_questions[self.state.open_index]
            prompt = KNOCKOUT_PASS_DONE_PROMPT.format(
                candidate_name=self.state.candidate_name,
                answer=user_message,
                next_question=next_q,
            )
        else:
            # More knockout questions coming
            next_q = self.state.knockout_questions[next_knockout_index]
            prompt = KNOCKOUT_PASS_NEXT_PROMPT.format(
                candidate_name=self.state.candidate_name,
                answer=user_message,
                next_question=next_q["question"],
            )

        return await self._generate(prompt)

    async def _generate_speculative_hello_ready(self, user_message: str) -> str:
        """
        Speculatively generate response assuming user is ready to start screening.

        This runs in parallel with evaluation - if user is actually ready, we use this response.
        If user isn't ready/unrelated, we discard it and generate the appropriate response.

        This optimization saves ~2s on the happy path (most common case).
        """
        first_q = self.state.knockout_questions[self.state.knockout_index]
        prompt = READY_START_PROMPT.format(
            candidate_name=self.state.candidate_name,
            answer=user_message,
            first_question=first_q["question"],
        )
        return await self._generate(prompt)

    async def _generate_confirm(self, scheduled_time: str) -> str:
        """Generate scheduling confirmation."""
        prompt = SCHEDULE_CONFIRM_PROMPT.format(
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
        import time
        from google import genai

        t0 = time.perf_counter()
        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=self.config.model_generate,
            contents=prompt,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"⏱️ _generate ({self.config.model_generate}): {elapsed:.0f}ms")
        # Convert Markdown bold (**text**) to WhatsApp bold (*text*)
        text = response.text.replace("**", "*")
        return text

    async def _evaluate(self, prompt: str) -> str:
        """Fast evaluation using lightweight model for JSON responses."""
        import time
        from google import genai

        t0 = time.perf_counter()
        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=self.config.model_evaluate,
            contents=prompt,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"⏱️ _evaluate ({self.config.model_evaluate}): {elapsed:.0f}ms")
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
        company_name=company_name or "ITZU",  # Default to ITZU if not provided
        knockout_questions=knockout_questions,
        open_questions=open_questions,
        alternate_questions=list(config.alternate_questions),
    )
    return SimplePreScreeningAgent(state, config)


def restore_agent_from_state(
    state_json: str,
    config: AgentConfig = None,
) -> SimplePreScreeningAgent:
    """
    Restore an agent from saved state JSON.

    Args:
        state_json: JSON string containing serialized ConversationState
        config: Optional AgentConfig for customization

    Returns:
        SimplePreScreeningAgent with restored state
    """
    config = config or DEFAULT_CONFIG
    state = ConversationState.from_json(state_json)
    return SimplePreScreeningAgent(state, config)


def is_conversation_complete(agent: SimplePreScreeningAgent) -> bool:
    """Check if the conversation has reached a terminal state."""
    return agent.state.phase in [Phase.DONE, Phase.FAILED]


def get_conversation_outcome(agent: SimplePreScreeningAgent) -> dict:
    """
    Get the outcome of a completed conversation.

    Returns:
        dict with:
            - phase: Final phase
            - outcome: Outcome description
            - qualified: Whether candidate passed knockout + completed open questions
            - scheduled_time: Scheduled interview time (if any)
            - knockout_results: List of knockout question results
            - open_results: List of open question results
            - alternate_results: List of alternate intake results (if applicable)
    """
    state = agent.state
    qualified = (
        state.phase == Phase.DONE
        and state.scheduled_time != ""
        and all(r.get("passed", False) for r in state.knockout_results)
    )
    return {
        "phase": state.phase.value,
        "outcome": state.outcome,
        "qualified": qualified,
        "scheduled_time": state.scheduled_time,
        "knockout_results": state.knockout_results,
        "open_results": state.open_results,
        "alternate_results": state.alternate_results,
        "failed_requirement": state.failed_requirement,
    }
