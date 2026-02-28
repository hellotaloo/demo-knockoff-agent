# Plan: Create Pre-Screening LiveKit Agent

## Overview
Create a new LiveKit-based voice agent for pre-screening, replacing the current VAPI-based approach with more control using LiveKit + OpenAI Realtime models.

## Folder Structure
Following the existing agent pattern (root-level folders):

```
pre_screening_livekit_agent/
├── __init__.py              # Export public API
├── agent.py                 # Main LiveKit agent entry point
└── requirements.txt         # LiveKit-specific dependencies
```

## Dependencies

```
livekit-agents[openai]~=1.4
livekit-plugins-noise-cancellation~=0.2
python-dotenv
```

> **Note:** `livekit-agents` v1.4.2 is the latest (Feb 2026). The `[openai]` extra installs the OpenAI Realtime plugin.

## Implementation (Latest Best Practices)

### 1. `pre_screening_livekit_agent/__init__.py`
Simple exports for the agent entry point.

### 2. `pre_screening_livekit_agent/agent.py`

**Key pattern (from latest LiveKit docs, verified Feb 2026):**

```python
from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import openai, noise_cancellation

load_dotenv()

# 1. Define Agent class with instructions
class PreScreeningAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="Je bent een vriendelijke AI-assistent voor pre-screening."
        )

# 2. Create server
server = AgentServer()

# 3. Entry point with @server.rtc_session()
@server.rtc_session(agent_name="pre-screening")
async def entrypoint(ctx: agents.JobContext):
    # 4. Create session with OpenAI Realtime
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(voice="coral")
    )

    # 5. Start session with room, agent, and noise cancellation
    await session.start(
        room=ctx.room,
        agent=PreScreeningAssistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # SIP-aware: use telephony NC for phone calls, regular for browser
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # 6. Generate initial greeting
    await session.generate_reply(
        instructions="Begroet de gebruiker vriendelijk in het Nederlands."
    )

# 7. CLI runner
if __name__ == "__main__":
    agents.cli.run_app(server)
```

### 3. Environment Variables Required
```bash
# LiveKit Server
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LIVEKIT_URL=wss://your-project.livekit.cloud

# OpenAI (for realtime model)
OPENAI_API_KEY=
```

## OpenAI Realtime Configuration

| Parameter | Default | Options |
|-----------|---------|---------|
| `model` | `"gpt-realtime"` | Any OpenAI realtime model ID |
| `voice` | `"alloy"` | alloy, ash, ballad, coral, echo, fable, marin, onyx, nova, sage, shimmer, verse |
| `temperature` | 0.8 | 0.6 - 1.2 |
| `modalities` | `["text", "audio"]` | Can use `["text"]` for separate TTS |
| `turn_detection` | semantic_vad (auto) | `semantic_vad` or `server_vad` (with eagerness: low/medium/high) |

## Running the Agent

```bash
# Console mode (local testing with mic/speaker)
python pre_screening_livekit_agent/agent.py console

# Dev mode (connects to LiveKit, use playground)
python pre_screening_livekit_agent/agent.py dev

# Production
python pre_screening_livekit_agent/agent.py start
```

> **Note:** Before first run, download model files: `python pre_screening_livekit_agent/agent.py download-files`

## Files to Create

| File | Purpose |
|------|---------|
| `pre_screening_livekit_agent/__init__.py` | Module exports |
| `pre_screening_livekit_agent/agent.py` | Main agent implementation |
| `pre_screening_livekit_agent/requirements.txt` | LiveKit dependencies |

## Verification

1. Install dependencies: `pip install -r pre_screening_livekit_agent/requirements.txt`
2. Set environment variables in `.env`
3. Download model files: `python pre_screening_livekit_agent/agent.py download-files`
4. Run in console mode: `python pre_screening_livekit_agent/agent.py console`
5. Test voice interaction locally

## LiveKit Cloud Setup

1. **Sign up** at https://cloud.livekit.io
2. **Create a project** (free tier available)
3. **Get credentials** from the project dashboard:
   - `LIVEKIT_URL` (e.g., `wss://your-project.livekit.cloud`)
   - `LIVEKIT_API_KEY`
   - `LIVEKIT_API_SECRET`
4. **Add to `.env`** file

## Known Issue: OpenTelemetry Version Conflict

The basic agent has been implemented and installed into the main project virtualenv. However, `livekit-agents` requires `opentelemetry ~=1.39` while `google-adk` pins `opentelemetry ==1.37`. Both libraries import and run fine at runtime despite pip's warning, but if you hit unexpected telemetry or tracing errors in the future, the clean solution is to run the LiveKit agent in its own separate virtualenv. This is the natural pattern anyway since the agent runs as a standalone process (`python pre_screening_livekit_agent/agent.py dev`).

## Next Steps (After Basic Setup)

Once this basic agent works, future enhancements could include:
- Integration with existing screening flow (vacancy context, questions)
- Webhook for call completion
- Transcript processing with existing `transcript_processor` agent
- Router endpoint for initiating calls
- SIP telephony integration for phone calls
