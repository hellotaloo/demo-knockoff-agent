"""
Health Monitor - Background service that checks system health and sends
WhatsApp alerts via Twilio when a service goes offline.
"""
import asyncio
import json
import logging
import time
from datetime import datetime

from src.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
    TWILIO_MESSAGING_SERVICE_SID,
    TWILIO_TEMPLATE_HEALTH_ALERT,
    ALERT_WHATSAPP_NUMBER,
    HEALTH_CHECK_INTERVAL,
    ALERT_COOLDOWN,
)
from src.routers.health import (
    _ping_gemini,
    _ping_livekit,
    _ping_twilio,
    _ping_with_timeout,
)
from src.services.whatsapp_service import get_twilio_client

logger = logging.getLogger(__name__)

# Service display names (Dutch)
SERVICE_LABELS = {
    "llm": "Taalmodel (LLM)",
    "voice": "Voice pipeline",
    "whatsapp": "Berichtenservice (WhatsApp)",
}

# Track previous state and last alert time per service
_previous_states: dict[str, str] = {}
_last_alert_at: dict[str, float] = {}


def _can_alert(service_slug: str) -> bool:
    """Check if enough time has passed since the last alert for this service."""
    last = _last_alert_at.get(service_slug, 0)
    return (time.time() - last) >= ALERT_COOLDOWN


async def _send_whatsapp_alert(service_slug: str, description: str):
    """Send a WhatsApp alert via Twilio.

    Uses the Content Template API if TWILIO_TEMPLATE_HEALTH_ALERT is set
    (required for proactive messages outside the 24h window in production).
    Falls back to a plain body message for local testing / sandbox.
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_NUMBER:
        logger.warning("Twilio not configured — cannot send health alert")
        return
    if not ALERT_WHATSAPP_NUMBER:
        logger.warning("ALERT_WHATSAPP_NUMBER not set — skipping alert")
        return

    label = SERVICE_LABELS.get(service_slug, service_slug)
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M")

    try:
        client = get_twilio_client()
        loop = asyncio.get_event_loop()

        if TWILIO_TEMPLATE_HEALTH_ALERT and TWILIO_MESSAGING_SERVICE_SID:
            # Production: use Content Template API (works outside 24h window)
            content_vars = json.dumps({"1": label, "2": description, "3": timestamp})
            await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                    to=ALERT_WHATSAPP_NUMBER,
                    content_sid=TWILIO_TEMPLATE_HEALTH_ALERT,
                    content_variables=content_vars,
                ),
            )
        else:
            # Fallback: plain body message (local testing / sandbox)
            body = f"⚠️ Taloo Alert: {label} is offline.\n{description}\nTijdstip: {timestamp}"
            await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=ALERT_WHATSAPP_NUMBER,
                    body=body,
                ),
            )

        _last_alert_at[service_slug] = time.time()
        logger.info(f"Health alert sent for {service_slug} → {ALERT_WHATSAPP_NUMBER}")
    except Exception as e:
        logger.error(f"Failed to send health alert for {service_slug}: {e}")


async def _check_and_alert():
    """Run all service pings and alert on transitions to offline."""
    results = await asyncio.gather(
        _ping_with_timeout(_ping_gemini()),
        _ping_with_timeout(_ping_livekit()),
        _ping_with_timeout(_ping_twilio()),
    )

    checks = [
        ("llm", results[0]),
        ("voice", results[1]),
        ("whatsapp", results[2]),
    ]

    for slug, (status, description) in checks:
        prev = _previous_states.get(slug)
        _previous_states[slug] = status

        # Skip services that aren't configured
        if status == "not_configured":
            continue

        # Alert on transition to offline (or first check that's offline)
        went_offline = status == "offline" and prev != "offline"
        if went_offline and _can_alert(slug):
            await _send_whatsapp_alert(slug, description)
        elif status == "offline" and not _can_alert(slug):
            logger.debug(f"Health alert for {slug} suppressed (cooldown)")


async def health_monitor_loop():
    """Background loop that checks health every HEALTH_CHECK_INTERVAL seconds."""
    if not ALERT_WHATSAPP_NUMBER:
        logger.info("ALERT_WHATSAPP_NUMBER not set — health monitor disabled")
        return

    logger.info(
        f"Health monitor started (interval={HEALTH_CHECK_INTERVAL}s, "
        f"cooldown={ALERT_COOLDOWN}s, alert_to={ALERT_WHATSAPP_NUMBER})"
    )

    while True:
        try:
            await _check_and_alert()
        except asyncio.CancelledError:
            logger.info("Health monitor stopped")
            break
        except Exception as e:
            logger.error(f"Health monitor error: {e}")

        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
