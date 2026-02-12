"""
Meta WhatsApp Cloud API service for sending messages directly.

This bypasses Twilio for potentially lower latency to EU users.
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

# Meta WhatsApp Cloud API credentials
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "1039159159271110")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")

# API endpoint
META_API_URL = f"https://graph.facebook.com/v21.0/{META_PHONE_NUMBER_ID}/messages"


async def send_meta_whatsapp_message(to_phone: str, message: str) -> bool:
    """
    Send a WhatsApp message via Meta Cloud API.

    Args:
        to_phone: Phone number to send to (without + prefix, e.g., "32487441391")
        message: Text message to send

    Returns:
        True if message was sent successfully, False otherwise
    """
    if not META_ACCESS_TOKEN:
        logger.error("META_ACCESS_TOKEN not configured")
        return False

    # Ensure phone number has country code but no +
    phone = to_phone.lstrip("+")

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(META_API_URL, headers=headers, json=payload)

            if response.status_code == 200:
                result = response.json()
                message_id = result.get("messages", [{}])[0].get("id", "unknown")
                logger.info(f"✅ Meta WhatsApp message sent to {phone}, message_id={message_id}")
                return True
            else:
                logger.error(f"❌ Meta WhatsApp API error: {response.status_code} - {response.text}")
                return False

    except Exception as e:
        logger.error(f"❌ Meta WhatsApp send error: {e}")
        return False
