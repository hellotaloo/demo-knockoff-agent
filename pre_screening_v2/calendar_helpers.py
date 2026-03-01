"""
Google Calendar helpers for the pre_screening_v2 agent.

Provides real calendar availability lookup and event creation via Google Calendar API,
with graceful fallback when credentials are not configured.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMEZONE = ZoneInfo("Europe/Brussels")
TIMEZONE_STR = "Europe/Brussels"

DEFAULT_MORNING_SLOTS = [10, 11]
DEFAULT_AFTERNOON_SLOTS = [14, 16]
DEFAULT_INTERVIEW_DURATION_MINUTES = 30

DUTCH_DAYS = {
    0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
    4: "vrijdag", 5: "zaterdag", 6: "zondag",
}
DUTCH_MONTHS = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}

# Project root — used to resolve relative credential paths during local dev.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_calendar_configured() -> bool:
    """Return True if Google Calendar credentials are available."""
    return bool(
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        and os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    )


def _resolve_credentials_path() -> str:
    """Resolve the service-account JSON path, handling relative paths."""
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if path and not os.path.isabs(path) and not os.path.exists(path):
        resolved = _PROJECT_ROOT / path
        if resolved.exists():
            return str(resolved)
    return path


def _get_next_business_days(start_date: datetime, num_days: int) -> list:
    """Return the next *num_days* business days (Mon-Fri) after *start_date*."""
    days: list[datetime] = []
    current = start_date
    while len(days) < num_days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days.append(current)
    return days


def _dutch_date_label(d, day_name: str, month_name: str) -> str:
    """Build a TTS-friendly date label, prefixing 'morgen' when applicable."""
    today = datetime.now(TIMEZONE).date()
    # d may be a datetime or a date; normalise to date
    day = d.date() if isinstance(d, datetime) else d
    prefix = "morgen " if (day - today).days == 1 else ""
    return f"{prefix}{day_name} {day.day} {month_name}"


def _format_day_slots(dutch_date: str, times: list[str]) -> str:
    """Format a day's slots for TTS: 'maandag 3 maart om 10 uur en 14 uur'."""
    if len(times) == 1:
        return f"{dutch_date} om {times[0]}"
    if len(times) == 2:
        return f"{dutch_date} om {times[0]} en {times[1]}"
    return f"{dutch_date} om {', '.join(times[:-1])} en {times[-1]}"


# ---------------------------------------------------------------------------
# Calendar service (private)
# ---------------------------------------------------------------------------

class _CalendarService:
    """Minimal Google Calendar client for free/busy queries and event creation."""

    def __init__(self):
        self._service_cache: dict = {}

    def _get_service(self, impersonate_email: str):
        if impersonate_email in self._service_cache:
            return self._service_cache[impersonate_email]

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        cred_path = _resolve_credentials_path()
        credentials = service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/calendar"],
            subject=impersonate_email,
        )
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self._service_cache[impersonate_email] = service
        logger.info(f"Created Google Calendar service (impersonating {impersonate_email})")
        return service

    # -- Free/busy query (sync, called via asyncio.to_thread) ----------------

    def _query_free_busy_sync(
        self, calendar_email: str, time_min: datetime, time_max: datetime
    ) -> list[dict]:
        from googleapiclient.errors import HttpError

        service = self._get_service(calendar_email)

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
            return [
                {
                    "start": datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                    "end": datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
                }
                for b in busy_times
            ]
        except HttpError as e:
            logger.error(f"Free/busy query failed for {calendar_email}: {e}")
            raise

    async def get_free_busy(
        self, calendar_email: str, time_min: datetime, time_max: datetime
    ) -> list[dict]:
        return await asyncio.to_thread(
            self._query_free_busy_sync, calendar_email, time_min, time_max
        )

    # -- Slot availability check ---------------------------------------------

    @staticmethod
    def _is_slot_available(slot_start: datetime, slot_end: datetime, busy_times: list[dict]) -> bool:
        for busy in busy_times:
            if slot_start < busy["end"] and slot_end > busy["start"]:
                return False
        return True

    # -- Available slots for a date range ------------------------------------

    async def get_available_slots(
        self,
        calendar_email: str,
        days_ahead: int = 3,
        start_offset_days: int = 1,
        slot_duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
    ) -> list[dict]:
        start_date = datetime.now(TIMEZONE) + timedelta(days=start_offset_days - 1)
        business_days = _get_next_business_days(start_date, days_ahead)
        if not business_days:
            return []

        time_min = datetime.combine(business_days[0], datetime.min.time(), tzinfo=TIMEZONE)
        time_max = datetime.combine(business_days[-1], datetime.max.time(), tzinfo=TIMEZONE)
        busy_times = await self.get_free_busy(calendar_email, time_min, time_max)

        slots = []
        for day in business_days:
            day_name = DUTCH_DAYS[day.weekday()]
            month_name = DUTCH_MONTHS[day.month]
            dutch_date = _dutch_date_label(day, day_name, month_name)

            morning = []
            afternoon = []
            for hour in DEFAULT_MORNING_SLOTS:
                start = datetime.combine(day, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
                if self._is_slot_available(start, start + timedelta(minutes=slot_duration_minutes), busy_times):
                    morning.append(f"{hour} uur")
            for hour in DEFAULT_AFTERNOON_SLOTS:
                start = datetime.combine(day, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
                if self._is_slot_available(start, start + timedelta(minutes=slot_duration_minutes), busy_times):
                    afternoon.append(f"{hour} uur")

            if morning or afternoon:
                slots.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "dutch_date": dutch_date,
                    "morning": morning,
                    "afternoon": afternoon,
                })

        logger.info(f"Found {len(slots)} days with availability for {calendar_email}")
        return slots

    # -- Quick slots (initial offer) -----------------------------------------

    async def get_quick_slots(
        self,
        calendar_email: str,
        num_days: int = 3,
        start_offset_days: int = 1,
        max_times_per_day: int = 2,
    ) -> list[dict]:
        full_slots = await self.get_available_slots(
            calendar_email=calendar_email,
            days_ahead=num_days + 2,
            start_offset_days=start_offset_days,
        )
        if not full_slots:
            return []

        chosen_days = full_slots[:num_days]

        # Pick one time per day
        selected = []
        for day_slot in chosen_days:
            all_times = (day_slot["morning"] + day_slot["afternoon"])[:max_times_per_day]
            selected.append({
                "date": day_slot["date"],
                "dutch_date": day_slot["dutch_date"],
                "times": all_times,
                "_pool": day_slot["morning"] + day_slot["afternoon"],
            })

        # Diversify: when every day picked the same single time (e.g. all "10 uur"),
        # spread across different available times so it feels more natural.
        if (
            max_times_per_day == 1
            and len(selected) > 1
            and len({s["times"][0] for s in selected}) == 1
        ):
            used: set[str] = set()
            for slot in selected:
                pick = next((t for t in slot["_pool"] if t not in used), slot["_pool"][0])
                slot["times"] = [pick]
                used.add(pick)

        # Format and clean up
        for slot in selected:
            slot["dutch_text"] = _format_day_slots(slot["dutch_date"], slot["times"])
            del slot["_pool"]

        logger.info(f"Selected {len(selected)} quick-slot days for {calendar_email}")
        return selected

    # -- Slots for a specific date -------------------------------------------

    async def get_slots_for_date(
        self,
        calendar_email: str,
        target_date: str,
    ) -> Optional[dict]:
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid date format: {target_date}")
            return None

        time_min = datetime.combine(target, datetime.min.time(), tzinfo=TIMEZONE)
        time_max = datetime.combine(target, datetime.max.time(), tzinfo=TIMEZONE)
        busy_times = await self.get_free_busy(calendar_email, time_min, time_max)

        day_name = DUTCH_DAYS[target.weekday()]
        month_name = DUTCH_MONTHS[target.month]
        dutch_date = _dutch_date_label(target, day_name, month_name)

        morning = []
        afternoon = []
        for hour in DEFAULT_MORNING_SLOTS:
            start = datetime.combine(target, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
            if self._is_slot_available(start, start + timedelta(minutes=DEFAULT_INTERVIEW_DURATION_MINUTES), busy_times):
                morning.append(f"{hour} uur")
        for hour in DEFAULT_AFTERNOON_SLOTS:
            start = datetime.combine(target, datetime.min.time(), tzinfo=TIMEZONE).replace(hour=hour)
            if self._is_slot_available(start, start + timedelta(minutes=DEFAULT_INTERVIEW_DURATION_MINUTES), busy_times):
                afternoon.append(f"{hour} uur")

        if not morning and not afternoon:
            logger.info(f"No available slots on {target_date} for {calendar_email}")
            return None

        return {
            "date": target_date,
            "dutch_date": dutch_date,
            "morning": morning,
            "afternoon": afternoon,
        }

    # -- Create event --------------------------------------------------------

    def _create_event_sync(
        self,
        calendar_email: str,
        summary: str,
        start_time: datetime,
        duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
        description: Optional[str] = None,
    ) -> dict:
        from googleapiclient.errors import HttpError

        service = self._get_service(calendar_email)

        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=TIMEZONE)
        end_time = start_time + timedelta(minutes=duration_minutes)

        event = {
            "summary": summary,
            "start": {"dateTime": start_time.isoformat(), "timeZone": TIMEZONE_STR},
            "end": {"dateTime": end_time.isoformat(), "timeZone": TIMEZONE_STR},
        }
        if description:
            event["description"] = description

        try:
            created = service.events().insert(calendarId=calendar_email, body=event, sendUpdates="none").execute()
            logger.info(f"Created calendar event {created.get('id')} for {calendar_email}")
            return {
                "id": created.get("id"),
                "htmlLink": created.get("htmlLink"),
                "summary": created.get("summary"),
            }
        except HttpError as e:
            logger.error(f"Failed to create event for {calendar_email}: {e}")
            raise

    async def create_event(
        self,
        calendar_email: str,
        summary: str,
        start_time: datetime,
        duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
        description: Optional[str] = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._create_event_sync, calendar_email, summary, start_time, duration_minutes, description
        )


_calendar = _CalendarService()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_initial_slots(
    start_offset_days: int = 1,
    num_days: int = 3,
    max_times_per_day: int = 1,
) -> dict:
    """Get the initial time-slot offer (3 days, 1 slot per day = 3 slots total).

    Returns:
        {slots: [...], formatted: str, has_availability: bool}
    """
    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    if not recruiter_email:
        return {"slots": [], "formatted": "", "has_availability": False}

    try:
        slots = await _calendar.get_quick_slots(
            calendar_email=recruiter_email,
            num_days=num_days,
            start_offset_days=start_offset_days,
            max_times_per_day=max_times_per_day,
        )
        if not slots:
            return {"slots": [], "formatted": "", "has_availability": False}

        formatted = ", ".join(s["dutch_text"] for s in slots)
        return {"slots": slots, "formatted": formatted, "has_availability": True}

    except Exception as e:
        logger.error(f"Failed to get calendar slots: {e}")
        return {"slots": [], "formatted": "", "has_availability": False, "error": str(e)}


async def get_slots_for_specific_date(date_str: str) -> dict:
    """Get available slots for a specific date (YYYY-MM-DD).

    Returns:
        {slots: [...], formatted: str, has_availability: bool}
    """
    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    if not recruiter_email:
        return {"slots": [], "formatted": "", "has_availability": False}

    try:
        slot = await _calendar.get_slots_for_date(
            calendar_email=recruiter_email,
            target_date=date_str,
        )
        if not slot:
            return {
                "slots": [],
                "formatted": "Er zijn helaas geen beschikbare momenten op die dag.",
                "has_availability": False,
            }

        all_times = slot["morning"] + slot["afternoon"]
        text = _format_day_slots(slot["dutch_date"], all_times)
        return {
            "slots": [{
                "date": slot["date"],
                "dutch_date": slot["dutch_date"],
                "times": all_times,
                "dutch_text": text,
            }],
            "formatted": text,
            "has_availability": True,
        }

    except Exception as e:
        logger.error(f"Failed to get slots for {date_str}: {e}")
        return {"slots": [], "formatted": "", "has_availability": False, "error": str(e)}


async def create_interview_event(
    candidate_name: str,
    date_str: str,
    time_str: str,
    duration_minutes: int = DEFAULT_INTERVIEW_DURATION_MINUTES,
    vacancy_title: str = "",
) -> dict:
    """Create a Google Calendar event for the confirmed interview.

    Args:
        candidate_name: Candidate's name for the event title.
        date_str: Date in YYYY-MM-DD format.
        time_str: Time in "10 uur" / "14 uur" / "10:00" format.
        duration_minutes: Interview duration.
        vacancy_title: Vacancy title to include in event title.

    Returns:
        {success: True, event_id: str} on success,
        {success: False, error: str} on failure.
    """
    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    if not recruiter_email:
        return {"success": False, "error": "No recruiter email configured"}

    try:
        interview_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"success": False, "error": f"Invalid date: {date_str}"}

    # Parse hour from various formats: "10 uur", "14 uur", "10u", "10:00"
    cleaned = time_str.lower().replace(" uur", "").replace("uur", "").replace("u", "").replace(":", "")
    try:
        hour = int(cleaned[:2]) if len(cleaned) >= 2 else int(cleaned)
    except ValueError:
        return {"success": False, "error": f"Invalid time: {time_str}"}

    start_time = interview_date.replace(hour=hour, minute=0, second=0, tzinfo=TIMEZONE)

    title = f"Interview - {candidate_name} x {vacancy_title}" if vacancy_title else f"Interview - {candidate_name}"

    try:
        event = await _calendar.create_event(
            calendar_email=recruiter_email,
            summary=title,
            start_time=start_time,
            duration_minutes=duration_minutes,
            description=f"Screeningsgesprek met {candidate_name}",
        )
        return {"success": True, "event_id": event.get("id"), "event_link": event.get("htmlLink")}
    except Exception as e:
        logger.error(f"Failed to create interview event: {e}")
        return {"success": False, "error": str(e)}
