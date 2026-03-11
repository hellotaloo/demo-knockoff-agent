#!/usr/bin/env python3
"""
Test script for CandidateContextService.

Run with: python test_candidate_context.py [candidate_id] [vacancy_id]

Examples:
  python test_candidate_context.py                      # Lists candidates to choose from
  python test_candidate_context.py <candidate_id>       # Get context for specific candidate
  python test_candidate_context.py <candidate_id> <vacancy_id>  # With vacancy context
"""
import asyncio
import sys
import json
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from src.database import get_db_pool, close_db_pool
from src.services.candidate_context_service import CandidateContextService


def format_json(obj):
    """Format object as pretty JSON."""
    def default_serializer(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, indent=2, default=default_serializer, ensure_ascii=False)


async def list_candidates(pool, limit=10):
    """List recent candidates for selection."""
    rows = await pool.fetch(
        """
        SELECT c.id, c.full_name, c.phone, c.status, c.is_test, c.created_at,
               COUNT(DISTINCT a.id) as app_count
        FROM ats.candidates c
        LEFT JOIN ats.applications a ON a.candidate_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC
        LIMIT $1
        """,
        limit
    )

    print("\n" + "=" * 80)
    print("BESCHIKBARE KANDIDATEN")
    print("=" * 80)

    for i, row in enumerate(rows, 1):
        test_badge = " [TEST]" if row['is_test'] else ""
        print(f"\n{i}. {row['full_name']}{test_badge}")
        print(f"   ID: {row['id']}")
        print(f"   Telefoon: {row['phone'] or 'Onbekend'}")
        print(f"   Status: {row['status']}")
        print(f"   Sollicitaties: {row['app_count']}")

    return rows


async def list_vacancies(pool, limit=10):
    """List recent vacancies for selection."""
    rows = await pool.fetch(
        """
        SELECT v.id, v.title, v.company, v.status, r.name as recruiter_name
        FROM ats.vacancies v
        LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
        WHERE v.status = 'open'
        ORDER BY v.created_at DESC
        LIMIT $1
        """,
        limit
    )

    print("\n" + "=" * 80)
    print("OPEN VACATURES")
    print("=" * 80)

    for i, row in enumerate(rows, 1):
        recruiter = f" (Recruiter: {row['recruiter_name']})" if row['recruiter_name'] else ""
        print(f"\n{i}. {row['title']} - {row['company']}{recruiter}")
        print(f"   ID: {row['id']}")

    return rows


async def test_context(candidate_id: str, vacancy_id: str = None):
    """Test the CandidateContextService."""
    print("\n" + "=" * 80)
    print("CANDIDATE CONTEXT SERVICE TEST")
    print("=" * 80)

    pool = await get_db_pool()
    service = CandidateContextService(pool)

    try:
        print(f"\nFetching context for candidate: {candidate_id}")
        if vacancy_id:
            print(f"With vacancy context: {vacancy_id}")

        context = await service.get_context(candidate_id, vacancy_id)

        if not context:
            print("\n[ERROR] Kandidaat niet gevonden!")
            return

        print("\n" + "-" * 80)
        print("RAW CONTEXT DATA (JSON)")
        print("-" * 80)
        print(format_json(context.model_dump()))

        print("\n" + "-" * 80)
        print("AGENT PROMPT (Dutch)")
        print("-" * 80)
        print(context.to_agent_prompt())

        print("\n" + "-" * 80)
        print("SUMMARY")
        print("-" * 80)
        print(f"Kandidaat: {context.full_name}")
        print(f"Trust Level: {context.trust_level.value}")
        print(f"Status: {context.status}")
        print(f"Geplande gesprekken: {len(context.scheduled_interviews)}")
        print(f"Bekende kwalificaties: {len(context.known_qualifications)}")
        print(f"Totaal sollicitaties: {context.total_applications}")
        print(f"Afgeronde sollicitaties: {context.completed_applications}")
        print(f"Kwalificatie percentage: {context.qualification_rate:.0%}" if context.qualification_rate else "Kwalificatie percentage: N/A")
        print(f"Andere vacatures zelfde recruiter: {len(context.same_recruiter_vacancies)}")
        print(f"Laatste kanaal: {context.communication.last_channel or 'N/A'}")
        print(f"Voorkeur kanaal: {context.communication.preferred_channel.value}")
        print(f"Dagen sinds laatste interactie: {context.days_since_last_interaction}")

    finally:
        await close_db_pool()


async def interactive_mode():
    """Interactive mode to select candidate and vacancy."""
    pool = await get_db_pool()

    try:
        # List candidates
        candidates = await list_candidates(pool)
        if not candidates:
            print("\nGeen kandidaten gevonden!")
            return

        print("\n" + "-" * 40)
        candidate_input = input("Kies kandidaat nummer (of voer ID in): ").strip()

        try:
            idx = int(candidate_input) - 1
            if 0 <= idx < len(candidates):
                candidate_id = str(candidates[idx]['id'])
            else:
                candidate_id = candidate_input
        except ValueError:
            candidate_id = candidate_input

        # List vacancies
        vacancies = await list_vacancies(pool)
        print("\n" + "-" * 40)
        vacancy_input = input("Kies vacature nummer (of Enter voor geen): ").strip()

        vacancy_id = None
        if vacancy_input:
            try:
                idx = int(vacancy_input) - 1
                if 0 <= idx < len(vacancies):
                    vacancy_id = str(vacancies[idx]['id'])
                else:
                    vacancy_id = vacancy_input
            except ValueError:
                vacancy_id = vacancy_input

    finally:
        await close_db_pool()

    # Now run the actual test
    await test_context(candidate_id, vacancy_id)


async def main():
    """Main entry point."""
    if len(sys.argv) >= 2:
        candidate_id = sys.argv[1]
        vacancy_id = sys.argv[2] if len(sys.argv) >= 3 else None
        await test_context(candidate_id, vacancy_id)
    else:
        await interactive_mode()


if __name__ == "__main__":
    asyncio.run(main())
