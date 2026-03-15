#!/usr/bin/env python3
"""
Interactive console chat with the document collection agent.

Usage:
    cd taloo-backend
    python agents/document_collection/collection/chat.py
    python agents/document_collection/collection/chat.py --name "Pieter" --vacancy "Productieoperator"

Simulate document uploads:
    --eu-id--          → EU ID-kaart (voor+achterkant)
    --eu-pass--        → EU paspoort
    --non-eu-pass--    → niet-EU paspoort (werkvergunning nodig)
    --img-success--    → document goedgekeurd
    --img-fail--       → document afgekeurd
    --signed--         → contract ondertekend

Type 'state' to see current conversation state.
Type 'quit' to exit.
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agents.document_collection.collection.agent import (
    DocumentCollectionAgent,
    create_collection_agent,
    is_collection_complete,
)
from agents.document_collection.collection.type_cache import MockTypeCache

# ─── Default Test Plan (conversation_flow format) ────────────────────────────

DEFAULT_PLAN = {
    "context": {
        "candidate": "Pieter de Vries",
        "vacancy": "Productieoperator (2 ploegen)",
        "company": "Klant regio Diest",
        "start_date": "2026-03-29",
        "days_remaining": 14,
        "regime": "full",
        "candidacy_stage": "offer",
    },
    "summary": "Verzamelplan voor Pieter de Vries — nieuwe kandidaat, 8 stappen.",
    "verification_flags": {
        "identity_verification": True,
        "work_eligibility": True,
        "address": True,
    },
    "conversation_flow": [
        {
            "step": 1,
            "type": "greeting_and_consent",
            "description": "Begroeting en toestemming vragen",
        },
        {
            "step": 2,
            "type": "identity_verification",
            "description": "Identiteitsdocument verzamelen",
        },
        {
            "step": 3,
            "type": "address_collection",
            "description": "Adresgegevens verzamelen",
        },
        {
            "step": 4,
            "type": "collect_attributes",
            "description": "Persoonsgegevens opvragen",
            "items": [
                {"slug": "has_own_transport", "priority": "recommended", "reason": "Ploegwerk, bereikbaarheid"},
                {"slug": "marital_status", "priority": "required", "reason": "Dimona + contract"},
                {"slug": "iban", "priority": "required", "reason": "Loonuitbetaling"},
                {"slug": "emergency_contact", "priority": "required", "reason": "Noodgevallen"},
            ],
        },
        {
            "step": 5,
            "type": "collect_documents",
            "description": "Aanvullende documenten",
            "items": [
                {"slug": "prato_1", "priority": "recommended", "reason": "Industrie + veiligheidsrisico's"},
                {"slug": "diploma", "priority": "recommended", "reason": "Technische achtergrond"},
                {"slug": "cv", "priority": "recommended", "reason": "Compleet dossier"},
            ],
        },
        {
            "step": 6,
            "type": "medical_screening",
            "description": "Medisch onderzoek inplannen",
            "risks": ["1,1,1-trichloorethaan", "Acetonitril", "Acrylpolymeren"],
            "requires": ["identity_verification"],
        },
        {
            "step": 7,
            "type": "contract_signing",
            "description": "Contract ter ondertekening",
            "requires": ["identity_verification", "address_collection", "collect_attributes"],
        },
        {
            "step": 8,
            "type": "closing",
            "description": "Samenvatting en afsluiting",
        },
    ],
    "attributes_from_documents": [
        {"slug": "date_of_birth", "reason": "Van identiteitsdocument"},
        {"slug": "nationality", "reason": "Van identiteitsdocument"},
        {"slug": "national_register_nr", "reason": "Van identiteitsdocument"},
        {"slug": "work_eligibility", "reason": "Afgeleid uit identiteitsdocument + nationaliteit"},
    ],
}


# ─── Chat Loop ───────────────────────────────────────────────────────────────

def _print_state(agent: DocumentCollectionAgent):
    s = agent.state
    step = agent._current_step()
    print(f"\n{'─' * 50}")
    print(f"  Step: {s.current_step_index + 1}/{len(s.conversation_flow)} ({step['type'] if step else 'done'})")
    print(f"  Item index: {s.step_item_index}")
    print(f"  Consent: {'✅' if s.consent_given else '❌'}")
    print(f"  EU citizen: {s.eu_citizen}")
    print(f"  Work eligibility: {s.work_eligibility}")
    print(f"  Identity phase: {s.identity_phase}")
    print(f"  Address phase: {s.address_phase}")
    print(f"  Completed steps: {s.completed_steps}")
    print(f"  Docs collected: {list(s.collected_documents.keys())}")
    print(f"  Attrs collected: {list(s.collected_attributes.keys())}")
    if s.skipped_items:
        print(f"  Skipped: {[i.get('name', i.get('slug', '?')) for i in s.skipped_items]}")
    if s.partial_attributes:
        print(f"  Partial: {s.partial_attributes}")
    print(f"{'─' * 50}\n")


async def run_chat(
    candidate_name: str = "Pieter de Vries",
    vacancy_title: str = "Productieoperator (2 ploegen)",
    company_name: str = "Klant regio Diest",
    start_date: str = "2026-03-29",
    days_remaining: int = 14,
):
    plan = DEFAULT_PLAN.copy()
    plan["context"] = {
        **plan["context"],
        "candidate": candidate_name,
        "vacancy": vacancy_title,
        "company": company_name,
        "start_date": start_date,
        "days_remaining": days_remaining,
    }

    type_cache = MockTypeCache()

    print("\n" + "=" * 60)
    print("Document Collection Agent — Interactive Chat (v3)")
    print("=" * 60)
    print(f"Kandidaat: {candidate_name}")
    print(f"Vacature: {vacancy_title} @ {company_name}")
    print(f"Startdatum: {start_date} (nog {days_remaining} dagen)")
    print(f"Stappen: {len(plan['conversation_flow'])}")
    print("=" * 60)
    print("Type je antwoorden als kandidaat.")
    print("  --eu-id--        → simuleer EU ID-kaart")
    print("  --eu-pass--      → simuleer EU paspoort")
    print("  --non-eu-pass--  → simuleer niet-EU paspoort (werkvergunning nodig)")
    print("  --img-success--  → simuleer goedgekeurde foto")
    print("  --img-fail--     → simuleer afgekeurde foto")
    print("  --signed--       → simuleer contract ondertekening")
    print("  'state'          → toon huidige status")
    print("  'quit'           → stop")
    print("=" * 60 + "\n")

    agent = create_collection_agent(
        plan=plan,
        type_cache=type_cache,
        collection_id=str(uuid.uuid4()),
        recruiter_name="Sophie Janssen",
        recruiter_email="sophie.janssen@uitzendbureau.be",
    )

    # Send intro
    intro_messages = await agent.get_initial_message()
    step = agent._current_step()
    step_label = step["type"] if step else "done"
    for msg in intro_messages:
        print(f"[{step_label}] AGENT:\n{msg}\n")

    # Chat loop
    while not is_collection_complete(agent):
        try:
            user_input = input("KANDIDAAT: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTot ziens!")
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            print("\nTot ziens!")
            break

        if user_input.lower() == "state":
            _print_state(agent)
            continue

        if user_input.lower() == "json":
            print(json.dumps(agent.state.to_dict(), indent=2, ensure_ascii=False))
            continue

        # Determine if this is an image upload simulation
        has_image = any(tag in user_input for tag in (
            "--img-success--", "--img-fail--",
            "--eu-id--", "--eu-pass--", "--non-eu-pass--",
        ))

        response = await agent.process_message(user_input, has_image=has_image)
        step = agent._current_step()
        step_label = step["type"] if step else "done"
        print(f"\n[{step_label}] AGENT:\n{response}\n")

    # Final summary
    print("\n" + "=" * 60)
    print("GESPREK AFGEROND")
    print("=" * 60)
    _print_state(agent)
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Document collection agent chat (v3)")
    parser.add_argument("--name", "-n", type=str, default="Pieter de Vries")
    parser.add_argument("--vacancy", "-v", type=str, default="Productieoperator (2 ploegen)")
    parser.add_argument("--company", type=str, default="Klant regio Diest")
    parser.add_argument("--start-date", type=str, default="2026-03-29")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    asyncio.run(run_chat(
        candidate_name=args.name,
        vacancy_title=args.vacancy,
        company_name=args.company,
        start_date=args.start_date,
        days_remaining=args.days,
    ))


if __name__ == "__main__":
    main()
