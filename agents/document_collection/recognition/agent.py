"""
Document Recognition Agent for verifying identity documents.

Uses Gemini 2.5-Flash vision capabilities to:
- Classify document type
- Extract candidate name + document-type-specific fields
- Verify name match
- Detect AI-generated or manipulated documents
"""

from google import genai
from google.genai import types
from dataclasses import dataclass, field
from typing import Optional, List
import base64
import io
import logging
import os
import uuid

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

# =============================================================================
# Document type → fields to extract
# =============================================================================

DOCUMENT_FIELDS = {
    "id_card": ["date_of_birth", "expiry_date", "national_registry_number", "nationality", "place_of_birth"],
    "driver_license": ["date_of_birth", "expiry_date", "license_categories", "issue_date"],
    "passport": ["date_of_birth", "expiry_date", "passport_number", "nationality", "place_of_birth"],
    "work_permit": ["expiry_date", "permit_type", "issuing_authority"],
    "medical_certificate": ["expiry_date", "issuing_authority", "certificate_type"],
    "certificate_diploma": ["issue_date", "institution", "qualification_title"],
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class FraudIndicator:
    indicator_type: str
    description: str
    severity: str  # low, medium, high
    confidence: float


@dataclass
class DocumentVerificationResult:
    document_category: str
    document_category_confidence: float
    extracted_name: Optional[str]
    name_extraction_confidence: float
    name_match_performed: bool
    name_match_result: Optional[str]
    name_match_confidence: Optional[float]
    name_match_details: Optional[str]
    fraud_risk_level: str
    fraud_indicators: List[FraudIndicator]
    overall_fraud_confidence: float
    image_quality: str
    readability_issues: List[str]
    verification_passed: bool
    verification_summary: str
    extracted_fields: dict = field(default_factory=dict)  # document-type-specific fields
    feedback_message: Optional[str] = None  # Dutch feedback for candidate when quality is poor
    raw_response: Optional[str] = None


# =============================================================================
# Prompt builder
# =============================================================================

BASE_INSTRUCTION = """You are an expert document verification specialist with expertise in detecting fraudulent or AI-generated documents.

Analyze the document image and provide a comprehensive verification report as a JSON object.

## ANALYSIS REQUIREMENTS

### 1. DOCUMENT CLASSIFICATION
Identify the document type:
- **id_card**: National identity card (identiteitskaart / ID-kaart)
- **driver_license**: Driving license (rijbewijs)
- **passport**: Passport
- **medical_certificate**: Medical fitness certificate (gezondheidsverklaring)
- **work_permit**: Work permit or visa (werkvergunning)
- **certificate_diploma**: Educational certificate or diploma
- **unknown**: Recognizable document but type unclear
- **unreadable**: Image too poor quality to identify

### 2. NAME EXTRACTION
Extract the full legal name. Handle Dutch/Belgian naming conventions (van, de, van der prefixes, multiple middle names).

### 3. NAME MATCHING (if expected name provided)
- **exact_match**: Names match exactly (case-insensitive)
- **partial_match**: Same person, different format (middle names, abbreviations) — COMMON in Belgian/Dutch names
- **no_match**: Different person
- **ambiguous**: Cannot determine

IMPORTANT: If first name AND last name match, it's partial_match even with extra middle names (e.g. "Jan Bart De Vries" vs "Jan De Vries" is NORMAL).

### 4. DOCUMENT-SPECIFIC FIELDS
{extra_fields_instruction}

### 5. FRAUD DETECTION
Check for: AI-generated portraits, digital manipulation, font mismatches, inconsistent resolution, tampered data.
For each indicator: type, description, severity (low/medium/high), confidence (0-1).

### 6. IMAGE QUALITY
- **excellent**: High res, well-lit, full document visible
- **good**: Clear, minor issues, usable for OCR
- **acceptable**: Readable despite slight angle/glare
- **poor**: Difficult to read
- **unreadable**: Cannot extract meaningful information

Be PRAGMATIC: slight glare and angles are NORMAL. Only reject if genuinely unusable.

## OUTPUT FORMAT
Respond ONLY with a JSON object:

```json
{{
  "document_category": "id_card",
  "document_category_confidence": 0.99,
  "extracted_name": "Jan de Vries",
  "name_extraction_confidence": 0.98,
  "name_match_performed": false,
  "name_match_result": null,
  "name_match_confidence": null,
  "name_match_details": null,
  "extracted_fields": {{
{example_fields}
  }},
  "fraud_indicators": [],
  "fraud_risk_level": "low",
  "overall_fraud_confidence": 0.05,
  "image_quality": "good",
  "readability_issues": [],
  "verification_summary": "Belgian ID card for Jan de Vries. No fraud indicators. Document appears authentic."
}}
```

IMPORTANT: Respond ONLY with JSON, no additional text.
"""

EXTRA_FIELDS_BY_TYPE = {
    "id_card": (
        "Extract these fields from the Belgian ID card:\n"
        "- date_of_birth (DD.MM.YYYY or as shown)\n"
        "- expiry_date (DD.MM.YYYY or as shown)\n"
        "- national_registry_number (rijksregisternummer, format: XX.XX.XX-XXX.XX)\n"
        "- nationality\n"
        "- place_of_birth\n"
        "Set to null if not visible."
    ),
    "driver_license": (
        "Extract these fields from the driving license:\n"
        "- date_of_birth (DD.MM.YYYY or as shown)\n"
        "- expiry_date\n"
        "- license_categories (e.g. 'B, BE')\n"
        "- issue_date\n"
        "Set to null if not visible."
    ),
    "passport": (
        "Extract these fields from the passport:\n"
        "- date_of_birth\n"
        "- expiry_date\n"
        "- passport_number\n"
        "- nationality\n"
        "- place_of_birth\n"
        "Set to null if not visible."
    ),
}

EXAMPLE_FIELDS_BY_TYPE = {
    "id_card": '    "date_of_birth": "01.01.1990",\n    "expiry_date": "01.01.2030",\n    "national_registry_number": "90.01.01-123.45",\n    "nationality": "Belg",\n    "place_of_birth": "Gent"',
    "driver_license": '    "date_of_birth": "01.01.1990",\n    "expiry_date": "01.01.2030",\n    "license_categories": "B",\n    "issue_date": "01.01.2020"',
    "passport": '    "date_of_birth": "01.01.1990",\n    "expiry_date": "01.01.2030",\n    "passport_number": "AB123456",\n    "nationality": "Belgian",\n    "place_of_birth": "Gent"',
}


def _build_prompt(
    document_type_hint: Optional[str],
    candidate_name: Optional[str],
    extract_fields: Optional[list[dict]] = None,
    available_types: Optional[list[dict]] = None,
) -> str:
    # Build extraction fields instruction
    if extract_fields:
        # Dynamic fields from verification_config
        field_lines = [f"- {f['name']} ({f.get('description', '')})" for f in extract_fields]
        extra = "Extract these fields from the document:\n" + "\n".join(field_lines) + "\nSet to null if not visible."
        example = "\n".join(f'    "{f["name"]}": "..."' for f in extract_fields[:3])
    else:
        extra = EXTRA_FIELDS_BY_TYPE.get(document_type_hint or "", "Extract any relevant fields visible on the document.")
        example = EXAMPLE_FIELDS_BY_TYPE.get(document_type_hint or "", '    "issue_date": "01.01.2020"')

    prompt = BASE_INSTRUCTION.format(extra_fields_instruction=extra, example_fields=example)

    # Override classification options if specific types are provided
    if available_types:
        type_list = "\n".join(f"- **{t['slug']}**: {t['name']}" for t in available_types)
        prompt += f"\n\n## AVAILABLE DOCUMENT TYPES\nClassify the document as one of:\n{type_list}\n- **unknown**: Document type not in the list above\n- **unreadable**: Image too poor quality to identify"

    parts = [prompt, "\nAnalyze this document image."]
    if document_type_hint:
        parts.append(f"Expected document type: {document_type_hint}")
    if candidate_name:
        parts.append(f"Expected candidate name: {candidate_name}")
        parts.append("Please verify if the name on the document matches this expected name.")
    return "\n".join(parts)


# =============================================================================
# Image preprocessing
# =============================================================================

def _preprocess_image(image_data: bytes, max_size: int = 1024) -> tuple[bytes, str]:
    """Resize image to max_size on longest side and re-encode as JPEG."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        result = buf.getvalue()
        logger.info(f"Image resized: {len(image_data)/1024:.1f}KB → {len(result)/1024:.1f}KB ({img.size[0]}x{img.size[1]}px)")
        return result, "image/jpeg"
    except Exception as e:
        logger.warning(f"Image preprocessing failed, using original: {e}")
        mime = "image/png" if image_data[:4] == b'\x89PNG' else "image/jpeg"
        return image_data, mime


# =============================================================================
# Main verification function — direct Gemini API (no ADK runner overhead)
# =============================================================================

from src.utils.text_utils import extract_json_from_response as parse_agent_response


def _generate_feedback(image_quality: str, readability_issues: list[str]) -> Optional[str]:
    """Generate Dutch feedback message for the candidate based on image quality."""
    if image_quality in ("excellent", "good", "acceptable"):
        return None

    issue_feedback = {
        "glare": "er is te veel weerkaatsing/glare op de foto",
        "blur": "de foto is onscherp",
        "blurry": "de foto is onscherp",
        "dark": "de foto is te donker",
        "cropped": "het document is niet volledig zichtbaar",
        "partial": "het document is niet volledig zichtbaar",
        "low_resolution": "de resolutie is te laag",
        "overexposed": "de foto is overbelicht",
        "shadow": "er valt een schaduw over het document",
        "angle": "het document staat te schuin",
        "processing_error": "er ging iets mis bij het verwerken",
    }

    specific = []
    for issue in readability_issues:
        for key, msg in issue_feedback.items():
            if key in issue.lower():
                specific.append(msg)
                break

    if image_quality == "unreadable":
        if specific:
            return f"De foto is helaas onleesbaar ({', '.join(specific)}). Kan je een nieuwe foto nemen met goede belichting en het volledige document in beeld?"
        return "De foto is helaas onleesbaar. Zorg voor goede belichting en dat het volledige document zichtbaar is."

    if specific:
        return f"De foto is niet duidelijk genoeg ({', '.join(specific)}). Kan je een nieuwe foto proberen?"
    return "De foto is niet duidelijk genoeg. Probeer opnieuw met meer licht en houd het document vlak."


async def verify_document(
    image_data: bytes,
    candidate_name: Optional[str] = None,
    document_type_hint: Optional[str] = None,
    extract_fields: Optional[list[dict]] = None,
    available_types: Optional[list[dict]] = None,
) -> DocumentVerificationResult:
    """
    Verify a document image with fraud detection and field extraction.

    Args:
        image_data: Raw image bytes (JPG/PNG)
        candidate_name: Expected name for verification
        document_type_hint: e.g. "id_card", "driver_license", "passport"
        extract_fields: Dynamic fields from verification_config [{name, description}]
        available_types: Document types to classify against [{slug, name}]

    Returns:
        DocumentVerificationResult with complete analysis
    """
    import asyncio
    import time

    logger.info("=" * 60)
    logger.info("DOCUMENT VERIFIER: Starting verification")
    logger.info(f"Image size: {len(image_data)/1024:.1f} KB | type: {document_type_hint} | name: {candidate_name}")

    # Preprocess image
    t0 = time.time()
    processed_image, mime_type = _preprocess_image(image_data)

    # Build prompt
    prompt = _build_prompt(document_type_hint, candidate_name, extract_fields, available_types)

    # Call Gemini directly (bypasses ADK runner overhead)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: _client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Part(inline_data=types.Blob(mime_type=mime_type, data=processed_image)),
                types.Part(text=prompt),
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
    )

    elapsed = time.time() - t0
    response_text = response.text or ""
    logger.info(f"Gemini response in {elapsed:.2f}s")

    # Parse response
    parsed = parse_agent_response(response_text)

    if not parsed:
        logger.error("Failed to parse agent response")
        return DocumentVerificationResult(
            document_category="unreadable",
            document_category_confidence=0.0,
            extracted_name=None,
            name_extraction_confidence=0.0,
            name_match_performed=bool(candidate_name),
            name_match_result=None,
            name_match_confidence=None,
            name_match_details="Failed to process document",
            fraud_risk_level="high",
            fraud_indicators=[],
            overall_fraud_confidence=1.0,
            image_quality="unreadable",
            readability_issues=["processing_error"],
            verification_passed=False,
            verification_summary="Error: Could not process document",
            feedback_message="Er ging iets mis bij het verwerken van de foto. Kan je het opnieuw proberen?",
            raw_response=response_text
        )

    # Parse fraud indicators
    fraud_indicators = [
        FraudIndicator(
            indicator_type=fi.get("indicator_type", ""),
            description=fi.get("description", ""),
            severity=fi.get("severity", "low"),
            confidence=fi.get("confidence", 0.0)
        )
        for fi in parsed.get("fraud_indicators", [])
    ]

    # Determine verification passed
    verification_passed = (
        parsed.get("document_category") not in ["unknown", "unreadable"] and
        parsed.get("fraud_risk_level") != "high" and
        parsed.get("image_quality") not in ["unreadable"]
    )
    # Leniency for Belgian/Dutch partial name match
    if candidate_name and parsed.get("name_match_result") == "partial_match":
        if parsed.get("fraud_risk_level") != "high":
            verification_passed = True

    image_quality = parsed.get("image_quality", "unreadable")
    readability_issues = parsed.get("readability_issues", [])
    feedback = _generate_feedback(image_quality, readability_issues)

    result = DocumentVerificationResult(
        document_category=parsed.get("document_category", "unknown"),
        document_category_confidence=parsed.get("document_category_confidence", 0.0),
        extracted_name=parsed.get("extracted_name"),
        name_extraction_confidence=parsed.get("name_extraction_confidence", 0.0),
        name_match_performed=parsed.get("name_match_performed", False),
        name_match_result=parsed.get("name_match_result"),
        name_match_confidence=parsed.get("name_match_confidence"),
        name_match_details=parsed.get("name_match_details"),
        fraud_risk_level=parsed.get("fraud_risk_level", "high"),
        fraud_indicators=fraud_indicators,
        overall_fraud_confidence=parsed.get("overall_fraud_confidence", 1.0),
        image_quality=image_quality,
        readability_issues=readability_issues,
        verification_passed=verification_passed,
        verification_summary=parsed.get("verification_summary", ""),
        extracted_fields=parsed.get("extracted_fields", {}),
        feedback_message=feedback,
        raw_response=response_text
    )

    logger.info("=" * 80)
    logger.info("📄 DOCUMENT VERIFICATION REPORT")
    logger.info("=" * 80)
    logger.info(f"Category   : {result.document_category} ({result.document_category_confidence:.2f})")
    logger.info(f"Name       : {result.extracted_name}")
    logger.info(f"Quality    : {result.image_quality}")
    logger.info(f"Fraud risk : {result.fraud_risk_level}")
    if result.extracted_fields:
        logger.info(f"Fields     : {result.extracted_fields}")
    logger.info(f"✅ PASSED  : {result.verification_passed}")
    logger.info(f"Summary    : {result.verification_summary}")
    logger.info("=" * 80)

    return result


async def verify_document_base64(
    image_base64: str,
    candidate_name: Optional[str] = None,
    document_type_hint: Optional[str] = None,
) -> DocumentVerificationResult:
    """Convenience wrapper for base64-encoded images."""
    try:
        image_data = base64.b64decode(image_base64)
    except Exception as e:
        logger.error(f"Failed to decode base64 image: {e}")
        return DocumentVerificationResult(
            document_category="unreadable",
            document_category_confidence=0.0,
            extracted_name=None,
            name_extraction_confidence=0.0,
            name_match_performed=bool(candidate_name),
            name_match_result=None,
            name_match_confidence=None,
            name_match_details="Invalid base64 encoding",
            fraud_risk_level="high",
            fraud_indicators=[],
            overall_fraud_confidence=1.0,
            image_quality="unreadable",
            readability_issues=["invalid_encoding"],
            verification_passed=False,
            verification_summary="Error: Invalid base64 image data",
            raw_response=None
        )
    return await verify_document(image_data, candidate_name, document_type_hint)
