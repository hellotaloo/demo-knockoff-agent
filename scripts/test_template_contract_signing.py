"""
Test script for the 'contract_signing' WhatsApp template.

This template uses a CTA button with a dynamic URL, which requires a real
WhatsApp Business sender — the Twilio sandbox does NOT support templates.

Template variables:
    {{1}} = contract name, e.g. "contract medewerker bakkerij"
    {{2}} = URL path, e.g. "signatures/abc123?s=..."  →  CTA becomes https://yousign.app/signatures/abc123?s=...

Usage:
    python scripts/test_template_contract_signing.py <phone> <signing_url>
    python scripts/test_template_contract_signing.py +32487441391 "signatures/ff97f2f1?s=abc123&sandbox=true"
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.services.whatsapp_service import send_whatsapp_template


TEMPLATE_SID = os.environ.get("TEMPLATE_SID") or os.environ.get("TWILIO_TEMPLATE_CONTRACT_SIGNING") or "HX2d21895b4ec386ade951f1f8231a0a49"
CONTRACT_NAME = "contract medewerker bakkerij"


async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_template_contract_signing.py <phone_number> <signing_url>")
        print('Example: python scripts/test_template_contract_signing.py +32487441391 "signatures/abc123?s=xyz&sandbox=true"')
        sys.exit(1)

    to_phone = sys.argv[1]
    signing_url = sys.argv[2]

    from src.config import TWILIO_ACCOUNT_SID, TWILIO_MESSAGING_SERVICE_SID, TWILIO_WHATSAPP_NUMBER
    sender = TWILIO_MESSAGING_SERVICE_SID or TWILIO_WHATSAPP_NUMBER
    print(f"📋  Template SID : {TEMPLATE_SID}")
    print(f"📱  Sender       : {sender}")
    print(f"➡️   To           : {to_phone}")
    print(f"   {{1}}          : {CONTRACT_NAME}")
    print(f"   {{2}}          : {signing_url}")
    print()

    sid = await send_whatsapp_template(
        to_phone=to_phone,
        content_sid=TEMPLATE_SID,
        content_variables={"1": CONTRACT_NAME, "2": signing_url},
    )

    if sid:
        print(f"✅  Message sent! SID: {sid}")
    else:
        print("❌  Send failed — check logs above for the Twilio error.")


if __name__ == "__main__":
    asyncio.run(main())
