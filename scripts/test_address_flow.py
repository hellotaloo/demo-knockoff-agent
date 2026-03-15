"""
Test the address flow in document collection agent.

Scenario 1: domicilie == verblijf (should skip verblijfs_adres)
Scenario 2: domicilie != verblijf (should ask for verblijfs_adres)
"""
import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from agents.document_collection.collection.agent import (
    DocumentCollectionAgent,
    Phase,
    create_collection_agent,
)

DOCUMENTS = [
    {"slug": "id_card", "name": "ID-kaart", "scan_mode": "front_back", "priority": "conditional", "reason": "Identiteitsbewijs", "category": "identity"},
]

ATTRIBUTES = [
    # Address attrs are now hardcoded in the agent factory — no need to pass them here.
    {"slug": "iban", "name": "IBAN rekeningnummer", "reason": "Loonuitbetaling", "collection_method": "ask",
     "ai_hint": "Aan kandidaat vragen."},
]


def create_agent():
    return create_collection_agent(
        collection_id=str(uuid.uuid4()),
        candidate_name="Test Kandidaat",
        vacancy_title="Productieoperator",
        company_name="Test BV",
        start_date="2026-03-20",
        days_remaining=6,
        summary="Test collectie",
        documents_to_collect=DOCUMENTS,
        attributes_to_collect=ATTRIBUTES,
    )


async def run_scenario(name, responses):
    print(f"\n{'='*60}")
    print(f"SCENARIO: {name}")
    print(f"{'='*60}")

    agent = create_agent()

    # Print item queue
    print(f"\nItem queue ({len(agent.state.item_queue)} items):")
    for i, item in enumerate(agent.state.item_queue):
        print(f"  {i+1}. [{item['type']}] {item['slug']} — {item['name']}")

    # Intro
    intro = await agent.get_initial_message()
    for msg in intro:
        print(f"\n🤖 AGENT: {msg}")

    # Process responses
    for user_msg, has_image in responses:
        print(f"\n👤 USER: {user_msg}")
        response = await agent.process_message(user_msg, has_image=has_image)
        print(f"🤖 AGENT: {response}")
        print(f"   [phase={agent.state.phase.value}, idx={agent.state.current_item_index}]")

        if agent.state.phase == Phase.DONE:
            break

    # Summary
    print(f"\n--- RESULTS ---")
    print(f"Collected attrs: {agent.state.collected_attributes}")
    print(f"Skipped items: {[(i['slug'], i.get('skip_reason')) for i in agent.state.skipped_items]}")
    print(f"Phase: {agent.state.phase.value}")


async def main():
    # Scenario 1: Address same as domicile → verblijfs_adres should be auto-skipped
    await run_scenario("Adres gelijk = JA → verblijfs_adres skip", [
        ("--eu-id--", True),                          # ID front
        ("--eu-id--", True),                          # ID back
        ("Kerkstraat 12, 3000 Leuven, België", False), # Domicilie adres
        ("Ja", False),                                 # Adres gelijk = ja
        ("BE68 5390 0754 7034", False),                # IBAN (should be next, verblijfs skipped)
    ])

    # Scenario 2: Address different → should ask for verblijfs_adres
    await run_scenario("Adres gelijk = NEE → verblijfs_adres asked", [
        ("--eu-id--", True),                           # ID front
        ("--eu-id--", True),                           # ID back
        ("Kerkstraat 12, 3000 Leuven, België", False),  # Domicilie adres
        ("Nee", False),                                 # Adres gelijk = nee
        ("Stationsstraat 5, 3010 Kessel-Lo, België", False),  # Verblijfs adres
        ("BE68 5390 0754 7034", False),                 # IBAN
    ])


if __name__ == "__main__":
    asyncio.run(main())
