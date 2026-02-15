"""
Calendar helpers for the WhatsApp agent.

These functions format calendar data specifically for WhatsApp text output,
using compact time format (e.g., "10u", "14u").
"""

import logging
import os
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from src.services.google_calendar_service import calendar_service

logger = logging.getLogger(__name__)


# =============================================================================
# Models
# =============================================================================

class TimeSlot(BaseModel):
    """A single day's available time slots."""
    date: str  # ISO format: YYYY-MM-DD
    dutch_date: str  # e.g., "Di 17/02" or "Maandag 16 februari"
    morning: list[str]  # e.g., ["10u", "11u"]
    afternoon: list[str]  # e.g., ["14u", "16u"]


class SlotData(BaseModel):
    """Response containing available slots and formatted text."""
    slots: list[TimeSlot]
    formatted_text: str


# =============================================================================
# WhatsApp-specific formatting
# =============================================================================

# Short day names for WhatsApp
SHORT_DAYS_NL = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]

DUTCH_DAYS = {
    0: "maandag", 1: "dinsdag", 2: "woensdag", 3: "donderdag",
    4: "vrijdag", 5: "zaterdag", 6: "zondag"
}

DUTCH_MONTHS = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december"
}


def _get_next_business_days(start_date: datetime, num_days: int) -> list[datetime]:
    """Get the next N business days (Mon-Fri) from start_date."""
    from datetime import timedelta
    business_days = []
    current = start_date
    while len(business_days) < num_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            business_days.append(current)
    return business_days


# =============================================================================
# WhatsApp agent calendar functions
# =============================================================================

async def get_time_slots_for_whatsapp(
    days_ahead: int = 3,
    start_offset_days: int = 3,
    skip_calendar: bool = False,
) -> SlotData:
    """
    Get available time slots formatted for WhatsApp.

    Uses compact format: "📅 **Di 17/02:** 10u, 11u, 14u, 16u"

    Args:
        days_ahead: Number of business days to return
        start_offset_days: Start from N days in the future
        skip_calendar: If True, skip real calendar API calls (for test mode)

    Returns:
        SlotData with slots and formatted text
    """
    # Skip real calendar lookups in test mode
    if skip_calendar:
        logger.info("[whatsapp] Using default slots (test mode)")
        return _get_default_slots(days_ahead, start_offset_days)

    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    # Check if Google Calendar is configured
    if recruiter_email and os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
        try:
            logger.info(f"[whatsapp] Fetching calendar for {recruiter_email}")
            calendar_slots = await calendar_service.get_available_slots(
                calendar_email=recruiter_email,
                days_ahead=days_ahead,
                start_offset_days=start_offset_days,
            )

            if calendar_slots:
                slots = []
                formatted_lines = []

                for s in calendar_slots:
                    # Convert "10 uur" format to "10u" for WhatsApp
                    morning = [t.replace(" uur", "u") for t in s["morning"]]
                    afternoon = [t.replace(" uur", "u") for t in s["afternoon"]]

                    # Parse date for short format
                    date_obj = datetime.strptime(s["date"], "%Y-%m-%d")
                    short_day = SHORT_DAYS_NL[date_obj.weekday()]
                    date_short = f"{date_obj.day:02d}/{date_obj.month:02d}"

                    slots.append(TimeSlot(
                        date=s["date"],
                        dutch_date=f"{short_day} {date_short}",
                        morning=morning,
                        afternoon=afternoon,
                    ))

                    all_times = morning + afternoon
                    if all_times:
                        formatted_lines.append(f"📅 **{short_day} {date_short}:** {', '.join(all_times)}")

                return SlotData(
                    slots=slots,
                    formatted_text="\n".join(formatted_lines)
                )
            else:
                logger.warning(f"[whatsapp] No calendar slots found for {recruiter_email}")

        except Exception as e:
            logger.error(f"[whatsapp] Failed to get calendar slots: {e}")
            # Fall through to default slots

    # Fallback to default slots
    logger.info("[whatsapp] Using default slots (no calendar integration)")
    return _get_default_slots(days_ahead, start_offset_days)


def _get_default_slots(days_ahead: int = 3, start_offset_days: int = 3) -> SlotData:
    """
    Generate default time slots when Google Calendar is not configured.
    """
    from datetime import timedelta

    start_date = datetime.now() + timedelta(days=start_offset_days - 1)
    business_days = _get_next_business_days(start_date, days_ahead)

    morning_slots = ["10u", "11u"]
    afternoon_slots = ["14u", "16u"]

    slots = []
    formatted_lines = []

    for day in business_days:
        short_day = SHORT_DAYS_NL[day.weekday()]
        date_short = f"{day.day:02d}/{day.month:02d}"
        day_name = DUTCH_DAYS[day.weekday()].capitalize()
        month_name = DUTCH_MONTHS[day.month]
        dutch_date_full = f"{day_name} {day.day} {month_name}"

        slots.append(TimeSlot(
            date=day.strftime("%Y-%m-%d"),
            dutch_date=f"{short_day} {date_short}",
            morning=morning_slots,
            afternoon=afternoon_slots,
        ))

        all_times = morning_slots + afternoon_slots
        formatted_lines.append(f"📅 **{short_day} {date_short}:** {', '.join(all_times)}")

    return SlotData(
        slots=slots,
        formatted_text="\n".join(formatted_lines)
    )


async def get_slots_for_specific_day(
    day_name: str,
    days_offset: int = 0,
) -> SlotData:
    """
    Get available slots for a specific weekday.

    Args:
        day_name: Dutch day name (e.g., "maandag", "dinsdag")
        days_offset: Additional days to add (e.g., 7 for next week)

    Returns:
        SlotData with slots for that day
    """
    from datetime import timedelta

    # Map Dutch day names to weekday numbers
    day_map = {
        "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3,
        "vrijdag": 4, "zaterdag": 5, "zondag": 6,
    }

    weekday = day_map.get(day_name.lower())
    if weekday is None:
        return SlotData(slots=[], formatted_text="Ongeldige dag opgegeven.")

    # Find the next occurrence of this weekday
    today = datetime.now()
    days_until = (weekday - today.weekday()) % 7
    if days_until == 0:
        days_until = 7  # Next week if today
    days_until += days_offset

    target_date = today + timedelta(days=days_until)
    target_date_str = target_date.strftime("%Y-%m-%d")

    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    if recruiter_email and os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
        try:
            slot = await calendar_service.get_slots_for_date(
                calendar_email=recruiter_email,
                target_date=target_date_str,
            )

            if slot:
                morning = [t.replace(" uur", "u") for t in slot["morning"]]
                afternoon = [t.replace(" uur", "u") for t in slot["afternoon"]]

                short_day = SHORT_DAYS_NL[target_date.weekday()]
                date_short = f"{target_date.day:02d}/{target_date.month:02d}"

                time_slot = TimeSlot(
                    date=target_date_str,
                    dutch_date=f"{short_day} {date_short}",
                    morning=morning,
                    afternoon=afternoon,
                )

                all_times = morning + afternoon
                formatted = f"📅 **{short_day} {date_short}:** {', '.join(all_times)}"

                return SlotData(slots=[time_slot], formatted_text=formatted)

        except Exception as e:
            logger.error(f"[whatsapp] Failed to get slots for {target_date_str}: {e}")

    # No slots available
    short_day = SHORT_DAYS_NL[target_date.weekday()]
    date_short = f"{target_date.day:02d}/{target_date.month:02d}"
    return SlotData(
        slots=[],
        formatted_text=f"Geen beschikbare momenten op {short_day} {date_short}."
    )
