"""
Full flow tests for multi-turn agent interactions.

NOTE: Tests that require multiple sequential KnockoutTask iterations or
TaskGroup-based open questions don't work with session.run() due to the SDK's
internal speech scheduler entering a draining state between tasks. These
behaviors are already covered by per-agent tests (test_knockout_questions.py,
test_open_questions.py).

Tests here cover single-interaction full flow scenarios that DO work.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from agents.screening import ScreeningAgent
from models import CandidateData, QuestionResult
from tests.conftest import make_session
from tests.configs import (
    default_session_input,
    all_known_answers_input,
)


def _patch_no_handoff(sess):
    """Prevent update_agent and shutdown so the session stays alive after agent completes."""
    sess.update_agent = MagicMock()
    sess.shutdown = MagicMock()


@pytest.mark.asyncio
async def test_screening_first_fail(llm, judge_llm):
    """First knockout question fails -> recorded as FAIL, handoff attempted."""
    inp = default_session_input()
    async with make_session(llm, inp) as sess:
        _patch_no_handoff(sess)
        agent = ScreeningAgent(job_title=inp.job_title, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        # Answer first question with NO
        result = await sess.run(user_input="Nee")
        result.expect.next_event().is_message(role="assistant")

        result = await sess.run(user_input="Ja dat klopt, nee")
        result.expect.contains_function_call(name="confirm_fail")

        # Allow on_enter to process the fail result
        await asyncio.sleep(1.0)

        userdata: CandidateData = sess.userdata
        q1_answers = [a for a in userdata.knockout_answers if a.question_id == "q1"]
        assert len(q1_answers) == 1
        assert q1_answers[0].result == QuestionResult.FAIL
        # Verify handoff to AlternativeAgent was attempted
        sess.update_agent.assert_called_once()


@pytest.mark.asyncio
async def test_all_known_skip_screening(llm, judge_llm):
    """All knockout answers pre-known -> screening completed immediately."""
    inp = all_known_answers_input()
    async with make_session(llm, inp) as sess:
        _patch_no_handoff(sess)
        agent = ScreeningAgent(job_title=inp.job_title, allow_escalation=inp.allow_escalation)
        await sess.start(agent)

        # Allow on_enter to process all pre-known answers
        await asyncio.sleep(1.0)

        userdata: CandidateData = sess.userdata
        assert userdata.passed_knockout is True
        assert len(userdata.knockout_answers) == len(inp.knockout_questions)
        assert all(a.result == QuestionResult.PASS for a in userdata.knockout_answers)
        # Verify handoff to OpenQuestionsAgent was attempted
        sess.update_agent.assert_called_once()


@pytest.mark.asyncio
async def test_escalation_mid_screening(llm, judge_llm):
    """Candidate requests recruiter during screening."""
    inp = default_session_input()
    async with make_session(llm, inp) as sess:
        agent = ScreeningAgent(job_title=inp.job_title, allow_escalation=True)
        await sess.start(agent)

        result = await sess.run(
            user_input="Ik wil liever met een echt persoon praten, kan dat?"
        )
        result.expect.contains_function_call(name="escalate_to_recruiter")
