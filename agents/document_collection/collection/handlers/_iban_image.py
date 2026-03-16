"""Extract IBAN from a bank card photo using Gemini vision."""

import asyncio
import logging

from google.genai import types

logger = logging.getLogger(__name__)


async def extract_iban_from_image(image_data: bytes) -> str | None:
    """Extract IBAN from a bank card image. Returns the IBAN string or None."""
    from agents.document_collection.recognition.agent import _client, _preprocess_image

    image_data, mime_type = _preprocess_image(image_data)

    prompt = (
        "This is a photo of a bank card or bank document. "
        "Extract the IBAN number from the image. "
        "Return ONLY the IBAN number as plain text (e.g. BE68 5390 0754 7034), nothing else. "
        "If no IBAN is visible, return: NONE"
    )

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_data)),
                    types.Part(text=prompt),
                ],
                config=types.GenerateContentConfig(temperature=0),
            ),
        )

        result = (response.text or "").strip()
        if not result or result.upper() == "NONE":
            return None

        logger.info(f"[IBAN-IMAGE] Extracted: {result}")
        return result

    except Exception as e:
        logger.warning(f"[IBAN-IMAGE] Extraction failed: {e}")
        return None
