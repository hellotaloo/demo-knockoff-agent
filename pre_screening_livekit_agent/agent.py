from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import openai, noise_cancellation

load_dotenv()


class PreScreeningAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="Je bent een vriendelijke AI-assistent voor pre-screening. Je spreekt altijd in het Nederlands (Vlaams nl-BE)."
        )


server = AgentServer()


@server.rtc_session(agent_name="pre-screening")
async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice="coral")
    )

    await session.start(
        room=ctx.room,
        agent=PreScreeningAssistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    await session.generate_reply(
        instructions="Begroet de gebruiker vriendelijk in het Nederlands."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
