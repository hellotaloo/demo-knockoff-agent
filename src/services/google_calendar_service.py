"""
Google Calendar Service for interview scheduling.

This module provides functionality to:
1. Query free/busy times from Google Calendar
2. Get available interview slots based on recruiter availability
3. Create calendar events for scheduled interviews

Uses Service Account with Domain-Wide Delegation for Workspace access.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.utils.dutch_dates import DUTCH_DAYS, DUTCH_MONTHS, get_next_business_days

logger = logging.getLogger(__name__)


# Timezone for Belgium/Netherlands
TIMEZONE = ZoneInfo("Europe/Brussels")
TIMEZONE_STR = "Europe/Brussels"

# Default interview duration
DEFAULT_INTERVIEW_DURATION_MINUTES = 30

# Default time slots (in 24h format)
DEFAULT_MORNING_SLOTS = [10, 11]  # 10:00, 11:00
DEFAULT_AFTERNOON_SLOTS = [14, 16]  # 14:00, 16:00


class GoogleCalendarService:
    """
    Service for interacting with Google Calendar API.

    Uses lazy initialization and singleton pattern for the API client.
    Supports Domain-Wide Delegation to access any user's calendar in the Workspace.
    """

    def __init__(self):
        self._service = None
        self._credentials = None

    def _get_credentials(self, impersonate_email: Optional[str] = None):
        """
        Get credentials for Google Calendar API.

        Args:
            impersonate_email: Email to impersonate (for domain-wide delegation).
                             If not provided, uses GOOGLE_CALENDAR_IMPERSONATE_EMAIL env var.

        Returns:
            google.oauth2.service_account.Credentials
        """
        service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not service_account_file:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_FILE environment variable is required. "
                "Set it to the path of your service account JSON key file."
            )

        subject = impersonate_email or os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=["https://www.googleapis.com/auth/calendar"],
            subject=subject,
        )

        logger.info(f"Created Google Calendar credentials (impersonating: {subject or 'none'})")
        return credentials

    def _get_service(self, impersonate_email: Optional[str] = None):
        """
        Get or create the Google Calendar API service.

        Args:
            impersonate_email: Optional email to impersonate for this request

        Returns:
            googleapiclient.discovery.Resource: Calendar API service
        """
        # If impersonating a specific user, create a new service
        if impersonate_email:
            credentials = self._get_credentials(impersonate_email)
            return build("calendar", "v3", credentials=credentials, cache_discovery=False)

        # Otherwise use cached service
        if self._service is None:
            self._credentials = self._get_credentials()
            self._service = build("calendar", "v3", credentials=self._credentials, cache_discovery=False)
            logger.info("Created Google Calendar API service")

        return self._service

    async def get_free_busy(
        self,
        calendar_email: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict]:
        """
        Query free/busy times for a calendar.

        Args:
            calendar_email: The calendar ID (usually email address)
            time_min: Start of the time range
            time_max: End of the time range

        Returns:
            List of busy time blocks: [{"start": datetime, "end": datetime}, ...]
        """
        service = self._get_service(impersonate_email=calendar_email)

        # Ensure times are in ISO format with timezone
        if time_min.tzinfo is None:
            time_min = time_min.replace(tzinfo=TIMEZONE)
        if time_max.tzinfo is None:
            time_max = time_max.replace(tzinfo=TIMEZONE)

        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "timeZone": TIMEZONE_STR,
            "items": [{"id": calendar_email}],
        }

        try:
            response = service.freebusy().query(body=body).execute()
            busy_times = response.get("calendars", {}).get(calendar_email, {}).get("busy", [])

            logger.info(f"Found {len(busy_times)} busy blocks for {calendar_email}")

            # Convert to datetime objects
            return [
                {
                    "start": datetime.fromisoformat(block["start"].replace("Z", "+00:00")),
                    "end": datetime.fromisoformat(block["end"].replace("Z", "+00:00")),
                }
                for block in busy_times
            ]

        except HttpError as e:
            logger.error(f"Failed to query free/busy for {calendar_email}: {e}")
            raise

    async def get_available_slots(
        self,
        calendar_email: str,
        days_ahead: int = 3,
        start_offset_days: int = 3,
        slot_duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
    ) -> list[dict]:
        """
        Get available interview slots based on calendar availability.

        Args:
            calendar_email: The recruiter's calendar email
            days_ahead: Number of business days to check
            start_offset_days: Start from N days in the future
            slot_duration_minutes: Required slot duration

        Returns:
            List of available slots with date and time info
        """
        # Calculate time range
        start_date = datetime.now(TIMEZONE) + timedelta(days=start_offset_days - 1)
        business_days = get_next_business_days(start_date, days_ahead)

        if not business_days:
            return []

        # Query free/busy for the entire range
        time_min = datetime.combine(business_days[0], datetime.min.time(), tzinfo=TIMEZONE)
        time_max = datetime.combine(business_days[-1], datetime.max.time(), tzinfo=TIMEZONE)

        busy_times = await self.get_free_busy(calendar_email, time_min, time_max)

        # Generate available slots
        slots = []

        for day in business_days:
            day_name = DUTCH_DAYS[day.weekday()].capitalize()
            month_name = DUTCH_MONTHS[day.month]
            dutch_date = f"{day_name} {day.day} {month_name}"

            available_morning = []
            available_afternoon = []

            # Check each potential slot
            for hour in DEFAULT_MORNING_SLOTS:
                slot_start = datetime.combine(day, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
                slot_end = slot_start + timedelta(minutes=slot_duration_minutes)

                if self._is_slot_available(slot_start, slot_end, busy_times):
                    available_morning.append(f"{hour}u")

            for hour in DEFAULT_AFTERNOON_SLOTS:
                slot_start = datetime.combine(day, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
                slot_end = slot_start + timedelta(minutes=slot_duration_minutes)

                if self._is_slot_available(slot_start, slot_end, busy_times):
                    available_afternoon.append(f"{hour}u")

            # Only include day if there are available slots
            if available_morning or available_afternoon:
                slots.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "dutch_date": dutch_date,
                    "morning": available_morning,
                    "afternoon": available_afternoon,
                })

        logger.info(f"Found {len(slots)} days with available slots for {calendar_email}")
        return slots

    def _is_slot_available(
        self,
        slot_start: datetime,
        slot_end: datetime,
        busy_times: list[dict],
    ) -> bool:
        """Check if a time slot is available (not overlapping with busy times)."""
        for busy in busy_times:
            # Check for overlap
            if slot_start < busy["end"] and slot_end > busy["start"]:
                return False
        return True

    async def create_event(
        self,
        calendar_email: str,
        summary: str,
        start_time: datetime,
        duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
        description: Optional[str] = None,
        attendee_email: Optional[str] = None,
    ) -> dict:
        """
        Create a calendar event for an interview.

        Args:
            calendar_email: The recruiter's calendar email
            summary: Event title (e.g., "Interview - Jan Janssen")
            start_time: Start time of the interview
            duration_minutes: Duration in minutes
            description: Optional event description
            attendee_email: Optional attendee to invite

        Returns:
            Created event details with id, htmlLink, etc.
        """
        service = self._get_service(impersonate_email=calendar_email)

        # Ensure start time has timezone
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=TIMEZONE)

        end_time = start_time + timedelta(minutes=duration_minutes)

        event = {
            "summary": summary,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": TIMEZONE_STR,
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": TIMEZONE_STR,
            },
        }

        if description:
            event["description"] = description

        if attendee_email:
            event["attendees"] = [{"email": attendee_email}]

        try:
            created_event = service.events().insert(
                calendarId=calendar_email,
                body=event,
                sendUpdates="all" if attendee_email else "none",
            ).execute()

            logger.info(f"Created calendar event: {created_event.get('id')} for {calendar_email}")

            return {
                "id": created_event.get("id"),
                "htmlLink": created_event.get("htmlLink"),
                "summary": created_event.get("summary"),
                "start": created_event.get("start"),
                "end": created_event.get("end"),
            }

        except HttpError as e:
            logger.error(f"Failed to create event for {calendar_email}: {e}")
            raise

    async def delete_event(self, calendar_email: str, event_id: str) -> bool:
        """
        Delete a calendar event.

        Args:
            calendar_email: The calendar owner's email
            event_id: The event ID to delete

        Returns:
            True if deleted successfully
        """
        service = self._get_service(impersonate_email=calendar_email)

        try:
            service.events().delete(calendarId=calendar_email, eventId=event_id).execute()
            logger.info(f"Deleted calendar event: {event_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            return False


# Singleton instance
calendar_service = GoogleCalendarService()
