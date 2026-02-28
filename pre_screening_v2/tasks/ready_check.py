from livekit.agents import AgentTask, function_tool

from models import check_irrelevant


class ReadyCheckTask(AgentTask[bool]):
    """Small task that waits for the user to confirm they're ready.

    Returns True if confirmed, False if irrelevant limit was hit.
    Has a turn counter (MAX_TURNS=3) as safety net.
    """

    MAX_TURNS = 3

    def __init__(self, message: str):
        super().__init__(
            turn_detection=None,  # simple yes/no confirmation
            instructions="""\
Je wacht tot de kandidaat bevestigt dat ze klaar zijn.

# Regels
- Als de kandidaat ja, ok, sure, of iets bevestigends zegt → roep `confirm_ready` aan.
- Als de kandidaat een vraag stelt over het proces → beantwoord heel kort en vraag opnieuw of ze klaar zijn.
- Als de kandidaat nee zegt of weigert → roep `mark_irrelevant` aan. De kandidaat moet meewerken aan de screening.
- Als de kandidaat off-topic of onzinnig antwoordt → roep METEEN `mark_irrelevant` aan.
- Ga NIET in op andere onderwerpen. Stel GEEN vragen. Je enige doel is bevestiging krijgen.
- Roep NOOIT twee tools aan in dezelfde beurt.""",
        )
        self._message = message
        self._turn_count = 0

    async def on_enter(self):
        userdata = self.session.userdata
        userdata.silence_count = 0
        userdata.suppress_silence = True
        await self.session.say(self._message, allow_interruptions=False)
        userdata.suppress_silence = False

    async def on_user_turn_completed(self, turn_ctx, new_message):
        self._turn_count += 1
        if not self.done() and self._turn_count >= self.MAX_TURNS:
            self.complete(False)

    @function_tool()
    async def confirm_ready(self):
        """De kandidaat is klaar om verder te gaan."""
        if self.done():
            return
        self.session.userdata.irrelevant_count = 0
        self.complete(True)

    @function_tool()
    async def mark_irrelevant(self, answer_summary: str):
        """De kandidaat antwoordt irrelevant of onzinnig. Roep dit METEEN aan bij elk irrelevant antwoord."""
        if self.done():
            return
        msg = check_irrelevant(self.session.userdata, suffix="of ze klaar zijn")
        if msg is None:
            self.complete(False)
            return
        return msg
