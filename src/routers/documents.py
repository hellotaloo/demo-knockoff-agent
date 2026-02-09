"""
Document Verification Router

Handles document verification endpoints including identity documents and
qualification certificates with fraud detection.
"""
import uuid
import logging
import hashlib
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends

from document_recognition_agent import verify_document_base64
from src.models.document import (
    DocumentVerifyRequest,
    DocumentVerifyResponse,
    FraudIndicator as FraudIndicatorModel,
)
from src.dependencies import get_application_repo
from src.repositories import ApplicationRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Document Verification"])


@router.post("/verify", response_model=DocumentVerifyResponse)
async def verify_document_endpoint(
    request: DocumentVerifyRequest,
    app_repo: ApplicationRepository = Depends(get_application_repo)
):
    """
    Verify a document image with fraud detection.

    Analyzes identity or qualification documents to:
    - Classify document type (driver license, medical certificate, work permit, certificate/diploma)
    - Extract candidate name from the document
    - Verify name matches expected candidate (from application or request)
    - Detect AI-generated or manipulated documents
    - Provide confidence scores and fraud risk assessment

    Returns comprehensive verification results including fraud indicators and quality assessment.
    """
    # Get candidate name if application_id provided
    candidate_name = request.candidate_name
    vacancy_id = None

    if request.application_id:
        try:
            app_uuid = uuid.UUID(request.application_id)
            app = await app_repo.get_by_id(app_uuid)

            if not app:
                raise HTTPException(status_code=404, detail="Application not found")

            candidate_name = app["candidate_name"]
            vacancy_id = str(app["vacancy_id"]) if app.get("vacancy_id") else None

            logger.info(f"Verifying document for application {request.application_id}, candidate: {candidate_name}")

        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid application ID format")
        except Exception as e:
            logger.error(f"Error fetching application: {e}")
            raise HTTPException(status_code=500, detail=f"Error fetching application: {str(e)}")

    # Verify document
    try:
        result = await verify_document_base64(
            image_base64=request.image_base64,
            candidate_name=candidate_name,
            document_type_hint=request.document_type_hint if request.document_type_hint != "unknown" else None,
        )
    except Exception as e:
        logger.error(f"Error during document verification: {e}")
        raise HTTPException(status_code=500, detail=f"Document verification failed: {str(e)}")

    # Convert fraud indicators to response models
    fraud_indicators = [
        FraudIndicatorModel(
            indicator_type=fi.indicator_type,
            description=fi.description,
            severity=fi.severity,
            confidence=fi.confidence
        )
        for fi in result.fraud_indicators
    ]

    # Prepare response
    response = DocumentVerifyResponse(
        document_category=result.document_category,
        document_category_confidence=result.document_category_confidence,
        extracted_name=result.extracted_name,
        name_extraction_confidence=result.name_extraction_confidence,
        name_match_performed=result.name_match_performed,
        name_match_result=result.name_match_result,
        name_match_confidence=result.name_match_confidence,
        name_match_details=result.name_match_details,
        fraud_risk_level=result.fraud_risk_level,
        fraud_indicators=fraud_indicators,
        overall_fraud_confidence=result.overall_fraud_confidence,
        image_quality=result.image_quality,
        readability_issues=result.readability_issues,
        verification_passed=result.verification_passed,
        verification_summary=result.verification_summary,
        processed_at=datetime.utcnow().isoformat() + "Z",
        raw_agent_response=result.raw_response if logger.level == logging.DEBUG else None
    )

    # TODO: If save_verification is True, implement database persistence
    # For POC, we skip database persistence and just return the response
    if request.save_verification:
        logger.info("Note: save_verification=true but database persistence not yet implemented for POC")
        # Future: Calculate image hash and save to document_verifications table
        # image_hash = hashlib.sha256(base64.b64decode(request.image_base64)).hexdigest()
        # verification_id = await doc_repo.create(...)
        # response.verification_id = str(verification_id)

    logger.info(f"Document verification complete: {result.document_category} - {result.fraud_risk_level} fraud risk")

    return response
