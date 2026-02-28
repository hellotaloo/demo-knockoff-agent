"""
Parameterized tests for each knockout question.
Tests: clear yes, clear no with confirmation, ambiguous, irrelevant, clarification.
Each scenario runs once per knockout question in the configuration.

Uses a thin wrapper agent (_KnockoutTestAgent) to run a single KnockoutTask
in isolation, avoiding race conditions with ScreeningAgent's task loop.
"""
import pytest

from livekit.agents import Agent

from models import KnockoutAnswer, QuestionResult
from tasks.knockout import KnockoutTask, KnockoutResult
from tests.conftest import make_session
from tests.configs import default_session_input


# Build parameterized IDs from the default config
_inp = default_session_input()
_knockout_ids = [
    pytest.param(i, id=f"{q.id}-{q.data_key}")
    for i, q in enumerate(_inp.knockout_questions)
]


class _KnockoutTestAgent(Agent):
    """Test wrapper that runs a single KnockoutTask in isolation."""

    def __init__(self, question, transition="", allow_escalation=True):
        super().__init__(
            instructions="Je bent een screening agent die knockout-vragen stelt.",
            turn_detection=None,
        )
        self._question = question
        self._transition = transition or "Stel de volgende vraag:"
        self._allow_escalation = allow_escalation

    async def on_enter(self):
        result = await KnockoutTask(
            question_id=self._question.id,
            question_text=self._question.text,
            transition=self._transition,
            context=self._question.context,
            allow_escalation=self._allow_escalation,
        )
        userdata = self.session.userdata
        userdata.knockout_answers.append(KnockoutAnswer(
            question_id=self._question.id,
            question_text=self._question.text,
            result=result.result,
            raw_answer=result.raw_answer,
            candidate_note=result.candidate_note,
        ))


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _knockout_ids)
async def test_knockout_clear_yes(q_index, llm, judge_llm):
    """Clear YES answer -> agent calls mark_pass."""
    inp = default_session_input()
    q = inp.knockout_questions[q_index]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(user_input="Ja, zeker")
        result.expect.contains_function_call(name="mark_pass")


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _knockout_ids)
async def test_knockout_clear_no(q_index, llm, judge_llm):
    """Clear NO answer -> confirmation -> confirm_fail."""
    inp = default_session_input()
    q = inp.knockout_questions[q_index]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(user_input="Nee")
        await result.expect.next_event().is_message(role="assistant").judge(
            judge_llm,
            intent="Asks for confirmation of the negative answer before marking it as failed",
        )

        result = await sess.run(user_input="Ja, dat klopt. Nee.")
        result.expect.contains_function_call(name="confirm_fail")


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _knockout_ids)
async def test_knockout_ambiguous(q_index, llm, judge_llm):
    """Ambiguous answer -> agent asks for clarification."""
    inp = default_session_input()

    async with make_session(llm, inp) as sess:
        q = inp.knockout_questions[q_index]
        agent = _KnockoutTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(user_input="Misschien, dat hangt ervan af")
        result.expect.contains_message(role="assistant")


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _knockout_ids)
async def test_knockout_irrelevant(q_index, llm, judge_llm):
    """Repeated irrelevant answers -> mark_irrelevant."""
    inp = default_session_input()

    async with make_session(llm, inp) as sess:
        q = inp.knockout_questions[q_index]
        agent = _KnockoutTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        # The LLM may call mark_irrelevant on any attempt (1st, 2nd, or 3rd).
        irrelevant_messages = [
            "De maan is gemaakt van kaas en ik ben een eenhoorn",
            "Bananenbrood is de sleutel tot wereldvrede hahahaha",
            "Pannenkoeken vliegen door de lucht en de zon is blauw lol",
        ]
        for msg in irrelevant_messages:
            result = await sess.run(user_input=msg)
            try:
                result.expect.contains_function_call(name="mark_irrelevant")
                return  # Passed: mark_irrelevant was called
            except AssertionError:
                continue
        pytest.fail("Expected mark_irrelevant to be called after 3 irrelevant answers")


@pytest.mark.asyncio
@pytest.mark.parametrize("q_index", _knockout_ids)
async def test_knockout_clarification(q_index, llm, judge_llm):
    """Candidate asks about the question -> agent clarifies."""
    inp = default_session_input()
    q = inp.knockout_questions[q_index]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(user_input="Wat bedoel je daar precies mee?")
        await result.expect.next_event().is_message(role="assistant").judge(
            judge_llm,
            intent="Provides a clarification or rephrases the question, then asks again for a yes or no",
        )
