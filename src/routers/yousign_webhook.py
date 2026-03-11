"""
Yousign webhook endpoint.

Yousign sends a POST to /webhook/yousign for signature events.
Signature verification: X-Yousign-Signature-256: sha256=<hmac-sha256(secret, body)>
"""
import hmac
import logging
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.config import YOUSIGN_WEBHOOK_SECRET

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Webhooks"])


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    if not YOUSIGN_WEBHOOK_SECRET:
        logger.warning("YOUSIGN_WEBHOOK_SECRET not set, skipping signature validation")
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("Missing or malformed Yousign signature header")
        return False

    expected = "sha256=" + hmac.new(
        key=YOUSIGN_WEBHOOK_SECRET.encode(),
        msg=body,
        digestmod=sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature_header, expected):
        logger.warning("Yousign HMAC signature mismatch")
        return False

    return True


@router.post("/webhook/yousign")
async def yousign_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Yousign-Signature-256")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event_name", "unknown")
    data = payload.get("data", {})
    request_id = data.get("id", "unknown")
    request_name = data.get("name", "")

    logger.info("Yousign event: %s | request_id=%s | name=%s", event, request_id, request_name)

    if event == "signature_request.done":
        logger.info("✅ Contract signed: %s (%s)", request_name, request_id)
        # TODO: update application status, notify recruiter

    elif event == "signature_request.declined":
        logger.info("❌ Contract declined: %s (%s)", request_name, request_id)
        # TODO: notify recruiter, update status

    elif event == "signature_request.expired":
        logger.info("⏰ Contract expired: %s (%s)", request_name, request_id)
        # TODO: notify candidate/recruiter, optionally resend

    elif event == "signature_request.canceled":
        logger.info("🚫 Contract canceled: %s (%s)", request_name, request_id)

    else:
        logger.info("Unhandled Yousign event: %s", event)

    return JSONResponse({"status": "ok"})
