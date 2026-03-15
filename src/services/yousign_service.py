"""
Yousign service — creates signature requests and retrieves signing URLs.

Uses Yousign API v3 (sandbox or production based on config).
Flow: create request → upload PDF → add signer → activate → get signing URL.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from src.config import YOUSIGN_API_KEY

logger = logging.getLogger(__name__)

# Sandbox vs production base URL
BASE_URL = "https://api-sandbox.yousign.app/v3" if "sandbox" in (YOUSIGN_API_KEY or "") else "https://api.yousign.app/v3"


@dataclass
class SignatureResult:
    success: bool
    signing_url: Optional[str] = None
    request_id: Optional[str] = None
    signer_id: Optional[str] = None
    error: Optional[str] = None


class YousignService:
    """Creates Yousign signature requests and returns mobile signing URLs."""

    def __init__(self):
        if not YOUSIGN_API_KEY:
            logger.warning("YOUSIGN_API_KEY not configured")
        self.headers = {"Authorization": f"Bearer {YOUSIGN_API_KEY}"}

    async def create_signature_request(
        self,
        pdf_bytes: bytes,
        pdf_filename: str,
        signer_first_name: str,
        signer_last_name: str,
        signer_email: str,
        signer_phone: str,
        request_name: str = "Arbeidsovereenkomst",
        signature_page: int = 1,
        signature_x: int = 50,
        signature_y: int = 100,
        signature_width: int = 200,
        signature_height: int = 50,
    ) -> SignatureResult:
        """
        Create a full signature request: upload PDF, add signer, activate, return signing URL.

        Args:
            pdf_bytes: The contract PDF content
            pdf_filename: Filename for the uploaded PDF
            signer_first_name/last_name: Signer identity
            signer_email: Signer email (required by Yousign)
            signer_phone: Signer phone in E.164 format (+32...)
            request_name: Name for the signature request
            signature_page/x/y/width/height: Signature field placement on the PDF

        Returns:
            SignatureResult with signing_url on success, error on failure.
        """
        if not YOUSIGN_API_KEY:
            return SignatureResult(success=False, error="YOUSIGN_API_KEY not configured")

        try:
            async with httpx.AsyncClient(headers=self.headers, base_url=BASE_URL, timeout=30) as client:
                # 1. Create signature request
                r = await client.post("/signature_requests", json={
                    "name": request_name,
                    "delivery_mode": "none",
                })
                r.raise_for_status()
                request_id = r.json()["id"]
                logger.info(f"[YOUSIGN] Created request: {request_id}")

                # 2. Upload PDF
                r = await client.post(
                    f"/signature_requests/{request_id}/documents",
                    files={"file": (pdf_filename, pdf_bytes, "application/pdf")},
                    data={"nature": "signable_document", "parse_anchors": "false"},
                )
                r.raise_for_status()
                document_id = r.json()["id"]
                logger.info(f"[YOUSIGN] Uploaded document: {document_id}")

                # 3. Add signer with signature field
                r = await client.post(
                    f"/signature_requests/{request_id}/signers",
                    json={
                        "info": {
                            "first_name": signer_first_name,
                            "last_name": signer_last_name,
                            "email": signer_email,
                            "phone_number": signer_phone,
                            "locale": "nl",
                        },
                        "signature_level": "electronic_signature",
                        "signature_authentication_mode": "no_otp",
                        "fields": [
                            {
                                "document_id": document_id,
                                "type": "signature",
                                "page": signature_page,
                                "x": signature_x,
                                "y": signature_y,
                                "width": signature_width,
                                "height": signature_height,
                            }
                        ],
                    },
                )
                r.raise_for_status()
                signer_id = r.json()["id"]
                logger.info(f"[YOUSIGN] Added signer: {signer_id}")

                # 4. Activate
                r = await client.post(f"/signature_requests/{request_id}/activate")
                r.raise_for_status()
                logger.info(f"[YOUSIGN] Activated request: {request_id}")

                # 5. Get signing URL
                r = await client.get(f"/signature_requests/{request_id}/signers/{signer_id}")
                r.raise_for_status()
                signing_url = r.json().get("signature_link")
                logger.info(f"[YOUSIGN] Signing URL: {signing_url}")

                return SignatureResult(
                    success=True,
                    signing_url=signing_url,
                    request_id=request_id,
                    signer_id=signer_id,
                )

        except httpx.HTTPStatusError as e:
            error_msg = f"Yousign API error {e.response.status_code}: {e.response.text}"
            logger.error(f"[YOUSIGN] {error_msg}")
            return SignatureResult(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Yousign error: {e}"
            logger.error(f"[YOUSIGN] {error_msg}")
            return SignatureResult(success=False, error=error_msg)

    async def get_signing_url(self, request_id: str, signer_id: str) -> Optional[str]:
        """Fetch the signing URL for an existing request/signer."""
        try:
            async with httpx.AsyncClient(headers=self.headers, base_url=BASE_URL, timeout=15) as client:
                r = await client.get(f"/signature_requests/{request_id}/signers/{signer_id}")
                r.raise_for_status()
                return r.json().get("signature_link")
        except Exception as e:
            logger.error(f"[YOUSIGN] Failed to get signing URL: {e}")
            return None
