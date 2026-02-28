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

logger = logging.getLogger(__name__)


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
            raise RuntimeError("SIP_OUTBOUND_TRUNK_ID environment variable is required")

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
    ) -> dict:
        """
        Map backend DB questions to pre_screening_v2 SessionInput format.

        Uses internal_id to store DB question UUIDs for round-tripping results.
        """
        return {
            "call_id": call_id,
            "candidate_name": candidate_name,
            "candidate_known": False,
            "candidate_record": None,
            "job_title": job_title,
            "office_location": office_location,
            "office_address": office_address,
            "knockout_questions": [
                {
                    "id": f"ko_{i + 1}",
                    "text": q["question_text"],
                    "internal_id": str(q["id"]),
                    "context": q.get("ideal_answer") or "",
                    "data_key": "",
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
            "allow_escalation": True,
            "require_consent": True,
        }

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
        knockout_questions = knockout_questions or []
        qualification_questions = qualification_questions or []

        room_name = f"screening-{uuid.uuid4().hex[:12]}"

        session_input = self._build_session_input(
            call_id=room_name,
            candidate_name=candidate_name,
            job_title=vacancy_title,
            knockout_questions=knockout_questions,
            qualification_questions=qualification_questions,
            office_location=office_location,
            office_address=office_address,
        )

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
