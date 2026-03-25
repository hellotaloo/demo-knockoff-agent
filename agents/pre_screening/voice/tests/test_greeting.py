"""
Tests for GreetingAgent behavior.
Covers: greeting, identity verification, voicemail, proxy detection,
        consent flow, trolling detection.

Uses mock_tools to prevent handoffs (candidate_ready -> ScreeningAgent)
and session.say/shutdown calls that don't work in text-only test mode.
"""
import pytest

from livekit.agents import mock_tools

from agents.greeting import GreetingAgent
from tests.conftest import make_session
from tests.configs import default_session_input, known_candidate_input, consent_enabled_input


# Mock ALL tools that trigger handoffs or shutdown to keep tests isolated.
# Applied from the start because the LLM may call candidate_ready earlier
# than expected (e.g., combining identity confirmation + ready in one turn).
_MOCK_ALL = {
    "candidate_ready": lambda: "Kandidaat is klaar.",
    "detected_voicemail": lambda: "Voicemail gedetecteerd.",
    "candidate_is_proxy": lambda: "Proxy gedetecteerd.",
    "candidate_not_available": lambda: "Niet beschikbaar.",
    "end_conversation_irrelevant": lambda: "Irrelevant beëindigd.",
}


@pytest.mark.asyncio
async def test_greeting_happy_path(llm, judge_llm):
    """Unknown candidate: hello -> introduction -> 'ja' -> handoff to ScreeningAgent."""
    inp = default_session_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=inp.candidate_known,
                require_consent=inp.require_consent,
            )
            await sess.start(agent)

            result = await sess.run(user_input="Hallo")
            await result.expect.next_event().is_message(role="assistant").judge(
                judge_llm,
                intent="Introduces herself as Anna and explains the purpose of the call",
            )

            result = await sess.run(user_input="Ja, stel maar je vragen")
            result.expect.contains_function_call(name="candidate_ready")


@pytest.mark.asyncio
async def test_greeting_known_candidate(llm, judge_llm):
    """Known candidate: asks to confirm identity before proceeding."""
    inp = known_candidate_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=inp.candidate_known,
                require_consent=inp.require_consent,
            )
            await sess.start(agent)

            result = await sess.run(user_input="Hallo")
            await result.expect.next_event().is_message(role="assistant").judge(
                judge_llm,
                intent=f"Introduces herself and asks if the caller is {inp.candidate_name}",
            )

            result = await sess.run(user_input="Ja, dat ben ik")
            # Agent may confirm identity and call candidate_ready in the same turn,
            # or may ask if the candidate is ready first
            result.expect.contains_message(role="assistant")


@pytest.mark.asyncio
async def test_greeting_voicemail(llm, judge_llm):
    """Voicemail detected -> leaves a message and shuts down."""
    inp = default_session_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=False,
                require_consent=False,
            )
            await sess.start(agent)

            result = await sess.run(
                user_input="Dit is de voicemail van Jan. Laat een bericht achter na de piep."
            )
            result.expect.contains_function_call(name="detected_voicemail")


@pytest.mark.asyncio
async def test_greeting_proxy_caller(llm, judge_llm):
    """Caller is not the candidate -> candidate_is_proxy tool called."""
    inp = known_candidate_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=True,
                require_consent=False,
            )
            await sess.start(agent)

            result = await sess.run(user_input="Hallo")
            result.expect.next_event().is_message(role="assistant")

            result = await sess.run(user_input="Nee, ik ben zijn vrouw. Hij is er niet.")
            result.expect.contains_function_call(name="candidate_is_proxy")


@pytest.mark.asyncio
async def test_greeting_not_available(llm, judge_llm):
    """Candidate has no time -> candidate_not_available tool called."""
    inp = default_session_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=False,
                require_consent=False,
            )
            await sess.start(agent)

            result = await sess.run(user_input="Hallo")
            result.expect.next_event().is_message(role="assistant")

            result = await sess.run(user_input="Nee sorry, ik heb nu echt geen tijd")
            result.expect.contains_function_call(name="candidate_not_available")


@pytest.mark.asyncio
async def test_greeting_consent_yes(llm, judge_llm):
    """Consent enabled + candidate agrees -> record_consent then candidate_ready."""
    inp = consent_enabled_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=False,
                require_consent=True,
            )
            await sess.start(agent)

            result = await sess.run(user_input="Hallo")
            await result.expect.next_event().is_message(role="assistant").judge(
                judge_llm,
                intent="Introduces herself and mentions recording or consent",
            )

            result = await sess.run(user_input="Ja dat is oke")
            result.expect.contains_function_call(name="record_consent")

            result = await sess.run(user_input="Ja, stel maar je vragen")
            result.expect.contains_function_call(name="candidate_ready")


@pytest.mark.asyncio
async def test_greeting_consent_no(llm, judge_llm):
    """Consent enabled + candidate declines -> record_no_consent, conversation continues."""
    inp = consent_enabled_input()
    with mock_tools(GreetingAgent, _MOCK_ALL):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=False,
                require_consent=True,
            )
            await sess.start(agent)

            result = await sess.run(user_input="Hallo")
            result.expect.next_event().is_message(role="assistant")

            result = await sess.run(user_input="Nee, liever niet opnemen")
            result.expect.contains_function_call(name="record_no_consent")

            result = await sess.run(user_input="Ja, ga maar verder")
            result.expect.contains_function_call(name="candidate_ready")


# Mock that excludes end_conversation_irrelevant so the real counter logic runs
_MOCK_TROLLING = {
    "candidate_ready": lambda: "Kandidaat is klaar.",
    "detected_voicemail": lambda: "Voicemail gedetecteerd.",
    "candidate_is_proxy": lambda: "Proxy gedetecteerd.",
    "candidate_not_available": lambda: "Niet beschikbaar.",
}


@pytest.mark.asyncio
async def test_greeting_trolling(llm, judge_llm):
    """Repeated irrelevant answers -> end_conversation_irrelevant with deterministic counter."""
    inp = default_session_input()
    with mock_tools(GreetingAgent, _MOCK_TROLLING):
        async with make_session(llm, inp) as sess:
            agent = GreetingAgent(
                job_title=inp.job_title,
                candidate_name=inp.candidate_name,
                candidate_known=False,
                require_consent=False,
            )
            await sess.start(agent)

            # Counter-based: LLM should call end_conversation_irrelevant on each attempt.
            # 3 attempts = MAX_IRRELEVANT → conversation ends deterministically.
            trolling_messages = [
                "Pizza met ananas is lekker toch?",
                "Ik wil graag een pizza bestellen met extra kaas",
                "Doe maar een quattro formaggi en een cola erbij",
            ]
            for msg in trolling_messages:
                result = await sess.run(user_input=msg)
                try:
                    result.expect.contains_function_call(name="end_conversation_irrelevant")
                    return
                except AssertionError:
                    continue
            pytest.fail("Expected end_conversation_irrelevant to be called within 3 irrelevant answers")
