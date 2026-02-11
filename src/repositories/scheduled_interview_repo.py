"""
Scheduled Interview repository - handles interview slot database operations.
"""
import asyncpg
import uuid
from typing import Optional, Tuple
from datetime import date


class ScheduledInterviewRepository:
    """Repository for scheduled interview database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(
        self,
        vacancy_id: uuid.UUID,
        conversation_id: str,
        selected_date: date,
        selected_time: str,
        selected_slot_text: Optional[str] = None,
        application_id: Optional[uuid.UUID] = None,
        candidate_name: Optional[str] = None,
        candidate_phone: Optional[str] = None,
        channel: str = "voice",
        notes: Optional[str] = None,
        calendar_event_id: Optional[str] = None,
    ) -> uuid.UUID:
        """
        Create a new scheduled interview record.

        Returns:
            UUID of the created scheduled interview
        """
        result = await self.pool.fetchval(
            """
            INSERT INTO ats.scheduled_interviews (
                vacancy_id, application_id, conversation_id,
                candidate_name, candidate_phone,
                selected_date, selected_time, selected_slot_text,
                channel, notes, calendar_event_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
            """,
            vacancy_id,
            application_id,
            conversation_id,
            candidate_name,
            candidate_phone,
            selected_date,
            selected_time,
            selected_slot_text,
            channel,
            notes,
            calendar_event_id,
        )
        return result

    async def get_by_id(self, interview_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a scheduled interview by ID."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.scheduled_interviews WHERE id = $1",
            interview_id
        )

    async def get_by_conversation_id(self, conversation_id: str) -> Optional[asyncpg.Record]:
        """Get a scheduled interview by ElevenLabs conversation_id."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.scheduled_interviews WHERE conversation_id = $1",
            conversation_id
        )

    async def get_active_by_conversation_id(self, conversation_id: str) -> Optional[asyncpg.Record]:
        """
        Get the most recent active (not rescheduled/cancelled) interview by conversation_id.

        Used for reschedule operations to find the current active booking.
        """
        return await self.pool.fetchrow(
            """
            SELECT * FROM ats.scheduled_interviews
            WHERE conversation_id = $1
            AND status NOT IN ('rescheduled', 'cancelled')
            ORDER BY scheduled_at DESC
            LIMIT 1
            """,
            conversation_id
        )

    async def list_for_vacancy(
        self,
        vacancy_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """List scheduled interviews for a vacancy."""
        conditions = ["vacancy_id = $1"]
        params = [vacancy_id]
        param_idx = 2

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        # Get total count
        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM ats.scheduled_interviews WHERE {where_clause}",
            *params
        )

        # Get records
        query = f"""
            SELECT * FROM ats.scheduled_interviews
            WHERE {where_clause}
            ORDER BY selected_date ASC, selected_time ASC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])
        rows = await self.pool.fetch(query, *params)

        return rows, total

    async def update_status(
        self,
        interview_id: uuid.UUID,
        status: str,
        notes: Optional[str] = None
    ):
        """Update interview status."""
        timestamp_field = None
        if status == "confirmed":
            timestamp_field = "confirmed_at"
        elif status == "cancelled":
            timestamp_field = "cancelled_at"

        if timestamp_field:
            await self.pool.execute(
                f"""
                UPDATE ats.scheduled_interviews
                SET status = $2, {timestamp_field} = NOW(), updated_at = NOW(),
                    notes = COALESCE($3, notes)
                WHERE id = $1
                """,
                interview_id, status, notes
            )
        else:
            await self.pool.execute(
                """
                UPDATE ats.scheduled_interviews
                SET status = $2, updated_at = NOW(), notes = COALESCE($3, notes)
                WHERE id = $1
                """,
                interview_id, status, notes
            )

    async def link_application(
        self,
        interview_id: uuid.UUID,
        application_id: uuid.UUID
    ):
        """Link a scheduled interview to an application."""
        await self.pool.execute(
            """
            UPDATE ats.scheduled_interviews
            SET application_id = $2, updated_at = NOW()
            WHERE id = $1
            """,
            interview_id, application_id
        )

    async def update_calendar_event_id(
        self,
        interview_id: uuid.UUID,
        calendar_event_id: str
    ):
        """Update the Google Calendar event ID for an interview."""
        await self.pool.execute(
            """
            UPDATE ats.scheduled_interviews
            SET calendar_event_id = $2, updated_at = NOW()
            WHERE id = $1
            """,
            interview_id, calendar_event_id
        )

    async def find_vacancy_by_conversation(
        self,
        conversation_id: str
    ) -> Optional[asyncpg.Record]:
        """
        Find vacancy info by looking up conversation_id in screening_conversations.

        The ElevenLabs conversation_id is stored as session_id in screening_conversations
        for voice calls.
        """
        return await self.pool.fetchrow(
            """
            SELECT sc.vacancy_id, sc.candidate_name, sc.candidate_phone,
                   v.title as vacancy_title
            FROM ats.screening_conversations sc
            JOIN ats.vacancies v ON v.id = sc.vacancy_id
            WHERE sc.session_id = $1 AND sc.channel = 'voice'
            """,
            conversation_id
        )

    async def update_notes_by_conversation_id(
        self,
        conversation_id: str,
        notes: str,
        append: bool = False
    ) -> Optional[asyncpg.Record]:
        """
        Update notes for a scheduled interview by conversation_id.

        Args:
            conversation_id: ElevenLabs conversation_id
            notes: The notes/summary to add
            append: If True, append to existing notes. If False, replace.

        Returns:
            Updated record or None if not found
        """
        if append:
            # Append to existing notes with separator
            return await self.pool.fetchrow(
                """
                UPDATE ats.scheduled_interviews
                SET notes = CASE
                    WHEN notes IS NULL OR notes = '' THEN $2
                    ELSE notes || E'\n\n---\n\n' || $2
                END,
                updated_at = NOW()
                WHERE conversation_id = $1
                RETURNING *
                """,
                conversation_id,
                notes
            )
        else:
            # Replace notes
            return await self.pool.fetchrow(
                """
                UPDATE ats.scheduled_interviews
                SET notes = $2, updated_at = NOW()
                WHERE conversation_id = $1
                RETURNING *
                """,
                conversation_id,
                notes
            )
