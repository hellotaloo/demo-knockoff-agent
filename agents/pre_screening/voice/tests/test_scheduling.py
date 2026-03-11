"""
Tests for SchedulingAgent behavior.
Covers: timeslot selection, no-match escalation, existing booking skip.
"""
import pytest

from livekit.agents import mock_tools

from agents.scheduling import SchedulingAgent, _build_slots
from models import CandidateData
from tests.conftest import make_session
from tests.configs import default_session_input


# Mock tools that trigger session.say + shutdown to keep tests isolated
_MOCK_SHUTDOWN = {
    "schedule_with_recruiter": lambda preference: f"Voorkeur genoteerd: {preference}",
    "escalate_to_recruiter": lambda: "Doorverbonden met recruiter.",
    "end_conversation_irrelevant": lambda: "Irrelevant beëindigd.",
}


@pytest.mark.asyncio
async def test_scheduling_select_timeslot(llm, judge_llm):
    """Agent proposes slots, candidate picks one -> confirm_timeslot called."""
    inp = default_session_input()
    async with make_session(llm, inp) as sess:
        agent = SchedulingAgent(
            office_location=inp.office_location,
            office_address=inp.office_address,
            allow_escalation=inp.allow_escalation,
        )
        await sess.start(agent)

        # on_enter says intro + get_available_timeslots + proposes slots
        # Give a specific slot name so the agent can confirm
        slots = _build_slots()
        first_slot = slots[0] if slots else "morgen om 10 uur"
        result = await sess.run(user_input=f"Ja, {first_slot} past perfect voor mij")
        result.expect.contains_function_call(name="confirm_timeslot")

        userdata: CandidateData = sess.userdata
        assert userdata.chosen_timeslot is not None


@pytest.mark.asyncio
async def test_scheduling_no_match(llm, judge_llm):
    """No slots match -> asks preference -> schedule_with_recruiter."""
    inp = default_session_input()
    with mock_tools(SchedulingAgent, _MOCK_SHUTDOWN):
        async with make_session(llm, inp) as sess:
            agent = SchedulingAgent(
                office_location=inp.office_location,
                office_address=inp.office_address,
                allow_escalation=inp.allow_escalation,
            )
            await sess.start(agent)

            result = await sess.run(
                user_input="Geen van die momenten past, alleen in het weekend. Laat maar een recruiter bellen."
            )
            try:
                result.expect.contains_function_call(name="schedule_with_recruiter")
                return
            except AssertionError:
                pass

            # Agent may ask for confirmation first
            result = await sess.run(user_input="Ja, laat de recruiter maar contact opnemen")
            result.expect.contains_function_call(name="schedule_with_recruiter")


@pytest.mark.asyncio
async def test_scheduling_cant_come_to_office(llm, judge_llm):
    """Candidate can't come physically -> escalation with context."""
    inp = default_session_input()
    with mock_tools(SchedulingAgent, _MOCK_SHUTDOWN):
        async with make_session(llm, inp) as sess:
            agent = SchedulingAgent(
                office_location=inp.office_location,
                office_address=inp.office_address,
                allow_escalation=inp.allow_escalation,
            )
            await sess.start(agent)

            result = await sess.run(
                user_input="Ik kan helaas niet fysiek naar het kantoor komen"
            )
            # next_event(type="message") returns ChatMessageAssert directly
            await result.expect.next_event(type="message").judge(
                judge_llm,
                intent="Acknowledges the issue and either asks for more details or escalates to recruiter",
            )


@pytest.mark.asyncio
async def test_scheduling_escalate_to_recruiter(llm, judge_llm):
    """Candidate explicitly asks for recruiter -> escalate_to_recruiter."""
    inp = default_session_input()
    with mock_tools(SchedulingAgent, _MOCK_SHUTDOWN):
        async with make_session(llm, inp) as sess:
            agent = SchedulingAgent(
                office_location=inp.office_location,
                office_address=inp.office_address,
                allow_escalation=True,
            )
            await sess.start(agent)

            result = await sess.run(
                user_input="Kan ik in plaats daarvan met een echte recruiter spreken?"
            )
            result.expect.contains_function_call(name="escalate_to_recruiter")
