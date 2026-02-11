"""
Scheduling service - handles time slot generation and scheduling for interviews.

This service provides the core business logic for:
- Generating available interview time slots (from Google Calendar or fallback)
- Formatting slots for voice/text output
- Scheduling interviews (creates Google Calendar events)
- Saving selected interview slots to database
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import asyncpg
from pydantic import BaseModel

from src.utils.dutch_dates import (
    DUTCH_DAYS,
    DUTCH_MONTHS,
    get_dutch_date,
    get_next_business_days,
)
from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository

logger = logging.getLogger(__name__)

# Timezone for Belgium
TIMEZONE = ZoneInfo("Europe/Brussels")


class TimeSlot(BaseModel):
    """A single day's available time slots."""
    date: str  # ISO format: YYYY-MM-DD
    dutch_date: str  # e.g., "Maandag 16 februari"
    morning: list[str]  # e.g., ["10u", "11u"]
    afternoon: list[str]  # e.g., ["14u", "16u"]


class SlotData(BaseModel):
    """Response containing available slots and formatted text."""
    slots: list[TimeSlot]
    formatted_text: str


class ScheduleResult(BaseModel):
    """Result of scheduling an interview."""
    confirmed: bool
    message: str
    slot: Optional[str] = None
    calendar_event_id: Optional[str] = None  # Google Calendar event ID


class SchedulingService:
    """
    Service for managing interview scheduling.

    Handles:
    - Generating available time slots (from Google Calendar when available)
    - Creating calendar events for scheduled interviews
    - Saving selected slots to database
    - Formatting slots for voice/text output
    """

    def __init__(self, pool: asyncpg.Pool = None):
        self.pool = pool
        self._repo = None
        self._calendar_service = None

    @property
    def calendar_service(self):
        """Lazy-load calendar service."""
        if self._calendar_service is None:
            # Only import if Google Calendar is configured
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

    def get_available_slots(
        self,
        recruiter_id: Optional[str] = None,
        days_ahead: int = 3,
        start_offset_days: int = 3,
    ) -> SlotData:
        """
        Get available time slots for scheduling interviews.

        Args:
            recruiter_id: Optional recruiter ID for calendar lookup (future)
            days_ahead: Number of business days to return
            start_offset_days: Start from N days in the future

        Returns:
            SlotData with slots and formatted Dutch text
        """
        logger.info(f"Getting available slots (recruiter={recruiter_id}, days={days_ahead})")

        # Start from +N days (get_next_business_days adds 1, so we use N-1)
        start_date = datetime.now() + timedelta(days=start_offset_days - 1)
        business_days = get_next_business_days(start_date, days_ahead)

        # Default time slots (future: read from recruiter preferences)
        morning_slots = ["10u", "11u"]
        afternoon_slots = ["14u", "16u"]

        slots = []
        formatted_lines = []

        for day in business_days:
            day_name = DUTCH_DAYS[day.weekday()].capitalize()
            month_name = DUTCH_MONTHS[day.month]
            dutch_date = f"{day_name} {day.day} {month_name}"

            slots.append(TimeSlot(
                date=day.strftime("%Y-%m-%d"),
                dutch_date=dutch_date,
                morning=morning_slots,
                afternoon=afternoon_slots
            ))

            formatted_lines.append(f"**{dutch_date}:**")
            formatted_lines.append(f"- Voormiddag: {', '.join(morning_slots)}")
            formatted_lines.append(f"- Namiddag: {', '.join(afternoon_slots)}")
            formatted_lines.append("")

        return SlotData(
            slots=slots,
            formatted_text="\n".join(formatted_lines).strip()
        )

    async def get_available_slots_async(
        self,
        recruiter_email: Optional[str] = None,
        days_ahead: int = 3,
        start_offset_days: int = 3,
    ) -> SlotData:
        """
        Get available time slots from Google Calendar.

        If recruiter_email is provided and Google Calendar is configured,
        queries real calendar availability. Otherwise falls back to default slots.

        Args:
            recruiter_email: Recruiter's email for calendar lookup
            days_ahead: Number of business days to return
            start_offset_days: Start from N days in the future

        Returns:
            SlotData with slots and formatted Dutch text
        """
        # If calendar service is available and email provided, use real data
        if self.calendar_service and recruiter_email:
            try:
                logger.info(f"Fetching real calendar availability for {recruiter_email}")
                calendar_slots = await self.calendar_service.get_available_slots(
                    calendar_email=recruiter_email,
                    days_ahead=days_ahead,
                    start_offset_days=start_offset_days,
                )

                if calendar_slots:
                    # Convert to TimeSlot format
                    slots = [
                        TimeSlot(
                            date=s["date"],
                            dutch_date=s["dutch_date"],
                            morning=s["morning"],
                            afternoon=s["afternoon"],
                        )
                        for s in calendar_slots
                    ]

                    formatted_lines = []
                    for slot in slots:
                        formatted_lines.append(f"**{slot.dutch_date}:**")
                        if slot.morning:
                            formatted_lines.append(f"- Voormiddag: {', '.join(slot.morning)}")
                        if slot.afternoon:
                            formatted_lines.append(f"- Namiddag: {', '.join(slot.afternoon)}")
                        formatted_lines.append("")

                    return SlotData(
                        slots=slots,
                        formatted_text="\n".join(formatted_lines).strip()
                    )
                else:
                    logger.warning(f"No calendar slots found for {recruiter_email}")

            except Exception as e:
                logger.error(f"Failed to get calendar slots for {recruiter_email}: {e}")
                # Fall through to default slots

        # Fallback to default slots (sync version)
        logger.info("Using default slots (no calendar integration)")
        return self.get_available_slots(days_ahead=days_ahead, start_offset_days=start_offset_days)

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
        # Parse the time
        time_str = time.lower().replace("u", "").replace(":", "")
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
        event_link = None

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
                event_link = event.get("htmlLink")
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

    def format_slots_for_voice(self, slots: list[TimeSlot]) -> str:
        """
        Format slots for voice output (more natural speech).

        Args:
            slots: List of TimeSlot objects

        Returns:
            Natural Dutch text suitable for TTS
        """
        if not slots:
            return "Er zijn momenteel geen beschikbare tijdsloten."

        parts = []
        for slot in slots:
            morning = " of ".join(slot.morning) if slot.morning else None
            afternoon = " of ".join(slot.afternoon) if slot.afternoon else None

            if morning and afternoon:
                parts.append(f"{slot.dutch_date} 's ochtends om {morning}, of 's middags om {afternoon}")
            elif morning:
                parts.append(f"{slot.dutch_date} 's ochtends om {morning}")
            elif afternoon:
                parts.append(f"{slot.dutch_date} 's middags om {afternoon}")

        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return f"{parts[0]}, of {parts[1]}"
        else:
            return ", ".join(parts[:-1]) + f", of {parts[-1]}"

    def schedule_slot(
        self,
        slot: str,
        conversation_id: str,
        candidate_id: Optional[str] = None,
    ) -> ScheduleResult:
        """
        Schedule an interview for the given slot.

        Args:
            slot: The selected time slot (e.g., "maandag om 10 uur")
            conversation_id: The conversation ID for tracking
            candidate_id: Optional candidate ID

        Returns:
            ScheduleResult with confirmation
        """
        logger.info(f"Scheduling slot: {slot} for conversation {conversation_id}")

        # Future: Actually create calendar event, send confirmation email, etc.
        return ScheduleResult(
            confirmed=True,
            message=f"Perfect! Je staat ingepland voor {slot}. Je krijgt een bevestiging per SMS.",
            slot=slot
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
        Save a scheduled interview slot from ElevenLabs webhook.

        Looks up vacancy_id from conversation_id via screening_conversations.

        Args:
            conversation_id: ElevenLabs conversation ID
            selected_date: Date in YYYY-MM-DD format
            selected_time: Time slot (e.g., "10u", "14u")
            selected_slot_text: Full Dutch text for display
            candidate_name: Candidate's name (may be overridden by DB lookup)
            candidate_phone: Candidate's phone (may be overridden by DB lookup)
            candidate_email: Candidate's email for calendar invite
            notes: Optional notes

        Returns:
            dict with success status and scheduled interview details

        Raises:
            ValueError: If conversation_id not found or vacancy lookup fails
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


# Singleton instance for easy import
scheduling_service = SchedulingService()
