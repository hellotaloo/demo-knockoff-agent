"""
Quick Yousign sandbox test.
Creates a dummy contract, sends a signature request, and prints the mobile signing URL.

Usage:
    python scripts/test_yousign.py
"""
import os
import textwrap
import httpx
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUSIGN_API_KEY")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER")
CONTRACT_TEMPLATE_SID = "HX2d21895b4ec386ade951f1f8231a0a49"
BASE_URL = "https://api-sandbox.yousign.app/v3"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}


def make_dummy_pdf() -> bytes:
    """Generate a minimal valid PDF with dummy contract text — no external libs needed."""
    content = textwrap.dedent("""\
        ARBEIDSOVEREENKOMST (TEST)

        Tussen Taloo NV en de kandidaat hieronder vermeld
        wordt de volgende arbeidsovereenkomst gesloten.

        Functie   : Software Developer
        Startdatum: 01/04/2026
        Loon      : Volgens barema

        De kandidaat verklaart kennis genomen te hebben van het
        arbeidsreglement en gaat akkoord met de bepalingen van
        deze overeenkomst.

        Handtekening kandidaat:
    """)

    # Minimal valid PDF built by hand (no dependencies)
    lines = content.split("\n")
    stream_lines = ["BT", "/F1 12 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "")
        stream_lines.append(f"({safe}) Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines)
    stream_bytes = stream.encode("latin-1", errors="replace")

    objects = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    objects[3] = (
        b"<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 595 842] "
        b"/Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects[4] = b"<< /Length " + str(len(stream_bytes)).encode() + b" >>\nstream\n" + stream_bytes + b"\nendstream"
    objects[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    body = b"%PDF-1.4\n"
    offsets = {}
    for obj_id, obj_data in objects.items():
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n".encode() + obj_data + b"\nendobj\n"

    xref_offset = len(body)
    body += b"xref\n"
    body += f"0 {len(objects) + 1}\n".encode()
    body += b"0000000000 65535 f \n"
    for obj_id in range(1, len(objects) + 1):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()

    body += (
        b"trailer\n"
        b"<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF"
    )
    return body


def run():
    client = httpx.Client(headers=HEADERS, base_url=BASE_URL, timeout=30)

    # 1. Create signature request
    print("1. Creating signature request...")
    r = client.post("/signature_requests", json={
        "name": "Taloo - Test arbeidsovereenkomst",
        "delivery_mode": "none",  # We'll send the link ourselves (via WhatsApp)
    })
    r.raise_for_status()
    request_id = r.json()["id"]
    print(f"   ✓ Request ID: {request_id}")

    # 2. Upload the dummy PDF (multipart form data)
    print("2. Uploading contract PDF...")
    pdf_bytes = make_dummy_pdf()
    r = client.post(
        f"/signature_requests/{request_id}/documents",
        files={"file": ("arbeidsovereenkomst.pdf", pdf_bytes, "application/pdf")},
        data={"nature": "signable_document", "parse_anchors": "false"},
    )
    if not r.is_success:
        print(f"   ✗ Error {r.status_code}: {r.text}")
        r.raise_for_status()
    document_id = r.json()["id"]
    print(f"   ✓ Document ID: {document_id}")

    # 3. Add signer + signature field placement on the document
    print("3. Adding signer...")
    r = client.post(
        f"/signature_requests/{request_id}/signers",
        json={
            "info": {
                "first_name": "Jan",
                "last_name": "Tester",
                "email": "jan.tester@example.com",
                "phone_number": "+32499000000",
                "locale": "nl",
            },
            "signature_level": "electronic_signature",  # SES
            "signature_authentication_mode": "no_otp",
            "fields": [
                {
                    "document_id": document_id,
                    "type": "signature",
                    "page": 1,
                    "x": 50,
                    "y": 100,
                    "width": 200,
                    "height": 50,
                }
            ],
        },
    )
    r.raise_for_status()
    signer_id = r.json()["id"]
    print(f"   ✓ Signer ID: {signer_id}")

    # 4. Activate — makes the request live and generates signing URLs
    print("4. Activating signature request...")
    r = client.post(f"/signature_requests/{request_id}/activate")
    r.raise_for_status()
    print("   ✓ Activated")

    # 5. Fetch the signing URL for our signer
    print("5. Fetching signing URL...")
    r = client.get(f"/signature_requests/{request_id}/signers/{signer_id}")
    r.raise_for_status()
    signing_url = r.json().get("signature_link")
    print()
    print("=" * 60)
    print("SIGNING URL (open this on your phone):")
    print()
    print(signing_url)
    print("=" * 60)
    print()
    print("Tip: Scan a QR code of this URL with your phone to test the mobile UI.")

    # 6. Send the signing link via WhatsApp template
    to_number = input("\nEnter your WhatsApp number to receive the link (e.g. +32499123456), or press Enter to skip: ").strip()
    if to_number:
        send_whatsapp_contract(
            to=f"whatsapp:{to_number}",
            contract_name="contract medewerker bakkerij",
            signing_url=signing_url,
        )


def send_whatsapp_contract(to: str, contract_name: str, signing_url: str):
    twilio = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    msg = twilio.messages.create(
        from_=TWILIO_FROM,
        to=to,
        content_sid=CONTRACT_TEMPLATE_SID,
        content_variables=f'{{"1": "{contract_name}", "2": "{signing_url}"}}',
    )
    print(f"\n✓ WhatsApp message sent! SID: {msg.sid}")
    print(f"  Status: {msg.status}")


if __name__ == "__main__":
    run()
