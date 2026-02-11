#!/usr/bin/env python3
"""
Test script for pre-screening WhatsApp agent flow stability.

Runs multiple simulated conversations to verify the agent handles
the full flow correctly: welcome → knockout → open questions → scheduling.

Usage:
    cd taloo-backend
    python -m pre_screening_whatsapp_agent.test_flow --runs 10
"""
import asyncio
import argparse
import uuid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agent import root_agent, DEFAULT_TEST_STATE
from src.utils.dutch_dates import get_dutch_date


# Simulated candidate responses for a successful flow
# Note: Answers are kept clear and on-topic to avoid false "unrelated" detection
CANDIDATE_RESPONSES = [
    # Welcome - confirm ready
    "Ja, ik ben er klaar voor!",
    # Knockout 1 - rijbewijs B
    "Ja, ik heb mijn rijbewijs B al 5 jaar",
    # Knockout 2 - shiften werken
    "Ja, ik kan in shiften werken, ook in het weekend",
    # Open question 1 - ervaring met magazijnwerk
    "Ik heb 3 jaar als magazijnmedewerker gewerkt bij PostNL. Daar deed ik orderpicking en voorraadbeheer.",
    # Open question 2 - motivatie
    "Ik wil graag bij jullie werken omdat het dichtbij is en ik een stabiel contract zoek",
    # Scheduling - choose a slot (extra responses in case model asks more)
    "Maandag om 10 uur past mij het beste",
    # Extra responses in case of clarifications
    "Ja, maandag 10 uur is goed",
    "Dat klopt, ik kan dan",
]


async def run_single_test(test_id: int, verbose: bool = False) -> dict:
    """
    Run a single conversation test.

    Returns:
        dict with test results including success status and any errors
    """
    session_id = f"test-{test_id}-{uuid.uuid4().hex[:8]}"
    user_id = f"test-user-{test_id}"

    # Create fresh session service for each test
    session_service = InMemorySessionService()

    # Create runner
    runner = Runner(
        agent=root_agent,
        app_name="pre_screening_test",
        session_service=session_service,
    )

    # Initialize session with test state
    session = await session_service.create_session(
        app_name="pre_screening_test",
        user_id=user_id,
        session_id=session_id,
    )

    # Set initial state
    for key, value in DEFAULT_TEST_STATE.items():
        session.state[key] = value

    # Set today's date
    today = datetime.now()
    session.state["today_date"] = f"{get_dutch_date(today)} {today.year}"

    results = {
        "test_id": test_id,
        "session_id": session_id,
        "success": False,
        "phases_completed": [],
        "errors": [],
        "turns": 0,
        "final_phase": None,
    }

    try:
        for i, user_message in enumerate(CANDIDATE_RESPONSES):
            results["turns"] += 1

            if verbose:
                print(f"  [{test_id}] Turn {i+1}: User says: {user_message[:50]}...")

            # Create user content
            content = types.Content(
                role="user",
                parts=[types.Part(text=user_message)]
            )

            # Run agent turn
            response_parts = []
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
            ):
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                response_parts.append(part.text)

            response_text = " ".join(response_parts) if response_parts else "(no text response)"

            if verbose:
                print(f"  [{test_id}] Agent: {response_text[:100]}...")

            # Get updated session to check state
            updated_session = await session_service.get_session(
                app_name="pre_screening_test",
                user_id=user_id,
                session_id=session_id,
            )

            # Check phase progression
            current_phase = updated_session.state.get("phase", "unknown")
            if current_phase not in results["phases_completed"]:
                results["phases_completed"].append(current_phase)

            # Check if conversation completed
            if updated_session.state.get("conversation_completed"):
                results["success"] = True
                results["final_phase"] = current_phase
                if verbose:
                    print(f"  [{test_id}] Conversation completed successfully!")
                break

            # Check for scheduling completion
            if updated_session.state.get("scheduled_time"):
                results["success"] = True
                results["final_phase"] = "scheduled"
                if verbose:
                    print(f"  [{test_id}] Interview scheduled: {updated_session.state['scheduled_time']}")
                break

        # If we exhausted all responses without completing
        if not results["success"]:
            # Get final session state
            final_session = await session_service.get_session(
                app_name="pre_screening_test",
                user_id=user_id,
                session_id=session_id,
            )
            results["errors"].append(f"Did not complete after {len(CANDIDATE_RESPONSES)} turns")
            results["final_phase"] = final_session.state.get("phase", "unknown") if final_session else "unknown"

    except Exception as e:
        results["errors"].append(str(e))
        results["final_phase"] = "error"
        if verbose:
            print(f"  [{test_id}] ERROR: {e}")

    return results


async def run_tests(num_runs: int, verbose: bool = False, parallel: int = 5):
    """Run multiple conversation tests."""
    print(f"\n{'='*60}")
    print(f"Pre-Screening Agent Flow Test")
    print(f"{'='*60}")
    print(f"Running {num_runs} tests (parallel: {parallel})")
    print(f"Expected flow: welcome → knockout → open_questions → scheduling")
    print(f"{'='*60}\n")

    start_time = datetime.now()

    # Run tests in batches
    all_results = []
    for batch_start in range(0, num_runs, parallel):
        batch_end = min(batch_start + parallel, num_runs)
        batch_tasks = [
            run_single_test(i, verbose)
            for i in range(batch_start, batch_end)
        ]
        batch_results = await asyncio.gather(*batch_tasks)
        all_results.extend(batch_results)

        # Progress update
        completed = len(all_results)
        successes = sum(1 for r in all_results if r["success"])
        print(f"Progress: {completed}/{num_runs} tests ({successes} passed)")

    # Calculate stats
    duration = (datetime.now() - start_time).total_seconds()
    successes = [r for r in all_results if r["success"]]
    failures = [r for r in all_results if not r["success"]]

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Total tests:     {num_runs}")
    print(f"Passed:          {len(successes)} ({100*len(successes)/num_runs:.1f}%)")
    print(f"Failed:          {len(failures)} ({100*len(failures)/num_runs:.1f}%)")
    print(f"Duration:        {duration:.1f}s")
    print(f"Avg per test:    {duration/num_runs:.2f}s")

    if failures:
        print(f"\n{'='*60}")
        print(f"FAILURES")
        print(f"{'='*60}")
        for f in failures[:10]:  # Show first 10 failures
            print(f"  Test {f['test_id']}:")
            print(f"    Final phase: {f['final_phase']}")
            print(f"    Phases seen: {' → '.join(f['phases_completed'])}")
            print(f"    Errors: {f['errors']}")

    # Phase analysis
    print(f"\n{'='*60}")
    print(f"PHASE ANALYSIS")
    print(f"{'='*60}")
    phase_counts = {}
    for r in all_results:
        phase = r["final_phase"] or "unknown"
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

    for phase, count in sorted(phase_counts.items(), key=lambda x: -x[1]):
        print(f"  {phase}: {count} ({100*count/num_runs:.1f}%)")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="Test pre-screening agent flow stability")
    parser.add_argument("--runs", type=int, default=10, help="Number of test runs")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--parallel", type=int, default=5, help="Parallel test runs")
    args = parser.parse_args()

    asyncio.run(run_tests(args.runs, args.verbose, args.parallel))


if __name__ == "__main__":
    main()
