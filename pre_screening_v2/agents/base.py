from livekit.agents import Agent, RunContext, function_tool

from i18n import SUPPORTED_LANGUAGES, deepgram_code, msg
from models import MAX_IRRELEVANT, check_irrelevant


class BaseAgent(Agent):
    """Base class for all prescreening agents. Provides shared tools."""

    def __init__(self, *, allow_escalation: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self._allow_escalation = allow_escalation

    @function_tool()
    async def switch_language(self, context: RunContext, language: str):
        """Switch the conversation language. Use when the candidate speaks a different language.
        Supported: nl, en, fr, de, es, it, pt, pl, tr, ar, ja, zh, hi, ko, id, fil, sv, bg, ro, cs, el, fi, hr, ms, sk, da, ta, uk, ru, hu, no, vi."""
        lang = language.lower().strip()
        if lang not in SUPPORTED_LANGUAGES:
            return f"Language '{lang}' is not supported. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        userdata = self.session.userdata
        userdata.language = lang
        self.session.tts.update_options(language=lang)
        self.session.stt.update_options(language=deepgram_code(lang))
        return f"Language switched to {lang}. Continue the conversation in this language."

    @function_tool()
    async def escalate_to_recruiter(self, context: RunContext):
        """De kandidaat wil met een echte recruiter praten."""
        if not self._allow_escalation:
            return
        from agents.recruiter import RecruiterAgent
        await self.session.say(msg(self.session.userdata, "recruiter_handoff"), allow_interruptions=False)
        self.session.update_agent(RecruiterAgent())

    @function_tool()
    async def end_conversation_irrelevant(self, context: RunContext):
        """De kandidaat antwoordt irrelevant of onzinnig. Roep dit METEEN aan bij elk irrelevant antwoord."""
        result = check_irrelevant(self.session.userdata, suffix="om bij het onderwerp te blijven")
        if result is None:
            await self.session.say(msg(self.session.userdata, "irrelevant_shutdown"), allow_interruptions=False)
            self.session.shutdown(drain=True)
            return
        return result

    async def _run_open_questions(
        self, questions: list[tuple[str, str, str, str]]
    ) -> bool:
        """Run open questions via TaskGroup. Returns True if recruiter was requested.

        Args:
            questions: list of (id, text, description, response_message) tuples.
        """
        from livekit.agents.beta.workflows import TaskGroup
        from models import OpenAnswer
        from tasks.open_question import OpenQuestionTask

        userdata = self.session.userdata

        task_group = TaskGroup(chat_ctx=self.chat_ctx)
        for q_id, q_text, q_desc, q_response in questions:
            task_group.add(
                lambda qid=q_id, qt=q_text, qr=q_response, esc=self._allow_escalation: OpenQuestionTask(
                    question_id=qid, question_text=qt, allow_escalation=esc, response_message=qr,
                ),
                id=q_id,
                description=q_desc or q_text,
            )

        results = await task_group
        recruiter_requested = False
        for q_id, q_text, _, _ in questions:
            result = results.task_results.get(q_id)
            if result:
                if result.recruiter_requested:
                    recruiter_requested = True
                if not result.answered:
                    continue  # Skip questions that were never actually asked/answered
                userdata.open_answers.append(OpenAnswer(
                    question_id=q_id,
                    question_text=q_text,
                    answer_summary=result.answer_summary,
                    candidate_note=result.candidate_note,
                ))

        return recruiter_requested
