"""
Pre-Screening Workflow Handlers

Handles events for pre-screening workflows (voice + WhatsApp).

Events:
- screening_completed: Called when voice call ends or WhatsApp agent finishes
- auto (after processed): Sends notifications if qualified + scheduled
"""
import logging
import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from src.services.whatsapp_service import send_whatsapp_message

if TYPE_CHECKING:
    from src.workflows.orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)

# =============================================================================
# STEP CONFIGURATION
# =============================================================================
# Timeout: How long before the workflow auto-completes as "timed_out"
# Stuck threshold: How long before the step is shown as "stuck" in dashboard
#
# Set to None for terminal states (no timeout needed)
# =============================================================================

STEP_CONFIG = {
    "in_progress": {
        "timeout_seconds": 12 * 3600,      # 12 hours - candidate may take time to complete interview
        "stuck_threshold_seconds": 4 * 3600,  # 4 hours - flag if no activity for this long
    },
    "processed": {
        "timeout_seconds": 5 * 60,         # 5 minutes - transcript processing should be quick
        "stuck_threshold_seconds": 2 * 60,   # 2 minutes - should process almost instantly
        "auto_delay_seconds": 60,          # 1 minute delay before sending notifications
    },
    "complete": {
        "timeout_seconds": None,           # Terminal state - no timeout
        "stuck_threshold_seconds": None,
    },
    "timed_out": {
        "timeout_seconds": None,           # Terminal state - no timeout
        "stuck_threshold_seconds": None,
    },
}

# Helper to get config with defaults
def get_step_timeout(step: str) -> Optional[int]:
    """Get timeout in seconds for a step, or None for terminal states."""
    return STEP_CONFIG.get(step, {}).get("timeout_seconds", 3600)  # Default 1h

def get_step_stuck_threshold(step: str) -> Optional[int]:
    """Get stuck threshold in seconds for a step."""
    return STEP_CONFIG.get(step, {}).get("stuck_threshold_seconds", 3600)  # Default 1h


# Teams notification channel config (from environment, with defaults from test endpoint)
TEAMS_ALERTS_SERVICE_URL = os.environ.get(
    "MS_TEAMS_ALERTS_SERVICE_URL",
    "https://smba.trafficmanager.net/emea/a26bd06f-6855-4146-bc95-efcf68a95619/"
)
TEAMS_ALERTS_CONVERSATION_ID = os.environ.get(
    "MS_TEAMS_ALERTS_CONVERSATION_ID",
    "19:201cf6383c2340cd9ff9da60f85d892f@thread.tacv2"
)
TEAMS_BOT_ID = os.environ.get(
    "MS_TEAMS_BOT_ID",
    "28:0e84f7f5-9c3f-4f64-ad8b-4155717a097b"
)


async def handle_screening_completed(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Handle screening completion event.

    Called when:
    - Voice: VAPI end-of-call-report webhook (after transcript processing)
    - WhatsApp: Agent's finish() function (after conversation ends)

    The caller passes the screening results in payload:
    - qualified: bool
    - interview_slot: Optional[str] (ISO datetime if scheduled)
    - application_id: str
    - summary: Optional[str]

    This handler updates the workflow context with results.
    """
    context = workflow["context"]
    channel = context.get("channel", "unknown")

    logger.info(f"Workflow {workflow['id']}: screening_completed (channel={channel})")

    # Extract results from payload
    qualified = payload.get("qualified", False)
    interview_slot = payload.get("interview_slot")
    application_id = payload.get("application_id")
    summary = payload.get("summary")

    # Update workflow context with results
    updates = {
        "qualified": qualified,
        "interview_slot": interview_slot,
        "application_id": application_id,
        "processed_at": datetime.utcnow().isoformat(),
    }
    if summary:
        updates["summary"] = summary

    await orchestrator.update_context(workflow["id"], updates)

    logger.info(
        f"Workflow {workflow['id']}: qualified={qualified}, "
        f"interview_slot={interview_slot}, application_id={application_id}"
    )

    return {
        "next_step": "processed",
        "qualified": qualified,
        "interview_slot": interview_slot,
    }


async def handle_send_notifications(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Send notifications after screening is processed.

    Auto-triggered when workflow advances to "processed" step.

    Sends notifications only if:
    - Candidate is qualified (passed knockouts)
    - Appointment was scheduled (interview_slot is set)

    Notifications:
    - WhatsApp: Appointment confirmation to candidate (both channels)
    - Teams: Notification to recruiter (both channels)
    """
    context = workflow["context"]
    qualified = context.get("qualified", False)
    interview_slot = context.get("interview_slot")
    candidate_phone = context.get("candidate_phone")
    candidate_name = context.get("candidate_name", "Kandidaat")

    # Only send notifications if qualified AND appointment scheduled
    if not qualified or not interview_slot:
        reason = []
        if not qualified:
            reason.append("niet gekwalificeerd")
        if not interview_slot:
            reason.append("geen interview ingepland")
        logger.info(
            f"⏭️  SKIP NOTIFICATIONS: {', '.join(reason)} | "
            f"qualified={qualified} | interview_slot={interview_slot} | "
            f"id={workflow['id'][:8]}"
        )
        return {
            "next_step": "complete",
            "new_status": "completed",
            "notifications_sent": False,
            "reason": "not_qualified_or_no_appointment",
        }

    logger.info(
        f"📤 SENDING NOTIFICATIONS: qualified={qualified} | interview={interview_slot} | "
        f"phone={candidate_phone} | id={workflow['id'][:8]}"
    )

    notifications_sent = []

    # Send WhatsApp confirmation to candidate (both voice and WhatsApp channels)
    if candidate_phone:
        try:
            whatsapp_sent = await _send_appointment_confirmation_whatsapp(
                phone=candidate_phone,
                candidate_name=candidate_name,
                interview_slot=interview_slot,
            )
            if whatsapp_sent:
                notifications_sent.append("whatsapp")
                logger.info(f"Workflow {workflow['id']}: sent WhatsApp confirmation")
        except Exception as e:
            logger.error(f"Workflow {workflow['id']}: failed to send WhatsApp: {e}")

    # Send Teams notification to recruiter
    try:
        teams_sent = await _send_teams_notification(
            workflow=workflow,
            context=context,
        )
        if teams_sent:
            notifications_sent.append("teams")
            logger.info(f"Workflow {workflow['id']}: sent Teams notification")
    except Exception as e:
        logger.error(f"Workflow {workflow['id']}: failed to send Teams notification: {e}")

    logger.info(
        f"✅ NOTIFICATIONS COMPLETE: {', '.join(notifications_sent) if notifications_sent else 'none'} | "
        f"id={workflow['id'][:8]}"
    )

    return {
        "next_step": "complete",
        "new_status": "completed",
        "notifications_sent": True,
        "notifications": notifications_sent,
    }


async def _send_appointment_confirmation_whatsapp(
    phone: str,
    candidate_name: str,
    interview_slot: str,
) -> bool:
    """
    Send appointment confirmation via WhatsApp.

    Args:
        phone: Candidate phone number
        candidate_name: Candidate's name
        interview_slot: ISO datetime string

    Returns:
        True if message was sent successfully
    """
    # Parse interview slot
    try:
        dt = datetime.fromisoformat(interview_slot.replace("Z", "+00:00"))
        date_str = dt.strftime("%d/%m/%Y")
        time_str = dt.strftime("%H:%M")
    except Exception:
        date_str = interview_slot
        time_str = ""

    # Extract first name
    first_name = candidate_name.split()[0] if candidate_name else "daar"

    # Build message
    message = f"""Beste {first_name},

Je afspraak is bevestigd!
📅 {date_str} om {time_str}

Groeten,
Het Taloo team"""

    message_sid = await send_whatsapp_message(phone, message)
    return message_sid is not None


async def _send_teams_notification(
    workflow: dict,
    context: dict,
) -> bool:
    """
    Send notification to recruiter via Teams.

    Looks up the existing Google Doc (created by screening_notes_integration_service)
    and sends an Adaptive Card with:
    - Candidate name and vacancy
    - Scheduled date/time
    - Summary (if available)
    - Link to the Google Doc

    Returns True if notification was sent successfully.
    """
    from src.database import get_db_pool
    from src.services.teams_service import get_teams_service

    candidate_name = context.get("candidate_name", "Unknown")
    vacancy_title = context.get("vacancy_title", "Unknown")
    interview_slot = context.get("interview_slot", "")
    summary = context.get("summary", "")
    application_id = context.get("application_id", "")
    channel = context.get("channel", "whatsapp")

    # Parse interview slot for display
    try:
        dt = datetime.fromisoformat(interview_slot.replace("Z", "+00:00"))
        formatted_date = dt.strftime("%d/%m/%Y om %H:%M")
    except Exception:
        formatted_date = interview_slot

    # Look up existing Google Doc URL from scheduled_interviews
    # (created by trigger_screening_notes_integration in webhook handlers)
    doc_url = None
    if application_id:
        try:
            pool = await get_db_pool()
            row = await pool.fetchrow(
                """
                SELECT screening_doc_url
                FROM ats.scheduled_interviews
                WHERE application_id = $1
                ORDER BY scheduled_at DESC
                LIMIT 1
                """,
                uuid.UUID(application_id)
            )
            if row and row["screening_doc_url"]:
                doc_url = row["screening_doc_url"]
                logger.info(f"Found existing screening notes doc: {doc_url}")
            else:
                logger.info(f"No screening doc found for application {application_id}")
        except Exception as e:
            logger.warning(f"Failed to look up screening notes doc: {e}")

    # Build Adaptive Card
    card = _build_screening_notification_card(
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        formatted_date=formatted_date,
        summary=summary,
        doc_url=doc_url,
        channel=channel,
    )

    # Send to Teams
    try:
        teams = get_teams_service()
        await teams.send_card_to_channel(
            service_url=TEAMS_ALERTS_SERVICE_URL,
            conversation_id=TEAMS_ALERTS_CONVERSATION_ID,
            card=card,
        )
        logger.info(f"✅ Sent Teams notification for {candidate_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to send Teams card: {e}")
        # Log what we would have sent
        logger.info(
            f"📢 Teams notification (failed to send):\n"
            f"  ✅ Gekwalificeerd + Ingepland\n"
            f"  👤 {candidate_name}\n"
            f"  💼 {vacancy_title}\n"
            f"  📅 {formatted_date}\n"
            f"  📝 {summary[:100] if summary else 'No summary'}\n"
            f"  🔗 Doc: {doc_url or 'N/A'}"
        )
        return False


def _build_screening_notification_card(
    candidate_name: str,
    vacancy_title: str,
    formatted_date: str,
    summary: str,
    doc_url: Optional[str],
    channel: str,
) -> dict:
    """
    Build an Adaptive Card for the screening notification.

    Returns the card JSON structure.
    """
    channel_emoji = "💬" if channel == "whatsapp" else "📞"
    channel_label = "WhatsApp" if channel == "whatsapp" else "Voice"

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "✅ Nieuwe match gevonden!",
                "weight": "Bolder",
                "size": "Large",
                "color": "Good",
            },
            {
                "type": "TextBlock",
                "text": f"Ik heb zojuist een kandidaat gescreend via {channel_label} en een afspraak ingepland in je agenda.",
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "👤 Kandidaat", "value": candidate_name},
                    {"title": "💼 Vacature", "value": vacancy_title},
                    {"title": "📅 Afspraak", "value": formatted_date},
                    {"title": f"{channel_emoji} Kanaal", "value": channel_label},
                ],
                "spacing": "Medium",
            },
        ],
        "actions": [],
    }

    # Add summary if available
    if summary:
        card["body"].append({
            "type": "TextBlock",
            "text": f"📝 **Samenvatting:** {summary[:200]}{'...' if len(summary) > 200 else ''}",
            "wrap": True,
            "spacing": "Medium",
        })

    # Add button to view Google Doc
    if doc_url:
        card["actions"].append({
            "type": "Action.OpenUrl",
            "title": "📄 Bekijk volledige notule",
            "url": doc_url,
        })

    return card
