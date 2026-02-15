"""
Calendar helpers for the voice agent.

These functions format calendar data specifically for voice TTS output,
converting times to Dutch words (e.g., "tien uur" instead of "10 uur").
"""

import logging
import os
from datetime import datetime
from typing import Optional

from src.services.google_calendar_service import calendar_service, TIMEZONE

logger = logging.getLogger(__name__)


# =============================================================================
# Voice-specific formatting
# =============================================================================

DUTCH_NUMBERS = {
    8: "acht", 9: "negen", 10: "tien", 11: "elf", 12: "twaalf",
    13: "dertien", 14: "veertien", 15: "vijftien", 16: "zestien",
    17: "zeventien", 18: "achttien", 19: "negentien", 20: "twintig",
}


def _time_to_words(time_str: str) -> str:
    """Convert '10 uur' to 'tien uur' for voice TTS."""
    try:
        num = int(time_str.replace(" uur", ""))
        return f"{DUTCH_NUMBERS.get(num, str(num))} uur"
    except (ValueError, AttributeError):
        return time_str


def _convert_times_to_words(times: list[str]) -> list[str]:
    """Convert all times in a list to Dutch words."""
    return [_time_to_words(t) for t in times]


# =============================================================================
# Voice agent calendar functions
# =============================================================================

async def get_time_slots_for_voice(
    specific_date: Optional[str] = None,
    start_from_days: int = 3,
    max_times_per_day: int = 2,
) -> dict:
    """
    Get available time slots formatted for voice TTS.

    Times are converted to Dutch words (e.g., "tien uur" instead of "10 uur")
    for natural text-to-speech output.

    Args:
        specific_date: Optional date in YYYY-MM-DD format for a specific day
        start_from_days: Start from N days in the future (default 3)
        max_times_per_day: Maximum times per day (default 2 for voice)

    Returns:
        dict with:
            - slots: List of available time slots
            - formatted: Text that can be read aloud directly
            - has_availability: True if there are available slots
    """
    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    if not recruiter_email:
        return {
            "slots": [],
            "formatted": "Geen recruiter agenda geconfigureerd.",
            "has_availability": False,
        }

    logger.info(f"[voice] Getting time slots for {recruiter_email}, specific_date={specific_date}")

    try:
        # Specific date requested
        if specific_date:
            slot = await calendar_service.get_slots_for_date(
                calendar_email=recruiter_email,
                target_date=specific_date,
            )

            if not slot:
                return {
                    "slots": [],
                    "formatted": "Er zijn helaas geen beschikbare momenten op die dag.",
                    "has_availability": False,
                    "requested_date": specific_date,
                }

            # Combine times, limit, and convert to words for voice
            all_times = _convert_times_to_words(
                (slot["morning"] + slot["afternoon"])[:max_times_per_day]
            )
            day_name = slot["dutch_date"].split()[0]

            if len(all_times) == 1:
                formatted = f"{day_name} kan om {all_times[0]}."
            elif len(all_times) == 2:
                formatted = f"{day_name} kan om {all_times[0]} of {all_times[1]}."
            else:
                formatted = f"{day_name} kan om {', '.join(all_times[:-1])} of {all_times[-1]}."

            return {
                "slots": [{
                    "date": slot["date"],
                    "dutch_date": slot["dutch_date"],
                    "times": all_times,
                    "dutch_text": formatted.rstrip("."),
                }],
                "formatted": formatted,
                "has_availability": True,
                "requested_date": specific_date,
            }

        # Default: get 3 days with limited times per day
        slots = await calendar_service.get_quick_slots(
            calendar_email=recruiter_email,
            num_days=3,
            start_offset_days=start_from_days,
            max_times_per_day=max_times_per_day,
        )

        if not slots:
            return {
                "slots": [],
                "formatted": "Er zijn momenteel geen beschikbare tijdsloten.",
                "has_availability": False,
            }

        # Convert times to words for voice TTS
        for slot in slots:
            slot["times"] = _convert_times_to_words(slot["times"])
            day_name = slot["dutch_date"].split()[0]
            times = slot["times"]
            if len(times) == 1:
                slot["dutch_text"] = f"{day_name} om {times[0]}"
            elif len(times) == 2:
                slot["dutch_text"] = f"{day_name} om {times[0]} en {times[1]}"
            else:
                slot["dutch_text"] = f"{day_name} om {', '.join(times[:-1])} en {times[-1]}"

        formatted_lines = [slot["dutch_text"] for slot in slots]

        return {
            "slots": slots,
            "formatted": ", ".join(formatted_lines),
            "has_availability": True,
        }

    except Exception as e:
        logger.error(f"[voice] Failed to get time slots: {e}")
        return {
            "slots": [],
            "formatted": "Sorry, ik kan de agenda momenteel niet controleren.",
            "has_availability": False,
            "error": str(e),
        }


async def schedule_interview(
    candidate_name: str,
    date: str,
    time: str,
    recruiter_email: Optional[str] = None,
    duration_minutes: int = 30,
    notes: Optional[str] = None,
) -> dict:
    """
    Schedule an interview on the recruiter's calendar.

    Args:
        candidate_name: Candidate's name for the appointment
        date: Date in YYYY-MM-DD format
        time: Time in "10 uur", "10u", or "10:00" format
        recruiter_email: Recruiter's email (defaults to GOOGLE_CALENDAR_IMPERSONATE_EMAIL)
        duration_minutes: Interview duration in minutes (default 30)
        notes: Optional notes for the appointment

    Returns:
        dict with:
            - success: True if appointment was created
            - message: Confirmation message for the candidate
            - event_id: Google Calendar event ID
            - event_link: Link to the appointment
    """
    recruiter_email = recruiter_email or os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    if not recruiter_email:
        return {
            "success": False,
            "message": "Geen recruiter e-mail geconfigureerd.",
        }

    logger.info(f"[voice] Scheduling interview for {candidate_name} on {date} at {time}")

    try:
        # Parse the date
        try:
            interview_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {
                "success": False,
                "message": f"Ongeldige datum: {date}. Gebruik formaat YYYY-MM-DD.",
            }

        # Parse the time (handle "10 uur", "10u", "10:00" formats)
        time_str = time.lower().replace(" uur", "").replace("uur", "").replace("u", "").replace(":", "")
        try:
            hour = int(time_str[:2]) if len(time_str) >= 2 else int(time_str)
        except ValueError:
            return {
                "success": False,
                "message": f"Ongeldige tijd: {time}.",
            }

        # Create the start time
        start_time = interview_date.replace(
            hour=hour,
            minute=0,
            second=0,
            tzinfo=TIMEZONE,
        )

        # Create the calendar event
        event = await calendar_service.create_event(
            calendar_email=recruiter_email,
            summary=f"Interview - {candidate_name}",
            start_time=start_time,
            duration_minutes=duration_minutes,
            description=notes or f"Screeningsgesprek met {candidate_name}",
        )

        # Format Dutch confirmation
        from src.utils.dutch_dates import get_dutch_date
        dutch_date = get_dutch_date(start_time)
        confirmation = f"Je interview is ingepland voor {dutch_date} om {hour} uur."

        logger.info(f"[voice] Successfully scheduled interview: {event.get('id')}")

        return {
            "success": True,
            "message": confirmation,
            "event_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "scheduled_for": f"{date} {hour}:00",
        }

    except Exception as e:
        logger.error(f"[voice] Failed to schedule interview: {e}")
        return {
            "success": False,
            "message": "Sorry, het lukte niet om het interview in te plannen.",
            "error": str(e),
        }
