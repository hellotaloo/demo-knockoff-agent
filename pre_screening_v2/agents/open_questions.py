from livekit.agents import AgentSession

from agents.base import BaseAgent
from i18n import msg
from models import CandidateData, MAX_IRRELEVANT
from prompts import open_questions_prompt
from tasks.ready_check import ReadyCheckTask


def _set_user_away_timeout(session: AgentSession, timeout: float):
    """Set user_away_timeout via private API. Isolated here for easy update when SDK adds a public API."""
    try:
        session._opts.user_away_timeout = timeout
    except AttributeError:
        pass


class OpenQuestionsAgent(BaseAgent):
    def __init__(self, job_title: str, allow_escalation: bool = True) -> None:
        super().__init__(
            instructions=open_questions_prompt(job_title, allow_escalation=allow_escalation),
            allow_escalation=allow_escalation,
        )

    async def on_enter(self) -> None:
        userdata: CandidateData = self.session.userdata
        userdata.silence_count = 0
        inp = userdata.input
        questions = inp.open_questions

        # Increase user_away_timeout for open questions (users need more thinking time)
        _set_user_away_timeout(self.session, 6.0)

        ready = await ReadyCheckTask(
            message=msg(userdata, "ready_check"),
        )

        if not ready:
            if userdata.irrelevant_count >= MAX_IRRELEVANT:
                await self.session.say(msg(userdata, "irrelevant_shutdown"), allow_interruptions=False)
            else:
                await self.session.say(msg(userdata, "ready_check_decline"), allow_interruptions=False)
            self.session.shutdown(drain=True)
            return

        # TaskGroup with regression — user can go back and amend previous answers
        question_specs = [(q.id, q.text, q.description or q.text, "") for q in questions]
        recruiter_requested = await self._run_open_questions(question_specs)

        # Restore default user_away_timeout
        _set_user_away_timeout(self.session, 4.0)

        # Check if irrelevant limit was hit during open questions
        if userdata.irrelevant_count >= MAX_IRRELEVANT:
            await self.session.say(msg(userdata, "irrelevant_shutdown"), allow_interruptions=False)
            self.session.shutdown(drain=True)
            return

        if recruiter_requested:
            from agents.recruiter import RecruiterAgent
            await self.session.say(msg(userdata, "recruiter_handoff"), allow_interruptions=False)
            self.session.update_agent(RecruiterAgent())
            return

        # Silent handoff to scheduling (or skip if existing booking)
        userdata.suppress_silence = True
        await self.session.say(msg(userdata, "open_questions_thanks"), allow_interruptions=False)
        userdata.suppress_silence = False

        record = inp.candidate_record if inp.candidate_known else None
        if record and record.existing_booking_date:
            await self.session.say(
                msg(userdata, "existing_booking", date=record.existing_booking_date),
                allow_interruptions=False,
            )
            self.session.shutdown(drain=True)
            return

        from agents.scheduling import SchedulingAgent
        self.session.update_agent(SchedulingAgent(
            office_location=inp.office_location,
            office_address=inp.office_address,
            allow_escalation=self._allow_escalation,
        ))

