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

from src.services.whatsapp_service import send_whatsapp_message, send_whatsapp_template

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
        "timeout_seconds": 15 * 60,        # 15 minutes - notifications may take a few minutes
        "stuck_threshold_seconds": 10 * 60,  # 10 minutes - flag if stuck for this long
        "auto_delay_seconds": 10,          # 10 second delay before sending notifications
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

    # Advance candidacy stage based on screening outcome
    candidate_id_str = context.get("candidate_id")
    vacancy_id_str = context.get("vacancy_id")
    if candidate_id_str and vacancy_id_str:
        try:
            await _advance_candidacy_after_screening(
                workflow_id=workflow["id"],
                candidate_id_str=candidate_id_str,
                vacancy_id_str=vacancy_id_str,
                qualified=qualified,
                interview_slot=interview_slot,
                application_id=application_id,
                channel=channel,
            )
        except Exception as e:
            logger.error(f"Workflow {workflow['id']}: failed to advance candidacy stage: {e}")

    return {
        "next_step": "processed",
        "qualified": qualified,
        "interview_slot": interview_slot,
    }


async def _advance_candidacy_after_screening(
    workflow_id: str,
    candidate_id_str: str,
    vacancy_id_str: str,
    qualified: bool,
    interview_slot: Optional[str],
    application_id: Optional[str],
    channel: str,
) -> None:
    """
    Advance candidacy pipeline based on screening outcome.

    Three cases:
    1. Passed + interview booked  → INTERVIEW_PLANNED on current vacancy
    2. Passed + no interview slot → QUALIFIED on current vacancy
    3. Not passed                 → Move candidacy to "Open Sollicitatie" as QUALIFIED
    """
    from src.database import get_db_pool
    from src.models.candidacy import CandidacyStage
    from src.repositories.candidacy_repo import CandidacyRepository
    from src.services.candidacy_transition_service import CandidacyStageTransitionService

    pool = await get_db_pool()
    candidacy_repo = CandidacyRepository(pool)
    transition_service = CandidacyStageTransitionService(pool)

    candidacy = await candidacy_repo.find_by_candidate_and_vacancy(
        uuid.UUID(candidate_id_str), uuid.UUID(vacancy_id_str)
    )
    if not candidacy:
        logger.debug(
            f"Workflow {workflow_id}: no candidacy found for "
            f"candidate={candidate_id_str} vacancy={vacancy_id_str}, skipping stage transition"
        )
        return

    meta = {"application_id": application_id, "channel": channel}

    if qualified and interview_slot:
        # Case 1: passed + interview booked → INTERVIEW_PLANNED
        await transition_service.transition(
            candidacy_id=candidacy["id"],
            to_stage=CandidacyStage.INTERVIEW_PLANNED,
            triggered_by="pre_screening_agent",
            metadata={**meta, "interview_slot": interview_slot},
        )
        logger.info(f"Workflow {workflow_id}: candidacy → INTERVIEW_PLANNED")

    elif qualified and not interview_slot:
        # Case 2: passed but no timeslot match → QUALIFIED (recruiter schedules manually)
        await transition_service.transition(
            candidacy_id=candidacy["id"],
            to_stage=CandidacyStage.QUALIFIED,
            triggered_by="pre_screening_agent",
            metadata={**meta, "reason": "no_matching_timeslot"},
        )
        logger.info(f"Workflow {workflow_id}: candidacy → QUALIFIED (no timeslot)")

    else:
        # Case 3: not passed → move to "Open Sollicitatie" as QUALIFIED
        open_vacancy = await pool.fetchrow(
            """
            SELECT id FROM ats.vacancies
            WHERE workspace_id = $1 AND is_open_application = true
            LIMIT 1
            """,
            candidacy["workspace_id"],
        )
        if open_vacancy:
            # Check if candidate already has a candidacy on Open Sollicitatie
            existing = await candidacy_repo.exists_for_vacancy(
                uuid.UUID(candidate_id_str), open_vacancy["id"]
            )
            if existing:
                logger.info(
                    f"Workflow {workflow_id}: candidate already has Open Sollicitatie candidacy, "
                    f"transitioning current candidacy to REJECTED"
                )
                await transition_service.transition(
                    candidacy_id=candidacy["id"],
                    to_stage=CandidacyStage.REJECTED,
                    triggered_by="pre_screening_agent",
                    metadata={**meta, "reason": "not_passed_already_in_open_pool"},
                )
            else:
                # Move candidacy to Open Sollicitatie + transition to QUALIFIED
                await candidacy_repo.reassign_vacancy(candidacy["id"], open_vacancy["id"])
                await transition_service.transition(
                    candidacy_id=candidacy["id"],
                    to_stage=CandidacyStage.QUALIFIED,
                    triggered_by="pre_screening_agent",
                    metadata={**meta, "reason": "not_passed_moved_to_open_pool"},
                )
                logger.info(f"Workflow {workflow_id}: candidacy → QUALIFIED on Open Sollicitatie")
        else:
            # No Open Sollicitatie vacancy found — reject on current vacancy
            logger.warning(f"Workflow {workflow_id}: no Open Sollicitatie vacancy found, rejecting")
            await transition_service.transition(
                candidacy_id=candidacy["id"],
                to_stage=CandidacyStage.REJECTED,
                triggered_by="pre_screening_agent",
                metadata={**meta, "reason": "not_passed_no_open_vacancy"},
            )


async def handle_screening_timeout(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Handle pre-screening timeout (candidate abandoned or failed to complete).

    Transitions candidacy to REJECTED on the current vacancy.
    """
    context = workflow["context"]
    candidate_id_str = context.get("candidate_id")
    vacancy_id_str = context.get("vacancy_id")
    channel = context.get("channel", "unknown")

    logger.info(f"Workflow {workflow['id']}: screening timed out (channel={channel})")

    if candidate_id_str and vacancy_id_str:
        try:
            from src.database import get_db_pool
            from src.models.candidacy import CandidacyStage
            from src.repositories.candidacy_repo import CandidacyRepository
            from src.services.candidacy_transition_service import CandidacyStageTransitionService

            pool = await get_db_pool()
            candidacy_repo = CandidacyRepository(pool)
            transition_service = CandidacyStageTransitionService(pool)

            candidacy = await candidacy_repo.find_by_candidate_and_vacancy(
                uuid.UUID(candidate_id_str), uuid.UUID(vacancy_id_str)
            )
            if candidacy:
                await transition_service.transition(
                    candidacy_id=candidacy["id"],
                    to_stage=CandidacyStage.WITHDRAWN,
                    triggered_by="pre_screening_timeout",
                    metadata={"channel": channel, "reason": "screening_abandoned"},
                )
                logger.info(f"Workflow {workflow['id']}: candidacy → WITHDRAWN (timeout)")
        except Exception as e:
            logger.error(f"Workflow {workflow['id']}: failed to reject candidacy on timeout: {e}")

    return {
        "next_step": "timed_out",
        "new_status": "timed_out",
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

    # Send WhatsApp confirmation to candidate (voice channel only — WhatsApp agent already confirms inline)
    channel = context.get("channel", "unknown")
    vacancy_id = context.get("vacancy_id", "")
    if candidate_phone and channel != "whatsapp":
        try:
            whatsapp_sent = await _send_appointment_confirmation_whatsapp(
                phone=candidate_phone,
                candidate_name=candidate_name,
                interview_slot=interview_slot,
                vacancy_id=vacancy_id,
            )
            if whatsapp_sent:
                notifications_sent.append("whatsapp")
                logger.info(f"Workflow {workflow['id']}: sent WhatsApp confirmation")
        except Exception as e:
            logger.error(f"Workflow {workflow['id']}: failed to send WhatsApp: {e}")
    elif channel == "whatsapp":
        logger.info(f"Workflow {workflow['id']}: skipping WhatsApp confirmation (agent already confirmed inline)")

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
    vacancy_id: str = "",
) -> bool:
    """
    Send appointment confirmation via WhatsApp using a Twilio content template.

    Falls back to a plain text message if the template SID is not configured.

    Args:
        phone: Candidate phone number
        candidate_name: Candidate's name
        interview_slot: ISO datetime or human-readable slot string
        vacancy_id: Vacancy UUID (used to look up office location)

    Returns:
        True if message was sent successfully
    """
    from src.config import TWILIO_TEMPLATE_INTERVIEW_CONFIRMATION
    from src.database import get_db_pool

    # Parse interview slot for display (Dutch human-friendly format)
    DUTCH_DAYS = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
    DUTCH_MONTHS = ["januari", "februari", "maart", "april", "mei", "juni",
                    "juli", "augustus", "september", "oktober", "november", "december"]
    try:
        dt = datetime.fromisoformat(interview_slot.replace("Z", "+00:00"))
        day_name = DUTCH_DAYS[dt.weekday()]
        month_name = DUTCH_MONTHS[dt.month - 1]
        if dt.minute == 0:
            time_str = f"{dt.hour} uur"
        else:
            time_str = f"{dt.hour}:{dt.minute:02d}"
        slot_display = f"{day_name} {dt.day} {month_name} om {time_str}"
    except Exception:
        slot_display = interview_slot

    first_name = candidate_name.split()[0] if candidate_name else "daar"

    # Look up office location from vacancy
    location_name = ""
    location_address = ""
    if vacancy_id:
        try:
            pool = await get_db_pool()
            row = await pool.fetchrow(
                """
                SELECT ol.name, ol.address
                FROM ats.vacancies v
                JOIN ats.office_locations ol ON ol.id = v.office_location_id
                WHERE v.id = $1
                """,
                uuid.UUID(vacancy_id),
            )
            if row:
                location_name = row["name"]
                location_address = row["address"]
        except Exception as e:
            logger.warning(f"Failed to look up office location for vacancy {vacancy_id}: {e}")

    # Try content template first
    if TWILIO_TEMPLATE_INTERVIEW_CONFIRMATION:
        content_variables = {
            "1": first_name,
            "2": slot_display,
            "3": location_name or "Ons kantoor",
            "4": location_address or "",
        }
        message_sid = await send_whatsapp_template(
            to_phone=phone,
            content_sid=TWILIO_TEMPLATE_INTERVIEW_CONFIRMATION,
            content_variables=content_variables,
        )
        return message_sid is not None

    # Fallback: plain text (no template configured) — mirrors the Twilio template copy
    location_line = f"\n📍 {location_name}, {location_address}" if location_name else ""
    message = (
        f"Hallo {first_name},\n\n"
        f"Je sollicitatiegesprek is bevestigd! 🎉\n\n"
        f"📅 {slot_display}{location_line}\n\n"
        f"Tip: neem je identiteitskaart mee!\n\n"
        f"Kun je toch niet? Geen probleem, stuur ons tijdig een berichtje via deze chat om je afspraak te verzetten.\n\n"
        f"Veel succes,\nAnna van Its You"
    )
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

    # Look up existing Google Doc URL and screening stats
    doc_url = None
    knockout_stats = ""
    qualification_stats = ""
    if application_id:
        pool = await get_db_pool()
        app_uuid = uuid.UUID(application_id)

        # Look up Google Doc URL (column may not exist yet)
        try:
            row = await pool.fetchrow(
                """
                SELECT screening_doc_url
                FROM ats.scheduled_interviews
                WHERE application_id = $1
                ORDER BY scheduled_at DESC
                LIMIT 1
                """,
                app_uuid,
            )
            if row and row["screening_doc_url"]:
                doc_url = row["screening_doc_url"]
        except Exception as e:
            logger.debug(f"Could not look up screening_doc_url: {e}")

        # Fetch knockout + qualification stats
        try:
            stats_rows = await pool.fetch(
                """
                SELECT aa.passed, aa.score,
                       COALESCE(psq.question_type, 'qualification') AS question_type
                FROM agents.pre_screening_answers aa
                LEFT JOIN agents.pre_screening_questions psq ON psq.id::text = aa.question_id
                WHERE aa.application_id = $1
                """,
                app_uuid,
            )
            ko_total = 0
            ko_passed = 0
            qual_scores = []
            for sr in stats_rows:
                if sr["question_type"] == "knockout":
                    ko_total += 1
                    if sr["passed"] is True:
                        ko_passed += 1
                else:
                    if sr["score"] is not None:
                        qual_scores.append(sr["score"])
            if ko_total:
                knockout_stats = f"\u2705 Knockoutvragen: {ko_passed}/{ko_total}"
            if qual_scores:
                avg = round(sum(qual_scores) / len(qual_scores))
                qualification_stats = f"\U0001f4ca Kwalificatievragen: {avg}%"
        except Exception as e:
            logger.warning(f"Failed to look up screening stats: {e}")

    # Build Adaptive Card
    card = _build_screening_notification_card(
        candidate_name=candidate_name,
        vacancy_title=vacancy_title,
        formatted_date=formatted_date,
        summary=summary,
        doc_url=doc_url,
        channel=channel,
        knockout_stats=knockout_stats,
        qualification_stats=qualification_stats,
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
    knockout_stats: str = "",
    qualification_stats: str = "",
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
                "text": "📅 Nieuw interview gepland",
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

    # Add screening results summary
    results_parts = []
    if knockout_stats:
        results_parts.append(knockout_stats)
    if qualification_stats:
        results_parts.append(qualification_stats)
    if results_parts:
        card["body"].append({
            "type": "TextBlock",
            "text": "  \n".join(results_parts),
            "wrap": True,
            "spacing": "Medium",
        })

    # Add executive summary if available
    if summary:
        card["body"].append({
            "type": "TextBlock",
            "text": f"📝 **Samenvatting:** {summary[:200]}{'...' if len(summary) > 200 else ''}",
            "wrap": True,
            "spacing": "Medium",
        })

    # Add buttons
    card["actions"].append({
        "type": "Action.OpenUrl",
        "title": "🔍 Bekijk details",
        "url": "https://taloo.be",
    })
    if doc_url:
        card["actions"].append({
            "type": "Action.OpenUrl",
            "title": "📄 Bekijk notule",
            "url": doc_url,
        })

    return card
