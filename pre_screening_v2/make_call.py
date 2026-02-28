import asyncio
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from livekit import api

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger("make-call")
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO)

room_name = "outbound-call-room"
agent_name = "elevenlabs-agent"
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")


async def make_call(phone_number: str):
    lkapi = api.LiveKitAPI()

    logger.info(f"Creating dispatch for agent '{agent_name}' in room '{room_name}'")
    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name, room=room_name, metadata=phone_number
        )
    )

    if not outbound_trunk_id or not outbound_trunk_id.startswith("ST_"):
        logger.error("SIP_OUTBOUND_TRUNK_ID is not set or invalid in .env")
        await lkapi.aclose()
        return

    logger.info(f"Dialing {phone_number} into room '{room_name}'")
    try:
        sip_participant = await lkapi.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=room_name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity="phone_user",
                participant_name="Kandidaat",
                krisp_enabled=True,
                wait_until_answered=True,
            )
        )
        logger.info(f"Call connected: {sip_participant}")
    except Exception as e:
        logger.error(f"Error creating SIP participant: {e}")

    await lkapi.aclose()


async def main():
    phone_number = "+32487441391"  # change to the number you want to call
    await make_call(phone_number)


if __name__ == "__main__":
    asyncio.run(main())
