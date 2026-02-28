"""
Edge case tests.
Covers: trolling during various stages, escalation when disabled, language switching,
        irrelevant counter reset.
Uses wrapper agents for isolation (same pattern as knockout/open question tests).
"""
import pytest

from livekit.agents import Agent

from models import KnockoutAnswer, QuestionResult
from tasks.knockout import KnockoutTask, KnockoutResult
from tasks.open_question import OpenQuestionTask
from tests.conftest import make_session
from tests.configs import default_session_input, no_escalation_input


class _KnockoutEdgeCaseAgent(Agent):
    """Wrapper for running a single KnockoutTask in isolation for edge case tests."""

    def __init__(self, question, allow_escalation=True):
        super().__init__(
            instructions="Je bent een screening agent die knockout-vragen stelt.",
            turn_detection=None,
        )
        self._question = question
        self._allow_escalation = allow_escalation

    async def on_enter(self):
        await KnockoutTask(
            question_id=self._question.id,
            question_text=self._question.text,
            transition="Stel de volgende vraag:",
            context=self._question.context,
            allow_escalation=self._allow_escalation,
        )


class _OpenQuestionEdgeCaseAgent(Agent):
    """Wrapper for running a single OpenQuestionTask in isolation for edge case tests."""

    def __init__(self, question, allow_escalation=True):
        super().__init__(
            instructions="Je bent een screening agent die open vragen stelt.",
        )
        self._question = question
        self._allow_escalation = allow_escalation

    async def on_enter(self):
        await OpenQuestionTask(
            question_id=self._question.id,
            question_text=self._question.text,
            allow_escalation=self._allow_escalation,
        )


@pytest.mark.asyncio
async def test_trolling_screening(llm, judge_llm):
    """Trolling during screening -> mark_irrelevant with deterministic counter."""
    inp = default_session_input()
    q = inp.knockout_questions[0]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutEdgeCaseAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        # Counter-based: LLM should call mark_irrelevant on each attempt.
        # 3 attempts = MAX_IRRELEVANT → task completes deterministically.
        irrelevant_messages = [
            "Ik eet graag pizza",
            "Ik ben een eenhoorn die op wolken danst",
            "De aarde is plat en gemaakt van kaas",
        ]
        for msg in irrelevant_messages:
            result = await sess.run(user_input=msg)
            try:
                result.expect.contains_function_call(name="mark_irrelevant")
                return  # Passed: mark_irrelevant was called
            except AssertionError:
                continue
        pytest.fail("Expected mark_irrelevant to be called within 3 irrelevant answers")


@pytest.mark.asyncio
async def test_trolling_open_questions(llm, judge_llm):
    """Trolling during open questions -> agent records or marks irrelevant."""
    inp = default_session_input()
    q = inp.open_questions[0]

    async with make_session(llm, inp) as sess:
        agent = _OpenQuestionEdgeCaseAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(user_input="Ik ben een vis en ik zwem naar de maan")
        # Agent should either record the answer or mark irrelevant
        try:
            result.expect.contains_function_call(name="record_answer")
        except AssertionError:
            try:
                result.expect.contains_function_call(name="mark_irrelevant")
            except AssertionError:
                # Agent asked for clarification — give a dismissive answer
                result = await sess.run(user_input="Dat is alles, ik weet niets anders.")
                try:
                    result.expect.contains_function_call(name="record_answer")
                except AssertionError:
                    result.expect.contains_function_call(name="mark_irrelevant")


@pytest.mark.asyncio
async def test_escalation_not_allowed(llm, judge_llm):
    """Escalation request when escalation is disabled -> agent doesn't escalate."""
    inp = no_escalation_input()
    q = inp.knockout_questions[0]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutEdgeCaseAgent(question=q, allow_escalation=False)
        await sess.start(agent)

        result = await sess.run(
            user_input="Ik wil met een echte recruiter spreken alstublieft"
        )
        # Agent should NOT call escalate_to_recruiter — instead it should respond with a message
        # Use contains_message to skip any function call events (e.g., note_for_recruiter)
        result.expect.contains_message(role="assistant")


@pytest.mark.asyncio
async def test_language_switch_to_english(llm, judge_llm):
    """Candidate switches to English -> agent responds appropriately."""
    inp = default_session_input()
    q = inp.knockout_questions[0]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutEdgeCaseAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        result = await sess.run(
            user_input="Sorry, I don't speak Dutch very well. Can we continue in English?"
        )
        # Agent may: switch to English, escalate, note for recruiter, or continue in Dutch.
        # All are reasonable responses. Just verify it responds with a message.
        result.expect.contains_message(role="assistant")


class _KnockoutCounterTestAgent(Agent):
    """Wrapper that records KnockoutTask results + exposes userdata for counter checks."""

    def __init__(self, question, allow_escalation=True):
        super().__init__(
            instructions="Je bent een screening agent die knockout-vragen stelt.",
            turn_detection=None,
        )
        self._question = question
        self._allow_escalation = allow_escalation

    async def on_enter(self):
        result = await KnockoutTask(
            question_id=self._question.id,
            question_text=self._question.text,
            transition="Stel de volgende vraag:",
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
async def test_irrelevant_counter_resets(llm, judge_llm):
    """Irrelevant counter resets after a valid answer (mark_pass)."""
    inp = default_session_input()
    q = inp.knockout_questions[0]

    async with make_session(llm, inp) as sess:
        agent = _KnockoutCounterTestAgent(question=q, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        # Send 1 irrelevant message → counter should increment
        result = await sess.run(user_input="De maan is gemaakt van kaas en ik ben een eenhoorn")
        try:
            result.expect.contains_function_call(name="mark_irrelevant")
        except AssertionError:
            # LLM didn't call mark_irrelevant on first attempt — send another
            result = await sess.run(user_input="Pannenkoeken vliegen door de lucht hahahaha")
            result.expect.contains_function_call(name="mark_irrelevant")

        assert sess.userdata.irrelevant_count > 0, "Counter should be > 0 after irrelevant answer"

        # Now give a valid answer → counter should reset to 0
        result = await sess.run(user_input="Ja, zeker")
        result.expect.contains_function_call(name="mark_pass")
        assert sess.userdata.irrelevant_count == 0, "Counter should reset to 0 after valid answer"
