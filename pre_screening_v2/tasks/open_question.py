from dataclasses import dataclass

from livekit.agents import AgentTask, function_tool, llm

from models import MAX_IRRELEVANT, check_irrelevant

MAX_TURNS = 6  # safety net: force-complete after 6 user turns


@dataclass
class OpenQuestionResult:
    answer_summary: str
    candidate_note: str = ""
    recruiter_requested: bool = False
    answered: bool = False  # True only when the candidate actually answered this question


class OpenQuestionTask(AgentTask[OpenQuestionResult]):
    def __init__(self, question_id: str, question_text: str, allow_escalation: bool = True, response_message: str = ""):
        escalation_rule = (
            "- Als de kandidaat vraagt om met een echte persoon of recruiter te praten → roep METEEN `escalate_to_recruiter` aan. Probeer NIET de kandidaat te overtuigen om bij jou te blijven.\n"
            if allow_escalation else ""
        )

        super().__init__(
            turn_detection="vad",  # VAD-only: no semantic model, gives users more time to think
            min_endpointing_delay=2.0,  # wait 2s of silence before committing the turn
            instructions=f"""\
Je stelt een open vraag aan de kandidaat en luistert naar het antwoord.

Vraag: "{question_text}"

# Regels
- Luister naar het antwoord van de kandidaat.
- Als de kandidaat klaar is met antwoorden → roep `record_answer` aan met een korte samenvatting.
- Stel GEEN vervolgvragen. Eén antwoord is genoeg.
- Als de kandidaat duidelijk off-topic of onzinnig antwoordt (trollen, compleet onzin) → roep METEEN `mark_irrelevant` aan. Het systeem houdt bij hoeveel kansen er nog zijn.
- Een kort of vaag antwoord zoals "weet ik niet" of "geen idee" is NIET irrelevant — noteer dit gewoon met `record_answer`.
- Als de kandidaat meer dan 2 verduidelijkende vragen stelt over de vraag → noteer de vragen met `note_for_recruiter` en roep `record_answer` aan met een samenvatting van wat de kandidaat tot nu toe heeft gezegd.
- Gebruik `note_for_recruiter` om vragen of opmerkingen van de kandidaat te bewaren voor de recruiter.
{escalation_rule}""",
        )
        self._question_id = question_id
        self._question_text = question_text
        self._candidate_note = ""
        self._turn_count = 0
        self._allow_escalation = allow_escalation
        self._response_message = response_message

    async def on_enter(self):
        userdata = self.session.userdata

        # If irrelevant limit was already hit on a previous question, skip immediately
        if userdata.irrelevant_count >= MAX_IRRELEVANT:
            self.complete(OpenQuestionResult(
                answer_summary="Gesprek beëindigd wegens irrelevante antwoorden",
            ))
            return

        userdata.silence_count = 0
        userdata.suppress_silence = True
        self.session.clear_user_turn()  # discard any leftover audio from previous answer
        await self.session.generate_reply(
            instructions=f"Stel deze open vraag op een natuurlijke, conversationele manier: {self._question_text}",
            allow_interruptions=False,
        )
        userdata.suppress_silence = False

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        self._turn_count += 1
        if not self.done() and self._turn_count >= MAX_TURNS:
            self.complete(OpenQuestionResult(
                answer_summary="Kandidaat kon de vraag niet beantwoorden",
                candidate_note=self._candidate_note,
                answered=True,
            ))

    @function_tool()
    async def note_for_recruiter(self, note: str):
        """Bewaar een vraag of opmerking van de kandidaat voor de recruiter."""
        self._candidate_note = note

    @function_tool()
    async def record_answer(self, answer_summary: str):
        """Sla het antwoord van de kandidaat op. Roep dit aan zodra je een bruikbaar antwoord hebt."""
        if self.done():
            return
        if self._response_message:
            await self.session.say(self._response_message, allow_interruptions=False)
        self.session.userdata.irrelevant_count = 0
        self.complete(OpenQuestionResult(
            answer_summary=answer_summary,
            candidate_note=self._candidate_note,
            answered=True,
        ))

    @function_tool()
    async def escalate_to_recruiter(self):
        """De kandidaat wil met een echte recruiter praten."""
        if self.done() or not self._allow_escalation:
            return
        self.complete(OpenQuestionResult(
            answer_summary="Kandidaat wil met recruiter praten",
            candidate_note=self._candidate_note,
            recruiter_requested=True,
            answered=True,
        ))

    @function_tool()
    async def mark_irrelevant(self, answer_summary: str):
        """De kandidaat antwoordt irrelevant of onzinnig. Roep dit METEEN aan bij elk irrelevant antwoord."""
        if self.done():
            return
        msg = check_irrelevant(self.session.userdata)
        if msg is None:
            self.complete(OpenQuestionResult(
                answer_summary=answer_summary,
                candidate_note=self._candidate_note,
                answered=True,
            ))
            return
        return msg
