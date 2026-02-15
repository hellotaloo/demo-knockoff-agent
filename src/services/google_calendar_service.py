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
                    available_morning.append(f"{hour} uur")

            for hour in DEFAULT_AFTERNOON_SLOTS:
                slot_start = datetime.combine(day, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
                slot_end = slot_start + timedelta(minutes=slot_duration_minutes)

                if self._is_slot_available(slot_start, slot_end, busy_times):
                    available_afternoon.append(f"{hour} uur")

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

    async def get_quick_slots(
        self,
        calendar_email: str,
        num_days: int = 3,
        start_offset_days: int = 3,
        slot_duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
        max_times_per_day: int = 2,
    ) -> list[dict]:
        """
        Get the first N available days with limited time slots per day.

        Returns days with times, formatted for voice output.
        Used when the candidate has no preference and wants options.

        Args:
            calendar_email: The recruiter's calendar email
            num_days: Number of days to return (default 3)
            start_offset_days: Start from N days in the future
            slot_duration_minutes: Required slot duration
            max_times_per_day: Maximum times to return per day (default 2)

        Returns:
            List of days with times: [
                {
                    "date": "2026-02-17",
                    "dutch_date": "Dinsdag 17 februari",
                    "times": ["10 uur", "14 uur"],
                    "dutch_text": "Dinsdag om 10 uur en 14 uur"
                },
                ...
            ]
        """
        # Get more days than needed to ensure we find enough
        full_slots = await self.get_available_slots(
            calendar_email=calendar_email,
            days_ahead=num_days + 2,
            start_offset_days=start_offset_days,
            slot_duration_minutes=slot_duration_minutes,
        )

        if not full_slots:
            return []

        # Take first N days and format for voice
        selected_days = []
        for day_slot in full_slots[:num_days]:
            morning_times = day_slot["morning"]
            afternoon_times = day_slot["afternoon"]

            # Combine and limit times for voice: "Dinsdag om 10 uur en 14 uur"
            all_times = (morning_times + afternoon_times)[:max_times_per_day]
            day_name = day_slot["dutch_date"].split()[0]  # "Dinsdag" from "Dinsdag 17 februari"

            # Simple format: "Dinsdag om 11 uur, 14 uur en 16 uur"
            if len(all_times) == 1:
                dutch_text = f"{day_name} om {all_times[0]}"
            elif len(all_times) == 2:
                dutch_text = f"{day_name} om {all_times[0]} en {all_times[1]}"
            else:
                dutch_text = f"{day_name} om {', '.join(all_times[:-1])} en {all_times[-1]}"

            selected_days.append({
                "date": day_slot["date"],
                "dutch_date": day_slot["dutch_date"],
                "times": all_times,
                "dutch_text": dutch_text,
            })

        logger.info(f"Selected {len(selected_days)} days with slots for {calendar_email}")
        return selected_days

    async def get_slots_for_date(
        self,
        calendar_email: str,
        target_date: str,
        slot_duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
    ) -> dict | None:
        """
        Get available slots for a specific date.

        Args:
            calendar_email: The recruiter's calendar email
            target_date: Date in YYYY-MM-DD format
            slot_duration_minutes: Required slot duration

        Returns:
            Dict with date info and available slots, or None if no slots available
        """
        from datetime import date as date_type

        try:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid date format: {target_date}")
            return None

        # Query free/busy for just this day
        time_min = datetime.combine(target, datetime.min.time(), tzinfo=TIMEZONE)
        time_max = datetime.combine(target, datetime.max.time(), tzinfo=TIMEZONE)

        busy_times = await self.get_free_busy(calendar_email, time_min, time_max)

        # Generate Dutch date text
        day_name = DUTCH_DAYS[target.weekday()].capitalize()
        month_name = DUTCH_MONTHS[target.month]
        dutch_date = f"{day_name} {target.day} {month_name}"

        available_morning = []
        available_afternoon = []

        # Check each potential slot
        for hour in DEFAULT_MORNING_SLOTS:
            slot_start = datetime.combine(target, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
            slot_end = slot_start + timedelta(minutes=slot_duration_minutes)

            if self._is_slot_available(slot_start, slot_end, busy_times):
                available_morning.append(f"{hour} uur")

        for hour in DEFAULT_AFTERNOON_SLOTS:
            slot_start = datetime.combine(target, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
            slot_end = slot_start + timedelta(minutes=slot_duration_minutes)

            if self._is_slot_available(slot_start, slot_end, busy_times):
                available_afternoon.append(f"{hour} uur")

        if not available_morning and not available_afternoon:
            logger.info(f"No available slots on {target_date} for {calendar_email}")
            return None

        logger.info(f"Found slots on {target_date} for {calendar_email}: morning={available_morning}, afternoon={available_afternoon}")
        return {
            "date": target_date,
            "dutch_date": dutch_date,
            "morning": available_morning,
            "afternoon": available_afternoon,
        }

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

    async def update_event(
        self,
        calendar_email: str,
        event_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        append_description: bool = False,
        start_time: Optional[datetime] = None,
        duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
    ) -> dict | None:
        """
        Update an existing calendar event.

        Only updates fields that are provided (non-None). Preserves all other
        fields including any notes the recruiter may have added.

        Args:
            calendar_email: The calendar owner's email
            event_id: The event ID to update
            summary: New event title (optional)
            description: New description (optional)
            append_description: If True, append to existing description instead of replacing
            start_time: New start time (optional) - used for rescheduling
            duration_minutes: Duration in minutes (only used if start_time is provided)

        Returns:
            Updated event dict or None if failed
        """
        service = self._get_service(impersonate_email=calendar_email)

        try:
            # Get current event to preserve existing fields
            event = service.events().get(calendarId=calendar_email, eventId=event_id).execute()

            # Update only the fields that are provided
            if summary is not None:
                event["summary"] = summary

            if description is not None:
                if append_description and event.get("description"):
                    event["description"] = event["description"] + "\n\n" + description
                else:
                    event["description"] = description

            # Update time if provided (for rescheduling)
            if start_time is not None:
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=TIMEZONE)
                end_time = start_time + timedelta(minutes=duration_minutes)

                event["start"] = {
                    "dateTime": start_time.isoformat(),
                    "timeZone": TIMEZONE_STR,
                }
                event["end"] = {
                    "dateTime": end_time.isoformat(),
                    "timeZone": TIMEZONE_STR,
                }

            # Update the event
            updated_event = service.events().update(
                calendarId=calendar_email,
                eventId=event_id,
                body=event
            ).execute()

            logger.info(f"Updated calendar event: {event_id}")

            return {
                "id": updated_event.get("id"),
                "htmlLink": updated_event.get("htmlLink"),
                "summary": updated_event.get("summary"),
                "description": updated_event.get("description"),
                "start": updated_event.get("start"),
                "end": updated_event.get("end"),
            }

        except HttpError as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            return None

    async def add_attachment_to_event(
        self,
        calendar_email: str,
        event_id: str,
        file_url: str,
        file_title: str,
        description_note: Optional[str] = None,
        mime_type: str = "application/vnd.google-apps.document",
    ) -> bool:
        """
        Add an attachment (Google Drive link) to a calendar event.

        Attempts to add as a native Google Calendar attachment first.
        Falls back to embedding the link in the event description.

        Args:
            calendar_email: The calendar owner's email
            event_id: The calendar event ID
            file_url: URL of the Google Drive file
            file_title: Title/name of the file
            description_note: Optional note to add to event description (e.g., executive summary)
            mime_type: MIME type of the file

        Returns:
            True if updated successfully
        """
        import re

        service = self._get_service(impersonate_email=calendar_email)

        # Extract file ID from URL for native attachments
        file_id = None
        patterns = [
            r"/document/d/([a-zA-Z0-9_-]+)",
            r"/file/d/([a-zA-Z0-9_-]+)",
            r"id=([a-zA-Z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, file_url)
            if match:
                file_id = match.group(1)
                break

        try:
            # Get current event
            event = service.events().get(calendarId=calendar_email, eventId=event_id).execute()

            # Build new description
            # Start with the description note (executive summary) if provided
            if description_note:
                new_description = description_note
            else:
                new_description = event.get("description", "")

            # Add document link to description as fallback
            doc_link = f"\n\n📄 Screening Notule: {file_url}"
            new_description = new_description + doc_link

            event["description"] = new_description

            # Try to add as native attachment
            # Native attachments require:
            # 1. supportsAttachments=True
            # 2. Properly formatted attachment object with fileId
            native_attachment_success = False

            if file_id:
                try:
                    if "attachments" not in event:
                        event["attachments"] = []

                    # Use fileId for native attachment (more reliable than fileUrl)
                    attachment = {
                        "fileId": file_id,
                        "fileUrl": file_url,
                        "title": file_title,
                        "mimeType": mime_type,
                    }
                    event["attachments"].append(attachment)

                    updated_event = service.events().update(
                        calendarId=calendar_email,
                        eventId=event_id,
                        body=event,
                        supportsAttachments=True
                    ).execute()

                    # Check if attachment was actually added
                    if updated_event.get("attachments"):
                        native_attachment_success = True
                        logger.info(f"Added native attachment to calendar event {event_id}")

                except HttpError as attach_error:
                    # Native attachment failed - fall back to description only
                    logger.warning(f"Native attachment failed, using description link: {attach_error}")
                    if "attachments" in event:
                        del event["attachments"]
                    service.events().update(
                        calendarId=calendar_email,
                        eventId=event_id,
                        body=event
                    ).execute()
            else:
                # No file ID extracted, just update description
                logger.info(f"Could not extract file ID from URL, updating description only")
                service.events().update(
                    calendarId=calendar_email,
                    eventId=event_id,
                    body=event
                ).execute()

            logger.info(f"Updated calendar event {event_id} (native_attachment={native_attachment_success})")
            return True

        except HttpError as e:
            logger.error(f"Failed to add attachment to event {event_id}: {e}")
            return False

    async def get_event(self, calendar_email: str, event_id: str) -> Optional[dict]:
        """
        Get a calendar event by ID.

        Args:
            calendar_email: The calendar owner's email
            event_id: The event ID

        Returns:
            Event dict or None if not found
        """
        service = self._get_service(impersonate_email=calendar_email)

        try:
            event = service.events().get(calendarId=calendar_email, eventId=event_id).execute()
            return event
        except HttpError as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            return None


# Singleton instance
calendar_service = GoogleCalendarService()
