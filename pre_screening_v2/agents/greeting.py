import asyncio

from livekit.agents import RunContext, function_tool

from agents.base import BaseAgent
from i18n import msg
from prompts import greeting_prompt


class GreetingAgent(BaseAgent):
    def __init__(self, job_title: str, candidate_name: str = "", candidate_known: bool = False, allow_escalation: bool = True, require_consent: bool = False) -> None:
        super().__init__(
            instructions=greeting_prompt(job_title, candidate_name, candidate_known, allow_escalation=allow_escalation, require_consent=require_consent),
            turn_detection=None,  # disable semantic turn detection for simple yes/no
            allow_escalation=allow_escalation,
        )

    @function_tool()
    async def record_consent(self, context: RunContext):
        """De kandidaat geeft toestemming voor opname."""
        self.session.userdata.consent_given = True
        return "Toestemming genoteerd. Ga verder met de introductie."

    @function_tool()
    async def record_no_consent(self, context: RunContext):
        """De kandidaat wil niet dat het gesprek wordt opgenomen."""
        self.session.userdata.consent_given = False
        return "Genoteerd. Ga verder met de introductie."

    @function_tool()
    async def candidate_ready(self, context: RunContext):
        """De kandidaat heeft bevestigd dat ze tijd hebben voor de prescreening."""
        from agents.screening import ScreeningAgent

        userdata = self.session.userdata
        userdata.irrelevant_count = 0
        if userdata.thinking_audio:
            await userdata.thinking_audio.start(room=userdata.room, agent_session=self.session)
        self.session.update_agent(ScreeningAgent(
            job_title=userdata.input.job_title,
            allow_escalation=userdata.input.allow_escalation,
        ))

    @function_tool()
    async def detected_voicemail(self, context: RunContext):
        """Roep aan als je een voicemailsysteem of antwoordapparaat detecteert, NA de voicemailbegroeting."""
        userdata = self.session.userdata
        userdata.voicemail_detected = True
        candidate_name = userdata.input.candidate_name
        if candidate_name:
            message = msg(userdata, "voicemail_with_name", name=candidate_name)
        else:
            message = msg(userdata, "voicemail_without_name")
        await self.session.say(message, allow_interruptions=False)
        await asyncio.sleep(0.5)
        self.session.shutdown(drain=True)

    @function_tool()
    async def candidate_is_proxy(self, context: RunContext):
        """De beller is niet de kandidaat zelf, maar belt namens iemand anders (vriend, familie)."""
        await self.session.say(msg(self.session.userdata, "proxy_detected"), allow_interruptions=False)
        self.session.shutdown(drain=True)

    @function_tool()
    async def candidate_not_available(self, context: RunContext):
        """De kandidaat heeft geen tijd of is niet geinteresseerd."""
        await self.session.say(msg(self.session.userdata, "candidate_not_available"), allow_interruptions=False)
        self.session.shutdown(drain=True)

