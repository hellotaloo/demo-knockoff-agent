#!/usr/bin/env python3
"""
Stability test for the simple pre-screening agent.

Runs multiple conversations to verify reliability.

Usage:
    cd taloo-backend
    python -m pre_screening_whatsapp_agent.test_simple_stability --runs 10
"""
import asyncio
import argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from .simple_agent import create_simple_agent, Phase


# Test data
TEST_KNOCKOUT_QUESTIONS = [
    {
        "question": "Heb je een rijbewijs B?",
        "requirement": "Kandidaat moet rijbewijs B hebben"
    },
    {
        "question": "Ben je bereid om in shiften te werken, ook in het weekend?",
        "requirement": "Kandidaat moet flexibel zijn qua werkuren"
    },
]

TEST_OPEN_QUESTIONS = [
    "Kun je me vertellen over je ervaring met magazijnwerk?",
    "Waarom solliciteer je voor deze functie?",
]

# Simulated candidate responses for a successful flow
CANDIDATE_RESPONSES = [
    "Ja, ik ben er klaar voor!",
    "Ja, ik heb mijn rijbewijs B al 5 jaar",
    "Ja, ik kan in shiften werken",
    "Ik heb 3 jaar bij PostNL gewerkt",
    "Ik zoek een stabiele baan",
    "Maandag om 10 uur graag",
]


async def run_single_test(test_id: int, verbose: bool = False) -> dict:
    """Run a single conversation test."""
    result = {
        "test_id": test_id,
        "success": False,
        "final_phase": None,
        "turns": 0,
        "error": None,
    }

    try:
        agent = create_simple_agent(
            candidate_name=f"Kandidaat{test_id}",
            vacancy_title="Magazijnmedewerker",
            company_name="ITZU",
            knockout_questions=TEST_KNOCKOUT_QUESTIONS,
            open_questions=TEST_OPEN_QUESTIONS,
        )

        # Get initial message
        _ = await agent.get_initial_message()

        # Process responses
        for response in CANDIDATE_RESPONSES:
            result["turns"] += 1

            if verbose:
                print(f"  [{test_id}] Turn {result['turns']}: {response[:30]}...")

            _ = await agent.process_message(response)

            if agent.state.phase in [Phase.DONE, Phase.FAILED]:
                break

        result["final_phase"] = agent.state.phase.value
        result["success"] = (
            agent.state.phase == Phase.DONE
            and agent.state.scheduled_time != ""
        )

    except Exception as e:
        result["error"] = str(e)
        result["final_phase"] = "error"

    return result


async def run_tests(num_runs: int, verbose: bool = False, parallel: int = 3):
    """Run multiple tests and report results."""
    print(f"\n{'=' * 60}")
    print("Simple Agent Stability Test")
    print(f"{'=' * 60}")
    print(f"Running {num_runs} tests (parallel: {parallel})")
    print(f"Expected flow: hello → knockout → open → schedule → done")
    print(f"{'=' * 60}\n")

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

        # Progress
        completed = len(all_results)
        successes = sum(1 for r in all_results if r["success"])
        print(f"Progress: {completed}/{num_runs} tests ({successes} passed)")

    # Results
    duration = (datetime.now() - start_time).total_seconds()
    successes = [r for r in all_results if r["success"]]
    failures = [r for r in all_results if not r["success"]]

    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")
    print(f"Total tests:     {num_runs}")
    print(f"Passed:          {len(successes)} ({100*len(successes)/num_runs:.1f}%)")
    print(f"Failed:          {len(failures)} ({100*len(failures)/num_runs:.1f}%)")
    print(f"Duration:        {duration:.1f}s")
    print(f"Avg per test:    {duration/num_runs:.2f}s")

    if failures:
        print(f"\n{'=' * 60}")
        print("FAILURES")
        print(f"{'=' * 60}")
        for f in failures[:10]:
            print(f"  Test {f['test_id']}: phase={f['final_phase']}, error={f['error']}")

    # Phase distribution
    print(f"\n{'=' * 60}")
    print("PHASE DISTRIBUTION")
    print(f"{'=' * 60}")
    phase_counts = {}
    for r in all_results:
        phase = r["final_phase"] or "unknown"
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

    for phase, count in sorted(phase_counts.items(), key=lambda x: -x[1]):
        print(f"  {phase}: {count} ({100*count/num_runs:.1f}%)")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="Test simple agent stability")
    parser.add_argument("--runs", type=int, default=10, help="Number of test runs")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--parallel", type=int, default=3, help="Parallel tests")
    args = parser.parse_args()

    asyncio.run(run_tests(args.runs, args.verbose, args.parallel))


if __name__ == "__main__":
    main()
