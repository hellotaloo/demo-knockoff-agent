"""
Screening Notes Service - Generates formatted screening notes for candidates.

This service creates formatted documents containing:
- Pre-screening summary
- Status overview table
- Contact information
- Knockout question results
- Qualification question results with scores
- Original vacancy description
- Candidate history/context
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

import asyncpg

from src.services.google_drive_service import drive_service

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Brussels")


def format_duration(seconds: int) -> str:
    """Format duration in seconds to 'Xm Ys' format."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    if remaining_seconds == 0:
        return f"{minutes}m"
    return f"{minutes}m {remaining_seconds}s"


def format_date_dutch(dt: datetime) -> str:
    """Format a datetime in Dutch format."""
    dutch_months = {
        1: "januari", 2: "februari", 3: "maart", 4: "april",
        5: "mei", 6: "juni", 7: "juli", 8: "augustus",
        9: "september", 10: "oktober", 11: "november", 12: "december"
    }
    return f"{dt.day} {dutch_months[dt.month]} {dt.year}, {dt.hour:02d}:{dt.minute:02d}"


async def generate_screening_notes_sections(
    pool: asyncpg.Pool,
    application_id: uuid.UUID,
    include_candidate_context: bool = True,
) -> dict:
    """
    Generate structured screening notes sections for rich document formatting.

    Args:
        pool: Database connection pool
        application_id: The application UUID
        include_candidate_context: Whether to include candidate history section

    Returns:
        Dict with:
        - title: Document title
        - sections: List of section dicts for rich formatting
        - candidate_name: Candidate's name
        - vacancy_title: Vacancy title
    """
    # Fetch application with candidate and vacancy info
    app_row = await pool.fetchrow(
        """
        SELECT
            a.id, a.vacancy_id, a.candidate_id,
            COALESCE(c.full_name, a.candidate_name) as candidate_name,
            COALESCE(c.phone, a.candidate_phone) as candidate_phone,
            c.email as candidate_email,
            a.channel, a.status, a.qualified,
            a.started_at, a.completed_at, a.interaction_seconds,
            a.summary,
            v.title as vacancy_title,
            v.company as company_name,
            v.description as vacancy_description,
            v.location as vacancy_location
        FROM ats.applications a
        LEFT JOIN ats.candidates c ON c.id = a.candidate_id
        LEFT JOIN ats.vacancies v ON v.id = a.vacancy_id
        WHERE a.id = $1
        """,
        application_id
    )

    if not app_row:
        raise ValueError(f"Application {application_id} not found")

    # Fetch answers
    answers = await pool.fetch(
        """
        SELECT question_id, question_text, answer, passed, score, rating, motivation
        FROM ats.application_answers
        WHERE application_id = $1
        ORDER BY id
        """,
        application_id
    )

    # Separate knockout and qualification questions
    knockout_answers = [a for a in answers if a["passed"] is not None]
    qualification_answers = [a for a in answers if a["passed"] is None and a["score"] is not None]

    # Calculate overall score
    scores = [a["score"] for a in qualification_answers if a["score"] is not None]
    overall_score = round(sum(scores) / len(scores)) if scores else None

    # Count knockout results
    knockout_passed = sum(1 for a in knockout_answers if a["passed"])
    knockout_total = len(knockout_answers)

    # Format data
    candidate_name = app_row["candidate_name"] or "Onbekende kandidaat"
    vacancy_title = app_row["vacancy_title"] or "Onbekende vacature"
    company_name = app_row["company_name"] or ""

    # Build sections in the exact order from the screenshot
    sections: List[Dict[str, Any]] = []

    # 1. Header - "Pre-screening Notule: Sven Bakker"
    sections.append({
        "type": "header",
        "content": f"Pre-screening Notule: {candidate_name}"
    })

    # 2. Metadata line - date, vacancy, company, location
    metadata_parts = []
    if app_row["completed_at"]:
        completed_at = app_row["completed_at"]
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=TIMEZONE)
        metadata_parts.append(f"Datum: {format_date_dutch(completed_at)}")
    metadata_parts.append(f"Vacature: {vacancy_title}")
    if company_name:
        metadata_parts.append(f"Bedrijf: {company_name}")
    if app_row["vacancy_location"]:
        metadata_parts.append(f"Locatie: {app_row['vacancy_location']}")

    sections.append({
        "type": "metadata",
        "content": " | ".join(metadata_parts)
    })

    # 3. SAMENVATTING section header
    sections.append({
        "type": "section_header",
        "emoji": "📋",
        "content": "SAMENVATTING"
    })

    # 4. Summary box (green background)
    if app_row["summary"]:
        sections.append({
            "type": "summary_box",
            "content": app_row["summary"]
        })

    # 5. Status table
    sections.append({
        "type": "status_table",
        "status": "Afgerond" if app_row["status"] == "completed" else app_row["status"].capitalize(),
        "qualified": app_row["qualified"],
        "score": overall_score,
        "duration": format_duration(app_row["interaction_seconds"]) if app_row["interaction_seconds"] else "Onbekend",
        "questions": len(answers)
    })

    # 6. CONTACTGEGEVENS section
    sections.append({
        "type": "section_header",
        "emoji": "👤",
        "content": "CONTACTGEGEVENS"
    })

    sections.append({
        "type": "contact_info",
        "name": candidate_name,
        "phone": app_row["candidate_phone"] or "",
        "email": app_row["candidate_email"] or ""
    })

    # 7. KNOCK-OUT VRAGEN section
    if knockout_answers:
        sections.append({
            "type": "section_header",
            "emoji": "🚦",
            "content": f"KNOCK-OUT VRAGEN ({knockout_passed}/{knockout_total} geslaagd)"
        })

        for answer in knockout_answers:
            sections.append({
                "type": "qa_knockout",
                "question": answer["question_text"],
                "answer": answer["answer"] or "",
                "passed": answer["passed"]
            })

    # 8. KWALIFICATIEVRAGEN section
    if qualification_answers:
        avg_text = f" (Gemiddeld: {overall_score}/100)" if overall_score else ""
        sections.append({
            "type": "section_header",
            "emoji": "📊",
            "content": f"KWALIFICATIEVRAGEN{avg_text}"
        })

        for answer in qualification_answers:
            sections.append({
                "type": "qa_qualification",
                "question": answer["question_text"],
                "answer": answer["answer"] or "",
                "score": answer["score"] or 0,
                "rating": answer["rating"] or "",
                "motivation": answer["motivation"] or ""
            })

    # 9. Divider
    sections.append({"type": "divider"})

    # 10. VACATURE section
    if app_row["vacancy_description"]:
        sections.append({
            "type": "vacancy_box",
            "title": vacancy_title,
            "content": app_row["vacancy_description"]
        })

    # 11. Footer
    sections.append({
        "type": "footer",
        "content": "Dit document is automatisch gegenereerd door Taloo"
    })

    # 12. KANDIDAAT HISTORIE section (from candidate context)
    if include_candidate_context and app_row["candidate_id"]:
        try:
            from src.services.candidate_context_service import CandidateContextService

            context_service = CandidateContextService(pool)
            context = await context_service.get_context(
                candidate_id=str(app_row["candidate_id"]),
                current_vacancy_id=str(app_row["vacancy_id"])
            )

            if context:
                # Add extra spacing before Kandidaat historie
                sections.append({"type": "spacing"})

                sections.append({
                    "type": "section_header",
                    "emoji": "🎯",
                    "content": "Kandidaat historie"
                })

                # Use the agent prompt format which is nicely formatted Dutch
                context_text = context.to_agent_prompt()
                sections.append({
                    "type": "candidate_history",
                    "content": context_text
                })
        except Exception as e:
            logger.warning(f"Could not load candidate context: {e}")

    return {
        "title": f"Pre-screening Notule - {candidate_name}",
        "sections": sections,
        "candidate_name": candidate_name,
        "vacancy_title": vacancy_title,
    }


async def generate_screening_notes_content(
    pool: asyncpg.Pool,
    application_id: uuid.UUID,
) -> dict:
    """
    Generate screening notes content for an application (legacy plain text format).
    """
    data = await generate_screening_notes_sections(pool, application_id, include_candidate_context=False)

    lines = []
    for section in data["sections"]:
        section_type = section.get("type")

        if section_type == "header":
            lines.append(f"# {section['content']}")
            lines.append("")
        elif section_type == "section_header":
            emoji = section.get("emoji", "")
            lines.append(f"## {emoji} {section['content']}")
            lines.append("")
        elif section_type == "metadata":
            lines.append(section["content"])
            lines.append("")
        elif section_type == "status_table":
            lines.append(f"Status: {section['status']}")
            qual_text = "✓ Gekwalificeerd" if section["qualified"] else "✗ Niet gekwalificeerd"
            lines.append(f"Kwalificatie: {qual_text}")
            if section.get("score"):
                lines.append(f"Score: {section['score']}/100")
            lines.append(f"Duur: {section['duration']}")
            lines.append(f"Vragen: {section['questions']}")
            lines.append("")
        elif section_type == "summary_box":
            lines.append(section["content"])
            lines.append("")
        elif section_type == "contact_info":
            lines.append(f"Naam: {section['name']}")
            if section.get("phone"):
                lines.append(f"Telefoon: {section['phone']}")
            if section.get("email"):
                lines.append(f"Email: {section['email']}")
            lines.append("")
        elif section_type == "qa_knockout":
            lines.append(f"❓ {section['question']}")
            lines.append(f'Antwoord: "{section["answer"]}"')
            result = "✓ Geslaagd" if section["passed"] else "✗ Niet geslaagd"
            lines.append(f"Resultaat: {result}")
            lines.append("")
        elif section_type == "qa_qualification":
            lines.append(f"❓ {section['question']}")
            lines.append(f'Antwoord: "{section["answer"]}"')
            rating_dutch = {
                "weak": "Zwak", "below_average": "Onder gemiddeld",
                "average": "Gemiddeld", "good": "Goed", "excellent": "Uitstekend"
            }.get(section["rating"], section["rating"])
            lines.append(f"Score: {section['score']}/100 ({rating_dutch})")
            if section.get("motivation"):
                lines.append(f"💡 {section['motivation']}")
            lines.append("")
        elif section_type == "vacancy_box":
            lines.append(f"📁 VACATURE: {section['title']}")
            lines.append("")
            lines.append(section["content"])
            lines.append("")
        elif section_type == "divider":
            lines.append("─" * 60)
            lines.append("")
        elif section_type == "footer":
            lines.append(section["content"])

    return {
        "title": data["title"],
        "content": "\n".join(lines),
        "candidate_name": data["candidate_name"],
        "vacancy_title": data["vacancy_title"],
    }


async def create_screening_notes_document(
    pool: asyncpg.Pool,
    application_id: uuid.UUID,
    owner_email: Optional[str] = None,
    folder_id: Optional[str] = None,
    use_rich_formatting: bool = True,
    include_candidate_context: bool = True,
) -> dict:
    """
    Create a Google Docs screening notes document for an application.

    Args:
        pool: Database connection pool
        application_id: The application UUID
        owner_email: Email of the document owner (uses default if not specified)
        folder_id: Optional Google Drive folder ID
        use_rich_formatting: Use rich formatting with colors/tables (default True)
        include_candidate_context: Include candidate history section (default True)

    Returns:
        Dict with:
        - doc_id: Google Doc ID
        - title: Document title
        - webViewLink: URL to view the document
        - candidate_name: Candidate's name
    """
    import os

    if not owner_email:
        owner_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    if not owner_email:
        raise RuntimeError(
            "No owner_email specified and GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set"
        )

    if use_rich_formatting:
        notes_data = await generate_screening_notes_sections(
            pool, application_id, include_candidate_context=include_candidate_context
        )

        doc_result = await drive_service.create_rich_screening_doc(
            owner_email=owner_email,
            title=notes_data["title"],
            sections=notes_data["sections"],
            folder_id=folder_id,
        )
    else:
        notes_data = await generate_screening_notes_content(pool, application_id)

        doc_result = await drive_service.create_screening_notes_doc(
            owner_email=owner_email,
            title=notes_data["title"],
            content=notes_data["content"],
            folder_id=folder_id,
        )

    logger.info(
        f"Created screening notes document for application {application_id}: "
        f"{doc_result['webViewLink']}"
    )

    return {
        "doc_id": doc_result["id"],
        "title": doc_result["title"],
        "webViewLink": doc_result["webViewLink"],
        "candidate_name": notes_data["candidate_name"],
        "vacancy_title": notes_data["vacancy_title"],
    }
