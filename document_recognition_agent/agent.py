"""
Document Recognition Agent for verifying identity documents.

Uses Gemini 2.5-Flash vision capabilities to:
- Classify document type
- Extract candidate name
- Verify name match
- Detect AI-generated or manipulated documents
"""

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from dataclasses import dataclass
from typing import Optional, List
import base64
import json
import logging
import re
import uuid

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes for Results
# =============================================================================

@dataclass
class FraudIndicator:
    """Individual fraud detection finding."""
    indicator_type: str
    description: str
    severity: str  # low, medium, high
    confidence: float


@dataclass
class DocumentVerificationResult:
    """Complete result from document verification."""
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
    raw_response: Optional[str] = None


# =============================================================================
# Agent Instruction - Multi-language Support (Dutch/English)
# =============================================================================

INSTRUCTION = """You are an expert document verification specialist with expertise in detecting fraudulent or AI-generated documents.

Your task is to analyze an image of an identity or qualification document and provide a comprehensive verification report.

## INPUT
You will receive:
1. An image (JPG/PNG) of a document
2. Optional: expected candidate name for verification
3. Optional: document type hint

## ANALYSIS REQUIREMENTS

### 1. DOCUMENT CLASSIFICATION
Identify the document type:
- **id_card**: National identity card (identiteitskaart / ID-kaart)
- **driver_license**: Driving license (rijbewijs)
- **medical_certificate**: Medical fitness certificate (gezondheidsverklaring)
- **work_permit**: Work permit or visa (werkvergunning)
- **certificate_diploma**: Educational certificate or diploma
- **unknown**: Recognizable document but type unclear
- **unreadable**: Image too poor quality to identify

Provide confidence score 0-1.

### 2. NAME EXTRACTION
Extract the person's name from the document. Look for:
- Full legal name fields
- First name / Last name sections
- Multiple name formats (Western, non-Western)
- Handle prefixes (van, de, van der, etc.)

Provide confidence score 0-1.

### 3. NAME MATCHING (if expected name provided)
Compare extracted name with expected candidate name:
- **exact_match**: Names match exactly (case-insensitive)
- **partial_match**: Same person, different format (e.g., "Jan de Vries" vs "J. de Vries") OR extra middle names present
- **no_match**: Different person
- **ambiguous**: Cannot determine with confidence

IMPORTANT - Belgian/Dutch Naming Conventions:
- Multiple middle names are VERY COMMON (e.g., "Jan Bart Cleasend De Vries" vs "Jan De Vries")
- If first name AND last name match, treat as **partial_match** even if middle names differ
- Middle names can be abbreviated or omitted in informal contexts
- Example: "Jan Bart Cleasend De Vries" should match "Jan De Vries" - this is NORMAL
- Another example: "Laurijn André L Deschepper" should match "Laurijn Deschepper" - this is NORMAL

Consider:
- Name order variations
- Middle name presence/absence (COMMON, not suspicious)
- Prefixes and suffixes (van, de, van der, etc.)
- Spelling variations (ij vs y, etc.)

Provide detailed explanation and confidence 0-1.

### 4. FRAUD DETECTION
Analyze for signs of manipulation or AI generation:

**Synthetic Image Indicators:**
- AI-generated portrait photos (unusual skin texture, symmetry artifacts)
- Deepfake characteristics
- Generated backgrounds

**Digital Manipulation:**
- Clone stamp artifacts
- Unnatural shadows or lighting
- Inconsistent resolution across document
- Editing tool traces (layers, masks)

**Inconsistent Fonts/Layout:**
- Font mismatches within document
- Improper alignment or spacing
- Text not following document curves
- Incorrect official logos or watermarks

**Quality Issues:**
- Deliberately poor quality to hide manipulation
- Strategic blurring over specific fields
- Inconsistent compression artifacts

**Tampered Data:**
- Dates or numbers that don't align with original print
- Overwritten or replaced text fields
- Inconsistent aging of document vs. data

For each indicator found:
- Type of indicator
- Description of what you observed
- Severity: low, medium, high
- Confidence: 0-1

### 5. OVERALL FRAUD RISK
Based on all indicators:
- **low**: No significant indicators, document appears authentic
- **medium**: Some suspicious elements, requires human review
- **high**: Strong indicators of fraud, likely manipulated/fake

### 6. IMAGE QUALITY ASSESSMENT
Rate image quality FOR OCR AND AUTHENTICATION PURPOSES:
- **excellent**: High resolution, well-lit, entire document visible, perfect alignment
- **good**: Clear and readable, minor quality issues, usable for OCR
- **acceptable**: Readable with some issues (slight angle, some glare, minor lighting issues) BUT STILL USABLE FOR OCR
- **poor**: Very difficult to read, text barely legible, OCR would struggle significantly
- **unreadable**: Cannot extract meaningful information at all

IMPORTANT: Be PRAGMATIC about quality issues:
- Slight glare or reflections are COMMON and ACCEPTABLE if text is still readable
- Photos taken at a slight angle are NORMAL and ACCEPTABLE if document is fully visible
- Minor lighting variations are ACCEPTABLE
- Only mark as "poor" if the document is genuinely difficult to read for authentication
- Only mark as "unreadable" if you cannot extract ANY useful information

Focus on: "Can this be used for authentication and OCR?" not "Is this a perfect scan?"

List specific readability issues: blurry, low_resolution, partial_document, poor_lighting, excessive_glare, etc.

## OUTPUT FORMAT
Respond ONLY with a JSON object:

```json
{
  "document_category": "driver_license",
  "document_category_confidence": 0.95,
  "extracted_name": "Jan de Vries",
  "name_extraction_confidence": 0.92,
  "name_match_performed": true,
  "name_match_result": "exact_match",
  "name_match_confidence": 0.98,
  "name_match_details": "Names match exactly when normalized",
  "fraud_indicators": [
    {
      "indicator_type": "poor_quality",
      "description": "Image intentionally blurred around date field",
      "severity": "medium",
      "confidence": 0.7
    }
  ],
  "fraud_risk_level": "medium",
  "overall_fraud_confidence": 0.65,
  "image_quality": "acceptable",
  "readability_issues": ["partial_blur", "low_resolution"],
  "verification_summary": "Document appears to be a Dutch driving license for Jan de Vries. Medium fraud risk due to suspicious blurring around date field. Recommend manual verification."
}
```

## IMPORTANT RULES
1. Be PRAGMATIC not PERFECTIONIST - real-world photos have quality issues (glare, angles, lighting)
2. Focus on "usable for authentication" not "perfect scan quality"
3. Belgian/Dutch naming: Multiple middle names are VERY COMMON - first+last name match is sufficient
4. Consider cultural context (Dutch/Belgian documents have specific layouts)
5. High fraud confidence requires multiple strong indicators - don't be paranoid
6. Verification summary should be clear and actionable
7. Respond ONLY with JSON, no additional text
8. If image is completely unreadable, still provide structured response with "unreadable" category
9. Be conservative with fraud detection - false positives harm legitimate candidates
10. Consider that genuine documents may have wear, folds, or age-related artifacts
11. Minor glare or slight angles are ACCEPTABLE - only reject if genuinely unusable
12. Think like a practical recruiter, not a forensic scientist
"""


# =============================================================================
# Agent and Runner Setup
# =============================================================================

document_verification_agent = Agent(
    name="document_verifier",
    model="gemini-2.5-flash",  # Vision-enabled, fast, cost-effective
    instruction=INSTRUCTION,
    description="Agent for verifying identity and qualification documents with fraud detection",
)

_session_service = InMemorySessionService()

_runner = Runner(
    agent=document_verification_agent,
    app_name="document_verification",
    session_service=_session_service,
)


# =============================================================================
# Helper Functions
# =============================================================================

def parse_agent_response(response_text: str) -> dict:
    """Parse JSON response from agent."""
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
            logger.error(f"Could not find JSON in response: {response_text[:500]}")
            return {}

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}\nJSON string: {json_str[:500]}")
        return {}


# =============================================================================
# Main Verification Function
# =============================================================================

async def verify_document(
    image_data: bytes,
    candidate_name: Optional[str] = None,
    document_type_hint: Optional[str] = None,
) -> DocumentVerificationResult:
    """
    Verify a document image with fraud detection.

    Args:
        image_data: Raw image bytes (JPG/PNG)
        candidate_name: Expected name for verification
        document_type_hint: Optional hint about document type

    Returns:
        DocumentVerificationResult with complete analysis
    """
    # Build prompt
    prompt_parts = ["Analyze this document image and provide a verification report."]

    if document_type_hint and document_type_hint != "unknown":
        prompt_parts.append(f"Expected document type: {document_type_hint}")

    if candidate_name:
        prompt_parts.append(f"Expected candidate name: {candidate_name}")
        prompt_parts.append("Please verify if the name on the document matches this expected name.")

    prompt_text = "\n".join(prompt_parts)

    logger.info("=" * 60)
    logger.info("DOCUMENT VERIFIER: Starting verification")
    logger.info("=" * 60)
    logger.info(f"Image size: {len(image_data)} bytes")
    logger.info(f"Expected name: {candidate_name or 'None'}")
    logger.info(f"Type hint: {document_type_hint or 'None'}")
    logger.info("-" * 40)

    # Create unique session for this verification
    session_id = f"doc_verify_{uuid.uuid4().hex[:8]}"

    await _session_service.create_session(
        app_name="document_verification",
        user_id="system",
        session_id=session_id
    )

    # Detect MIME type from image data
    mime_type = "image/jpeg"
    if image_data[:4] == b'\x89PNG':
        mime_type = "image/png"

    # Create content with image and prompt
    content = types.Content(
        role="user",
        parts=[
            types.Part(
                inline_data=types.Blob(
                    mime_type=mime_type,
                    data=image_data
                )
            ),
            types.Part(text=prompt_text)
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

    logger.info("Agent response received")
    logger.debug(f"Raw response: {response_text[:500]}...")

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
            raw_response=response_text
        )

    # Parse fraud indicators
    fraud_indicators = []
    for fi in parsed.get("fraud_indicators", []):
        fraud_indicators.append(FraudIndicator(
            indicator_type=fi.get("indicator_type", ""),
            description=fi.get("description", ""),
            severity=fi.get("severity", "low"),
            confidence=fi.get("confidence", 0.0)
        ))

    # Determine verification passed - be pragmatic!
    # Accept if: document is recognizable, fraud risk is low/medium, and quality is usable
    verification_passed = (
        parsed.get("document_category") not in ["unknown", "unreadable"] and
        parsed.get("fraud_risk_level") != "high" and
        parsed.get("image_quality") not in ["unreadable"]  # Accept poor quality if OCR can work
    )

    # Additional leniency for name matching with middle names (Belgian/Dutch convention)
    if candidate_name and parsed.get("name_match_result") == "partial_match":
        # If it's a partial match (likely due to middle names), still consider it passed
        # as long as fraud risk is not high
        if parsed.get("fraud_risk_level") != "high":
            verification_passed = True

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
        image_quality=parsed.get("image_quality", "unreadable"),
        readability_issues=parsed.get("readability_issues", []),
        verification_passed=verification_passed,
        verification_summary=parsed.get("verification_summary", ""),
        raw_response=response_text
    )

    # ========================================================================
    # DETAILED VERIFICATION REPORT
    # ========================================================================
    logger.info("=" * 80)
    logger.info("📄 DOCUMENT VERIFICATION REPORT")
    logger.info("=" * 80)
    logger.info(f"Expected Name    : {candidate_name or 'N/A'}")
    logger.info(f"Extracted Name   : {result.extracted_name or 'N/A'}")
    logger.info("-" * 80)
    logger.info(f"Document Category: {result.document_category} (confidence: {result.document_category_confidence:.2f})")
    logger.info(f"Image Quality    : {result.image_quality}")
    if result.readability_issues:
        logger.info(f"Quality Issues   : {', '.join(result.readability_issues)}")
    logger.info("-" * 80)
    if result.name_match_performed:
        logger.info(f"Name Match       : {result.name_match_result} (confidence: {result.name_match_confidence:.2f})")
        logger.info(f"Match Details    : {result.name_match_details}")
    logger.info("-" * 80)
    logger.info(f"Fraud Risk Level : {result.fraud_risk_level} (confidence: {result.overall_fraud_confidence:.2f})")
    if fraud_indicators:
        logger.info(f"Fraud Indicators : {len(fraud_indicators)} found")
        for i, fi in enumerate(fraud_indicators, 1):
            logger.info(f"  {i}. [{fi.severity.upper()}] {fi.indicator_type}: {fi.description} (confidence: {fi.confidence:.2f})")
    else:
        logger.info("Fraud Indicators : None detected")
    logger.info("-" * 80)
    logger.info(f"✅ VERIFICATION  : {'PASSED' if verification_passed else 'FAILED'}")
    logger.info(f"Summary          : {result.verification_summary}")
    logger.info("=" * 80)
    logger.info("")

    return result


async def verify_document_base64(
    image_base64: str,
    candidate_name: Optional[str] = None,
    document_type_hint: Optional[str] = None,
) -> DocumentVerificationResult:
    """
    Convenience wrapper for base64-encoded images.

    Args:
        image_base64: Base64-encoded image string
        candidate_name: Expected name for verification
        document_type_hint: Optional hint about document type

    Returns:
        DocumentVerificationResult with complete analysis
    """
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
