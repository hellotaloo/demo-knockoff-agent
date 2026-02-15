"""
Scheduling service - handles interview scheduling and calendar event creation.

This service provides:
- Creating calendar events for scheduled interviews
- Saving selected interview slots to database
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import asyncpg
from pydantic import BaseModel

from src.utils.dutch_dates import get_dutch_date
from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository

logger = logging.getLogger(__name__)

# Timezone for Belgium
TIMEZONE = ZoneInfo("Europe/Brussels")


class ScheduleResult(BaseModel):
    """Result of scheduling an interview."""
    confirmed: bool
    message: str
    slot: Optional[str] = None
    calendar_event_id: Optional[str] = None


class SchedulingService:
    """
    Service for scheduling interviews.

    Handles:
    - Creating calendar events for scheduled interviews
    - Saving selected slots to database
    """

    def __init__(self, pool: asyncpg.Pool = None):
        self.pool = pool
        self._repo = None
        self._calendar_service = None

    @property
    def calendar_service(self):
        """Lazy-load calendar service."""
        if self._calendar_service is None:
            if os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
                from src.services.google_calendar_service import calendar_service
                self._calendar_service = calendar_service
        return self._calendar_service

    @property
    def repo(self) -> ScheduledInterviewRepository:
        """Lazy-load repository."""
        if self._repo is None and self.pool:
            self._repo = ScheduledInterviewRepository(self.pool)
        return self._repo

    async def schedule_slot_async(
        self,
        recruiter_email: str,
        candidate_name: str,
        date: str,
        time: str,
        conversation_id: Optional[str] = None,
        duration_minutes: int = 30,
        candidate_email: Optional[str] = None,
    ) -> ScheduleResult:
        """
        Schedule an interview and create a Google Calendar event.

        Args:
            recruiter_email: Recruiter's email for calendar event
            candidate_name: Candidate's name for event title
            date: Date in YYYY-MM-DD format
            time: Time in "10u" or "14u" format
            conversation_id: Optional conversation ID for tracking
            duration_minutes: Interview duration in minutes
            candidate_email: Optional candidate email to send calendar invite

        Returns:
            ScheduleResult with confirmation and calendar event details
        """
        # Parse the time (handle "10u", "10 uur", "10:00" formats)
        time_str = time.lower().replace(" uur", "").replace("uur", "").replace("u", "").replace(":", "")
        try:
            hour = int(time_str[:2]) if len(time_str) >= 2 else int(time_str)
        except ValueError:
            return ScheduleResult(
                confirmed=False,
                message=f"Ongeldige tijd: {time}",
            )

        # Parse the date
        try:
            interview_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return ScheduleResult(
                confirmed=False,
                message=f"Ongeldige datum: {date}",
            )

        # Create start time with timezone
        start_time = interview_date.replace(hour=hour, minute=0, second=0, tzinfo=TIMEZONE)
        dutch_date = get_dutch_date(start_time)
        slot_text = f"{dutch_date} om {hour}u"

        # Try to create calendar event if service is available
        event_id = None

        if self.calendar_service and recruiter_email:
            try:
                event = await self.calendar_service.create_event(
                    calendar_email=recruiter_email,
                    summary=f"Interview - {candidate_name}",
                    start_time=start_time,
                    duration_minutes=duration_minutes,
                    description=f"Screeningsgesprek met {candidate_name}",
                    attendee_email=candidate_email,
                )
                event_id = event.get("id")
                invite_note = f" (invite sent to {candidate_email})" if candidate_email else ""
                logger.info(f"Created calendar event {event_id} for {candidate_name}{invite_note}")
            except Exception as e:
                logger.error(f"Failed to create calendar event: {e}")
                # Continue without calendar event

        return ScheduleResult(
            confirmed=True,
            message=f"Perfect! Je staat ingepland voor {slot_text}. Je krijgt een bevestiging per SMS.",
            slot=slot_text,
            calendar_event_id=event_id,
        )

    async def save_scheduled_slot(
        self,
        conversation_id: str,
        selected_date: str,
        selected_time: str,
        selected_slot_text: str = None,
        candidate_name: str = None,
        candidate_phone: str = None,
        candidate_email: str = None,
        notes: str = None,
    ) -> dict:
        """
        Save a scheduled interview slot from webhook.

        Looks up vacancy_id from conversation_id via screening_conversations.

        Args:
            conversation_id: Conversation ID (e.g., from ElevenLabs)
            selected_date: Date in YYYY-MM-DD format
            selected_time: Time slot (e.g., "10u", "14u")
            selected_slot_text: Full Dutch text for display
            candidate_name: Candidate's name
            candidate_phone: Candidate's phone
            candidate_email: Candidate's email for calendar invite
            notes: Optional notes

        Returns:
            dict with success status and scheduled interview details
        """
        if not self.repo:
            raise RuntimeError("SchedulingService requires pool for database operations")

        # Look up vacancy_id from conversation_id
        conv_info = await self.repo.find_vacancy_by_conversation(conversation_id)

        if not conv_info:
            logger.warning(f"No screening conversation found for conversation_id: {conversation_id}")
            raise ValueError(f"Conversation not found: {conversation_id}")

        vacancy_id = conv_info["vacancy_id"]
        vacancy_title = conv_info["vacancy_title"]

        # Use candidate info from DB if not provided
        final_candidate_name = candidate_name or conv_info["candidate_name"]
        final_candidate_phone = candidate_phone or conv_info["candidate_phone"]

        # Parse date
        try:
            date_obj = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"Invalid date format: {selected_date}. Expected YYYY-MM-DD")

        # Create scheduled interview
        interview_id = await self.repo.create(
            vacancy_id=vacancy_id,
            conversation_id=conversation_id,
            selected_date=date_obj,
            selected_time=selected_time,
            selected_slot_text=selected_slot_text,
            candidate_name=final_candidate_name,
            candidate_phone=final_candidate_phone,
            channel="voice",
            notes=notes,
        )

        logger.info(
            f"Scheduled interview {interview_id} for vacancy {vacancy_id}: "
            f"{selected_date} at {selected_time}"
        )

        return {
            "success": True,
            "scheduled_interview_id": str(interview_id),
            "vacancy_id": str(vacancy_id),
            "vacancy_title": vacancy_title,
            "selected_date": selected_date,
            "selected_time": selected_time,
            "selected_slot_text": selected_slot_text,
            "candidate_name": final_candidate_name,
            "candidate_email": candidate_email,
            "message": f"Interview gepland voor {selected_slot_text or f'{selected_date} om {selected_time}'}"
        }


# Singleton instance
scheduling_service = SchedulingService()
