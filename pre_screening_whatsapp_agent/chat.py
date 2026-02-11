#!/usr/bin/env python3
"""
Interactive console chat with the simple pre-screening agent.

Usage:
    cd taloo-backend
    python -m pre_screening_whatsapp_agent.chat
    python -m pre_screening_whatsapp_agent.chat --config config.json
    python -m pre_screening_whatsapp_agent.chat --name "Piet" --vacancy "Chauffeur"
"""
import argparse
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

from .simple_agent import create_simple_agent, Phase


# Default test configuration - 5 knockout + 3 open questions
DEFAULT_KNOCKOUT_QUESTIONS = [
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

DEFAULT_OPEN_QUESTIONS = [
    "Kun je me vertellen over je ervaring met magazijnwerk of logistiek?",
    "Waarom solliciteer je voor deze functie?",
    "Wat zijn je sterke punten die relevant zijn voor deze job?",
]


def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    with open(config_path, "r") as f:
        return json.load(f)


async def run_chat(
    candidate_name: str = "Jan",
    vacancy_title: str = "Magazijnmedewerker",
    company_name: str = "ITZU",
    knockout_questions: list = None,
    open_questions: list = None,
):
    """Run interactive chat session."""
    knockout_questions = knockout_questions or DEFAULT_KNOCKOUT_QUESTIONS
    open_questions = open_questions or DEFAULT_OPEN_QUESTIONS

    print("\n" + "=" * 60)
    print("Simple Pre-Screening Agent - Interactive Chat")
    print("=" * 60)
    print(f"Candidate: {candidate_name}")
    print(f"Vacancy: {vacancy_title} @ {company_name}")
    print(f"Knockout questions: {len(knockout_questions)}")
    print(f"Open questions: {len(open_questions)}")
    print("=" * 60)
    print("Type your responses. Type 'quit' to exit.")
    print("Type 'state' to see current state.")
    print("=" * 60 + "\n")

    # Create agent
    agent = create_simple_agent(
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        company_name=company_name,
        knockout_questions=knockout_questions,
        open_questions=open_questions,
    )

    # Get and show initial message
    initial_msg = await agent.get_initial_message()
    print(f"[{agent.state.phase.value}] AGENT: {initial_msg}\n")

    # Chat loop
    while agent.state.phase not in [Phase.DONE, Phase.FAILED]:
        try:
            user_input = input("YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            print("\nGoodbye!")
            break

        if user_input.lower() == "state":
            print(f"\n--- Current State ---")
            print(f"Phase: {agent.state.phase.value}")
            print(f"Knockout: {agent.state.knockout_index}/{len(agent.state.knockout_questions)}")
            print(f"Open: {agent.state.open_index}/{len(agent.state.open_questions)}")
            print(f"Knockout results: {agent.state.knockout_results}")
            print(f"Open results: {agent.state.open_results}")
            print(f"Scheduled: {agent.state.scheduled_time}")
            print(f"Outcome: {agent.state.outcome}")
            print(f"---------------------\n")
            continue

        # Process message
        response = await agent.process_message(user_input)
        print(f"\n[{agent.state.phase.value}] AGENT: {response}\n")

    # Final summary
    print("\n" + "=" * 60)
    print("CONVERSATION ENDED")
    print("=" * 60)
    print(f"Final phase: {agent.state.phase.value}")
    print(f"Outcome: {agent.state.outcome}")
    if agent.state.scheduled_time:
        print(f"Scheduled: {agent.state.scheduled_time}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Interactive pre-screening agent chat")
    parser.add_argument("--config", "-c", type=str, help="Path to JSON config file")
    parser.add_argument("--name", "-n", type=str, default="Jan", help="Candidate name")
    parser.add_argument("--vacancy", "-v", type=str, default="Magazijnmedewerker", help="Vacancy title")
    parser.add_argument("--company", type=str, default="ITZU", help="Company name")
    args = parser.parse_args()

    # Load config from file or use defaults
    if args.config:
        config = load_config(args.config)
        candidate_name = config.get("candidate_name", args.name)
        vacancy_title = config.get("vacancy_title", args.vacancy)
        company_name = config.get("company_name", args.company)
        knockout_questions = config.get("knockout_questions", DEFAULT_KNOCKOUT_QUESTIONS)
        open_questions = config.get("open_questions", DEFAULT_OPEN_QUESTIONS)
    else:
        candidate_name = args.name
        vacancy_title = args.vacancy
        company_name = args.company
        knockout_questions = DEFAULT_KNOCKOUT_QUESTIONS
        open_questions = DEFAULT_OPEN_QUESTIONS

    asyncio.run(run_chat(
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        company_name=company_name,
        knockout_questions=knockout_questions,
        open_questions=open_questions,
    ))


if __name__ == "__main__":
    main()
