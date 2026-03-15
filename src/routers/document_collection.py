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
from src.utils.conversation_cache import conversation_cache
from src.services.whatsapp_service import send_whatsapp_message

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
            FROM agents.document_collection_uploads
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
            """UPDATE agents.document_collections
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
    global session_manager
    pool = await get_db_pool()

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
        """UPDATE agents.pre_screening_sessions
        SET status = 'abandoned', updated_at = NOW()
        WHERE candidate_phone = $1 AND status = 'active'""",
        phone_normalized
    )

    await pool.execute(
        """UPDATE agents.document_collections
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

    # Send via centralized WhatsApp service (handles ** to * conversion)
    message_sid = await send_whatsapp_message(request.whatsapp_number, opening_message)
    if not message_sid:
        raise HTTPException(500, "Failed to send WhatsApp message")

    logger.info(f"Sent WhatsApp message: {message_sid}")

    # Create conversation record
    conv_row = await pool.fetchrow(
        """INSERT INTO agents.document_collections
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
        """INSERT INTO agents.document_collection_session_turns
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
        FROM agents.document_collections
        WHERE candidate_phone = $1
        ORDER BY started_at DESC LIMIT 5""",
        phone_normalized
    )

    # Check for active screenings
    screen_convs = await pool.fetch(
        """SELECT id, vacancy_id, session_id, candidate_name, status,
                  channel, started_at
        FROM agents.pre_screening_sessions
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

    Uses the code-controlled DocumentCollectionAgent (same pattern as pre-screening).
    Agent state is persisted to the agent_state JSONB column on document_collections.

    Flow:
    1. Find active collection by phone
    2. Restore or create agent from DB state
    3. Process message through agent (handles verification simulation, skip, etc.)
    4. Persist updated state to DB
    5. Check for completion
    6. Return TwiML response
    """
    from agents.document_collection.collection.agent import (
        create_collection_agent,
        restore_collection_agent,
        is_collection_complete,
    )
    from agents.document_collection.collection.type_cache import TypeCache

    pool = await get_db_pool()
    phone_normalized = From.replace("whatsapp:", "").lstrip("+")

    # Find active collection with plan data
    conv_row = await pool.fetchrow(
        """SELECT id, candidacy_id, candidate_name, candidate_id, vacancy_id,
                  workspace_id, collection_plan, agent_state, message_count
        FROM agents.document_collections
        WHERE candidate_phone = $1 AND status = 'active'
        ORDER BY started_at DESC LIMIT 1""",
        phone_normalized
    )

    if not conv_row:
        logger.warning(f"No active document collection for {phone_normalized}")
        resp = MessagingResponse()
        resp.message("Geen actieve document verzameling gevonden. Neem contact op met ons voor hulp.")
        return PlainTextResponse(str(resp), media_type="application/xml")

    conversation_id = conv_row["id"]
    candidate_name = conv_row["candidate_name"]
    agent_state_json = conv_row["agent_state"]

    # Store user message
    user_message_text = Body or "[IMAGE UPLOADED]"
    await pool.execute(
        """INSERT INTO agents.document_collection_session_turns
        (conversation_id, role, message)
        VALUES ($1, 'user', $2)""",
        conversation_id,
        user_message_text
    )

    # Build TypeCache for this workspace
    type_cache = TypeCache(pool, conv_row["workspace_id"])
    await type_cache.ensure_loaded()

    # Restore or create agent
    if agent_state_json and isinstance(agent_state_json, str):
        agent = restore_collection_agent(agent_state_json, type_cache=type_cache)
    elif agent_state_json and isinstance(agent_state_json, dict):
        agent = restore_collection_agent(json.dumps(agent_state_json), type_cache=type_cache)
    else:
        # First message — create agent from plan
        plan = conv_row["collection_plan"]
        if isinstance(plan, str):
            plan = json.loads(plan)

        if not plan:
            logger.error(f"No collection plan for {conversation_id}")
            resp = MessagingResponse()
            resp.message("Er is een probleem met je dossier. Een medewerker neemt contact met je op.")
            return PlainTextResponse(str(resp), media_type="application/xml")

        # Get vacancy info for recruiter contact
        vacancy_row = await pool.fetchrow(
            """SELECT r.name AS recruiter_name, r.email AS recruiter_email, r.phone AS recruiter_phone
               FROM ats.vacancies v
               LEFT JOIN ats.recruiters r ON r.id = v.recruiter_id
               WHERE v.id = $1""",
            conv_row["vacancy_id"]
        )

        # Inject candidate phone into plan context for Yousign integration
        if "context" not in plan:
            plan["context"] = {}
        plan["context"]["candidate_phone"] = f"+{phone_normalized}" if not phone_normalized.startswith("+") else phone_normalized

        agent = create_collection_agent(
            plan=plan,
            type_cache=type_cache,
            collection_id=str(conversation_id),
            recruiter_name=vacancy_row["recruiter_name"] or "" if vacancy_row else "",
            recruiter_email=vacancy_row["recruiter_email"] or "" if vacancy_row else "",
            recruiter_phone=vacancy_row["recruiter_phone"] or "" if vacancy_row else "",
        )

        # Send intro as separate messages
        intro_messages = await agent.get_initial_message()

        # Store each message + persist state
        for msg in intro_messages:
            await pool.execute(
                """INSERT INTO agents.document_collection_session_turns
                (conversation_id, role, message) VALUES ($1, 'agent', $2)""",
                conversation_id, msg
            )
        await pool.execute(
            """UPDATE agents.document_collections
            SET agent_state = $1::jsonb, message_count = COALESCE(message_count, 0) + $2, updated_at = NOW()
            WHERE id = $3""",
            agent.state.to_json(), len(intro_messages), conversation_id
        )

        # Send each as a separate WhatsApp message via TwiML
        resp = MessagingResponse()
        for msg in intro_messages:
            resp.message(msg.replace("**", "*"))
        return PlainTextResponse(str(resp), media_type="application/xml")

    # Process message through agent
    has_image = NumMedia > 0
    response_text = await agent.process_message(Body, has_image=has_image)

    # Persist updated state
    await pool.execute(
        """UPDATE agents.document_collections
        SET agent_state = $1::jsonb, message_count = COALESCE(message_count, 0) + 1, updated_at = NOW()
        WHERE id = $2""",
        agent.state.to_json(), conversation_id
    )

    # Store agent response
    await pool.execute(
        """INSERT INTO agents.document_collection_session_turns
        (conversation_id, role, message) VALUES ($1, 'agent', $2)""",
        conversation_id, response_text
    )

    # Handle completion
    if is_collection_complete(agent):
        logger.info(f"Document collection complete: {conversation_id}")
        await conversation_cache.invalidate(phone_normalized)
        asyncio.create_task(_process_document_collection(
            pool, conversation_id, None,
            f"Collected: {list(agent.state.collected_documents.keys())}, "
            f"Attributes: {list(agent.state.collected_attributes.keys())}"
        ))

        # Advance workflow
        try:
            from src.workflows import get_orchestrator
            orchestrator = await get_orchestrator()
            wf = await orchestrator.find_by_context("collection_id", str(conversation_id))
            if wf:
                await orchestrator.service.update_step(wf["id"], "collection_complete")
        except Exception as e:
            logger.error(f"Failed to advance workflow for collection {conversation_id}: {e}")

    # Send TwiML response
    resp = MessagingResponse()
    resp.message((response_text or "Bedankt voor je bericht!").replace("**", "*"))
    return PlainTextResponse(str(resp), media_type="application/xml")
