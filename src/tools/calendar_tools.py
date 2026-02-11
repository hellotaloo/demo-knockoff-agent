"""
Google Calendar ADK tools for interview scheduling.

These tools allow ADK agents (like Knockout Agent) to:
1. Check recruiter availability from Google Calendar
2. Schedule interviews on the recruiter's calendar

Uses the GoogleCalendarService for all calendar operations.
"""

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from google.adk.tools import FunctionTool

from src.services.google_calendar_service import calendar_service, TIMEZONE

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Functions
# =============================================================================

async def check_recruiter_availability(
    recruiter_email: str,
    days_ahead: int = 3,
) -> dict:
    """
    Controleer de beschikbaarheid van een recruiter voor de komende dagen.

    Gebruik deze tool om te zien wanneer de recruiter beschikbaar is voor een interview.
    De tool geeft beschikbare tijdsloten terug in het Nederlands.

    Args:
        recruiter_email: Het e-mailadres van de recruiter (bijv. "jan@bedrijf.be")
        days_ahead: Aantal werkdagen om te controleren (standaard 3)

    Returns:
        dict: Bevat:
            - slots: Lijst van beschikbare dagen met ochtend/middag tijden
            - formatted: Tekst die je direct aan de kandidaat kunt tonen
            - has_availability: True als er minstens 1 slot beschikbaar is
    """
    logger.info(f"Checking availability for {recruiter_email}, {days_ahead} days ahead")

    try:
        slots = await calendar_service.get_available_slots(
            calendar_email=recruiter_email,
            days_ahead=days_ahead,
        )

        if not slots:
            return {
                "slots": [],
                "formatted": "Er zijn momenteel geen beschikbare tijdsloten.",
                "has_availability": False,
            }

        # Format for voice/chat output
        formatted_lines = []
        for slot in slots:
            morning = ", ".join(slot["morning"]) if slot["morning"] else None
            afternoon = ", ".join(slot["afternoon"]) if slot["afternoon"] else None

            if morning and afternoon:
                formatted_lines.append(
                    f"- {slot['dutch_date']}: 's ochtends om {morning}, of 's middags om {afternoon}"
                )
            elif morning:
                formatted_lines.append(f"- {slot['dutch_date']}: 's ochtends om {morning}")
            elif afternoon:
                formatted_lines.append(f"- {slot['dutch_date']}: 's middags om {afternoon}")

        formatted_text = "Beschikbare tijdsloten:\n" + "\n".join(formatted_lines)

        logger.info(f"Found {len(slots)} days with availability for {recruiter_email}")

        return {
            "slots": slots,
            "formatted": formatted_text,
            "has_availability": True,
        }

    except Exception as e:
        logger.error(f"Failed to check availability for {recruiter_email}: {e}")
        return {
            "slots": [],
            "formatted": "Sorry, ik kan de agenda momenteel niet controleren. Probeer het later opnieuw.",
            "has_availability": False,
            "error": str(e),
        }


async def schedule_interview(
    recruiter_email: str,
    candidate_name: str,
    date: str,
    time: str,
    duration_minutes: int = 30,
    notes: Optional[str] = None,
) -> dict:
    """
    Plan een interview in op de agenda van de recruiter.

    Gebruik deze tool nadat de kandidaat een tijdslot heeft gekozen.
    Maakt een kalenderafspraak aan en stuurt een uitnodiging.

    Args:
        recruiter_email: Het e-mailadres van de recruiter
        candidate_name: Naam van de kandidaat voor de afspraaknaam
        date: Datum in YYYY-MM-DD formaat (bijv. "2026-02-12")
        time: Tijd in "10u" of "14u" formaat, of "10:00" formaat
        duration_minutes: Duur van het interview in minuten (standaard 30)
        notes: Optionele notities voor de afspraak

    Returns:
        dict: Bevat:
            - success: True als de afspraak is aangemaakt
            - message: Bevestigingsbericht voor de kandidaat
            - event_id: Google Calendar event ID
            - event_link: Link naar de afspraak
    """
    logger.info(f"Scheduling interview for {candidate_name} with {recruiter_email} on {date} at {time}")

    try:
        # Parse the date
        try:
            interview_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {
                "success": False,
                "message": f"Ongeldige datum: {date}. Gebruik formaat YYYY-MM-DD.",
            }

        # Parse the time (handle both "10u" and "10:00" formats)
        time_str = time.lower().replace("u", "").replace(":", "")
        try:
            hour = int(time_str[:2]) if len(time_str) >= 2 else int(time_str)
        except ValueError:
            return {
                "success": False,
                "message": f"Ongeldige tijd: {time}. Gebruik formaat zoals '10u' of '14:00'.",
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
        confirmation = f"Je interview is ingepland voor {dutch_date} om {hour}u."

        logger.info(f"Successfully scheduled interview: {event.get('id')}")

        return {
            "success": True,
            "message": confirmation,
            "event_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "scheduled_for": f"{date} {hour}:00",
        }

    except Exception as e:
        logger.error(f"Failed to schedule interview: {e}")
        return {
            "success": False,
            "message": "Sorry, het lukte niet om het interview in te plannen. Probeer het later opnieuw.",
            "error": str(e),
        }


# =============================================================================
# ADK FunctionTool Wrappers
# =============================================================================

check_availability_tool = FunctionTool(func=check_recruiter_availability)
schedule_interview_tool = FunctionTool(func=schedule_interview)
