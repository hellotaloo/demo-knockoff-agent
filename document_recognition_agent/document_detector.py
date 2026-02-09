"""
AI-Powered Document Detection

Uses Gemini Vision to detect document boundaries and orientation in images.
Much more reliable than traditional edge detection for real-world photos.
"""

import logging
from typing import Optional, Tuple
from dataclasses import dataclass
from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
import json
import re
import uuid

logger = logging.getLogger(__name__)


@dataclass
class DocumentBounds:
    """Document boundary detection result."""
    top_left: Tuple[float, float]
    top_right: Tuple[float, float]
    bottom_right: Tuple[float, float]
    bottom_left: Tuple[float, float]
    confidence: float
    rotation_degrees: float
    detection_notes: str


DETECTION_INSTRUCTION = """You are a document boundary detection specialist.

Your task is to identify the exact boundaries of an identity document (ID card, driver's license, etc.) in a photo.

## INPUT
You will receive a photo that contains an identity document. The document may be:
- At an angle or rotated
- Partially in shadow
- On a table with other objects
- Held in a hand
- Not perfectly aligned

## TASK
Identify the 4 corners of the document and estimate the rotation angle.

## OUTPUT FORMAT
Respond ONLY with a JSON object:

```json
{
  "document_found": true,
  "corners": {
    "top_left": [x, y],
    "top_right": [x, y],
    "bottom_right": [x, y],
    "bottom_left": [x, y]
  },
  "rotation_degrees": 0,
  "confidence": 0.95,
  "notes": "Document clearly visible, slight rotation clockwise, good lighting"
}
```

**Coordinate System:**
- (0, 0) is the top-left corner of the image
- (1, 1) is the bottom-right corner of the image
- All coordinates are normalized between 0 and 1

**Rotation:**
- 0° = document is horizontal/landscape oriented correctly
- Positive degrees = clockwise rotation
- Negative degrees = counter-clockwise rotation

**Important:**
- If no document is visible, set document_found to false
- Confidence should reflect how certain you are about the boundaries (0-1)
- In notes, briefly describe what you see and any challenges

## EXAMPLES

Example 1 - Perfect horizontal document:
```json
{
  "document_found": true,
  "corners": {
    "top_left": [0.1, 0.3],
    "top_right": [0.9, 0.3],
    "bottom_right": [0.9, 0.7],
    "bottom_left": [0.1, 0.7]
  },
  "rotation_degrees": 0,
  "confidence": 0.98,
  "notes": "ID card clearly visible, perfectly horizontal, good lighting"
}
```

Example 2 - Rotated document:
```json
{
  "document_found": true,
  "corners": {
    "top_left": [0.2, 0.4],
    "top_right": [0.7, 0.2],
    "bottom_right": [0.8, 0.6],
    "bottom_left": [0.3, 0.8]
  },
  "rotation_degrees": -15,
  "confidence": 0.92,
  "notes": "Driver's license rotated counter-clockwise, held in hand, slight glare on left side"
}
```

Example 3 - No document visible:
```json
{
  "document_found": false,
  "confidence": 0.0,
  "notes": "No identity document visible in the image"
}
```

## RULES
1. Be accurate - incorrect corners will result in poor crops
2. Include the entire document area within the corners
3. If document is partially cut off, include only the visible portion
4. Confidence < 0.7 means uncertain detection
5. Respond ONLY with JSON, no additional text
"""


# Create detection agent
_detection_agent = Agent(
    name="document_detector",
    model="gemini-2.5-flash",
    instruction=DETECTION_INSTRUCTION,
    description="AI agent for detecting document boundaries in photos"
)

_session_service = InMemorySessionService()
_runner = Runner(
    agent=_detection_agent,
    app_name="document_detection",
    session_service=_session_service
)


def parse_detection_response(response_text: str) -> Optional[dict]:
    """Parse JSON response from detection agent."""
    # Try to extract JSON from markdown code block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.error(f"Could not find JSON in detection response: {response_text[:500]}")
            return None

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse detection JSON: {e}\nJSON string: {json_str[:500]}")
        return None


async def detect_document_bounds(image_data: bytes) -> Optional[DocumentBounds]:
    """
    Use AI to detect document boundaries in an image.

    Args:
        image_data: Raw image bytes (JPEG/PNG)

    Returns:
        DocumentBounds with corner coordinates, or None if detection failed
    """
    try:
        logger.info("🔍 AI Document Detection: Analyzing image with Gemini...")

        # Create unique session
        session_id = f"doc_detect_{uuid.uuid4().hex[:8]}"
        await _session_service.create_session(
            app_name="document_detection",
            user_id="system",
            session_id=session_id
        )

        # Detect MIME type
        mime_type = "image/jpeg"
        if image_data[:4] == b'\x89PNG':
            mime_type = "image/png"

        # Create content with image
        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    inline_data=types.Blob(
                        mime_type=mime_type,
                        data=image_data
                    )
                ),
                types.Part(text="Detect the document boundaries in this image.")
            ]
        )

        # Run agent
        response_text = ""
        async for event in _runner.run_async(
            user_id="system",
            session_id=session_id,
            new_message=content
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text += part.text

        # Parse response
        parsed = parse_detection_response(response_text)
        if not parsed:
            logger.error("Failed to parse detection response")
            return None

        if not parsed.get("document_found", False):
            logger.warning(f"Document not found in image: {parsed.get('notes', 'N/A')}")
            return None

        corners = parsed.get("corners", {})
        if not all(k in corners for k in ["top_left", "top_right", "bottom_right", "bottom_left"]):
            logger.error("Missing corner coordinates in detection response")
            return None

        result = DocumentBounds(
            top_left=tuple(corners["top_left"]),
            top_right=tuple(corners["top_right"]),
            bottom_right=tuple(corners["bottom_right"]),
            bottom_left=tuple(corners["bottom_left"]),
            confidence=parsed.get("confidence", 0.0),
            rotation_degrees=parsed.get("rotation_degrees", 0.0),
            detection_notes=parsed.get("notes", "")
        )

        logger.info(f"✅ Document detected (confidence: {result.confidence:.2%})")
        logger.info(f"   Rotation: {result.rotation_degrees:.1f}°")
        logger.info(f"   Notes: {result.detection_notes}")

        return result

    except Exception as e:
        logger.error(f"Error detecting document bounds: {e}", exc_info=True)
        return None
