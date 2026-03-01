"""
WhatsApp messaging service using Twilio REST API.

Provides async message sending for faster webhook responses.
Instead of returning TwiML, we return 200 OK immediately and
send the response message via Twilio's REST API in the background.
"""
import asyncio
import logging
from functools import lru_cache

from twilio.rest import Client

from src.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER, TWILIO_MESSAGING_SERVICE_SID, TWILIO_TEMPLATE_INTERVIEW_CONFIRMATION

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_twilio_client() -> Client:
    """Get cached Twilio client instance."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise RuntimeError("Twilio credentials not configured")
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


from typing import Optional


async def send_whatsapp_message(to_phone: str, message: str) -> Optional[str]:
    """
    Send a WhatsApp message via Twilio REST API.

    Args:
        to_phone: Recipient phone number (with or without + prefix, no 'whatsapp:' prefix)
        message: The message text to send

    Returns:
        Message SID if sent successfully, None otherwise
    """
    try:
        client = get_twilio_client()

        # Normalize phone number format
        if not to_phone.startswith("+"):
            to_phone = f"+{to_phone}"

        # Convert Markdown bold (**text**) to WhatsApp bold (*text*)
        message = message.replace("**", "*")

        # Run the blocking Twilio call in a thread pool
        # Use Messaging Service SID if available (required for WhatsApp Business)
        loop = asyncio.get_event_loop()
        if TWILIO_MESSAGING_SERVICE_SID:
            result = await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    body=message,
                    messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                    to=f"whatsapp:{to_phone}"
                )
            )
        else:
            result = await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    body=message,
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=f"whatsapp:{to_phone}"
                )
            )

        logger.info(f"📤 WhatsApp message sent to {to_phone}: SID={result.sid}")
        return result.sid

    except Exception as e:
        logger.error(f"❌ Failed to send WhatsApp message to {to_phone}: {e}")
        return None


async def send_whatsapp_template(
    to_phone: str,
    content_sid: str,
    content_variables: dict[str, str],
) -> Optional[str]:
    """
    Send a WhatsApp content template via Twilio REST API.

    Args:
        to_phone: Recipient phone number (with or without + prefix)
        content_sid: Twilio Content Template SID (e.g., "HXxxxxxxxx")
        content_variables: Template variable mapping (e.g., {"1": "Jan", "2": "dinsdag 4 maart"})

    Returns:
        Message SID if sent successfully, None otherwise
    """
    import json

    try:
        client = get_twilio_client()

        if not to_phone.startswith("+"):
            to_phone = f"+{to_phone}"

        loop = asyncio.get_event_loop()
        kwargs = {
            "content_sid": content_sid,
            "content_variables": json.dumps(content_variables),
            "to": f"whatsapp:{to_phone}",
        }
        if TWILIO_MESSAGING_SERVICE_SID:
            kwargs["messaging_service_sid"] = TWILIO_MESSAGING_SERVICE_SID
        else:
            kwargs["from_"] = TWILIO_WHATSAPP_NUMBER

        result = await loop.run_in_executor(
            None,
            lambda: client.messages.create(**kwargs)
        )

        logger.info(f"📤 WhatsApp template sent to {to_phone}: SID={result.sid}, template={content_sid}")
        return result.sid

    except Exception as e:
        logger.error(f"❌ Failed to send WhatsApp template to {to_phone}: {e}")
        return None


async def send_whatsapp_message_background(to_phone: str, message: str):
    """
    Send a WhatsApp message in the background (fire and forget).

    Use this when you don't need to wait for the result.
    """
    asyncio.create_task(send_whatsapp_message(to_phone, message))
