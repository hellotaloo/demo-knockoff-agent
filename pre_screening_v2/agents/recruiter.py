from livekit.agents import RunContext, function_tool
from livekit.plugins import elevenlabs

from agents.base import BaseAgent
from i18n import msg
from models import CandidateData
from prompts import recruiter_prompt


class RecruiterAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            instructions=recruiter_prompt(),
            tts=elevenlabs.TTS(
                voice_id="s7Z6uboUuE4Nd8Q2nye6",
                model="eleven_flash_v2_5",
                language="nl",
            ),
            allow_escalation=False,
        )

    async def on_enter(self) -> None:
        userdata: CandidateData = self.session.userdata
        userdata.silence_count = 0
        userdata.suppress_silence = True
        # Sync TTS language with session (recruiter uses a different voice)
        self.session.tts.update_options(language=userdata.language)
        candidate_name = userdata.input.candidate_name
        await self.session.say(
            msg(userdata, "recruiter_greeting", name=candidate_name),
            allow_interruptions=False,
        )
        userdata.suppress_silence = False

    @function_tool()
    async def end_conversation(self, context: RunContext):
        """Het gesprek met de recruiter is afgerond."""
        await self.session.say(msg(self.session.userdata, "recruiter_goodbye"), allow_interruptions=False)
        self.session.shutdown(drain=True)
