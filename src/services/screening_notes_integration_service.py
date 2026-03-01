"""
Screening Notes Integration Service.

Orchestrates automatic creation of Google Doc screening notes
and attachment to calendar events after transcript processing.

This service is called as a background task when:
1. Transcript processing completes
2. Candidate is qualified (passed all knockouts)
3. A scheduled interview with calendar_event_id exists
"""

import os
import logging
import uuid
import re
from typing import Optional

import asyncpg

from src.services.screening_notes_service import create_screening_notes_document
from src.services.google_calendar_service import calendar_service

logger = logging.getLogger(__name__)


def extract_file_id_from_url(url: str) -> Optional[str]:
    """
    Extract Google Drive file ID from a web view URL.

    Handles URLs like:
    - https://docs.google.com/document/d/FILE_ID/edit
    - https://drive.google.com/file/d/FILE_ID/view
    """
    patterns = [
        r"/document/d/([a-zA-Z0-9_-]+)",
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


class ScreeningNotesIntegrationService:
    """
    Service that integrates screening notes with calendar events.

    Triggered after transcript processing completes for qualified candidates
    with scheduled interviews.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create_and_attach_notes(
        self,
        application_id: uuid.UUID,
        recruiter_email: Optional[str] = None,
    ) -> dict:
        """
        Create screening notes document and attach to calendar event.

        Args:
            application_id: The application UUID
            recruiter_email: Email for Google services (owner of doc/calendar)

        Returns:
            Dict with doc_id, webViewLink, calendar_updated status
        """
        if not recruiter_email:
            recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

        if not recruiter_email:
            logger.warning("No recruiter email configured, skipping notes integration")
            return {"success": False, "reason": "no_recruiter_email"}

        # 1. Get application details including summary
        app_row = await self.pool.fetchrow(
            """
            SELECT a.id, a.vacancy_id, a.qualified, a.summary, a.candidate_id,
                   a.candidate_name, a.conversation_id
            FROM ats.applications a
            WHERE a.id = $1
            """,
            application_id
        )

        if not app_row:
            logger.error(f"Application {application_id} not found")
            return {"success": False, "reason": "application_not_found"}

        if not app_row["qualified"]:
            logger.info(f"Skipping notes for disqualified application {application_id}")
            return {"success": False, "reason": "not_qualified"}

        # 2. Find scheduled interview with calendar_event_id
        # Match by application_id first, then fallback to vacancy + candidate name
        scheduled = await self.pool.fetchrow(
            """
            SELECT si.id, si.calendar_event_id, si.selected_date, si.selected_time
            FROM ats.scheduled_interviews si
            WHERE si.application_id = $1
            ORDER BY si.scheduled_at DESC
            LIMIT 1
            """,
            application_id
        )

        if not scheduled:
            # Fallback: match by vacancy_id and candidate_name
            scheduled = await self.pool.fetchrow(
                """
                SELECT si.id, si.calendar_event_id, si.selected_date, si.selected_time
                FROM ats.scheduled_interviews si
                WHERE si.vacancy_id = $1 AND si.candidate_name = $2
                ORDER BY si.scheduled_at DESC
                LIMIT 1
                """,
                app_row["vacancy_id"],
                app_row["candidate_name"]
            )

        calendar_event_id = scheduled["calendar_event_id"] if scheduled else None

        if not scheduled or not calendar_event_id:
            logger.info(
                f"No scheduled interview with calendar event found for application {application_id}"
            )
            return {"success": False, "reason": "no_calendar_event"}

        # 3. Create Google Doc with screening notes
        try:
            doc_result = await create_screening_notes_document(
                pool=self.pool,
                application_id=application_id,
                owner_email=recruiter_email,
                use_rich_formatting=True,
                include_candidate_context=True,
            )
            logger.info(f"Created screening doc: {doc_result['webViewLink']}")
        except Exception as e:
            logger.error(f"Failed to create screening doc: {e}")
            return {"success": False, "reason": f"doc_creation_failed: {e}"}

        result = {
            "success": True,
            "doc_id": doc_result["doc_id"],
            "webViewLink": doc_result["webViewLink"],
            "calendar_updated": False,
            "scheduled_interview_id": str(scheduled["id"]),
        }

        # 4. Update calendar event with attachment and rich description
        try:
            summary_text = app_row["summary"] or ""
            candidate_name = app_row["candidate_name"] or "Onbekende kandidaat"

            description_content = await self._build_rich_description(
                application_id=application_id,
                candidate_name=candidate_name,
                summary_text=summary_text,
            )

            # Attach doc and update description
            attachment_success = await calendar_service.add_attachment_to_event(
                calendar_email=recruiter_email,
                event_id=calendar_event_id,
                file_url=doc_result["webViewLink"],
                file_title=doc_result["title"],
                description_note=description_content,
            )

            result["calendar_updated"] = attachment_success
            if attachment_success:
                logger.info(f"Updated calendar event {calendar_event_id} with doc and summary")
            else:
                logger.warning(f"Calendar attachment may have fallen back to description link")

        except Exception as e:
            logger.warning(f"Failed to update calendar event: {e}")
            result["calendar_update_error"] = str(e)

        # 5. Store doc reference in scheduled_interviews notes
        try:
            await self.pool.execute(
                """
                UPDATE ats.scheduled_interviews
                SET notes = COALESCE(notes, '') || $2,
                    screening_doc_url = $3,
                    updated_at = NOW()
                WHERE id = $1
                """,
                scheduled["id"],
                f"\n\nScreening Notule: {doc_result['webViewLink']}",
                doc_result["webViewLink"]
            )
        except Exception as e:
            # Column might not exist - log and continue
            logger.warning(f"Failed to update scheduled_interviews notes: {e}")
            # Try without screening_doc_url column
            try:
                await self.pool.execute(
                    """
                    UPDATE ats.scheduled_interviews
                    SET notes = COALESCE(notes, '') || $2,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    scheduled["id"],
                    f"\n\nScreening Notule: {doc_result['webViewLink']}"
                )
            except Exception as e2:
                logger.warning(f"Also failed without screening_doc_url: {e2}")

        return result

    async def _build_rich_description(
        self,
        application_id: uuid.UUID,
        candidate_name: str,
        summary_text: str,
    ) -> str:
        """Build an HTML calendar event description matching the Google Doc style."""

        # Fetch answers joined with pre_screening_questions to get question_type
        rows = await self.pool.fetch(
            """
            SELECT aa.question_text, aa.answer, aa.passed, aa.score, aa.rating,
                   COALESCE(psq.question_type, 'qualification') AS question_type
            FROM ats.application_answers aa
            LEFT JOIN ats.pre_screening_questions psq ON psq.id::text = aa.question_id
            WHERE aa.application_id = $1
            ORDER BY psq.position ASC NULLS LAST
            """,
            application_id,
        )

        knockout_items = []
        qualification_items = []
        qualification_scores = []

        for row in rows:
            q_text = row["question_text"] or ""
            answer = row["answer"] or "\u2014"

            if row["question_type"] == "knockout":
                if row["passed"] is True:
                    label = "Bevestigd \u2705"
                elif row["passed"] is False:
                    label = "Niet bevestigd \u274c"
                else:
                    label = "Onduidelijk \u2753"
                knockout_items.append(f"<li><b>{q_text}</b><br>&nbsp;&nbsp;&nbsp;\u2022 {label}</li>")
            else:
                score = row["score"]
                rating = row["rating"] or ""
                if score is not None:
                    qualification_scores.append(score)
                score_rating = f"{score}% \u2013 {rating}" if score is not None and rating else ("\u2014" if score is None else f"{score}%")
                qualification_items.append(
                    f"<li><b>{q_text}</b> ({score_rating})<br>"
                    f"&nbsp;&nbsp;&nbsp;<i>\"{answer}\"</i></li>"
                )

        # Assemble HTML description
        html = []
        html.append(
            f"\U0001f464 <b>Kandidaat:</b> {candidate_name} (nieuwe kandidaat)<br>"
            f"\U0001f4cb ATS: <a href=\"https://taloo.be\">Bekijk fiche</a><br><br>"
        )

        if summary_text:
            html.append(f"\U0001f4dd <b>Samenvatting</b><br>{summary_text}<br><br>")

        if knockout_items:
            html.append(f"\u2757 <b>Knockoutvragen</b><ul>{''.join(knockout_items)}</ul>")

        if qualification_items:
            avg = round(sum(qualification_scores) / len(qualification_scores)) if qualification_scores else None
            avg_display = f" \u2014 gemiddeld {avg}%" if avg is not None else ""
            html.append(f"\U0001f4ca <b>Kwalificatievragen{avg_display}</b><ul>{''.join(qualification_items)}</ul>")

        return "".join(html)


async def trigger_screening_notes_integration(
    pool: asyncpg.Pool,
    application_id: uuid.UUID,
    recruiter_email: Optional[str] = None,
):
    """
    Background task wrapper for screening notes integration.

    Call this with asyncio.create_task() after transcript processing.
    Errors are logged but not raised.
    """
    try:
        service = ScreeningNotesIntegrationService(pool)
        result = await service.create_and_attach_notes(
            application_id=application_id,
            recruiter_email=recruiter_email,
        )
        logger.info(f"Screening notes integration complete for {application_id}: {result}")
    except Exception as e:
        logger.error(f"Screening notes integration failed for {application_id}: {e}")
