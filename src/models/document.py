"""
Pydantic models for document verification API.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


class DocumentVerifyRequest(BaseModel):
    """Request to verify a document image."""

    image_base64: str = Field(
        ...,
        description="Base64-encoded image (JPG/PNG) of the document"
    )

    # Identity verification options
    application_id: Optional[str] = Field(
        None,
        description="Application ID to fetch candidate name from database"
    )

    candidate_name: Optional[str] = Field(
        None,
        description="Expected candidate name if no application_id provided"
    )

    # Document type hint (optional, agent will auto-detect if not provided)
    document_type_hint: Optional[Literal[
        "driver_license",
        "medical_certificate",
        "work_permit",
        "certificate_diploma",
        "unknown"
    ]] = Field(
        "unknown",
        description="Optional hint about document type for better accuracy"
    )

    # Store result in database?
    save_verification: bool = Field(
        False,
        description="Whether to persist verification result in database"
    )


class FraudIndicator(BaseModel):
    """Individual fraud detection finding."""

    indicator_type: Literal[
        "synthetic_image",
        "digital_manipulation",
        "inconsistent_fonts",
        "poor_quality",
        "tampered_data",
        "inconsistent_layout",
        "suspicious_artifacts"
    ]

    description: str = Field(..., description="Description of the fraud indicator")

    severity: Literal["low", "medium", "high"] = Field(
        ...,
        description="Severity level of the fraud indicator"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score 0-1 for this indicator"
    )


class DocumentVerifyResponse(BaseModel):
    """Response from document verification."""

    # Document classification
    document_category: Literal[
        "driver_license",
        "medical_certificate",
        "work_permit",
        "certificate_diploma",
        "unknown",
        "unreadable"
    ] = Field(..., description="Classified document type")

    document_category_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for document classification"
    )

    # Name extraction
    extracted_name: Optional[str] = Field(
        None,
        description="Name found in the document"
    )

    name_extraction_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for name extraction"
    )

    # Name matching (if candidate name provided)
    name_match_performed: bool = Field(
        ...,
        description="Whether name matching was performed"
    )

    name_match_result: Optional[Literal[
        "exact_match",
        "partial_match",
        "no_match",
        "ambiguous"
    ]] = Field(
        None,
        description="Result of name matching if performed"
    )

    name_match_confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence score for name matching"
    )

    name_match_details: Optional[str] = Field(
        None,
        description="Detailed explanation of name matching result"
    )

    # Fraud detection
    fraud_risk_level: Literal["low", "medium", "high"] = Field(
        ...,
        description="Overall fraud risk assessment"
    )

    fraud_indicators: List[FraudIndicator] = Field(
        default_factory=list,
        description="List of detected fraud indicators"
    )

    overall_fraud_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence in fraud assessment"
    )

    # Quality checks
    image_quality: Literal[
        "excellent",
        "good",
        "acceptable",
        "poor",
        "unreadable"
    ] = Field(..., description="Assessment of image quality")

    readability_issues: List[str] = Field(
        default_factory=list,
        description="List of specific readability issues detected"
    )

    # Overall assessment
    verification_passed: bool = Field(
        ...,
        description="True if document is readable, categorized, and has acceptable fraud risk"
    )

    verification_summary: str = Field(
        ...,
        description="Human-readable summary of verification results"
    )

    # Metadata
    verification_id: Optional[str] = Field(
        None,
        description="UUID if verification was saved to database"
    )

    processed_at: str = Field(
        ...,
        description="ISO timestamp when verification was processed"
    )

    # Raw response for debugging
    raw_agent_response: Optional[str] = Field(
        None,
        description="Raw agent response for debugging purposes"
    )
