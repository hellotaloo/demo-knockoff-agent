import logging
from dataclasses import dataclass

from livekit.agents import AgentTask, function_tool, llm

from models import QuestionResult, check_irrelevant

logger = logging.getLogger("knockout")

MAX_TURNS = 4  # question + 3 user turns, then force-exit


@dataclass
class KnockoutResult:
    result: QuestionResult
    raw_answer: str
    candidate_note: str = ""


class KnockoutTask(AgentTask[KnockoutResult]):
    def __init__(self, question_id: str, question_text: str, transition: str = "", context: str = "", allow_escalation: bool = True):
        context_block = f"""
# Context bij deze vraag (ALLEEN voor jouw achtergrondkennis — NOOIT voorlezen of parafraseren!)
{context}
""" if context else ""

        escalation_rule = (
            "- Als de kandidaat vraagt om met een echte persoon of recruiter te praten → roep METEEN `escalate_to_recruiter` aan. Probeer NIET de kandidaat te overtuigen om bij jou te blijven.\n"
            if allow_escalation else ""
        )

        super().__init__(
            turn_detection=None,  # disable semantic turn detection for yes/no questions
            instructions=f"""\
Je stelt een ja/nee knockout-vraag aan de kandidaat.

Vraag: "{question_text}"
{context_block}
# Regels
- Stel de vraag op een natuurlijke, conversationele manier.
- Als de kandidaat JA antwoordt → roep `mark_pass` aan met een korte samenvatting.
- Als de kandidaat NEE antwoordt → herhaal het specifieke antwoord terug als bevestigingsvraag.
  Bijvoorbeeld: als de vraag "Heb je een rijbewijs?" was en de kandidaat zegt nee, vraag dan: "Oke, dus je hebt geen rijbewijs, klopt dat?"
  Gebruik NOOIT een generieke zin zoals "dus dat is een nee?". Verwijs altijd naar het concrete onderwerp.
  - Als de kandidaat bevestigt → roep `confirm_fail` aan.
  - Als de kandidaat zich bedenkt en toch JA zegt → roep `mark_pass` aan.
- Dit zijn ENKEL ja/nee vragen. Vraag NOOIT om meer uitleg, details of toelichting.
- Als het antwoord onduidelijk is → vraag beleefd om ja of nee te antwoorden.
- Als de kandidaat duidelijk off-topic of onzinnig antwoordt (trollen, compleet onzin) → roep METEEN `mark_irrelevant` aan. Het systeem houdt bij hoeveel kansen er nog zijn.
- Roep NOOIT twee tools aan in dezelfde beurt.

# Verduidelijking door de kandidaat
- Lees de context NOOIT spontaan voor. Gebruik het alleen als de kandidaat zelf om verduidelijking vraagt.
- Als de kandidaat een verduidelijkende vraag stelt en het antwoord staat in de context hierboven → geef een kort, vloeiend antwoord in spreektaal en herformuleer de ja/nee vraag.
  Begin NOOIT met "ja" of "nee" als je een verduidelijking geeft — dat klinkt als een antwoord op de knockout-vraag zelf.
  Goed: "Nee hoor, niet elk weekend. Het gaat om een paar weekends per maand." / "Niet per se, horeca of retail telt ook mee."
  Fout: "Ja hoor, het gaat om een paar weekends per maand." (klinkt alsof je 'elk weekend' bevestigt)
  Dus: wees beknopt en natuurlijk, geef NOOIT de volledige context letterlijk weer.
- Als de kandidaat iets vraagt dat NIET in de context staat → verzin NOOIT een antwoord. Roep EERST `note_for_recruiter` aan met de vraag, en zeg daarna dat je het noteert voor de recruiter. Vraag opnieuw ja of nee.
  Bijvoorbeeld: "Goede vraag. Dat noteer ik even zodat de recruiter je daar later over kan informeren. Zou je in principe beschikbaar zijn om in het weekend te werken?"
{escalation_rule}""",
        )
        self._question_id = question_id
        self._question_text = question_text
        self._transition = transition
        self._candidate_note = ""
        self._turn_count = 0
        self._allow_escalation = allow_escalation

    async def on_enter(self):
        userdata = self.session.userdata
        userdata.silence_count = 0
        userdata.suppress_silence = True
        if self._transition:
            intro = f"{self._transition} Stel vervolgens deze vraag op een natuurlijke manier: {self._question_text}"
        else:
            intro = f"Stel deze vraag op een natuurlijke manier: {self._question_text}"
        await self.session.generate_reply(instructions=intro, allow_interruptions=False)
        userdata.suppress_silence = False

    @function_tool()
    async def note_for_recruiter(self, note: str):
        """Bewaar een vraag of opmerking van de kandidaat voor de recruiter. Roep dit aan VOORDAT je mark_pass/confirm_fail aanroept."""
        logger.info(f"[{self._question_id}] note_for_recruiter called: {note}")
        self._candidate_note = note
        return "Genoteerd. Vertel de kandidaat dat je het noteert voor de recruiter en ga verder met de vraag."

    @function_tool()
    async def mark_pass(self, answer_summary: str):
        """De kandidaat heeft JA geantwoord op de knockout-vraag."""
        logger.info(f"[{self._question_id}] mark_pass called: {answer_summary}")
        if self.done():
            return
        self.session.userdata.irrelevant_count = 0
        self.complete(KnockoutResult(
            result=QuestionResult.PASS,
            raw_answer=answer_summary,
            candidate_note=self._candidate_note,
        ))

    @function_tool()
    async def confirm_fail(self, answer_summary: str):
        """De kandidaat heeft NEE geantwoord en dit bevestigd na navraag."""
        logger.info(f"[{self._question_id}] confirm_fail called: {answer_summary}")
        if self.done():
            return
        self.session.userdata.irrelevant_count = 0
        self.complete(KnockoutResult(
            result=QuestionResult.FAIL,
            raw_answer=answer_summary,
            candidate_note=self._candidate_note,
        ))

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        self._turn_count += 1
        if not self.done() and self._turn_count >= MAX_TURNS:
            logger.info(f"[{self._question_id}] max turns reached, force-completing as UNCLEAR")
            self.complete(KnockoutResult(
                result=QuestionResult.UNCLEAR,
                raw_answer="Kandidaat kon de vraag niet beantwoorden",
                candidate_note=self._candidate_note,
            ))

    @function_tool()
    async def escalate_to_recruiter(self):
        """De kandidaat wil met een echte recruiter praten."""
        logger.info(f"[{self._question_id}] escalate_to_recruiter called")
        if self.done() or not self._allow_escalation:
            return
        self.complete(KnockoutResult(
            result=QuestionResult.RECRUITER_REQUESTED,
            raw_answer="Kandidaat wil met recruiter praten",
            candidate_note=self._candidate_note,
        ))

    @function_tool()
    async def mark_irrelevant(self, answer_summary: str):
        """De kandidaat antwoordt irrelevant of onzinnig. Roep dit METEEN aan bij elk irrelevant antwoord."""
        logger.info(f"[{self._question_id}] mark_irrelevant called: {answer_summary}")
        if self.done():
            return
        msg = check_irrelevant(self.session.userdata)
        if msg is None:
            self.complete(KnockoutResult(
                result=QuestionResult.IRRELEVANT,
                raw_answer=answer_summary,
                candidate_note=self._candidate_note,
            ))
            return
        return msg
