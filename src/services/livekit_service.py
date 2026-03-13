"""
LiveKit Service - Voice agent call dispatch via LiveKit.

Handles outbound call creation by dispatching the pre-screening v2 agent
and dialing candidates via SIP.
"""
import json
import logging
import uuid
from typing import Optional

from livekit import api

from src.config import (
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    SIP_OUTBOUND_TRUNK_ID,
    LIVEKIT_AGENT_NAME,
)
from src.database import get_db_pool

logger = logging.getLogger(__name__)


async def fetch_agent_config(config_type: str = "pre_screening") -> dict:
    """Fetch active agent config settings from agents.agent_config."""
    try:
        pool = await get_db_pool()
        row = await pool.fetchrow(
            "SELECT settings FROM agents.agent_config WHERE config_type = $1 AND is_active = true LIMIT 1",
            config_type,
        )
        if row:
            import json
            settings = row["settings"] if isinstance(row["settings"], dict) else json.loads(row["settings"])
            logger.info(f"Agent config loaded ({config_type}): {list(settings.keys())}")
            return settings
        logger.info(f"No agent config found for {config_type}, using defaults")
        return {}
    except Exception as e:
        logger.warning(f"Failed to fetch agent config ({config_type}): {e}")
        return {}


async def fetch_voice_config() -> Optional[dict]:
    """Fetch voice config from agents.agent_config settings.voice group."""
    settings = await fetch_agent_config("pre_screening")
    voice = settings.get("voice", {})
    if voice and voice.get("voice_id"):
        logger.info(f"Voice config loaded: voice_id={voice['voice_id']}, model={voice.get('model_id')}")
        return {
            "voice_id": voice["voice_id"],
            "model_id": voice.get("model_id", "eleven_flash_v2_5"),
            "stability": float(voice.get("stability", 1.0)),
            "similarity_boost": float(voice.get("similarity_boost", 1.0)),
        }
    logger.info("No voice config found in agent_config, using defaults")
    return None


async def fetch_pre_screening_config() -> dict:
    """Fetch pre-screening config from agents.agent_config grouped settings."""
    settings = await fetch_agent_config("pre_screening")
    escalation = settings.get("escalation", {})
    interview = settings.get("interview", {})
    return {
        "require_consent": interview.get("require_consent", False),
        "allow_escalation": escalation.get("allow_escalation", True),
    }


async def fetch_scheduling_config() -> dict:
    """Fetch scheduling config (planning group) from agents.agent_config."""
    settings = await fetch_agent_config("pre_screening")
    planning = settings.get("planning", {})
    return {
        "schedule_days_ahead": planning.get("schedule_days_ahead", 3),
        "schedule_start_offset": planning.get("schedule_start_offset", 1),
    }


class LiveKitService:
    """
    Service for dispatching voice screening calls via LiveKit.

    Creates a LiveKit room, dispatches the pre-screening agent with
    SessionInput as metadata, and dials the candidate via SIP.
    """

    def __init__(self):
        if not LIVEKIT_URL:
            raise RuntimeError("LIVEKIT_URL environment variable is required")
        if not LIVEKIT_API_KEY:
            raise RuntimeError("LIVEKIT_API_KEY environment variable is required")
        if not LIVEKIT_API_SECRET:
            raise RuntimeError("LIVEKIT_API_SECRET environment variable is required")
        if not SIP_OUTBOUND_TRUNK_ID:
            logger.warning("SIP_OUTBOUND_TRUNK_ID not set — outbound SIP calls will be disabled")

        self.agent_name = LIVEKIT_AGENT_NAME
        self.sip_trunk_id = SIP_OUTBOUND_TRUNK_ID
        self.lkapi = api.LiveKitAPI()

        logger.info(f"LiveKit service initialized (agent_name={self.agent_name})")

    def _build_session_input(
        self,
        call_id: str,
        candidate_name: str,
        job_title: str,
        knockout_questions: list[dict],
        qualification_questions: list[dict],
        office_location: str = "",
        office_address: str = "",
        voice_config: Optional[dict] = None,
        known_answers: Optional[dict[str, str]] = None,
        existing_booking_date: Optional[str] = None,
        require_consent: bool = False,
        allow_escalation: bool = True,
        persona_name: str = "Anna",
    ) -> dict:
        """
        Map backend DB questions to pre_screening_voice_agent SessionInput format.

        Uses internal_id to store DB question UUIDs for round-tripping results.
        """
        result = {
            "call_id": call_id,
            "candidate_name": candidate_name,
            "candidate_known": False,
            "candidate_record": {
                "known_answers": known_answers or {},
                "existing_booking_date": existing_booking_date,
            } if (known_answers or existing_booking_date) else None,
            "job_title": job_title,
            "office_location": office_location,
            "office_address": office_address,
            "knockout_questions": [
                {
                    "id": f"ko_{i + 1}",
                    "text": q["question_text"],
                    "internal_id": str(q["id"]),
                    "context": q.get("ideal_answer") or "",
                }
                for i, q in enumerate(knockout_questions)
            ],
            "open_questions": [
                {
                    "id": f"oq_{i + 1}",
                    "text": q["question_text"],
                    "internal_id": str(q["id"]),
                    "description": q.get("ideal_answer") or "",
                }
                for i, q in enumerate(qualification_questions)
            ],
            "allow_escalation": allow_escalation,
            "require_consent": require_consent,
            "persona_name": persona_name,
        }
        if voice_config:
            result["voice_config"] = voice_config
        return result

    async def create_outbound_call(
        self,
        to_number: str,
        candidate_name: str,
        candidate_id: str,
        vacancy_id: str,
        vacancy_title: str,
        knockout_questions: Optional[list[dict]] = None,
        qualification_questions: Optional[list[dict]] = None,
        pre_screening_id: Optional[str] = None,
        office_location: str = "",
        office_address: str = "",
    ) -> dict:
        """
        Create an outbound screening call via LiveKit.

        1. Generates a unique room name
        2. Builds SessionInput from DB questions
        3. Dispatches the agent with metadata
        4. Dials the candidate via SIP

        Returns:
            dict with success, message, call_id (room_name), status
        """
        if not self.sip_trunk_id:
            return {
                "success": False,
                "message": "SIP_OUTBOUND_TRUNK_ID not configured — cannot make outbound calls",
                "call_id": None,
                "status": "failed",
            }

        knockout_questions = knockout_questions or []
        qualification_questions = qualification_questions or []

        room_name = f"screening-{uuid.uuid4().hex[:12]}"

        voice_config = await fetch_voice_config()
        screening_config = await fetch_pre_screening_config()
        scheduling_config = await fetch_scheduling_config()

        session_input = self._build_session_input(
            call_id=room_name,
            candidate_name=candidate_name,
            job_title=vacancy_title,
            knockout_questions=knockout_questions,
            qualification_questions=qualification_questions,
            office_location=office_location,
            office_address=office_address,
            voice_config=voice_config,
            require_consent=screening_config["require_consent"],
            allow_escalation=screening_config["allow_escalation"],
        )
        session_input["schedule_days_ahead"] = scheduling_config["schedule_days_ahead"]
        session_input["schedule_start_offset"] = scheduling_config["schedule_start_offset"]

        logger.info(
            f"Dispatching LiveKit call: room={room_name}, agent={self.agent_name}, "
            f"candidate={candidate_name}, knockout={len(knockout_questions)}, "
            f"open={len(qualification_questions)}"
        )

        try:
            # 1. Dispatch the agent with SessionInput as room metadata
            await self.lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=self.agent_name,
                    room=room_name,
                    metadata=json.dumps(session_input),
                )
            )

            # 2. Dial the candidate into the room via SIP
            await self.lkapi.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=room_name,
                    sip_trunk_id=self.sip_trunk_id,
                    sip_call_to=to_number,
                    participant_identity="phone_user",
                    participant_name="Kandidaat",
                    krisp_enabled=True,
                    wait_until_answered=True,
                )
            )

            result = {
                "success": True,
                "message": "Call initiated successfully",
                "call_id": room_name,
                "status": "dispatched",
            }
            logger.info(f"LiveKit call dispatched: {result}")
            return result

        except Exception as e:
            logger.error(f"LiveKit call dispatch failed: {e}")
            return {
                "success": False,
                "message": str(e),
                "call_id": None,
                "status": "failed",
            }

    def create_playground_token(
        self,
        room_name: str,
        session_input: dict,
        participant_identity: str = "playground-user",
        participant_name: str = "Playground User",
    ) -> dict:
        """
        Generate a LiveKit access token for browser playground sessions.

        The token includes room_config with agent dispatch, so when the browser
        connects, LiveKit auto-creates the room and dispatches the agent.
        """
        token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
            .with_identity(participant_identity) \
            .with_name(participant_name) \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )) \
            .with_room_config(api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(
                    agent_name=self.agent_name,
                    metadata=json.dumps(session_input),
                )],
            ))

        return {
            "livekit_url": LIVEKIT_URL,
            "access_token": token.to_jwt(),
            "room_name": room_name,
        }

    async def close(self):
        """Clean up the LiveKit API client."""
        await self.lkapi.aclose()


# Singleton instance
_livekit_service: Optional[LiveKitService] = None


def get_livekit_service() -> LiveKitService:
    """Get or create the LiveKit service singleton."""
    global _livekit_service
    if _livekit_service is None:
        _livekit_service = LiveKitService()
    return _livekit_service
