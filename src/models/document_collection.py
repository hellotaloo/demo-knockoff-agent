"""
Pydantic models for document collection API.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any


class OutboundDocumentRequest(BaseModel):
    """Request to start document collection conversation."""
    vacancy_id: str = Field(
        ...,
        description="UUID of the vacancy this is for"
    )
    candidate_name: str = Field(
        ...,
        description="First name of the candidate",
        min_length=1
    )
    candidate_lastname: str = Field(
        ...,
        description="Last name of the candidate",
        min_length=1
    )
    whatsapp_number: str = Field(
        ...,
        description="WhatsApp phone number (e.g., +32412345678)",
        pattern=r'^\+?[1-9]\d{1,14}$'
    )
    documents: List[Literal["id_card", "driver_license"]] = Field(
        ...,
        description="List of documents to collect",
        min_length=1
    )
    application_id: Optional[str] = Field(
        None,
        description="Optional application ID to link to existing application"
    )


class OutboundDocumentResponse(BaseModel):
    """Response from document collection initiation."""
    conversation_id: str = Field(..., description="UUID of the conversation created")
    vacancy_id: str = Field(..., description="UUID of the vacancy")
    candidate_name: str = Field(..., description="Full name of the candidate")
    whatsapp_number: str = Field(..., description="WhatsApp number used")
    documents_requested: List[str] = Field(..., description="Documents to be collected")
    opening_message: str = Field(..., description="First message sent to candidate")
    application_id: Optional[str] = Field(None, description="Application ID if linked")


class DocumentCollectionDebugResponse(BaseModel):
    """
    Final debug response with all verification results.

    Returned when document collection is complete or needs review.
    """
    conversation_id: str = Field(..., description="UUID of the conversation")
    application_id: str = Field(..., description="UUID of the application")

    status: Literal["completed", "needs_review", "abandoned"] = Field(
        ...,
        description="Final status of the collection"
    )

    documents_collected: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of document uploads with verification results"
    )

    all_verified: bool = Field(
        ...,
        description="True if all documents passed verification"
    )

    retry_attempts: int = Field(
        ...,
        description="Total number of retry attempts made"
    )

    overall_summary: str = Field(
        ...,
        description="Summary of the entire collection process"
    )

    completion_outcome: Optional[str] = Field(
        None,
        description="Outcome message from the agent"
    )
