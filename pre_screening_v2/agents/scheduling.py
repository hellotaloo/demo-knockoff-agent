import logging
from datetime import date, timedelta

from livekit.agents import RunContext, function_tool

from agents.base import BaseAgent
from calendar_helpers import is_calendar_configured, get_initial_slots, get_slots_for_specific_date, create_interview_event
from i18n import msg
from models import CandidateData
from prompts import scheduling_prompt

logger = logging.getLogger(__name__)

# Minimum number of days from today before the first available slot.
# E.g. 1 = earliest slot is tomorrow, 2 = earliest slot is the day after tomorrow.
SLOT_OFFSET_DAYS = 1

# Dutch day/month names (avoid locale dependency)
_DAY_NAMES = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
_MONTH_NAMES = [
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]

# TTS-friendly time slots per weekday (hour, spoken format)
_TIME_SLOTS = {
    0: [(10, "10 uur"), (15, "15 uur")],          # maandag
    1: [(9, "9 uur"), (14, "14 uur")],             # dinsdag
    2: [(11, "11 uur"), (16, "16 uur")],           # woensdag
    3: [(10, "10 uur"), (14, "half 3")],           # donderdag
    4: [(9, "half 10"), (13, "13 uur")],           # vrijdag
}


def _format_slot(d: date, spoken_time: str, today: date) -> str:
    """Format a date + time into TTS-friendly Dutch, e.g. 'morgen dinsdag 3 maart om 10 uur'."""
    day_name = _DAY_NAMES[d.weekday()]
    month_name = _MONTH_NAMES[d.month]
    prefix = "morgen " if (d - today).days == 1 else ""
    return f"{prefix}{day_name} {d.day} {month_name} om {spoken_time}"


def _build_fallback_slots() -> list[str]:
    """Build 3 hardcoded slots (fallback when Google Calendar is not configured)."""
    today = date.today()
    slots: list[str] = []

    d = today + timedelta(days=SLOT_OFFSET_DAYS)
    while len(slots) < 3:
        if d.weekday() < 5:  # mon-fri
            times = _TIME_SLOTS.get(d.weekday(), [])
            if times:
                slots.append(_format_slot(d, times[0][1], today))
        d += timedelta(days=1)

    return slots


class SchedulingAgent(BaseAgent):
    def __init__(self, office_location: str = "", office_address: str = "", allow_escalation: bool = True) -> None:
        today = date.today()
        today_str = f"{_DAY_NAMES[today.weekday()]} {today.day} {_MONTH_NAMES[today.month]} {today.year}"
        super().__init__(
            instructions=scheduling_prompt(today_str, allow_escalation=allow_escalation),
            turn_detection=None,  # short answers, no semantic turn detection needed
            allow_escalation=allow_escalation,
        )
        self._office_location = office_location
        self._office_address = office_address

    async def on_enter(self) -> None:
        self._use_calendar = is_calendar_configured()
        userdata = self.session.userdata
        userdata.silence_count = 0
        userdata.suppress_silence = True
        await self.session.say(
            msg(userdata, "scheduling_invite", location=self._office_location),
            allow_interruptions=False,
        )
        await self.session.generate_reply(
            instructions="Roep nu `get_available_timeslots` aan om de beschikbare momenten op te halen."
        )
        userdata.suppress_silence = False

    @function_tool()
    async def get_available_timeslots(self, context: RunContext) -> str:
        """Haal de beschikbare tijdsloten op voor een sollicitatiegesprek."""
        if self._use_calendar:
            result = await get_initial_slots(start_offset_days=SLOT_OFFSET_DAYS)
            if result["has_availability"]:
                return f"Beschikbare momenten:\n{result['formatted']}"
            logger.warning("Calendar returned no availability, falling back to hardcoded slots")

        # Fallback: hardcoded slots (dev mode or no calendar availability)
        slots = _build_fallback_slots()
        slots_text = "\n".join(f"- {s}" for s in slots)
        return f"Beschikbare momenten:\n{slots_text}"

    @function_tool()
    async def get_timeslots_for_dates(self, context: RunContext, datums: list[str]) -> str:
        """Haal beschikbare tijdsloten op voor een of meer specifieke datums. Geef elke datum in YYYY-MM-DD formaat."""
        if not self._use_calendar:
            return "Ik kan helaas geen specifieke dagen opzoeken. Kies een van de eerder genoemde momenten, of geef je voorkeur door."

        available = []
        unavailable = []
        for datum in datums:
            result = await get_slots_for_specific_date(datum)
            if result["has_availability"]:
                available.append(result["formatted"])
            else:
                unavailable.append(datum)

        if available:
            text = "Beschikbare momenten:\n" + ", ".join(available)
            if unavailable:
                text += f"\nGeen beschikbaarheid op: {', '.join(unavailable)}"
            return text
        return "Er zijn helaas geen beschikbare momenten op die dagen. Wil je andere dagen proberen, of zal ik je voorkeur doorgeven aan de recruiter?"

    @function_tool()
    async def confirm_timeslot(self, context: RunContext, timeslot: str, slot_date: str = "", slot_time: str = ""):
        """De kandidaat heeft een tijdslot gekozen. Bevestig het en sluit het gesprek af.

        Args:
            timeslot: Het gekozen tijdslot als tekst, bijv. "dinsdag 4 maart om 10 uur".
            slot_date: De datum in YYYY-MM-DD formaat (optioneel, voor agenda-integratie).
            slot_time: Het tijdstip, bijv. "10 uur" (optioneel, voor agenda-integratie).
        """
        userdata: CandidateData = self.session.userdata
        userdata.irrelevant_count = 0
        userdata.chosen_timeslot = timeslot
        userdata.scheduled_date = slot_date or None
        userdata.scheduled_time = slot_time or None

        # Create calendar event if possible (fire-and-forget: failure does not block confirmation)
        if self._use_calendar and slot_date and slot_time:
            candidate_name = userdata.input.candidate_name or "Kandidaat"
            vacancy_title = userdata.input.job_title or ""
            result = await create_interview_event(candidate_name, slot_date, slot_time, vacancy_title=vacancy_title)
            if result["success"]:
                userdata.calendar_event_id = result.get("event_id")
                logger.info(f"Calendar event created: {result.get('event_id')}")
            else:
                logger.warning(f"Calendar event creation failed: {result.get('error')}")

        tomorrow = date.today() + timedelta(days=1)
        tomorrow_str = f"{tomorrow.day} {_MONTH_NAMES[tomorrow.month]}"
        is_tomorrow = tomorrow_str in timeslot
        followup_key = "scheduling_followup_tomorrow" if is_tomorrow else "scheduling_followup_later"
        followup = msg(userdata, followup_key)
        await self.session.say(
            msg(userdata, "scheduling_confirm",
                timeslot=timeslot, location=self._office_location,
                address=self._office_address, followup=followup),
            allow_interruptions=False,
        )
        self.session.shutdown(drain=True)

    @function_tool()
    async def schedule_with_recruiter(self, context: RunContext, preference: str):
        """Geen geschikt moment gevonden. Sla de voorkeur van de kandidaat op zodat de recruiter contact opneemt."""
        userdata: CandidateData = self.session.userdata
        userdata.scheduling_preference = preference
        await self.session.say(msg(userdata, "scheduling_preference"), allow_interruptions=False)
        self.session.shutdown(drain=True)

