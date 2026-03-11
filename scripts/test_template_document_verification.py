"""
Test script for the 'document_verification' WhatsApp template.

This template uses a CTA button with a dynamic URL, which requires a real
WhatsApp Business sender — the Twilio sandbox does NOT support templates.

Usage (with staging credentials):
    TWILIO_ACCOUNT_SID=ACxxxx \
    TWILIO_AUTH_TOKEN=xxxx \
    TWILIO_MESSAGING_SERVICE_SID=MGxxxx \
    TEMPLATE_SID=HXxxxx \
    python scripts/test_template_document_verification.py +32XXXXXXXXX

Or set STAGING_ENV=1 to load from a staging .env file.

Template variables:
    {{1}} = document type, e.g. "identiteitskaart"
    {{2}} = URL path, e.g. "w/TOKEN/signature"  →  CTA becomes https://demo.taloo.be/w/TOKEN/signature

Usage:
    python scripts/test_template_document_verification.py <phone> <url_path>
    python scripts/test_template_document_verification.py +32487441391 w/abc123/signature
"""
import asyncio
import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env for local credentials (override below if needed)
from dotenv import load_dotenv
load_dotenv()

from src.services.whatsapp_service import send_whatsapp_template


TEMPLATE_SID = os.environ.get("TEMPLATE_SID") or os.environ.get("TWILIO_TEMPLATE_DOCUMENT_VERIFICATION")
DOCUMENT_TYPE = "identiteitskaart"


async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_template_document_verification.py <phone_number> <url_path>")
        print("Example: python scripts/test_template_document_verification.py +32487441391 w/abc123/signature")
        sys.exit(1)

    to_phone = sys.argv[1]
    url_path = sys.argv[2]

    if not TEMPLATE_SID:
        print("❌  TEMPLATE_SID (or TWILIO_TEMPLATE_DOCUMENT_VERIFICATION) env var is required.")
        print("    Get the HX... SID from the Twilio Console → Content Template Builder.")
        sys.exit(1)

    from src.config import TWILIO_ACCOUNT_SID, TWILIO_MESSAGING_SERVICE_SID, TWILIO_WHATSAPP_NUMBER
    sender = TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_NUMBER
    print(f"📋  Template SID : {TEMPLATE_SID}")
    print(f"📱  Sender       : {sender}")
    print(f"➡️   To           : {to_phone}")
    print(f"   {{1}}          : {DOCUMENT_TYPE}")
    print(f"   {{2}}          : {url_path}")
    print(f"   CTA URL      : https://demo.taloo.be/{url_path}")
    print()

    sid = await send_whatsapp_template(
        to_phone=to_phone,
        content_sid=TEMPLATE_SID,
        content_variables={"1": DOCUMENT_TYPE, "2": url_path},
    )

    if sid:
        print(f"✅  Message sent! SID: {sid}")
    else:
        print("❌  Send failed — check logs above for the Twilio error.")


if __name__ == "__main__":
    asyncio.run(main())
