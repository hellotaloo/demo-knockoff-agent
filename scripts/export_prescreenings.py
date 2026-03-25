"""
Export all pre-screenings with questions to a markdown file for client review.
Usage: python scripts/export_prescreenings.py
"""
import asyncio
import asyncpg
import os
import re
from dotenv import load_dotenv
from datetime import datetime
WEBSITE_BASE = "https://staging.itzu-website-2025.scalecity.space/job-id"
CONNEXYS_BASE = "https://connexys-5051--itzudev.sandbox.lightning.force.com/lightning/r/cxsrec__cxsPosition__c"


def website_link(source_id: str) -> str:
    return f"{WEBSITE_BASE}/{source_id}"


def connexys_link(source_id: str) -> str:
    return f"{CONNEXYS_BASE}/{source_id}/view"

load_dotenv()


async def main():
    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)

    try:
        # Fetch all pre-screenings with vacancy info
        rows = await conn.fetch("""
            SELECT
                ps.id,
                ps.display_title,
                ps.status,
                ps.created_at,
                v.title AS vacancy_title,
                v.source_id,
                v.id AS vacancy_id
            FROM agents.pre_screenings ps
            JOIN ats.vacancies v ON v.id = ps.vacancy_id
            ORDER BY ps.created_at DESC
        """)

        if not rows:
            print("No pre-screenings found.")
            return

        lines = []
        lines.append(f"# Pre-screening Overzicht — {datetime.now().strftime('%d/%m/%Y')}")
        lines.append("")
        lines.append(f"**Totaal: {len(rows)} pre-screenings**")
        lines.append("")
        lines.append("---")
        lines.append("")

        for i, ps in enumerate(rows, 1):
            ps_id = ps["id"]
            title = ps["display_title"] or ps["vacancy_title"]

            # Fetch questions for this pre-screening
            questions = await conn.fetch("""
                SELECT
                    question_type,
                    position,
                    question_text,
                    ideal_answer,
                    vacancy_snippet,
                    is_approved
                FROM agents.pre_screening_questions
                WHERE pre_screening_id = $1
                ORDER BY question_type DESC, position ASC
            """, ps_id)

            ko_questions = [q for q in questions if q["question_type"] == "knockout"]
            qual_questions = [q for q in questions if q["question_type"] == "qualification"]

            lines.append(f"## {i}. Vacature: {title}")
            lines.append("")

            # Vacancy link
            if ps["source_id"]:
                lines.append(f"Website: {website_link(ps['source_id'])}")
                lines.append(f"Connexys: {connexys_link(ps['source_id'])}")
                lines.append("")

            # Knockout questions
            if ko_questions:
                lines.append(f"### Knockout vragen ({len(ko_questions)})")
                lines.append("")
                for j, q in enumerate(ko_questions, 1):
                    approved = " ✓" if q["is_approved"] else ""
                    lines.append(f"KO{j}. {q['question_text']}{approved}")
                    if q["vacancy_snippet"]:
                        lines.append(f"  - Bron: {q['vacancy_snippet']}")
                    lines.append("")

            # Qualification questions
            if qual_questions:
                lines.append(f"### Kwalificatievragen ({len(qual_questions)})")
                lines.append("")
                for j, q in enumerate(qual_questions, 1):
                    approved = " ✓" if q["is_approved"] else ""
                    lines.append(f"Q{j}. {q['question_text']}{approved}")
                    if q["ideal_answer"]:
                        lines.append(f"  - Ideaal antwoord: {q['ideal_answer']}")
                    if q["vacancy_snippet"]:
                        lines.append(f"  - Bron: {q['vacancy_snippet']}")
                    lines.append("")

            lines.append("---")
            lines.append("")

        output = "\n".join(lines)

        # Write to file
        output_path = "exports/prescreenings_review.md"
        os.makedirs("exports", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(output)

        print(f"Exported {len(rows)} pre-screenings to {output_path}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
