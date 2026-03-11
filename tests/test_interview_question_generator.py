#!/usr/bin/env python3
"""
Test script for the Interview Generator Agent - specifically testing vacancy_snippet linking.

Usage:
    python tests/test_interview_generator.py

Tests that each generated question includes a vacancy_snippet that links back to the source text.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from interview_generator.agent import generator_agent


# Sample vacancy text for testing (Dutch)
SAMPLE_VACANCY = """
Productieoperator - 2 ploegen

Locatie: Diest, Vlaams-Brabant
Type: Voltijds, vast contract

Over de functie:
Je werkt in een 2-ploegensysteem (6u-14u / 14u-22u) in onze moderne productiefaciliteit.
Als productieoperator ben je verantwoordelijk voor het bedienen van CNC-gestuurde machines
en het controleren van de kwaliteit van onze producten.

Wat we zoeken:
- Technische achtergrond of ervaring met productiemachines
- Bereid om in ploegen te werken, inclusief vroege diensten
- Fysiek fit - je staat de hele dag en tilt regelmatig materialen tot 15kg
- Woonachtig in regio Diest of bereid om te pendelen (moeilijk bereikbaar met openbaar vervoer)
- Goede kennis van Nederlands

Wij bieden:
- Competitief salaris + ploegenpremies
- Maaltijdcheques en hospitalisatieverzekering
- Opleiding on-the-job
- Doorgroeimogelijkheden binnen het bedrijf

Interesse? Solliciteer nu!
"""


async def main():
    print("=" * 70)
    print("TEST: Interview Generator - Vacancy Snippet Linking")
    print("=" * 70)
    print()

    # Create in-memory session for testing
    session_service = InMemorySessionService()
    session_id = "test-vacancy-snippet"

    # Create session
    await session_service.create_session(
        app_name="interview_generator",
        user_id="test",
        session_id=session_id
    )

    # Create runner
    runner = Runner(
        agent=generator_agent,
        app_name="interview_generator",
        session_service=session_service
    )

    print("Sending vacancy text to agent...")
    print("-" * 70)
    print(SAMPLE_VACANCY[:200] + "...")
    print("-" * 70)
    print()

    # Run the agent with vacancy text
    content = types.Content(role="user", parts=[types.Part(text=SAMPLE_VACANCY)])

    agent_response = ""
    tool_calls = []

    async for event in runner.run_async(
        user_id="test",
        session_id=session_id,
        new_message=content
    ):
        # Capture tool calls
        if hasattr(event, "actions") and event.actions:
            if hasattr(event.actions, "tool_code_execution_result"):
                pass  # Skip code execution

        # Check for function calls in the event
        if hasattr(event, "content") and event.content:
            if hasattr(event.content, "parts"):
                for part in event.content.parts:
                    # Check for function response
                    if hasattr(part, "function_response"):
                        tool_calls.append(part.function_response)
                    # Check for text response
                    if hasattr(part, "text") and part.text:
                        agent_response += part.text

    print()
    print("=" * 70)
    print("AGENT RESPONSE:")
    print("=" * 70)
    print(agent_response)
    print()

    # Get the session state to retrieve the interview
    session = await session_service.get_session(
        app_name="interview_generator",
        user_id="test",
        session_id=session_id
    )

    interview = session.state.get("interview", {})

    if isinstance(interview, str):
        interview = json.loads(interview)

    print("=" * 70)
    print("GENERATED INTERVIEW STRUCTURE:")
    print("=" * 70)
    print()

    if not interview:
        print("ERROR: No interview was generated!")
        return

    # Print intro
    print(f"INTRO: {interview.get('intro', 'N/A')}")
    print()

    # Print knockout questions with vacancy snippets
    print("-" * 70)
    print("KNOCKOUT QUESTIONS (with vacancy_snippet):")
    print("-" * 70)
    for i, q in enumerate(interview.get("knockout_questions", []), 1):
        print(f"\n{i}. [{q.get('id')}] {q.get('question')}")
        snippet = q.get("vacancy_snippet", "MISSING!")
        print(f"   Vacancy Snippet: \"{snippet}\"")
        print(f"   Status: {q.get('change_status', 'N/A')}")

    print()

    # Print qualification questions with vacancy snippets
    print("-" * 70)
    print("QUALIFICATION QUESTIONS (with vacancy_snippet):")
    print("-" * 70)
    for i, q in enumerate(interview.get("qualification_questions", []), 1):
        print(f"\n{i}. [{q.get('id')}] {q.get('question')}")
        snippet = q.get("vacancy_snippet", "MISSING!")
        print(f"   Vacancy Snippet: \"{snippet}\"")
        print(f"   Ideal Answer: {q.get('ideal_answer', 'N/A')}")
        print(f"   Status: {q.get('change_status', 'N/A')}")

    print()

    # Validation summary
    print("=" * 70)
    print("VALIDATION SUMMARY:")
    print("=" * 70)

    ko_questions = interview.get("knockout_questions", [])
    qual_questions = interview.get("qualification_questions", [])

    ko_with_snippet = sum(1 for q in ko_questions if q.get("vacancy_snippet"))
    qual_with_snippet = sum(1 for q in qual_questions if q.get("vacancy_snippet"))

    print(f"Knockout questions: {len(ko_questions)} total, {ko_with_snippet} with vacancy_snippet")
    print(f"Qualification questions: {len(qual_questions)} total, {qual_with_snippet} with vacancy_snippet")

    all_have_snippet = (ko_with_snippet == len(ko_questions) and
                        qual_with_snippet == len(qual_questions))

    if all_have_snippet:
        print("\nSUCCESS: All questions have vacancy_snippet!")
    else:
        print("\nWARNING: Some questions are missing vacancy_snippet!")

    # Print raw JSON for debugging
    print()
    print("=" * 70)
    print("RAW JSON (for debugging):")
    print("=" * 70)
    print(json.dumps(interview, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
