from livekit.agents import RunContext, function_tool

from agents.base import BaseAgent
from i18n import msg
from models import CandidateData
from prompts import alternative_prompt

ALTERNATIVE_QUESTIONS = [
    ("alt1", "In welke regio zoek je werk?", "Ok, goed, in die regio hebben we meer dan 50 vacatures."),
    ("alt2", "Zoek je fulltime, parttime of flex?", ""),
    ("alt3", "Heb je ervaring in een bepaalde sector? Bijvoorbeeld logistiek, productie, retail?", ""),
]


class AlternativeAgent(BaseAgent):
    def __init__(self, job_title: str, failed_question: str, allow_escalation: bool = True) -> None:
        super().__init__(
            instructions=alternative_prompt(job_title, allow_escalation=allow_escalation),
            turn_detection=None,  # yes/no + short answers, no semantic turn detection needed
            allow_escalation=allow_escalation,
        )
        self._failed_question = failed_question

    async def on_enter(self) -> None:
        self.session.userdata.silence_count = 0
        await self.session.generate_reply(
            instructions=f"De kandidaat voldeed niet aan de vereiste: '{self._failed_question}'. "
            "Zeg dat dat jammer is maar dat je graag wil kijken of er andere mogelijkheden zijn. "
            "Vraag of de kandidaat interesse heeft in andere vacatures."
        )

    @function_tool()
    async def candidate_interested(self, context: RunContext):
        """De kandidaat heeft interesse in andere vacatures."""
        userdata: CandidateData = self.session.userdata
        userdata.irrelevant_count = 0
        userdata.interested_in_alternatives = True

        question_specs = [(q_id, q_text, q_text, q_response) for q_id, q_text, q_response in ALTERNATIVE_QUESTIONS]
        recruiter_requested = await self._run_open_questions(question_specs)

        if recruiter_requested:
            from agents.recruiter import RecruiterAgent
            await self.session.say(msg(userdata, "recruiter_handoff"), allow_interruptions=False)
            self.session.update_agent(RecruiterAgent())
            return

        await self.session.say(msg(userdata, "alternative_thanks"), allow_interruptions=False)
        self.session.shutdown(drain=True)

    @function_tool()
    async def candidate_not_interested(self, context: RunContext):
        """De kandidaat heeft geen interesse in andere vacatures."""
        await self.session.say(msg(self.session.userdata, "alternative_not_interested"), allow_interruptions=False)
        self.session.shutdown(drain=True)

