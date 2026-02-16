"""
Script to reprocess a single conversation through the transcript processor.

Usage:
    python scripts/reprocess_conversation.py <conversation_id>

Example:
    python scripts/reprocess_conversation.py 1dd7ec19-dd2c-437a-95d1-8771976821d5
"""

import asyncio
import sys
import os
import logging
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.database import get_db_pool
from transcript_processor import process_transcript

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def reprocess_conversation(conversation_id: str):
    """Reprocess a single conversation through the transcript processor."""

    pool = await get_db_pool()

    # Fetch conversation details
    conv = await pool.fetchrow(
        """
        SELECT
            sc.id,
            sc.vacancy_id,
            sc.candidate_name,
            sc.candidate_phone,
            sc.channel,
            sc.status,
            sc.created_at
        FROM ats.screening_conversations sc
        WHERE sc.id = $1
        """,
        conversation_id
    )

    if not conv:
        logger.error(f"Conversation {conversation_id} not found")
        return None

    logger.info(f"Found conversation for: {conv['candidate_name']}")
    logger.info(f"Vacancy ID: {conv['vacancy_id']}")
    logger.info(f"Channel: {conv['channel']}")
    logger.info(f"Status: {conv['status']}")

    # Find linked application
    app = await pool.fetchrow(
        """
        SELECT id, candidate_name, qualified, summary
        FROM ats.applications
        WHERE vacancy_id = $1
        AND (
            (candidate_phone IS NOT NULL AND candidate_phone = $2)
            OR (candidate_phone IS NULL AND candidate_name = $3)
        )
        ORDER BY started_at DESC
        LIMIT 1
        """,
        conv['vacancy_id'],
        conv['candidate_phone'],
        conv['candidate_name']
    )

    if not app:
        logger.error("No linked application found for this conversation")
        return None

    application_id = app['id']
    logger.info(f"Found application: {application_id}")
    logger.info(f"Current qualified status: {app['qualified']}")
    logger.info(f"Current summary: {app['summary']}")

    # Fetch messages
    messages = await pool.fetch(
        """
        SELECT role, message, created_at
        FROM ats.conversation_messages
        WHERE conversation_id = $1
        ORDER BY created_at
        """,
        conversation_id
    )

    if not messages:
        logger.error("No messages found for this conversation")
        return None

    logger.info(f"Found {len(messages)} messages")

    # Convert to transcript format
    transcript = []
    for msg in messages:
        transcript.append({
            "role": "user" if msg["role"] == "user" else "agent",
            "message": msg["message"],
            "time_in_call_secs": 0
        })

    # Print transcript for review
    print("\n" + "="*60)
    print("TRANSCRIPT:")
    print("="*60)
    for entry in transcript:
        role_label = "👤 USER" if entry["role"] == "user" else "🤖 AGENT"
        print(f"{role_label}: {entry['message'][:100]}..." if len(entry['message']) > 100 else f"{role_label}: {entry['message']}")
    print("="*60 + "\n")

    # Fetch pre-screening questions
    ps_row = await pool.fetchrow(
        "SELECT id FROM ats.pre_screenings WHERE vacancy_id = $1",
        conv['vacancy_id']
    )

    if not ps_row:
        logger.error("No pre-screening found for vacancy")
        return None

    questions = await pool.fetch(
        """
        SELECT id, question_type, question_text, ideal_answer
        FROM ats.pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        ps_row["id"]
    )

    # Split questions by type
    knockout_questions = []
    qualification_questions = []
    ko_idx = 1
    qual_idx = 1

    for q in questions:
        q_dict = {
            "db_id": str(q["id"]),
            "question_text": q["question_text"],
            "ideal_answer": q["ideal_answer"],
        }
        if q["question_type"] == "knockout":
            q_dict["id"] = f"ko_{ko_idx}"
            knockout_questions.append(q_dict)
            ko_idx += 1
        else:
            q_dict["id"] = f"qual_{qual_idx}"
            qualification_questions.append(q_dict)
            qual_idx += 1

    logger.info(f"Knockout questions: {len(knockout_questions)}")
    logger.info(f"Qualification questions: {len(qualification_questions)}")

    print("\n" + "="*60)
    print("KNOCKOUT QUESTIONS:")
    print("="*60)
    for q in knockout_questions:
        print(f"  {q['id']}: {q['question_text']}")
    print("="*60 + "\n")

    # Process transcript
    call_date = datetime.now().strftime("%Y-%m-%d")
    logger.info("Processing transcript...")

    result = await process_transcript(
        transcript=transcript,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        call_date=call_date,
    )

    # Print results
    print("\n" + "="*60)
    print("PROCESSING RESULTS:")
    print("="*60)
    print(f"Overall Passed: {result.overall_passed}")
    print(f"Needs Human Review: {result.needs_human_review}")
    print(f"Summary: {result.summary}")
    print(f"Notes: {result.notes}")

    print("\n--- KNOCKOUT RESULTS ---")
    for kr in result.knockout_results:
        status_emoji = "✅" if kr.status == "passed" else ("❌" if kr.status == "failed" else "⚠️")
        print(f"  {status_emoji} {kr.id}: {kr.question_text}")
        print(f"      Answer: \"{kr.answer}\"")
        print(f"      Status: {kr.status} (score: {kr.score})")

    print("\n--- QUALIFICATION RESULTS ---")
    for qr in result.qualification_results:
        print(f"  📊 {qr.id}: {qr.question_text}")
        print(f"      Answer: \"{qr.answer[:100]}...\"" if len(qr.answer) > 100 else f"      Answer: \"{qr.answer}\"")
        print(f"      Score: {qr.score}/100 ({qr.rating})")
        print(f"      Motivation: {qr.motivation}")

    print("="*60 + "\n")

    # Ask for confirmation before updating (skip if --yes flag passed)
    if len(sys.argv) > 2 and sys.argv[2] == '--yes':
        confirm = 'y'
    else:
        try:
            confirm = input("Do you want to update the application with these results? (y/n): ")
        except EOFError:
            logger.info("No input provided, skipping update")
            return result

    if confirm.lower() != 'y':
        logger.info("Update cancelled")
        return result

    # Update application and answers in transaction
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update application summary and qualified status
            await conn.execute(
                """
                UPDATE ats.applications
                SET qualified = $1, summary = $2
                WHERE id = $3
                """,
                result.overall_passed,
                result.summary,
                application_id
            )

            # Delete existing answers
            await conn.execute(
                "DELETE FROM ats.application_answers WHERE application_id = $1",
                application_id
            )

            # Insert new knockout results
            for kr in result.knockout_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    application_id,
                    kr.id,
                    kr.question_text,
                    kr.answer,
                    kr.passed,
                    kr.score,
                    kr.rating,
                    conv["channel"] or "chat"
                )

            # Insert new qualification results with motivation
            for qr in result.qualification_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source, motivation)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, $7, $8)
                    """,
                    application_id,
                    qr.id,
                    qr.question_text,
                    qr.answer,
                    qr.score,
                    qr.rating,
                    conv["channel"] or "chat",
                    qr.motivation
                )

    logger.info(f"✅ Application {application_id} updated successfully!")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reprocess_conversation.py <conversation_id>")
        print("Example: python scripts/reprocess_conversation.py 1dd7ec19-dd2c-437a-95d1-8771976821d5")
        sys.exit(1)

    conversation_id = sys.argv[1]
    asyncio.run(reprocess_conversation(conversation_id))
