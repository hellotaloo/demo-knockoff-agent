from agents.base import BaseAgent
from i18n import msg
from models import CandidateData, KnockoutAnswer, QuestionResult
from prompts import screening_prompt
from tasks.knockout import KnockoutTask


class ScreeningAgent(BaseAgent):
    def __init__(self, job_title: str, allow_escalation: bool = True) -> None:
        super().__init__(
            instructions=screening_prompt(job_title, allow_escalation=allow_escalation),
            turn_detection=None,  # knockout questions are yes/no, no semantic turn detection needed
            allow_escalation=allow_escalation,
        )

    async def on_enter(self) -> None:
        userdata: CandidateData = self.session.userdata
        userdata.silence_count = 0
        inp = userdata.input
        record = inp.candidate_record if inp.candidate_known else None
        questions = inp.knockout_questions

        # If all knockout questions are already known, skip screening entirely
        if record and all(q.data_key in record.known_answers for q in questions if q.data_key):
            for q in questions:
                userdata.knockout_answers.append(KnockoutAnswer(
                    question_id=q.id,
                    question_text=q.text,
                    result=QuestionResult.PASS,
                    raw_answer=f"(vooraf bekend: {record.known_answers.get(q.data_key, '')})",
                ))
            userdata.passed_knockout = True
            from agents.open_questions import OpenQuestionsAgent
            self.session.update_agent(OpenQuestionsAgent(job_title=inp.job_title, allow_escalation=self._allow_escalation))
            return

        prev_answer = ""
        first_asked = True  # tracks whether this is the first question actually asked
        for i, q in enumerate(questions):
            # Skip questions we already know the answer to
            if record and q.data_key and q.data_key in record.known_answers:
                userdata.knockout_answers.append(KnockoutAnswer(
                    question_id=q.id,
                    question_text=q.text,
                    result=QuestionResult.PASS,
                    raw_answer=f"(vooraf bekend: {record.known_answers[q.data_key]})",
                ))
                continue

            # Build transition text
            remaining = sum(
                1 for rq in questions[i:]
                if not (record and rq.data_key and rq.data_key in record.known_answers)
            )
            if first_asked:
                transition = "Zeg kort 'ok super, dan starten we met een eerste vraag.' en ga meteen over naar de eerste vraag."
                first_asked = False
            elif remaining == 1:
                transition = "Erken het vorige antwoord met een kort woordje zoals een recruiter zou doen (bijv. 'Ok, top.', 'Ah fijn.', 'Prima.'). Noem hoogstens één kernwoord uit het antwoord, niet de hele zin. Zeg dan dat je nog een laatste ja of nee vraagje hebt."
            else:
                transition = "Erken het vorige antwoord met een kort woordje zoals een recruiter zou doen (bijv. 'Ok, top.', 'Ah fijn.', 'Prima.'). Noem hoogstens één kernwoord uit het antwoord, niet de hele zin. Leid de volgende vraag natuurlijk in."

            result = await KnockoutTask(
                question_id=q.id,
                question_text=q.text,
                transition=transition,
                context=q.context,
                allow_escalation=self._allow_escalation,
            )
            prev_answer = result.raw_answer

            userdata.knockout_answers.append(KnockoutAnswer(
                question_id=q.id,
                question_text=q.text,
                result=result.result,
                raw_answer=result.raw_answer,
                candidate_note=result.candidate_note,
            ))

            if result.result == QuestionResult.RECRUITER_REQUESTED:
                from agents.recruiter import RecruiterAgent
                await self.session.say(msg(userdata, "recruiter_handoff"), allow_interruptions=False)
                self.session.update_agent(RecruiterAgent())
                return

            if result.result == QuestionResult.UNCLEAR:
                await self.session.say(msg(userdata, "screening_unclear"), allow_interruptions=False)
                self.session.shutdown(drain=True)
                return

            if result.result == QuestionResult.IRRELEVANT:
                await self.session.say(msg(userdata, "irrelevant_shutdown"), allow_interruptions=False)
                self.session.shutdown(drain=True)
                return

            if result.result == QuestionResult.FAIL:
                from agents.alternative import AlternativeAgent
                self.session.update_agent(AlternativeAgent(
                    job_title=inp.job_title,
                    failed_question=q.text,
                    allow_escalation=self._allow_escalation,
                ))
                return

        # All passed → silent handoff, OpenQuestionsAgent handles the transition speech
        userdata.passed_knockout = True
        from agents.open_questions import OpenQuestionsAgent
        self.session.update_agent(OpenQuestionsAgent(job_title=inp.job_title, allow_escalation=self._allow_escalation))

