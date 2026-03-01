import json
import logging
import os
from datetime import datetime
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from livekit import agents, api, rtc
from livekit.agents import AgentServer, AgentSession, BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip, CloseEvent, JobProcess, MetricsCollectedEvent, UserStateChangedEvent, room_io, metrics
from livekit.agents.inference import stt as inference_stt
from livekit.plugins import elevenlabs, openai, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("usage")

from i18n import msg
from models import CandidateData, SessionInput, CandidateRecord, KnockoutQuestion, OpenQuestion
from agents.greeting import GreetingAgent
from agents.screening import ScreeningAgent
from agents.open_questions import OpenQuestionsAgent
from agents.scheduling import SchedulingAgent

def _build_start_agent(name: str, inp: SessionInput):
    """Build a start agent by name, using the session input for configuration."""
    esc = inp.allow_escalation
    if name == "greeting":
        return GreetingAgent(job_title=inp.job_title, candidate_name=inp.candidate_name, candidate_known=inp.candidate_known, allow_escalation=esc, require_consent=inp.require_consent)
    if name == "screening":
        return ScreeningAgent(job_title=inp.job_title, allow_escalation=esc)
    if name == "open_questions":
        return OpenQuestionsAgent(job_title=inp.job_title, allow_escalation=esc)
    if name == "scheduling":
        return SchedulingAgent(office_location=inp.office_location, office_address=inp.office_address, allow_escalation=esc)
    if name == "alternative":
        from agents.alternative import AlternativeAgent
        return AlternativeAgent(job_title=inp.job_title, failed_question="(debug mode)", allow_escalation=esc)
    if name == "recruiter":
        from agents.recruiter import RecruiterAgent
        return RecruiterAgent()
    return None

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def prewarm(proc: JobProcess):
    """Load VAD model once at worker startup to avoid cold start latency on first call."""
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=prewarm)


def _dev_session_input() -> SessionInput:
    """Hardcoded session input for local development/testing."""
    return SessionInput(
        call_id="dev_local",
        candidate_name="Mark Verbeke",
        candidate_known=False,
        require_consent=False,
        candidate_record=CandidateRecord(
            known_answers={"work_permit": "ja"},
            existing_booking_date="dinsdag 4 maart om 10 uur",
        ),
        job_title="Bakkerij Medewerker",
        office_location="Antwerpen Centrum",
        office_address="Mechelsesteenweg nummer 27",
        knockout_questions=[
            KnockoutQuestion(id="q1", text="Mag je wettelijk werken in Belgie?", data_key="work_permit"),
            KnockoutQuestion(id="q2", text="Heb je ervaring met werken in een bakkerij of in de verkoop?", data_key="relevant_experience"),
            KnockoutQuestion(id="q3", text="Ben je beschikbaar om in het weekend te werken?", context="2 a 3 weekends per maand is prima.", data_key="weekend_available"),
        ],
        open_questions=[
            OpenQuestion(id="oq1", text="Waarom wil je in een bakkerij werken?", description="Motivatievraag"),
            OpenQuestion(id="oq2", text="Wat zijn je sterke punten voor deze functie?", description="Sterke punten"),
            OpenQuestion(id="oq3", text="Wanneer zou je kunnen starten?", description="Beschikbaarheid"),
        ],
        # start_agent="greeting",  # skip to a specific agent for testing 
    )


@server.rtc_session(agent_name="pre-screening")
async def entrypoint(ctx: agents.JobContext):
    # Parse session input from job metadata (production) or use dev fallback
    metadata = ctx.job.metadata if ctx.job.metadata else None
    logger.info(f"Job metadata present: {bool(metadata)}, job id: {ctx.job.id}, raw metadata length: {len(ctx.job.metadata) if ctx.job.metadata else 0}")
    if metadata:
        inp = SessionInput.from_dict(json.loads(metadata))
        logger.info(f"Session input loaded from job metadata (call_id={inp.call_id}, knockout={len(inp.knockout_questions)}, open={len(inp.open_questions)})")
    else:
        inp = _dev_session_input()
        logger.info("No job metadata — using dev session input")

    session = AgentSession[CandidateData](
        userdata=CandidateData(input=inp),
        vad=ctx.proc.userdata.get("vad") or silero.VAD.load(),
        turn_detection=MultilingualModel(),  # session default, overridden per-agent where needed
        user_away_timeout=4.0,  # trigger fallback prompt after 4s of silence
        stt=inference_stt.STT(
            "deepgram/nova-3",
            language="nl",
            extra_kwargs={
                "keyterm": [
                    "Hans", "ja", "nee",
                    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
                ],
            },
        ),
        llm="openai/gpt-4.1-mini",
        tts=elevenlabs.TTS(
            voice_id="ANHrhmaFeVN0QJaa0PhL", # petra
            model="eleven_flash_v2_5",
            language="nl",
            voice_settings=elevenlabs.VoiceSettings(
                stability=1,
                similarity_boost=1,
                style=0,
                use_speaker_boost=False,
            ),
        ),
    )

    # Ambient sound: office background (always on)
    ambient_audio = BackgroundAudioPlayer(
        ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=1.0),
    )

    # Thinking sound: keyboard typing (started later by ScreeningAgent)
    thinking_audio = BackgroundAudioPlayer(
        thinking_sound=[
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.6, probability=0.8),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.4, probability=0.2),
        ],
    )
    userdata = session.userdata
    userdata.thinking_audio = thinking_audio
    userdata.room = ctx.room

    # Silence fallback: two-step approach
    # 1st silence → gentle "are you there?" prompt
    # 2nd silence → end the conversation
    # Reset counter whenever user speaks (state changes back to "present")
    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent):
        userdata = session.userdata
        if ev.new_state == "present":
            userdata.silence_count = 0
            return

        if ev.new_state == "away":
            if userdata.suppress_silence:
                return  # agent is in an intro sequence, not real user silence

            userdata.silence_count += 1

            if userdata.silence_count < 2:
                # Use session.say to bypass the agent's LLM — avoids misinterpretation as "nee"
                session.say(msg(userdata, "silence_prompt"))
            else:
                session.say(msg(userdata, "silence_shutdown"), allow_interruptions=False)
                session.shutdown(drain=True)

    # Resolve start agent from setting or default to greeting
    start_agent = _build_start_agent(inp.start_agent, inp) or GreetingAgent(
        job_title=inp.job_title,
        candidate_name=inp.candidate_name,
        candidate_known=inp.candidate_known,
        allow_escalation=inp.allow_escalation,
        require_consent=inp.require_consent,
    )

    # Usage tracking: collect metrics per session and write to file on shutdown
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        usage_collector.collect(ev.metrics)

    async def _save_usage():
        summary = usage_collector.get_summary()
        usage_dir = Path("usage_logs")
        usage_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = usage_dir / f"{ctx.room.name}_{timestamp}.json"
        # Cost rates (USD)
        llm_prompt_cost = summary.llm_prompt_tokens * 0.40 / 1_000_000   # GPT-4.1-mini input
        llm_completion_cost = summary.llm_completion_tokens * 1.60 / 1_000_000  # GPT-4.1-mini output
        tts_cost = summary.tts_characters_count * 0.00001125  # ElevenLabs Flash v2.5: $11.25/1M chars
        stt_cost = summary.stt_audio_duration / 3600 * 0.462  # Deepgram Nova-3: $0.462/hr

        total_cost = llm_prompt_cost + llm_completion_cost + tts_cost + stt_cost

        data = {
            "room": ctx.room.name,
            "timestamp": timestamp,
            "candidate_name": inp.candidate_name,
            "job_title": inp.job_title,
            "llm_prompt_tokens": summary.llm_prompt_tokens,
            "llm_completion_tokens": summary.llm_completion_tokens,
            "tts_characters": summary.tts_characters_count,
            "stt_audio_duration": summary.stt_audio_duration,
            "cost_usd": {
                "llm": round(llm_prompt_cost + llm_completion_cost, 6),
                "tts": round(tts_cost, 6),
                "stt": round(stt_cost, 6),
                "total": round(total_cost, 6),
            },
        }
        filepath.write_text(json.dumps(data, indent=2))
        logger.info(f"Usage saved to {filepath}")

    async def _delete_room():
        """Delete the room to hang up the SIP call."""
        try:
            await ctx.delete_room()
            logger.info(f"Room {ctx.room.name} deleted")
        except Exception as e:
            logger.error(f"Failed to delete room: {e}")

    async def _on_session_complete():
        """Called when the session ends. POST results to backend webhook."""
        results = session.userdata.to_dict()

        # Capture full conversation transcript from session history
        transcript = []
        if session.history and session.history.items:
            for item in session.history.items:
                if item.type == "message" and item.text_content:
                    transcript.append({
                        "role": item.role,
                        "message": item.text_content,
                    })
        results["transcript"] = transcript

        logger.info(f"Session complete (call_id={inp.call_id}, status={results['status']}, transcript_messages={len(transcript)})")

        # Skip webhook POST in playground mode — no processing, no DB writes
        if inp.is_playground:
            logger.info(f"Playground mode: skipping backend webhook POST (call_id={inp.call_id})")
            return

        backend_url = os.environ.get("BACKEND_WEBHOOK_URL")
        webhook_secret = os.environ.get("LIVEKIT_WEBHOOK_SECRET", "")

        if backend_url:
            try:
                async with aiohttp.ClientSession() as http_session:
                    response = await http_session.post(
                        f"{backend_url}/webhook/livekit/call-result",
                        json=results,
                        headers={"X-Webhook-Secret": webhook_secret},
                        timeout=aiohttp.ClientTimeout(total=30),
                    )
                    logger.info(f"Backend webhook response: {response.status}")
            except Exception as e:
                logger.error(f"Failed to POST results to backend: {e}")
        else:
            logger.warning("BACKEND_WEBHOOK_URL not set, results not sent to backend")

    ctx.add_shutdown_callback(_on_session_complete)
    ctx.add_shutdown_callback(_save_usage)
    ctx.add_shutdown_callback(_delete_room)

    # When the agent session closes, shut down the job context too.
    # Without this, session.shutdown() only ends the session — the room
    # stays open and the SIP caller hears silence indefinitely.
    @session.on("close")
    def _on_session_close(ev: CloseEvent):
        ctx.shutdown()

    await session.start(
        room=ctx.room,
        agent=start_agent,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await ambient_audio.start(room=ctx.room, agent_session=session)
    # Thinking audio starts after greeting (triggered in GreetingAgent.candidate_ready)
    # For debug start agents that skip the greeting, start it immediately
    if inp.start_agent and inp.start_agent != "greeting":
        await thinking_audio.start(room=ctx.room, agent_session=session)



if __name__ == "__main__":
    agents.cli.run_app(server)
