"""
Test attribute extraction on a real conversation from the database.

Usage:
    # Dry run (extract but don't save)
    python scripts/test_attribute_extraction.py <conversation_id>

    # Save extracted attributes to DB
    python scripts/test_attribute_extraction.py <conversation_id> --save

Example:
    python scripts/test_attribute_extraction.py 1dd7ec19-dd2c-437a-95d1-8771976821d5
"""

import asyncio
import sys
import os
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.database import get_db_pool
from src.services.attribute_extraction_service import extract_and_save_attributes

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def test_extraction(conversation_id: str, save: bool = False):
    """Test attribute extraction on a real conversation."""

    pool = await get_db_pool()

    # 1. Fetch conversation details
    conv = await pool.fetchrow(
        """
        SELECT id, vacancy_id, candidate_name, candidate_phone, channel, status
        FROM agents.pre_screening_sessions
        WHERE id = $1
        """,
        conversation_id,
    )

    if not conv:
        logger.error(f"Conversation {conversation_id} not found")
        return

    print(f"\nConversation: {conv['id']}")
    print(f"Candidate: {conv['candidate_name']}")
    print(f"Channel: {conv['channel']}")
    print(f"Status: {conv['status']}")

    # 2. Find linked application + candidate
    app = await pool.fetchrow(
        """
        SELECT a.id AS application_id, a.candidate_id, c.workspace_id, c.full_name
        FROM ats.applications a
        JOIN ats.candidates c ON c.id = a.candidate_id
        WHERE a.vacancy_id = $1
        AND (
            (a.candidate_phone IS NOT NULL AND a.candidate_phone = $2)
            OR (a.candidate_phone IS NULL AND a.candidate_name = $3)
        )
        ORDER BY a.started_at DESC
        LIMIT 1
        """,
        conv["vacancy_id"],
        conv["candidate_phone"],
        conv["candidate_name"],
    )

    if not app:
        logger.error("No linked application/candidate found for this conversation")
        return

    candidate_id = app["candidate_id"]
    workspace_id = app["workspace_id"]
    print(f"Candidate ID: {candidate_id}")
    print(f"Workspace ID: {workspace_id}")

    # 3. Fetch transcript
    messages = await pool.fetch(
        """
        SELECT role, message, created_at
        FROM agents.pre_screening_session_turns
        WHERE conversation_id = $1
        ORDER BY created_at
        """,
        conversation_id,
    )

    if not messages:
        logger.error("No messages found for this conversation")
        return

    print(f"\nTranscript: {len(messages)} messages")
    print("=" * 60)
    for msg in messages:
        role_label = "USER " if msg["role"] == "user" else "AGENT"
        text = msg["message"]
        if len(text) > 120:
            text = text[:120] + "..."
        print(f"  {role_label}: {text}")
    print("=" * 60)

    # 4. Build transcript text
    transcript_text = "\n".join(f"{m['role']}: {m['message']}" for m in messages)

    # 5. Run extraction
    dry_run = not save
    print(f"\nRunning extraction ({'DRY RUN' if dry_run else 'SAVING TO DB'})...")
    print()

    results = await extract_and_save_attributes(
        text=transcript_text,
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        pool=pool,
        source="pre_screening",
        source_session_id=conversation_id,
        collected_by="pre_screening",
        dry_run=dry_run,
    )

    # 6. Print results
    if not results:
        print("No attributes extracted.")
        return

    print(f"\nExtracted {len(results)} attributes:")
    print("-" * 70)
    print(f"  {'Attribute':<30} {'Type':<15} {'Value'}")
    print("-" * 70)
    for attr in results:
        print(f"  {attr['name']:<30} {attr['data_type']:<15} {attr['value']}")
    print("-" * 70)

    if dry_run:
        print("\nDry run — nothing saved. Use --save to persist to DB.")
    else:
        print(f"\nSaved {len(results)} attributes for candidate {candidate_id}")

    # 7. Show existing attributes for comparison
    existing = await pool.fetch(
        """
        SELECT cat.slug, cat.name, ca.value, ca.source
        FROM ats.candidate_attributes ca
        JOIN ontology.types_attributes cat ON cat.id = ca.attribute_type_id
        WHERE ca.candidate_id = $1 AND cat.is_active = true
        ORDER BY cat.sort_order
        """,
        candidate_id,
    )

    if existing:
        print(f"\nAll current attributes for this candidate:")
        print("-" * 70)
        print(f"  {'Attribute':<30} {'Source':<15} {'Value'}")
        print("-" * 70)
        for row in existing:
            print(f"  {row['name']:<30} {row['source'] or '-':<15} {row['value'] or '-'}")
        print("-" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_attribute_extraction.py <conversation_id> [--save]")
        print("Example: python scripts/test_attribute_extraction.py 1dd7ec19-dd2c-437a-95d1-8771976821d5")
        sys.exit(1)

    conversation_id = sys.argv[1]
    save = "--save" in sys.argv

    asyncio.run(test_extraction(conversation_id, save=save))
