"""
Parameterized tests for each open question.
Tests: normal answer, short answer, off-topic answer.
Each scenario runs once per open question in the configuration.

Uses a thin wrapper agent (_OpenQuestionTestAgent) to run a single
OpenQuestionTask in isolation, avoiding the ReadyCheckTask and TaskGroup
lifecycle in OpenQuestionsAgent.
"""
import pytest

from livekit.agents import Agent

from models import OpenAnswer
from tasks.open_question import OpenQuestionTask, OpenQuestionResult
from tests.conftest import make_session
from tests.configs import default_session_input


# Build parameterized IDs from the default config
_inp = default_session_input()
_open_ids = [
    pytest.param(i, id=f"{q.id}-{q.description}")
    for i, q in enumerate(_inp.open_questions)
]


class _OpenQuestionTestAgent(Agent):
    """Test wrapper that runs a single OpenQuestionTask in isolation."""

    def __init__(self, question, allow_escalation=True):
        super().__init__(
            instructions="Je bent een screening agent die open vragen stelt.",
        )
        self._question = question
        self._allow_escalation = allow_escalation

    async def on_enter(self):
        result = await OpenQuestionTask(
            question_id=self._question.id,
            question_text=self._question.text,
            allow_escalation=self._allow_escalation,
        )
        userdata = self.session.userdata
        userdata.open_answers.append(OpenAnswer(
            question_id=self._question.id,
            question_text=self._question.text,
            answer_summary=result.answer_summary,
            candidate_note=result.candidate_note,
        ))


_ANSWERS_PER_QUESTION = {
    "oq1": "Ik heb altijd al graag met mensen gewerkt en ik vind het leuk om in een team te werken.",
    "oq2": "Ik ben heel punctueel en ik werk graag in een team. Ik leer ook snel nieuwe dingen.",
    "oq3": "Ik kan meteen starten, ik ben direct beschikbaar.",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _open_ids)
async def test_open_normal_answer(q_index, llm, judge_llm):
    """Substantive answer -> agent records summary via record_answer."""
    inp = default_session_input()
    q = inp.open_questions[q_index]

    async with make_session(llm, inp) as sess:
        agent = _OpenQuestionTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        answer = _ANSWERS_PER_QUESTION.get(q.id, "Ik vind dat een interessante vraag.")
        result = await sess.run(user_input=answer)
        result.expect.contains_function_call(name="record_answer")


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _open_ids)
async def test_open_short_answer(q_index, llm, judge_llm):
    """Very short answer -> agent accepts without follow-up interrogation."""
    inp = default_session_input()

    async with make_session(llm, inp) as sess:
        q = inp.open_questions[q_index]
        agent = _OpenQuestionTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(user_input="Weet ik niet zo goed eigenlijk.")
        result.expect.contains_function_call(name="record_answer")


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _open_ids)
async def test_open_off_topic(q_index, llm, judge_llm):
    """Off-topic answer -> agent records it without extensive follow-up."""
    inp = default_session_input()

    async with make_session(llm, inp) as sess:
        q = inp.open_questions[q_index]
        agent = _OpenQuestionTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        # First attempt: clearly off-topic
        result = await sess.run(
            user_input="Geen idee eigenlijk. Ik heb gisteren een leuke film gezien op Netflix."
        )
        # Agent should either record_answer (even if vague) or mark_irrelevant
        try:
            result.expect.contains_function_call(name="record_answer")
        except AssertionError:
            try:
                result.expect.contains_function_call(name="mark_irrelevant")
            except AssertionError:
                # Agent redirected — give a final dismissive answer
                result = await sess.run(user_input="Dat is alles wat ik erover kan zeggen.")
                try:
                    result.expect.contains_function_call(name="record_answer")
                except AssertionError:
                    result.expect.contains_function_call(name="mark_irrelevant")
