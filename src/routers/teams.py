"""
Microsoft Teams Bot Framework webhook and test endpoints.

Handles:
- Incoming messages from Teams (Bot Framework webhook)
- Test endpoint for sending messages
"""
import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.services.teams_service import get_teams_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["teams"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SendMessageRequest(BaseModel):
    """Request to send a message to a Teams channel."""
    service_url: str  # e.g., "https://smba.trafficmanager.net/emea/"
    conversation_id: str  # Channel conversation ID
    message: str


class SendMessageResponse(BaseModel):
    """Response from sending a message."""
    success: bool
    activity_id: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# Webhook Endpoint (receives messages from Teams)
# =============================================================================

@router.post("/webhook")
async def teams_webhook(request: Request):
    """
    Webhook endpoint for Microsoft Bot Framework.

    This receives all activities (messages, reactions, etc.) from Teams.
    Configure this URL in your Azure Bot settings.
    """
    try:
        activity = await request.json()
        teams_service = get_teams_service()

        # Log raw activity for debugging
        logger.info(f"Raw activity: {activity}")

        # Parse the incoming activity
        parsed = teams_service.parse_incoming_activity(activity)

        logger.info(f"Received Teams activity: type={parsed['type']}, from={parsed['from']['name']}")

        # Handle different activity types
        activity_type = parsed["type"]

        if activity_type == "message":
            # User sent a message
            user_message = parsed["text"]
            user_name = parsed["from"]["name"] or "gebruiker"
            user_id = parsed["from"]["id"]  # Capture user ID for @mentions
            conversation_id = parsed["conversation"]["id"]
            activity_id = parsed["id"]
            service_url = parsed["service_url"]
            # Use the bot's recipient ID from the incoming message as the from.id
            bot_id = parsed["recipient"]["id"]

            logger.info(f"Teams message from {user_name} (ID: {user_id}): {user_message[:100] if user_message else '(empty)'}")
            logger.info(f"Service URL: {service_url}")
            logger.info(f"Conversation ID: {conversation_id}")
            logger.info(f"Bot ID (recipient): {bot_id}")

            # For now, echo back the message (replace with your AI agent logic)
            response_text = f"Hallo {user_name}! Je zei: {user_message}"

            # Send reply via Bot Connector API
            try:
                result = await teams_service.reply_to_activity(
                    service_url=service_url,
                    conversation_id=conversation_id,
                    activity_id=activity_id,
                    message=response_text,
                    bot_id=bot_id,
                )
                logger.info(f"Reply sent successfully: {result}")
            except Exception as send_error:
                logger.error(f"Failed to send reply: {send_error}", exc_info=True)

        elif activity_type == "invoke":
            # Adaptive Card action (e.g., approve button clicked)
            action_data = activity.get("value", {}).get("action", {})
            # Fallback: some Bot Framework versions put data directly in value
            if not action_data:
                action_data = activity.get("value", {})

            action_name = action_data.get("action", "")
            service_url = parsed["service_url"]
            conversation_id = parsed["conversation"]["id"]
            bot_id = parsed["recipient"]["id"]
            user_name = parsed["from"]["name"] or "Recruiter"

            logger.info(f"Teams invoke from {user_name}: action={action_name}, data={action_data}")

            if action_name == "approve_vacancy_setup":
                workflow_id = action_data.get("workflow_id")
                vacancy_id = action_data.get("vacancy_id")

                if workflow_id:
                    try:
                        from src.workflows.orchestrator import get_orchestrator
                        orchestrator = await get_orchestrator()
                        result = await orchestrator.handle_event(
                            workflow_id, "recruiter_approved", {"approved_by": user_name}
                        )
                        logger.info(f"Recruiter {user_name} approved vacancy_setup workflow {workflow_id[:8]}")

                        # Send confirmation reply
                        try:
                            activity_id = parsed["id"]
                            await teams_service.reply_to_activity(
                                service_url=service_url,
                                conversation_id=conversation_id,
                                activity_id=activity_id,
                                message=f"✅ Goedgekeurd door {user_name}. Pre-screening wordt gepubliceerd...",
                                bot_id=bot_id,
                            )
                        except Exception as reply_error:
                            logger.warning(f"Failed to send approval confirmation: {reply_error}")

                    except Exception as wf_error:
                        logger.error(f"Failed to handle recruiter approval: {wf_error}", exc_info=True)

            # Return invoke response (required by Bot Framework for Adaptive Card actions)
            return {
                "status": 200,
                "body": {"statusCode": 200, "type": "application/vnd.microsoft.activity.message", "value": "OK"},
            }

        elif activity_type == "conversationUpdate":
            # Bot was added to a conversation or members changed
            logger.info(f"Conversation update: {parsed['conversation']}")
            service_url = parsed["service_url"]
            conversation_id = parsed["conversation"]["id"]
            bot_id = parsed["recipient"]["id"]

            # Check if bot was added
            members_added = activity.get("membersAdded", [])

            for member in members_added:
                if member.get("id") == bot_id:
                    # Bot was added to the conversation
                    logger.info("Bot was added to conversation")
                    try:
                        await teams_service.send_to_channel(
                            service_url=service_url,
                            conversation_id=conversation_id,
                            message="Hallo! Ik ben de Taloo bot. Ik help je met recruitment taken.",
                            bot_id=bot_id,
                        )
                    except Exception as send_error:
                        logger.error(f"Failed to send welcome: {send_error}", exc_info=True)

        # Return 200 OK to acknowledge receipt
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error processing Teams webhook: {e}", exc_info=True)
        # Still return 200 to prevent retries for now
        return {"status": "error", "message": str(e)}


# =============================================================================
# Test Endpoints
# =============================================================================

@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """
    Test endpoint to send a message to a Teams channel.

    You need the service_url and conversation_id from a previous conversation
    or from the Teams channel settings.
    """
    try:
        teams_service = get_teams_service()

        result = await teams_service.send_to_channel(
            service_url=request.service_url,
            conversation_id=request.conversation_id,
            message=request.message,
        )

        return SendMessageResponse(
            success=True,
            activity_id=result.get("id"),
        )

    except Exception as e:
        logger.error(f"Failed to send Teams message: {e}")
        return SendMessageResponse(
            success=False,
            error=str(e),
        )


@router.get("/test-auth")
async def test_auth():
    """
    Test endpoint to verify Teams authentication is working.

    Returns the access token info (without exposing the actual token).
    """
    try:
        teams_service = get_teams_service()
        token = await teams_service.get_access_token()

        return {
            "success": True,
            "message": "Successfully authenticated with Microsoft",
            "token_length": len(token),
            "token_preview": token[:20] + "..." if token else None,
        }

    except Exception as e:
        logger.error(f"Teams auth test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_config():
    """
    Check Teams configuration status (doesn't expose secrets).
    """
    teams_service = get_teams_service()
    config = teams_service.config

    return {
        "app_id_configured": bool(config.app_id),
        "app_id_preview": config.app_id[:8] + "..." if config.app_id else None,
        "tenant_id_configured": bool(config.tenant_id),
        "tenant_id_preview": config.tenant_id[:8] + "..." if config.tenant_id else None,
        "client_secret_configured": bool(config.app_password),
    }


@router.post("/test-recruitment-alerts")
async def test_recruitment_alerts():
    """
    Test endpoint to send a proactive message to the Recruitment Alerts channel.

    Uses the conversation reference captured from the conversationUpdate event.
    """
    try:
        teams_service = get_teams_service()

        # Recruitment Alerts channel details (captured from conversationUpdate)
        service_url = "https://smba.trafficmanager.net/emea/a26bd06f-6855-4146-bc95-efcf68a95619/"
        conversation_id = "19:201cf6383c2340cd9ff9da60f85d892f@thread.tacv2"
        bot_id = "28:0e84f7f5-9c3f-4f64-ad8b-4155717a097b"

        # @mention Laurijn to trigger notification
        result = await teams_service.send_with_mention(
            service_url=service_url,
            conversation_id=conversation_id,
            message="🔔 Test notificatie van Taloo Bot!\n\nDit is een proactief bericht naar het Recruitment Alerts kanaal.",
            mention_user_id="29:18oex_ZMfnVqsApLS4ducdhFEkkpY9tdMEINBEP3nNHxS3_C2t-GozlW4V0sckfDnd8v3jPd66voTbdC7aSFJUg",
            mention_user_name="Laurijn Deschepper",
            bot_id=bot_id,
        )

        logger.info(f"Proactive message sent to Recruitment Alerts: {result}")

        return {
            "success": True,
            "message": "Notification sent to Recruitment Alerts channel",
            "result": result,
        }

    except Exception as e:
        logger.error(f"Failed to send proactive message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
