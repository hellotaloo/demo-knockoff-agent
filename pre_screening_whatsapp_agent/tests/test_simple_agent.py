#!/usr/bin/env python3
"""
Test script for the pre-screening agent.

Tests the code-controlled flow where Python manages phase transitions
and the LLM generates conversational responses.

Usage:
    cd taloo-backend
    python -m pre_screening_whatsapp_agent.tests.test_simple_agent
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from ..agent import create_simple_agent, Phase


# Test data - 5 knockout questions
TEST_KNOCKOUT_QUESTIONS = [
    {
        "question": "Heb je een rijbewijs B?",
        "requirement": "Kandidaat moet rijbewijs B hebben"
    },
    {
        "question": "Ben je bereid om in shiften te werken, ook in het weekend?",
        "requirement": "Kandidaat moet flexibel zijn qua werkuren en weekendwerk"
    },
    {
        "question": "Kun je fysiek zwaar werk aan, zoals tillen tot 20kg?",
        "requirement": "Kandidaat moet fysiek in staat zijn om te tillen tot 20kg"
    },
    {
        "question": "Heb je een geldig heftruckcertificaat?",
        "requirement": "Kandidaat moet een geldig heftruckcertificaat hebben"
    },
    {
        "question": "Ben je direct beschikbaar of binnen 2 weken?",
        "requirement": "Kandidaat moet binnen 2 weken kunnen starten"
    },
]

# Test data - 3 open questions
TEST_OPEN_QUESTIONS = [
    "Kun je me vertellen over je ervaring met magazijnwerk of logistiek?",
    "Waarom solliciteer je voor deze functie?",
    "Wat zijn je sterke punten die relevant zijn voor deze job?",
]


async def run_conversation_test(verbose: bool = True):
    """Run a single conversation test through all phases."""

    print("\n" + "=" * 60)
    print("Simple Agent Flow Test")
    print("=" * 60)

    # Create agent
    agent = create_simple_agent(
        candidate_name="Jan",
        vacancy_title="Magazijnmedewerker",
        company_name="ITZU",
        knockout_questions=TEST_KNOCKOUT_QUESTIONS,
        open_questions=TEST_OPEN_QUESTIONS,
    )

    # Simulated candidate responses
    responses = [
        # Welcome confirmation
        "Ja, ik ben klaar!",
        # Knockout 1 - rijbewijs
        "Ja, ik heb mijn rijbewijs B al 5 jaar",
        # Knockout 2 - shiften
        "Ja, geen probleem, ik kan flexibel werken",
        # Knockout 3 - fysiek werk
        "Ja hoor, 20kg tillen is geen probleem voor mij",
        # Knockout 4 - heftruckcertificaat
        "Ja, ik heb vorig jaar mijn heftruckcertificaat gehaald",
        # Knockout 5 - beschikbaarheid
        "Ik kan volgende week al beginnen",
        # Open 1 - ervaring
        "Ik heb 3 jaar bij PostNL gewerkt als orderpicker",
        # Open 2 - motivatie
        "Het is dichtbij en ik zoek een stabiele baan",
        # Open 3 - sterke punten
        "Ik ben heel nauwkeurig en werk graag in team",
        # Scheduling
        "Maandag om 10 uur graag",
    ]

    # Get initial welcome message
    print(f"\n[Phase: {agent.state.phase.value}]")
    initial_msg = await agent.get_initial_message()
    print(f"AGENT: {initial_msg}")

    # Run through responses
    for i, user_response in enumerate(responses):
        print(f"\n{'─' * 40}")
        print(f"USER: {user_response}")

        agent_response = await agent.process_message(user_response)

        print(f"[Phase: {agent.state.phase.value}]")
        print(f"AGENT: {agent_response}")

        # Check if done
        if agent.state.phase in [Phase.DONE, Phase.FAILED]:
            break

    # Print final state
    print(f"\n{'=' * 60}")
    print("FINAL STATE")
    print(f"{'=' * 60}")
    print(f"Phase: {agent.state.phase.value}")
    print(f"Outcome: {agent.state.outcome}")
    print(f"Knockout results: {len(agent.state.knockout_results)}")
    print(f"Open results: {len(agent.state.open_results)}")
    print(f"Scheduled time: {agent.state.scheduled_time}")

    # Determine success
    success = agent.state.phase == Phase.DONE and agent.state.scheduled_time
    print(f"\nTEST {'PASSED' if success else 'FAILED'}")

    return success


async def run_knockout_fail_test():
    """Test that knockout failure works correctly."""

    print("\n" + "=" * 60)
    print("Knockout Failure Test")
    print("=" * 60)

    agent = create_simple_agent(
        candidate_name="Piet",
        vacancy_title="Chauffeur",
        company_name="ITZU",
        knockout_questions=[
            {
                "question": "Heb je een rijbewijs B?",
                "requirement": "Kandidaat moet rijbewijs B hebben"
            }
        ],
        open_questions=["Waarom wil je hier werken?"],
    )

    # Get initial message
    print(f"\n[Phase: {agent.state.phase.value}]")
    initial_msg = await agent.get_initial_message()
    print(f"AGENT: {initial_msg}")

    # Confirm start
    print(f"\n{'─' * 40}")
    print("USER: Ja, ik ben klaar")
    response = await agent.process_message("Ja, ik ben klaar")
    print(f"[Phase: {agent.state.phase.value}]")
    print(f"AGENT: {response}")

    # Fail the knockout
    print(f"\n{'─' * 40}")
    print("USER: Nee, ik heb geen rijbewijs")
    response = await agent.process_message("Nee, ik heb geen rijbewijs")
    print(f"[Phase: {agent.state.phase.value}]")
    print(f"AGENT: {response}")

    # Decline interest in other jobs
    print(f"\n{'─' * 40}")
    print("USER: Nee, bedankt")
    response = await agent.process_message("Nee, bedankt")
    print(f"[Phase: {agent.state.phase.value}]")
    print(f"AGENT: {response}")

    # Check result
    print(f"\n{'=' * 60}")
    print("FINAL STATE")
    print(f"Phase: {agent.state.phase.value}")
    print(f"Outcome: {agent.state.outcome}")

    success = agent.state.phase == Phase.FAILED
    print(f"\nTEST {'PASSED' if success else 'FAILED'}")

    return success


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SIMPLE AGENT TEST SUITE")
    print("=" * 60)

    # Test 1: Full successful flow
    test1_passed = await run_conversation_test()

    # Test 2: Knockout failure
    test2_passed = await run_knockout_fail_test()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Full flow test: {'PASSED' if test1_passed else 'FAILED'}")
    print(f"Knockout fail test: {'PASSED' if test2_passed else 'FAILED'}")

    all_passed = test1_passed and test2_passed
    print(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
