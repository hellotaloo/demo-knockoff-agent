"""
Document Collection Router - WhatsApp document collection with real-time verification.

This router handles:
1. Outbound initiation: Start document collection conversation
2. Webhook processing: Handle incoming messages and media uploads
"""
import logging
import uuid
import json
import base64
import hashlib
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from google.genai import types

from src.models.document_collection import (
    OutboundDocumentRequest,
    OutboundDocumentResponse,
    DocumentCollectionDebugResponse
)
from src.database import get_db_pool
from src.repositories import ApplicationRepository
from src.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Document Collection"])

# Global session manager (set by main app)
session_manager = None


def set_session_manager(manager):
    """Set the session manager instance."""
    global session_manager
    session_manager = manager


# =============================================================================
# Helper Functions
# =============================================================================

async def download_twilio_media(media_url: str) -> bytes:
    """Download media from Twilio's secure URL."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        # Twilio requires Basic Auth
        auth = aiohttp.BasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        async with session.get(media_url, auth=auth) as resp:
            if resp.status != 200:
                raise HTTPException(500, f"Failed to download media: HTTP {resp.status}")
            return await resp.read()


async def save_original_document(
    image_bytes: bytes,
    conversation_id: uuid.UUID,
    upload_id: uuid.UUID,
    document_side: str
):
    """
    Background task: Save original document image for records.

    Saves images to: ./document_uploads/{conversation_id}/{document_side}_{upload_id}.jpg
    """
    try:
        from pathlib import Path

        logger.info(f"💾 Background: Saving original document {upload_id}...")

        # Create directory structure
        base_dir = Path("./document_uploads")
        conversation_dir = base_dir / str(conversation_id)
        conversation_dir.mkdir(parents=True, exist_ok=True)

        # Save original image to file
        filename = f"{document_side}_{upload_id}.jpg"
        file_path = conversation_dir / filename

        with open(file_path, 'wb') as f:
            f.write(image_bytes)

        logger.info(f"✅ Saved document: {file_path}")

    except Exception as e:
        logger.error(f"Failed to save document {upload_id}: {e}", exc_info=True)
        # Don't raise - this is a background task, failure shouldn't affect the main flow


def determine_document_side(documents_collected: list, documents_required: list) -> str:
    """
    Determine which document side should be next based on what's already collected.

    Args:
        documents_collected: List of already collected document_side values
        documents_required: List of required documents (e.g., ["id_front", "id_back"])

    Returns:
        Next document_side to collect
    """
    for doc in documents_required:
        if doc not in documents_collected:
            return doc
    return "unknown"


async def _process_document_collection(
    pool,
    conversation_id: uuid.UUID,
    application_id: uuid.UUID,
    completion_outcome: Optional[str]
):
    """
    Background task to process completed document collection.

    Fetches all verification results and updates application status.
    """
    try:
        logger.info(f"Processing completed document collection: {conversation_id}")

        # Fetch all document uploads
        uploads = await pool.fetch(
            """SELECT document_side, verification_result, verification_passed
            FROM ats.document_uploads
            WHERE conversation_id = $1
            ORDER BY uploaded_at""",
            conversation_id
        )

        # Analyze results
        all_verified = all(u["verification_passed"] for u in uploads)
        fraud_risks = [
            u["verification_result"].get("fraud_risk", "low")
            for u in uploads if u["verification_result"]
        ]
        max_fraud_risk = max(fraud_risks, default="low", key=lambda x: {"low": 0, "medium": 1, "high": 2}[x])

        # Update conversation
        await pool.execute(
            """UPDATE ats.document_collection_conversations
            SET status = 'completed', completed_at = NOW()
            WHERE id = $1""",
            conversation_id
        )

        # Update application summary
        summary = f"Documents collected: {len(uploads)}. All verified: {all_verified}. Max fraud risk: {max_fraud_risk}."
        if completion_outcome:
            summary += f" Outcome: {completion_outcome}"

        await pool.execute(
            """UPDATE ats.applications
            SET summary = COALESCE(summary, '') || '\n' || $1,
                updated_at = NOW()
            WHERE id = $2""",
            summary,
            application_id
        )

        logger.info(f"✅ Document collection processed: {conversation_id}")

    except Exception as e:
        logger.error(f"Error processing document collection {conversation_id}: {e}", exc_info=True)


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/documents/collect", response_model=OutboundDocumentResponse)
async def initiate_document_collection(request: OutboundDocumentRequest):
    """
    Start document collection conversation via WhatsApp.

    Flow:
    1. Validate vacancy exists
    2. Build full candidate name
    3. Map document types to agent format
    4. Abandon any previous active collections
    5. Create ADK session
    6. Get or create document collection agent
    7. Generate opening message
    8. Send via Twilio WhatsApp
    9. Store conversation record
    """
    from twilio.rest import Client

    global session_manager
    pool = await get_db_pool()

    # Initialize Twilio client
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    # Validate vacancy_id
    try:
        vacancy_uuid = uuid.UUID(request.vacancy_id)
    except ValueError:
        raise HTTPException(400, f"Invalid vacancy ID format: {request.vacancy_id}")

    # Verify vacancy exists
    vacancy_row = await pool.fetchrow(
        "SELECT id FROM ats.vacancies WHERE id = $1",
        vacancy_uuid
    )
    if not vacancy_row:
        raise HTTPException(404, "Vacancy not found")

    # Build full candidate name
    full_name = f"{request.candidate_name} {request.candidate_lastname}"

    # Normalize phone number
    phone_normalized = request.whatsapp_number.lstrip("+")

    # Map document types to agent format
    # Frontend: "id_card", "driver_license"
    # Agent expects: ["id_front", "id_back"] for ID card, or ["driver_license"] for license
    documents_required = []
    for doc_type in request.documents:
        if doc_type == "id_card":
            documents_required.extend(["id_front", "id_back"])
        elif doc_type == "driver_license":
            documents_required.append("driver_license")

    # Validate application_id if provided
    app_uuid = None
    if request.application_id:
        try:
            app_uuid = uuid.UUID(request.application_id)
            # Verify application exists
            app_row = await pool.fetchrow(
                "SELECT id FROM ats.applications WHERE id = $1",
                app_uuid
            )
            if not app_row:
                raise HTTPException(404, "Application not found")
        except ValueError:
            raise HTTPException(400, f"Invalid application ID format: {request.application_id}")

    # Abandon ALL active sessions for this phone number (pre-screening + document collection)
    # This ensures only one active conversation per phone number
    await pool.execute(
        """UPDATE ats.screening_conversations
        SET status = 'abandoned', updated_at = NOW()
        WHERE candidate_phone = $1 AND status = 'active'""",
        phone_normalized
    )

    await pool.execute(
        """UPDATE ats.document_collection_conversations
        SET status = 'abandoned', updated_at = NOW()
        WHERE candidate_phone = $1 AND status = 'active'""",
        phone_normalized
    )

    logger.info(f"Starting document collection for {full_name} ({phone_normalized})")

    # Create ADK session
    adk_session_id = str(uuid.uuid4())
    await session_manager.document_session_service.create_session(
        app_name="document_collection",
        user_id="whatsapp",
        session_id=adk_session_id
    )

    # Get or create runner
    runner = session_manager.get_or_create_document_runner(
        collection_id=adk_session_id,
        candidate_name=full_name,
        documents_required=documents_required
    )

    # Generate opening message
    trigger_message = f"START_COLLECTION name={full_name}"
    opening_message = ""

    async for event in runner.run_async(
        user_id="whatsapp",
        session_id=adk_session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=trigger_message)]
        )
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    opening_message += part.text

    if not opening_message:
        opening_message = f"Hallo {full_name}! Ik help je graag met het uploaden van je documenten."

    # Send via Twilio WhatsApp
    message = twilio_client.messages.create(
        body=opening_message,
        from_=TWILIO_WHATSAPP_NUMBER,
        to=f"whatsapp:{request.whatsapp_number}"
    )

    logger.info(f"Sent WhatsApp message: {message.sid}")

    # Create conversation record
    conv_row = await pool.fetchrow(
        """INSERT INTO ats.document_collection_conversations
        (application_id, vacancy_id, session_id, candidate_name, candidate_phone,
         documents_required, status)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, 'active')
        RETURNING id""",
        app_uuid,
        vacancy_uuid,
        adk_session_id,
        full_name,
        phone_normalized,
        json.dumps(documents_required)
    )

    conversation_id = conv_row["id"]

    # Store opening message
    await pool.execute(
        """INSERT INTO ats.document_collection_messages
        (conversation_id, role, message)
        VALUES ($1, 'agent', $2)""",
        conversation_id,
        opening_message
    )

    logger.info(f"✅ Document collection started: {conversation_id}")

    return OutboundDocumentResponse(
        conversation_id=str(conversation_id),
        vacancy_id=str(vacancy_uuid),
        candidate_name=full_name,
        whatsapp_number=request.whatsapp_number,
        documents_requested=request.documents,
        opening_message=opening_message,
        application_id=str(app_uuid) if app_uuid else None
    )


@router.get("/documents/debug/{phone_number}")
async def debug_active_conversations(phone_number: str):
    """
    Debug endpoint to inspect active conversations for a phone number.

    Shows both document collection and pre-screening conversations to help diagnose routing issues.
    """
    pool = await get_db_pool()

    # Normalize phone
    phone_normalized = phone_number.lstrip("+")

    # Check for active document collections
    doc_convs = await pool.fetch(
        """SELECT id, vacancy_id, session_id, candidate_name, status,
                  documents_required, retry_count, started_at
        FROM ats.document_collection_conversations
        WHERE candidate_phone = $1
        ORDER BY started_at DESC LIMIT 5""",
        phone_normalized
    )

    # Check for active screenings
    screen_convs = await pool.fetch(
        """SELECT id, vacancy_id, session_id, candidate_name, status,
                  channel, started_at
        FROM ats.screening_conversations
        WHERE candidate_phone = $1
        ORDER BY started_at DESC LIMIT 5""",
        phone_normalized
    )

    return {
        "phone_number": phone_number,
        "phone_normalized": phone_normalized,
        "document_collections": [
            {
                "id": str(row["id"]),
                "vacancy_id": str(row["vacancy_id"]),
                "session_id": row["session_id"],
                "candidate_name": row["candidate_name"],
                "status": row["status"],
                "documents_required": json.loads(row["documents_required"]) if row["documents_required"] else [],
                "retry_count": row["retry_count"],
                "started_at": row["started_at"].isoformat()
            }
            for row in doc_convs
        ],
        "screening_conversations": [
            {
                "id": str(row["id"]),
                "vacancy_id": str(row["vacancy_id"]),
                "session_id": row["session_id"],
                "candidate_name": row["candidate_name"],
                "status": row["status"],
                "channel": row["channel"],
                "started_at": row["started_at"].isoformat()
            }
            for row in screen_convs
        ],
        "routing_decision": "document_collection" if any(r["status"] == "active" for r in doc_convs)
                          else "screening" if any(r["status"] == "active" for r in screen_convs)
                          else "generic_fallback"
    }


@router.post("/webhook/documents")
async def document_webhook(
    Body: str = Form(""),
    From: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None)
):
    """
    Handle incoming WhatsApp messages and media for document collection.

    KEY FEATURE: Handles image uploads from WhatsApp!

    Flow:
    1. Find active conversation by phone number
    2. If media upload: download, verify with document_recognition_agent, store result
    3. Build message for agent (include verification result if media)
    4. Run agent to get response
    5. Check for completion or max retries
    6. Send TwiML response
    """
    global session_manager
    pool = await get_db_pool()

    phone_normalized = From.replace("whatsapp:", "").lstrip("+")

    # Find active conversation
    conv_row = await pool.fetchrow(
        """SELECT dcc.id, dcc.application_id, dcc.session_id, dcc.candidate_name,
                  dcc.retry_count, dcc.documents_required
        FROM ats.document_collection_conversations dcc
        WHERE dcc.candidate_phone = $1
        AND dcc.status = 'active'
        ORDER BY dcc.started_at DESC LIMIT 1""",
        phone_normalized
    )

    if not conv_row:
        # No active collection
        logger.warning(f"No active document collection for {phone_normalized}")
        resp = MessagingResponse()
        resp.message("Geen actieve document verzameling gevonden. Neem contact op met ons voor hulp.")
        return PlainTextResponse(str(resp), media_type="application/xml")

    conversation_id = conv_row["id"]
    session_id = conv_row["session_id"]
    candidate_name = conv_row["candidate_name"]
    retry_count = conv_row["retry_count"] or 0
    documents_required = json.loads(conv_row["documents_required"]) if conv_row["documents_required"] else []

    # Store user message
    user_message_text = Body or "[IMAGE UPLOADED]"
    await pool.execute(
        """INSERT INTO ats.document_collection_messages
        (conversation_id, role, message)
        VALUES ($1, 'user', $2)""",
        conversation_id,
        user_message_text
    )

    # Handle media upload
    verification_result = None
    if NumMedia > 0 and MediaUrl0:
        logger.info(f"Processing media upload from {phone_normalized}: {MediaUrl0}")

        try:
            # Download image from Twilio
            image_bytes = await download_twilio_media(MediaUrl0)
            image_base64 = base64.b64encode(image_bytes).decode()

            # Verify document using document_recognition_agent (with ORIGINAL image)
            from document_recognition_agent import verify_document_base64
            verification_result = await verify_document_base64(
                image_base64=image_base64,
                candidate_name=candidate_name,
                document_type_hint="unknown"  # Let agent classify
            )

            # Determine which document this is
            collected_docs = await pool.fetch(
                """SELECT document_side FROM ats.document_uploads
                WHERE conversation_id = $1 AND verification_passed = true""",
                conversation_id
            )
            collected_sides = [d["document_side"] for d in collected_docs]
            document_side = determine_document_side(collected_sides, documents_required)

            # Store verification result
            upload_row = await pool.fetchrow(
                """INSERT INTO ats.document_uploads
                (conversation_id, application_id, document_side, image_hash,
                 verification_result, verification_passed)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                RETURNING id""",
                conversation_id,
                conv_row["application_id"],
                document_side,
                hashlib.sha256(image_bytes).hexdigest(),
                json.dumps({
                    "category": verification_result.document_category,
                    "extracted_name": verification_result.extracted_name,
                    "name_match_result": verification_result.name_match_result,
                    "fraud_risk": verification_result.fraud_risk_level,
                    "confidence": verification_result.document_category_confidence,
                    "quality": verification_result.image_quality,
                    "summary": verification_result.verification_summary
                }),
                verification_result.verification_passed
            )

            # BACKGROUND TASK: Save original image for records
            upload_id = upload_row["id"]
            asyncio.create_task(
                save_original_document(
                    image_bytes=image_bytes,
                    conversation_id=conversation_id,
                    upload_id=upload_id,
                    document_side=document_side
                )
            )

            # ====================================================================
            # 📋 VERIFICATION RESULT RECEIVED
            # ====================================================================
            logger.info("=" * 80)
            logger.info("📋 VERIFICATION RESULT FROM RECOGNITION AGENT")
            logger.info("=" * 80)
            logger.info(f"Candidate        : {candidate_name}")
            logger.info(f"Phone            : {phone_normalized}")
            logger.info(f"Conversation ID  : {conversation_id}")
            logger.info("-" * 80)

            # Document category with confidence
            logger.info(f"Document Category: {verification_result.document_category} "
                       f"(confidence: {verification_result.document_category_confidence:.2%})")

            # Name extraction and matching with confidence
            logger.info(f"Extracted Name   : {verification_result.extracted_name or 'N/A'} "
                       f"(confidence: {verification_result.name_extraction_confidence:.2%})")

            # Enhanced name match display
            if verification_result.name_match_result:
                match_display = verification_result.name_match_result
                if match_display == "partial_match" and verification_result.name_match_details:
                    # Check if it's due to middle names
                    details_lower = verification_result.name_match_details.lower()
                    if "middle" in details_lower:
                        match_display = "partial_match (middle names differ)"
                    elif "format" in details_lower:
                        match_display = "partial_match (different format)"

                logger.info(f"Name Match       : {match_display} "
                           f"(confidence: {verification_result.name_match_confidence:.2%})")
                if verification_result.name_match_details:
                    logger.info(f"Match Details    : {verification_result.name_match_details}")
            else:
                logger.info("Name Match       : N/A")

            logger.info("-" * 80)

            # Image quality (no confidence score for quality)
            logger.info(f"Image Quality    : {verification_result.image_quality}")
            if verification_result.readability_issues:
                logger.info(f"Quality Issues   : {', '.join(verification_result.readability_issues)}")

            # Fraud risk with confidence
            logger.info(f"Fraud Risk       : {verification_result.fraud_risk_level} "
                       f"(confidence: {verification_result.overall_fraud_confidence:.2%})")

            logger.info("-" * 80)
            logger.info(f"Verification     : {'✅ PASSED' if verification_result.verification_passed else '❌ FAILED'}")
            logger.info(f"Retry Count      : {retry_count}/3")
            logger.info("-" * 80)
            logger.info(f"Summary: {verification_result.verification_summary}")
            logger.info("=" * 80)
            logger.info("")

            # Update retry count if verification failed
            if not verification_result.verification_passed:
                retry_count += 1
                await pool.execute(
                    """UPDATE ats.document_collection_conversations
                    SET retry_count = $1, updated_at = NOW()
                    WHERE id = $2""",
                    retry_count,
                    conversation_id
                )

            # Build verification summary for agent
            verification_summary = f"""
[DOCUMENT_VERIFICATION_RESULT]
Category: {verification_result.document_category}
Name: {verification_result.extracted_name or 'N/A'}
Name Match: {verification_result.name_match_result or 'N/A'}
Fraud Risk: {verification_result.fraud_risk_level}
Quality: {verification_result.image_quality}
Passed: {verification_result.verification_passed}
Retry Count: {retry_count}/3
Summary: {verification_result.verification_summary}
"""

            user_message = Body + "\n" + verification_summary if Body else verification_summary

        except Exception as e:
            logger.error(f"Error processing media: {e}", exc_info=True)
            user_message = Body or "[IMAGE UPLOAD FAILED]"
    else:
        user_message = Body

    # Run agent
    runner = session_manager.get_or_create_document_runner(
        collection_id=session_id,
        candidate_name=candidate_name,
        documents_required=documents_required
    )

    response_text = ""
    is_complete = False
    completion_outcome = None

    async for event in runner.run_async(
        user_id="whatsapp",
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=user_message)]
        )
    ):
        # Check for tool call in content
        if event.content and event.content.parts:
            for part in event.content.parts:
                # Check for function call (tool call)
                if hasattr(part, 'function_call') and part.function_call:
                    if part.function_call.name == "document_collection_complete":
                        is_complete = True
                        args = part.function_call.args or {}
                        completion_outcome = args.get("outcome", "")
                        logger.info(f"📄 Document collection complete: {completion_outcome}")

                # Get response text
                if hasattr(part, 'text') and part.text:
                    if event.is_final_response():
                        response_text += part.text

    # Store agent response
    await pool.execute(
        """INSERT INTO ats.document_collection_messages
        (conversation_id, role, message)
        VALUES ($1, 'agent', $2)""",
        conversation_id,
        response_text
    )

    # Update message count
    await pool.execute(
        """UPDATE ats.document_collection_conversations
        SET message_count = message_count + 1, updated_at = NOW()
        WHERE id = $1""",
        conversation_id
    )

    # Handle completion
    if is_complete:
        logger.info(f"Triggering background processing for {conversation_id}")
        asyncio.create_task(_process_document_collection(
            pool, conversation_id, conv_row["application_id"], completion_outcome
        ))

    # Check max retries
    if retry_count >= 3 and not is_complete:
        logger.warning(f"Max retries reached for {conversation_id}")
        await pool.execute(
            """UPDATE ats.document_collection_conversations
            SET status = 'needs_review', completed_at = NOW()
            WHERE id = $1""",
            conversation_id
        )
        response_text = "Na 3 pogingen kunnen we helaas niet verder. Een medewerker zal binnenkort contact met je opnemen."

    # Send TwiML response
    resp = MessagingResponse()
    resp.message(response_text or "Bedankt voor je bericht!")
    return PlainTextResponse(str(resp), media_type="application/xml")
