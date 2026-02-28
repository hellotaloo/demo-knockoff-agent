from datetime import date, timedelta

from livekit.agents import RunContext, function_tool

from agents.base import BaseAgent
from i18n import msg
from models import CandidateData
from prompts import scheduling_prompt

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


def _build_slots() -> list[str]:
    """Build 3 available slots: first slot of each of the next 3 weekdays."""
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
        self._available_slots = _build_slots()
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
        slots_text = "\n".join(f"- {s}" for s in self._available_slots)
        return f"Beschikbare momenten:\n{slots_text}"

    @function_tool()
    async def confirm_timeslot(self, context: RunContext, timeslot: str):
        """De kandidaat heeft een tijdslot gekozen. Bevestig het en sluit het gesprek af."""
        userdata: CandidateData = self.session.userdata
        userdata.irrelevant_count = 0
        userdata.chosen_timeslot = timeslot
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

