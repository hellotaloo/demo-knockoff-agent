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

from pre_screening_whatsapp_agent.calendar_helpers import (
    get_time_slots_for_whatsapp,
    get_slots_for_specific_day,
    TimeSlot,
    SlotData,
)

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

    # System instruction for consistent tone
    system_instruction: str = """Je bent een professionele recruiter die een pre-screening gesprek voert via WhatsApp.

Stijl:
- Nederlands (Vlaams), professioneel maar warm
- Korte, natuurlijke berichten
- Vermijd "top" en "super"
- GEEN emojis (behalve 📅 📋 bij tijdsloten)
- Geen verkleinwoordjes, geen samenvattingen
- GEEN begroetingen halverwege het gesprek"""

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
    scheduling_attempts: int = 0  # Track how many times we've tried to find slots
    asked_for_day_preference: bool = False  # Whether we've asked for a preferred day

    # Outcome
    outcome: str = ""

    # Test mode (skip real calendar booking)
    is_test: bool = False

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
            "scheduling_attempts": self.scheduling_attempts,
            "asked_for_day_preference": self.asked_for_day_preference,
            "outcome": self.outcome,
            "is_test": self.is_test,
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
            scheduling_attempts=data.get("scheduling_attempts", 0),
            asked_for_day_preference=data.get("asked_for_day_preference", False),
            outcome=data.get("outcome", ""),
            is_test=data.get("is_test", False),
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

Hey {candidate_first_name}! 👋
Leuk dat je interesse hebt in de functie {vacancy_title}.

Ik heb een paar korte vragen voor je. Dit duurt maar een paar minuutjes.
Ben je klaar om te beginnen?

BELANGRIJK: Begin met "Hey {candidate_first_name}! 👋" en noem de vacature. Schrijf in het Nederlands (Vlaams)."""

INTENT_READY_PROMPT = """Bepaal of de kandidaat klaar is om te beginnen met het gesprek.

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"ready": true/false}}

- ready=true als de kandidaat instemt, bevestigt, of aangeeft klaar te zijn (ja, ok, yes, sure, prima, etc.)
- ready=false als de kandidaat twijfelt, een vraag stelt, of nog niet wil beginnen"""

READY_START_PROMPT = """De kandidaat is klaar om te beginnen. Stel de eerste vraag.

Kandidaat zei: "{answer}"
Eerste vraag: {first_question}

Schrijf een kort WhatsApp bericht. Je mag een korte overgang maken of direct de vraag stellen.
Max 2 zinnen. Geen emojis."""

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

KNOCKOUT_PASS_NEXT_PROMPT = """Stel ALLEEN de volgende vraag:
{next_question}

Geen reactie op het vorige antwoord. Geen "fijn", "oké", "mooi". Gewoon de vraag."""

KNOCKOUT_PASS_DONE_PROMPT = """Stel ALLEEN deze vraag:
{next_question}

Geen reactie op het vorige antwoord. Gewoon de vraag."""

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

OPEN_RECORD_NEXT_PROMPT = """Stel ALLEEN de volgende vraag:
{next_question}

Geen reactie op het vorige antwoord. Gewoon de vraag."""

OPEN_RECORD_DONE_PROMPT = """Laatste vraag beantwoord. Ga nu over naar het inplannen van een gesprek.

Tijdsloten:
{slots_text}

Bedank kort, zeg dat je een gesprek wilt inplannen, en toon de tijdsloten.
Kopieer de tijdsloten EXACT (met 📅 en **sterretjes** voor vetgedrukt).

Geen andere emojis. Max 3 zinnen voor je intro."""

SCHEDULE_CONFIRM_PROMPT = """Bevestig de afspraak. Begin met een korte enthousiaste zin (bijv. "Top!", "Super!", "Heel goed!") en dan:

Je gesprek met {recruiter_name} staat gepland:

📅 **{scheduled_time}**
📋 Functie: **{vacancy_title}**

Je ontvangt vooraf nog een reminder.

Komt er iets tussen? Dan kan je hier je afspraak aanpassen.

Succes!

GEEN begroeting zoals "Hoi". Kopieer de rest LETTERLIJK."""

SLOT_EXTRACT_PROMPT = """Extraheer de gekozen dag en tijd uit het bericht van de kandidaat.

BESCHIKBARE SLOTS:
{available_slots}

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"day": "maandag/dinsdag/woensdag/donderdag/vrijdag", "time": "<tijd uit beschikbare slots>", "date": "YYYY-MM-DD"}}

- Zoek de dag (ook afkortingen: ma=maandag, di=dinsdag, woe=woensdag, do=donderdag, vrij=vrijdag)
- Zoek de tijd uit de BESCHIKBARE SLOTS hierboven (of "ochtend"=eerste ochtendslot, "middag"=eerste middagslot)
- Geef de bijbehorende date uit de beschikbare slots
- Als onduidelijk: {{"day": null, "time": null, "date": null}}"""

SCHEDULE_INTENT_PROMPT = """Analyseer wat de kandidaat bedoelt met hun antwoord over de tijdsloten.

BESCHIKBARE SLOTS:
{available_slots}

BERICHT VAN KANDIDAAT: "{message}"

Antwoord ALLEEN met een JSON object:
{{"intent": "slot_choice" | "no_fit" | "specific_day" | "next_week" | "unclear", "day_mentioned": "maandag/dinsdag/woensdag/donderdag/vrijdag/null", "time_preference": "morning" | "afternoon" | null, "outside_hours": true/false}}

Intent types:
- "slot_choice": kandidaat kiest een specifiek moment uit de lijst (dag + tijd)
- "no_fit": kandidaat zegt dat geen enkel moment past ("past niet", "kan niet", "lukt niet", "geen van deze")
- "specific_day": kandidaat noemt een specifieke dag ("vrijdag", "liever donderdag", "volgende week maandag")
- "next_week": kandidaat vraagt om later/volgende week ZONDER specifieke dag ("een week later", "volgende week", "week erna", "later")
- "unclear": onduidelijk wat de kandidaat bedoelt

day_mentioned: als kandidaat een dag noemt (ook als niet in de lijst), geef de dag. Bij "next_week" zonder dag = null.
time_preference: "morning" als kandidaat ochtend/voormiddag wil, "afternoon" als kandidaat middag/namiddag wil, null als geen voorkeur.
  - Voorbeelden "morning": "'s ochtends", "in de ochtend", "voormiddag", "in the morning"
  - Voorbeelden "afternoon": "'s middags", "in de namiddag", "namiddag", "in the afternoon"
outside_hours: true als kandidaat aangeeft alleen 's avonds, weekend, of heel andere tijden te kunnen"""

SCHEDULE_ASK_DAY_PROMPT = """De kandidaat gaf aan dat de voorgestelde momenten niet passen.

Vraag vriendelijk welke dag WEL zou passen voor een gesprek.
Houd het kort (1-2 zinnen). Geen excuses nodig."""

SCHEDULE_NEW_SLOTS_PROMPT = """Je hebt nieuwe beschikbare momenten gevonden voor de gevraagde dag.

Nieuwe tijdsloten:
{slots_text}

Presenteer deze momenten aan de kandidaat. Gebruik altijd de dag + datum in je antwoord.
Voorbeeld: "Op {day_name} {date_short} kan ik je deze momenten aanbieden:"
Dan de tijdsloten EXACT zoals hierboven (met 📅 emoji en ** voor vetgedrukt).
Houd het kort en vriendelijk."""

SCHEDULE_NO_SLOTS_PROMPT = """Er zijn geen beschikbare momenten op de gevraagde dag ({day_name} {date_short}).

Vertel de kandidaat dat er helaas geen momenten beschikbaar zijn op die dag.
Vraag of een andere dag zou passen, of dat ze liever gebeld worden door een recruiter.
Houd het kort (2 zinnen)."""

SCHEDULE_RECRUITER_HANDOFF_PROMPT = """We kunnen geen geschikt moment vinden voor de kandidaat.

Dit kan zijn omdat:
- De kandidaat alleen buiten kantooruren kan
- De gevraagde dag is te ver in de toekomst
- We hebben al meerdere keren geprobeerd

Vertel de kandidaat vriendelijk dat een recruiter contact met hen opneemt om een geschikt moment te vinden.
Bedank voor hun geduld. Max 2 zinnen. GEEN handtekening."""

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

        # TEST COMMANDS - skip to specific phases for testing
        msg_lower = user_message.lower().strip()
        if msg_lower in ["/skip-schedule", "/test-schedule", "!schedule"]:
            logger.info(f"🧪 TEST: Skipping to SCHEDULE phase")
            # Mark all knockout questions as passed
            for q in self.state.knockout_questions:
                self.state.knockout_results.append({
                    "question": q["question"],
                    "answer": "[TEST SKIP]",
                    "passed": True,
                })
            self.state.knockout_index = len(self.state.knockout_questions)
            # Mark all open questions as answered
            for q in self.state.open_questions:
                self.state.open_results.append({
                    "question": q,
                    "answer": "[TEST SKIP]",
                })
            self.state.open_index = len(self.state.open_questions)
            # Jump to schedule phase
            self.state.phase = Phase.SCHEDULE
            return await self._start_scheduling()

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
        # Extract first name only for a more personal greeting
        first_name = self.state.candidate_name.split()[0] if self.state.candidate_name else "daar"
        prompt = HELLO_PROMPT.format(
            company_name=self.state.company_name,
            candidate_first_name=first_name,
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
            # Get slots from Google Calendar (or defaults in test mode)
            slot_data = await get_time_slots_for_whatsapp(
                days_ahead=self.config.schedule_days_ahead,
                start_offset_days=self.config.schedule_start_offset,
                skip_calendar=self.state.is_test,
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

    async def _start_scheduling(self) -> str:
        """
        Start the scheduling phase - fetch slots and present them.

        Used by test commands to skip directly to scheduling.
        """
        slot_data = await get_time_slots_for_whatsapp(
            days_ahead=self.config.schedule_days_ahead,
            start_offset_days=self.config.schedule_start_offset,
            skip_calendar=self.state.is_test,
        )
        self.state.available_slots = [s.model_dump() for s in slot_data.slots]

        # Use the same prompt as the normal flow (OPEN_RECORD_DONE_PROMPT)
        prompt = OPEN_RECORD_DONE_PROMPT.format(
            answer="[TEST SKIP]",
            slots_text=slot_data.formatted_text,
        )
        return await self._generate(prompt)

    async def _handle_schedule(self, user_message: str) -> str:
        """Handle scheduling phase - smart slot selection with day and time preference support."""
        self.state.scheduling_attempts += 1

        # Too many attempts → hand off to recruiter
        if self.state.scheduling_attempts > 3:
            return await self._recruiter_handoff()

        # Analyze intent: slot_choice, no_fit, specific_day, or unclear
        intent_info = await self._analyze_schedule_intent(user_message)
        intent = intent_info.get("intent", "unclear")
        day_mentioned = intent_info.get("day_mentioned")
        time_preference = intent_info.get("time_preference")  # "morning", "afternoon", or None
        outside_hours = intent_info.get("outside_hours", False)

        logger.info(f"📅 Schedule intent: {intent}, day={day_mentioned}, time_pref={time_preference}, outside_hours={outside_hours}")

        # User can only do outside business hours → recruiter handoff
        if outside_hours:
            return await self._recruiter_handoff()

        if intent == "slot_choice":
            # Try to extract the specific slot
            slot_info = await self._extract_slot_choice(user_message)
            if slot_info and slot_info.get("day") and slot_info.get("time"):
                return await self._confirm_slot(slot_info)
            # Couldn't extract → ask to clarify
            return await self._ask_to_clarify(user_message)

        elif intent == "no_fit":
            # No slots work → ask for preferred day
            if not self.state.asked_for_day_preference:
                self.state.asked_for_day_preference = True
                return await self._generate(SCHEDULE_ASK_DAY_PROMPT)
            else:
                # Already asked, still no fit → recruiter handoff
                return await self._recruiter_handoff()

        elif intent == "specific_day" and day_mentioned:
            # User mentioned a specific day → try to find slots for that day
            return await self._get_slots_for_day(day_mentioned, time_preference)

        elif intent == "next_week":
            # User wants slots a week later → fetch slots starting 7 days from now
            return await self._get_slots_next_week(time_preference)

        else:
            # Unclear → ask to clarify
            return await self._ask_to_clarify(user_message)

    async def _confirm_slot(self, slot_info: dict) -> str:
        """Confirm the selected slot and update state, creating Google Calendar event.

        Double-checks availability before booking to prevent conflicts when
        candidates take time to respond.
        """
        import os

        day = slot_info["day"]
        time = slot_info["time"]
        date = slot_info.get("date", "")

        # Build human-readable slot text
        slot_text = f"{day} om {time}"
        for slot in self.state.available_slots:
            if slot.get("date") == date:
                slot_text = f"{slot.get('dutch_date', day)} om {time}"
                break

        # Double-check availability before booking (prevents conflicts if candidate took hours to respond)
        # Skip real calendar lookups in test mode
        recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
        if recruiter_email and date and os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE") and not self.state.is_test:
            try:
                from src.services.google_calendar_service import calendar_service

                # Re-fetch availability for this specific date
                slot = await calendar_service.get_slots_for_date(
                    calendar_email=recruiter_email,
                    target_date=date,
                )

                if slot:
                    # Convert times to "10u" format and check availability
                    all_times = [t.replace(" uur", "u") for t in (slot["morning"] + slot["afternoon"])]
                    time_still_available = time in all_times

                    if not time_still_available:
                        # Slot was taken - refresh available slots and ask again
                        logger.warning(f"📅 Slot {date} {time} no longer available, refreshing slots")
                        slot_data = await get_time_slots_for_whatsapp(
                            days_ahead=self.config.schedule_days_ahead,
                            start_offset_days=self.config.schedule_start_offset,
                        )
                        self.state.available_slots = [s.model_dump() for s in slot_data.slots]

                        if slot_data.slots:
                            prompt = f"""Het moment dat je koos ({slot_text}) is helaas net ingepland door iemand anders.

Hier zijn de nog beschikbare momenten:
{slot_data.formatted_text}

Welk moment past jou het beste?"""
                            return await self._generate(prompt)
                        else:
                            return await self._recruiter_handoff()
                else:
                    # No slots on that date anymore
                    return await self._recruiter_handoff()

            except Exception as e:
                logger.error(f"📅 Error checking availability: {e}")
                # Continue with booking - better to potentially double-book than fail entirely

        # Store scheduling info in state
        self.state.scheduled_time = slot_text
        self.state.selected_date = date
        self.state.selected_time = time
        self.state.phase = Phase.DONE
        self.state.outcome = f"Scheduled: {slot_text}"

        # Note: Calendar event is created by the webhook handler (_save_scheduled_interview)
        # which has access to full vacancy info for the event title/description.
        # This avoids duplicate events and ensures consistent formatting.

        logger.info(f"📅 Slot selected: {slot_text} (date={date}, time={time})")
        return await self._generate_confirm(slot_text)

    async def _ask_to_clarify(self, user_message: str) -> str:
        """Ask user to clarify their slot choice."""
        slots_summary = ", ".join([s.get("dutch_date", "") for s in self.state.available_slots])
        prompt = f"""De kandidaat zei: "{user_message}"

Je begreep niet welk tijdslot ze willen. De beschikbare dagen zijn: {slots_summary}.
Vraag vriendelijk om te verduidelijken welke dag en tijd past. Max 2 zinnen."""
        return await self._generate(prompt)

    async def _recruiter_handoff(self) -> str:
        """Hand off to recruiter when no suitable slot can be found."""
        self.state.phase = Phase.DONE
        self.state.outcome = "Recruiter handoff - no suitable slot"
        logger.info("📅 Scheduling: recruiter handoff")
        return await self._generate(SCHEDULE_RECRUITER_HANDOFF_PROMPT)

    async def _get_slots_for_day(self, day_name: str, time_preference: str = None) -> str:
        """Get available slots for a specific weekday, optionally filtered by time preference."""
        import os
        from datetime import datetime, timedelta

        # Map Dutch day names to weekday numbers (0=Monday, 6=Sunday)
        day_map = {
            "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3,
            "vrijdag": 4, "zaterdag": 5, "zondag": 6,
        }

        weekday = day_map.get(day_name.lower())
        if weekday is None:
            # Unknown day → ask to clarify
            return await self._ask_to_clarify(day_name)

        # Weekend → no business hours available
        if weekday >= 5:
            prompt = f"""De kandidaat vroeg om een moment op {day_name.lower()}.

Vertel vriendelijk dat je alleen doordeweeks (maandag t/m vrijdag) gesprekken kunt inplannen.
Vraag welke doordeweekse dag zou passen. Max 2 zinnen."""
            return await self._generate(prompt)

        # Find the next occurrence of this weekday
        today = datetime.now()
        days_until = (weekday - today.weekday()) % 7
        if days_until == 0:
            days_until = 7  # Next week if today
        target_date = today + timedelta(days=days_until)

        # Check if too far in the future (more than 3 weeks)
        if days_until > 21:
            return await self._recruiter_handoff()

        # Format date for display (lowercase day name in Dutch)
        date_short = f"{target_date.day:02d}/{target_date.month:02d}"

        # Get slots for that day
        slot_data = await get_time_slots_for_whatsapp(
            days_ahead=1,
            start_offset_days=days_until,
            skip_calendar=self.state.is_test,
        )

        if slot_data.slots:
            # Filter by time preference if specified
            filtered_slots, filtered_text = self._filter_slots_by_time(
                slot_data.slots, time_preference
            )

            if filtered_slots:
                # Found slots → update state and present them
                self.state.available_slots = [s.model_dump() for s in filtered_slots]

                # Add context about the filter if applicable
                time_context = ""
                if time_preference == "morning":
                    time_context = " 's ochtends"
                elif time_preference == "afternoon":
                    time_context = " 's middags"

                prompt = f"""Je hebt nieuwe beschikbare momenten gevonden voor {day_name.lower()}{time_context}.

Nieuwe tijdsloten:
{filtered_text}

Presenteer deze momenten aan de kandidaat. Gebruik altijd de dag + datum in je antwoord.
Voorbeeld: "Op {day_name.lower()} {date_short} kan ik je deze momenten aanbieden:"
Dan de tijdsloten EXACT zoals hierboven (met 📅 emoji en ** voor vetgedrukt).
Houd het kort en vriendelijk."""
                return await self._generate(prompt)
            else:
                # Slots exist but not for requested time preference
                time_label = "'s ochtends" if time_preference == "morning" else "'s middags"
                prompt = f"""Er zijn helaas geen momenten beschikbaar op {day_name.lower()} {time_label}.

De kandidaat wilde {time_label}, maar er zijn wel andere momenten op die dag.
Hier zijn alle beschikbare momenten op {day_name.lower()}:
{slot_data.formatted_text}

Vertel de kandidaat dat {time_label} niet lukt, maar bied de andere tijden aan.
Houd het kort en vriendelijk (2-3 zinnen)."""
                self.state.available_slots = [s.model_dump() for s in slot_data.slots]
                return await self._generate(prompt)
        else:
            # No slots on that day
            prompt = SCHEDULE_NO_SLOTS_PROMPT.format(
                day_name=day_name.lower(),  # Dutch: lowercase days
                date_short=date_short,
            )
            return await self._generate(prompt)

    async def _get_slots_next_week(self, time_preference: str = None) -> str:
        """Get available slots starting a week from now, optionally filtered by time preference."""
        # Get slots starting 7 days from now
        slot_data = await get_time_slots_for_whatsapp(
            days_ahead=self.config.schedule_days_ahead,
            start_offset_days=7,  # Start from 1 week later
            skip_calendar=self.state.is_test,
        )

        if slot_data.slots:
            # Filter by time preference if specified
            filtered_slots, filtered_text = self._filter_slots_by_time(
                slot_data.slots, time_preference
            )

            if filtered_slots:
                # Found slots → update state and present them
                self.state.available_slots = [s.model_dump() for s in filtered_slots]

                # Add context about the filter if applicable
                time_context = ""
                if time_preference == "morning":
                    time_context = " 's ochtends"
                elif time_preference == "afternoon":
                    time_context = " 's middags"

                prompt = f"""Je hebt nieuwe beschikbare momenten gevonden voor volgende week{time_context}.

Nieuwe tijdsloten:
{filtered_text}

Presenteer deze momenten aan de kandidaat. Zeg iets als "Geen probleem! Hier zijn de momenten voor volgende week{time_context}:" en dan de tijdsloten EXACT zoals hierboven (met 📅 emoji en ** voor vetgedrukt).
Houd het kort en vriendelijk."""
                return await self._generate(prompt)
            else:
                # Slots exist but not for requested time preference
                time_label = "'s ochtends" if time_preference == "morning" else "'s middags"
                prompt = f"""Er zijn helaas geen momenten beschikbaar volgende week {time_label}.

De kandidaat wilde {time_label}, maar er zijn wel andere momenten.
Hier zijn alle beschikbare momenten voor volgende week:
{slot_data.formatted_text}

Vertel de kandidaat dat {time_label} niet lukt, maar bied de andere tijden aan.
Houd het kort en vriendelijk (2-3 zinnen)."""
                self.state.available_slots = [s.model_dump() for s in slot_data.slots]
                return await self._generate(prompt)
        else:
            # No slots next week either → recruiter handoff
            return await self._recruiter_handoff()

    async def _analyze_schedule_intent(self, message: str) -> dict:
        """Analyze the user's intent regarding scheduling."""
        slots_text = [
            f"- {slot['dutch_date']}: {slot['morning']}, {slot['afternoon']}"
            for slot in self.state.available_slots
        ]
        prompt = SCHEDULE_INTENT_PROMPT.format(
            available_slots="\n".join(slots_text),
            message=message,
        )
        response = await self._evaluate(prompt)
        return self._parse_json_response(response, {"intent": "unclear"})

    def _filter_slots_by_time(self, slots: list, time_preference: str = None) -> tuple[list, str]:
        """
        Filter slots by time preference (morning/afternoon).

        Args:
            slots: List of slot objects from scheduling_service
            time_preference: "morning", "afternoon", or None (no filter)

        Returns:
            tuple: (filtered_slots, formatted_text)
            - filtered_slots: List of slot objects with only matching times
            - formatted_text: Formatted string for display
        """
        if not time_preference or time_preference not in ("morning", "afternoon"):
            # No filter - return as-is
            formatted_lines = []
            for slot in slots:
                times = []
                if slot.morning:
                    times.extend(slot.morning)
                if slot.afternoon:
                    times.extend(slot.afternoon)
                if times:
                    formatted_lines.append(f"📅 **{slot.dutch_date}:** {', '.join(times)}")
            return slots, "\n".join(formatted_lines)

        # Filter slots based on preference
        filtered_slots = []
        formatted_lines = []

        for slot in slots:
            if time_preference == "morning" and slot.morning:
                # Create a modified slot with only morning times
                # TimeSlot imported from calendar_helpers at top of file
                filtered_slot = TimeSlot(
                    date=slot.date,
                    dutch_date=slot.dutch_date,
                    morning=slot.morning,
                    afternoon=[],  # Clear afternoon
                )
                filtered_slots.append(filtered_slot)
                formatted_lines.append(f"📅 **{slot.dutch_date}:** {', '.join(slot.morning)}")

            elif time_preference == "afternoon" and slot.afternoon:
                # Create a modified slot with only afternoon times
                # TimeSlot imported from calendar_helpers at top of file
                filtered_slot = TimeSlot(
                    date=slot.date,
                    dutch_date=slot.dutch_date,
                    morning=[],  # Clear morning
                    afternoon=slot.afternoon,
                )
                filtered_slots.append(filtered_slot)
                formatted_lines.append(f"📅 **{slot.dutch_date}:** {', '.join(slot.afternoon)}")

        return filtered_slots, "\n".join(formatted_lines)

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
            # More questions - just ask the next one, no reaction
            next_q = self.state.alternate_questions[self.state.alternate_index]
            prompt = f"""Stel ALLEEN de volgende vraag:
{next_q}

Geen reactie op het vorige antwoord. Gewoon de vraag."""
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
        # TODO: Refactor to inject recruiter name from context (vacancy/pre-screening settings)
        # For now, hardcoded recruiter name
        recruiter_name = "Sarah Peters"

        prompt = SCHEDULE_CONFIRM_PROMPT.format(
            scheduled_time=scheduled_time,
            recruiter_name=recruiter_name,
            vacancy_title=self.state.vacancy_title,
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
        """Generate text using LLM with system instruction for consistent tone."""
        import time
        from google import genai
        from google.genai import types

        t0 = time.perf_counter()
        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=self.config.model_generate,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.config.system_instruction,
            ),
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"⏱️ _generate ({self.config.model_generate}): {elapsed:.0f}ms")
        return response.text

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
    is_test: bool = False,
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
        is_test: If True, skip real calendar bookings (for simulation/testing)

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
        is_test=is_test,
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
