#!/usr/bin/env python3
"""
Script to create Google Docs screening notes for applicants and attach to calendar events.

Usage:
    # Create notes for a specific application
    python scripts/create_screening_notes.py --application-id <uuid>

    # Create notes for all completed applications with scheduled interviews
    python scripts/create_screening_notes.py --all-scheduled

    # Create notes for applications in a specific vacancy
    python scripts/create_screening_notes.py --vacancy-id <uuid>

    # Dry run (show what would be created without actually creating)
    python scripts/create_screening_notes.py --vacancy-id <uuid> --dry-run

Environment variables required:
    - DATABASE_URL: PostgreSQL connection string
    - GOOGLE_SERVICE_ACCOUNT_FILE: Path to service account JSON
    - GOOGLE_CALENDAR_IMPERSONATE_EMAIL: Email to impersonate for Drive/Calendar
"""

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env.staging")

import asyncpg

from src.services.screening_notes_service import (
    create_screening_notes_document,
    generate_screening_notes_content,
)
from src.services.google_calendar_service import calendar_service


async def get_pool():
    """Create database connection pool."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable not set")

    # Convert SQLAlchemy-style URL to standard PostgreSQL URL
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    # Disable statement cache for PgBouncer compatibility (Supabase pooler)
    return await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
        statement_cache_size=0
    )


async def list_completed_applications(pool: asyncpg.Pool, vacancy_id: uuid.UUID = None):
    """List all completed applications, optionally filtered by vacancy."""
    if vacancy_id:
        rows = await pool.fetch(
            """
            SELECT
                a.id, a.vacancy_id,
                COALESCE(c.full_name, a.candidate_name) as candidate_name,
                a.completed_at, a.qualified,
                v.title as vacancy_title,
                si.id as scheduled_interview_id,
                si.calendar_event_id,
                si.selected_date,
                si.selected_time
            FROM ats.applications a
            LEFT JOIN ats.candidates c ON c.id = a.candidate_id
            LEFT JOIN ats.vacancies v ON v.id = a.vacancy_id
            LEFT JOIN ats.scheduled_interviews si ON si.application_id = a.id
                AND si.status NOT IN ('cancelled', 'rescheduled')
            WHERE a.status = 'completed'
              AND a.vacancy_id = $1
            ORDER BY a.completed_at DESC
            """,
            vacancy_id
        )
    else:
        rows = await pool.fetch(
            """
            SELECT
                a.id, a.vacancy_id,
                COALESCE(c.full_name, a.candidate_name) as candidate_name,
                a.completed_at, a.qualified,
                v.title as vacancy_title,
                si.id as scheduled_interview_id,
                si.calendar_event_id,
                si.selected_date,
                si.selected_time
            FROM ats.applications a
            LEFT JOIN ats.candidates c ON c.id = a.candidate_id
            LEFT JOIN ats.vacancies v ON v.id = a.vacancy_id
            LEFT JOIN ats.scheduled_interviews si ON si.application_id = a.id
                AND si.status NOT IN ('cancelled', 'rescheduled')
            WHERE a.status = 'completed'
            ORDER BY a.completed_at DESC
            LIMIT 50
            """
        )

    return rows


async def list_scheduled_applications(pool: asyncpg.Pool):
    """List applications that have scheduled interviews with calendar events."""
    rows = await pool.fetch(
        """
        SELECT
            a.id, a.vacancy_id,
            COALESCE(c.full_name, a.candidate_name) as candidate_name,
            a.completed_at, a.qualified,
            v.title as vacancy_title,
            si.id as scheduled_interview_id,
            si.calendar_event_id,
            si.selected_date,
            si.selected_time
        FROM ats.applications a
        LEFT JOIN ats.candidates c ON c.id = a.candidate_id
        LEFT JOIN ats.vacancies v ON v.id = a.vacancy_id
        JOIN ats.scheduled_interviews si ON si.application_id = a.id
            AND si.status NOT IN ('cancelled', 'rescheduled')
        WHERE a.status = 'completed'
          AND si.calendar_event_id IS NOT NULL
        ORDER BY si.selected_date ASC
        LIMIT 50
        """
    )
    return rows


async def process_application(
    pool: asyncpg.Pool,
    application_id: uuid.UUID,
    calendar_event_id: str = None,
    dry_run: bool = False,
):
    """
    Create screening notes document and optionally attach to calendar event.

    Args:
        pool: Database pool
        application_id: Application UUID
        calendar_event_id: Optional calendar event to attach to
        dry_run: If True, only show what would be done

    Returns:
        Dict with results
    """
    # Generate content (always do this to show what would be created)
    notes_data = await generate_screening_notes_content(pool, application_id)

    print(f"\n{'='*60}")
    print(f"📋 Application: {application_id}")
    print(f"   Candidate: {notes_data['candidate_name']}")
    print(f"   Vacancy: {notes_data['vacancy_title']}")
    print(f"   Document title: {notes_data['title']}")
    print(f"{'='*60}")

    if dry_run:
        print("\n📄 Document content preview (first 500 chars):")
        print("-" * 40)
        print(notes_data["content"][:500])
        print("...")
        print("-" * 40)
        print("\n[DRY RUN] Would create document and attach to calendar")
        return {"dry_run": True, "title": notes_data["title"]}

    # Create the document
    print("\n📝 Creating Google Doc...")
    doc_result = await create_screening_notes_document(pool, application_id)

    print(f"   ✓ Document created: {doc_result['doc_id']}")
    print(f"   📎 Link: {doc_result['webViewLink']}")

    # Attach to calendar event if provided
    if calendar_event_id:
        owner_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
        if owner_email:
            print(f"\n📅 Attaching to calendar event: {calendar_event_id}")
            success = await calendar_service.add_attachment_to_event(
                calendar_email=owner_email,
                event_id=calendar_event_id,
                file_url=doc_result["webViewLink"],
                file_title=doc_result["title"],
            )
            if success:
                print("   ✓ Attached to calendar event")
            else:
                print("   ⚠ Failed to attach to calendar event")

    return {
        "doc_id": doc_result["doc_id"],
        "webViewLink": doc_result["webViewLink"],
        "title": doc_result["title"],
        "calendar_attached": calendar_event_id is not None,
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Create Google Docs screening notes for applicants"
    )
    parser.add_argument(
        "--application-id",
        type=str,
        help="Process a specific application by UUID"
    )
    parser.add_argument(
        "--vacancy-id",
        type=str,
        help="Process all completed applications for a vacancy"
    )
    parser.add_argument(
        "--all-scheduled",
        action="store_true",
        help="Process all completed applications with scheduled interviews"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List applications without processing"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually creating documents"
    )

    args = parser.parse_args()

    if not any([args.application_id, args.vacancy_id, args.all_scheduled, args.list]):
        parser.print_help()
        print("\n❌ Error: Must specify --application-id, --vacancy-id, --all-scheduled, or --list")
        return 1

    # Check required environment variables
    required_vars = ["DATABASE_URL", "GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_CALENDAR_IMPERSONATE_EMAIL"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return 1

    print(f"🔧 Configuration:")
    print(f"   Calendar/Drive owner: {os.environ.get('GOOGLE_CALENDAR_IMPERSONATE_EMAIL')}")
    print(f"   Service account file: {os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE')}")

    pool = await get_pool()

    try:
        if args.list:
            # List mode
            print("\n📋 Listing completed applications...")
            if args.vacancy_id:
                applications = await list_completed_applications(pool, uuid.UUID(args.vacancy_id))
            else:
                applications = await list_completed_applications(pool)

            print(f"\nFound {len(applications)} applications:\n")
            for app in applications:
                qualified = "✓" if app["qualified"] else "✗"
                calendar = "📅" if app["calendar_event_id"] else "  "
                interview_date = ""
                if app["selected_date"]:
                    interview_date = f" | Interview: {app['selected_date']} {app['selected_time']}"
                print(f"  {qualified} {calendar} {app['id']} - {app['candidate_name']}")
                print(f"       Vacancy: {app['vacancy_title']}{interview_date}")
            return 0

        if args.application_id:
            # Single application mode
            app_id = uuid.UUID(args.application_id)

            # Check if there's a calendar event for this application
            row = await pool.fetchrow(
                """
                SELECT si.calendar_event_id
                FROM ats.scheduled_interviews si
                WHERE si.application_id = $1
                  AND si.status NOT IN ('cancelled', 'rescheduled')
                  AND si.calendar_event_id IS NOT NULL
                ORDER BY si.scheduled_at DESC
                LIMIT 1
                """,
                app_id
            )
            calendar_event_id = row["calendar_event_id"] if row else None

            result = await process_application(
                pool,
                app_id,
                calendar_event_id=calendar_event_id,
                dry_run=args.dry_run,
            )

            print("\n✅ Done!")
            return 0

        if args.vacancy_id:
            # Vacancy mode
            print(f"\n📋 Processing applications for vacancy: {args.vacancy_id}")
            applications = await list_completed_applications(pool, uuid.UUID(args.vacancy_id))

            if not applications:
                print("No completed applications found for this vacancy")
                return 0

            print(f"Found {len(applications)} completed applications\n")

            for app in applications:
                await process_application(
                    pool,
                    app["id"],
                    calendar_event_id=app["calendar_event_id"],
                    dry_run=args.dry_run,
                )

            print("\n✅ All done!")
            return 0

        if args.all_scheduled:
            # All scheduled mode
            print("\n📋 Processing applications with scheduled interviews...")
            applications = await list_scheduled_applications(pool)

            if not applications:
                print("No applications with scheduled interviews found")
                return 0

            print(f"Found {len(applications)} applications with scheduled interviews\n")

            for app in applications:
                await process_application(
                    pool,
                    app["id"],
                    calendar_event_id=app["calendar_event_id"],
                    dry_run=args.dry_run,
                )

            print("\n✅ All done!")
            return 0

    finally:
        await pool.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)
