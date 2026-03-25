"""
Vacancy Setup Workflow Handlers

Automates the pipeline from question generation to publication:
  generating → (awaiting_review | publishing) → notifying → complete

Events:
- questions_saved: Fired when recruiter saves pre-screening questions
- recruiter_approved: Recruiter clicks approve on Teams notification
- auto (publishing): Auto-publishes all 3 channels
- auto (notifying): Sends Teams notification with full question list
"""
import logging
import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from src.config import FRONTEND_URL

if TYPE_CHECKING:
    from src.workflows.orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


async def _get_config_setting(dotted_key: str, workspace_id: uuid.UUID, default=None):
    """
    Read a setting from agents.agent_config (pre_screening config).

    Args:
        dotted_key: Dot-separated path, e.g. "publishing.require_review"
        workspace_id: Workspace UUID for tenant-scoped config lookup
        default: Value to return if key is not found
    """
    from src.database import get_db_pool
    from src.repositories.agent_config_repo import AgentConfigRepository
    import json

    try:
        pool = await get_db_pool()
        repo = AgentConfigRepository(pool)
        row = await repo.get_active(workspace_id, "pre_screening")
        if not row:
            return default

        settings = row["settings"] if isinstance(row["settings"], dict) else json.loads(row["settings"])

        # Navigate dotted path: "publishing.require_review" → settings["publishing"]["require_review"]
        for key in dotted_key.split("."):
            if not isinstance(settings, dict) or key not in settings:
                return default
            settings = settings[key]
        return settings
    except Exception as e:
        logger.warning(f"Failed to read config setting '{dotted_key}': {e}")
        return default


# =============================================================================
# STEP CONFIGURATION
# =============================================================================

STEP_CONFIG = {
    "generating": {
        "timeout_seconds": 5 * 60,          # 5 min - question generation
        "stuck_threshold_seconds": 3 * 60,
    },
    "awaiting_review": {
        "timeout_seconds": 24 * 3600,        # 24h SLA for recruiter review
        "stuck_threshold_seconds": 12 * 3600,
    },
    "publishing": {
        "timeout_seconds": 2 * 60,           # 2 min - publish channels
        "stuck_threshold_seconds": 60,
        "auto_delay_seconds": 0,             # Immediate
    },
    "notifying": {
        "timeout_seconds": 2 * 60,           # 2 min - Teams notification
        "stuck_threshold_seconds": 60,
        "auto_delay_seconds": 0,             # Immediate after publishing
    },
    "complete": {
        "timeout_seconds": None,
        "stuck_threshold_seconds": None,
    },
    "timed_out": {
        "timeout_seconds": None,
        "stuck_threshold_seconds": None,
    },
}


# Teams notification channel config (reuse from pre_screening workflow)
TEAMS_ALERTS_SERVICE_URL = os.environ.get(
    "MS_TEAMS_ALERTS_SERVICE_URL",
    "https://smba.trafficmanager.net/emea/a26bd06f-6855-4146-bc95-efcf68a95619/"
)
TEAMS_ALERTS_CONVERSATION_ID = os.environ.get(
    "MS_TEAMS_ALERTS_CONVERSATION_ID",
    "19:201cf6383c2340cd9ff9da60f85d892f@thread.tacv2"
)


# =============================================================================
# HANDLERS
# =============================================================================

async def handle_questions_saved(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Handle questions_saved event - recruiter saved pre-screening questions.

    Payload: {pre_screening_id, vacancy_id}
    Transitions to: awaiting_review (if require_review) or publishing
    """
    from src.database import get_db_pool

    pre_screening_id = payload.get("pre_screening_id")
    vacancy_id = payload.get("vacancy_id")

    logger.info(
        f"Workflow {workflow['id']}: questions_saved "
        f"(ps={pre_screening_id}, vacancy={vacancy_id})"
    )

    await orchestrator.update_context(workflow["id"], {
        "pre_screening_id": pre_screening_id,
        "vacancy_id": vacancy_id,
    })

    # Update agent status to 'generated'
    from src.database import get_db_pool as _get_pool
    from src.repositories import VacancyRepository
    _pool = await _get_pool()
    _vacancy_repo = VacancyRepository(_pool)
    await _vacancy_repo.set_agent_status(uuid.UUID(vacancy_id), "prescreening", "generated")

    # Check if recruiter review is required
    context = workflow["context"]
    require_review = context.get("require_review", False)

    if not require_review:
        pool = await get_db_pool()
        vacancy_uuid = uuid.UUID(vacancy_id)
        ws_row = await pool.fetchrow("SELECT workspace_id FROM ats.vacancies WHERE id = $1", vacancy_uuid)
        workspace_id = ws_row["workspace_id"] if ws_row else None

        if workspace_id:
            require_review = await _get_config_setting("publishing.require_review", workspace_id, default=False)

    if require_review:
        logger.info(f"Workflow {workflow['id']}: require_review=True → awaiting_review")
        await _send_review_teams_notification(workflow, {
            **context,
            "pre_screening_id": pre_screening_id,
            "vacancy_id": vacancy_id,
        })
        return {"next_step": "awaiting_review"}

    logger.info(f"Workflow {workflow['id']}: require_review=False → publishing")
    return {"next_step": "publishing"}


async def handle_recruiter_approved(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Recruiter approved the pre-screening via Teams.

    Transitions to: publishing
    """
    approved_by = payload.get("approved_by", "Recruiter")

    logger.info(f"Workflow {workflow['id']}: recruiter approved by {approved_by}")

    await orchestrator.update_context(workflow["id"], {
        "approved_by": approved_by,
        "approved_at": datetime.utcnow().isoformat(),
    })

    return {"next_step": "publishing"}


async def handle_auto_publish(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Auto-triggered: publish pre-screening on all 3 channels.

    Reuses the same DB logic as POST /vacancies/{id}/pre-screening/publish.
    """
    from src.database import get_db_pool
    from src.repositories.pre_screening_repo import PreScreeningRepository

    context = workflow["context"]
    vacancy_id = context.get("vacancy_id")

    if not vacancy_id:
        logger.error(f"Workflow {workflow['id']}: missing vacancy_id for publish")
        return {"next_step": "complete", "new_status": "completed", "error": "missing_vacancy_id"}

    pool = await get_db_pool()
    ps_repo = PreScreeningRepository(pool)

    vacancy_uuid = uuid.UUID(vacancy_id)
    ps_row = await ps_repo.get_for_vacancy(vacancy_uuid)

    if not ps_row:
        logger.error(f"Workflow {workflow['id']}: no pre-screening found for vacancy {vacancy_id}")
        return {"next_step": "complete", "new_status": "completed", "error": "no_pre_screening"}

    pre_screening_id = ps_row["id"]

    # Resolve workspace_id from vacancy for tenant-scoped config
    ws_row = await pool.fetchrow("SELECT workspace_id FROM ats.vacancies WHERE id = $1", vacancy_uuid)
    workspace_id = ws_row["workspace_id"] if ws_row else None

    # Get default channels from agent config (publishing section, with fallback to general for backwards compat)
    default_channels_default = {"voice": True, "whatsapp": True, "cv": True}
    default_channels = None
    if workspace_id:
        default_channels = await _get_config_setting("publishing.default_channels", workspace_id, default=None)
        if default_channels is None:
            default_channels = await _get_config_setting("general.default_channels", workspace_id, default=None)
    if default_channels is None:
        default_channels = default_channels_default
    voice_enabled = default_channels.get("voice", True)
    whatsapp_enabled = default_channels.get("whatsapp", True)
    cv_enabled = default_channels.get("cv", True)

    published_at = datetime.utcnow()
    whatsapp_agent_id = vacancy_id if whatsapp_enabled else None

    enabled_channels = [ch for ch, on in [("voice", voice_enabled), ("whatsapp", whatsapp_enabled), ("cv", cv_enabled)] if on]
    logger.info(f"Workflow {workflow['id']}: publishing pre-screening ({', '.join(enabled_channels)})")

    await ps_repo.update_publish_state(
        pre_screening_id,
        published_at,
        elevenlabs_agent_id=None,  # Voice uses master agent from env
        whatsapp_agent_id=whatsapp_agent_id,
        voice_enabled=voice_enabled,
        whatsapp_enabled=whatsapp_enabled,
        cv_enabled=cv_enabled,
    )

    # Register prescreening agent in vacancy_agents table
    from src.repositories import VacancyRepository as _VacancyRepository
    va_repo = _VacancyRepository(pool)
    await va_repo.ensure_agent_registered(vacancy_uuid, "prescreening", status="published")

    await orchestrator.update_context(workflow["id"], {
        "published_at": published_at.isoformat(),
        "channels": enabled_channels,
    })

    logger.info(f"Workflow {workflow['id']}: published successfully → notifying")

    return {"next_step": "notifying"}


# =============================================================================
# REVIEW NOTIFICATION
# =============================================================================

async def _send_review_teams_notification(
    workflow: dict,
    context: dict,
) -> bool:
    """
    Send Adaptive Card to Teams asking recruiter to review the pre-screening.

    Card includes vacancy title, approve action button, and link to pre-screening page.
    """
    from src.services.teams_service import get_teams_service

    vacancy_title = context.get("vacancy_title", "Onbekende vacature")
    vacancy_id = context.get("vacancy_id", "")

    review_url = f"{FRONTEND_URL}/pre-screening/detail/{vacancy_id}?mode=dashboard"

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "📋 Pre-screening klaar voor review",
                "weight": "Bolder",
                "size": "Large",
            },
            {
                "type": "TextBlock",
                "text": f"De interviewvragen voor **{vacancy_title}** zijn gegenereerd en klaar voor beoordeling.",
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "💼 Vacature", "value": vacancy_title},
                ],
                "spacing": "Medium",
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "📄 Bekijk pre-screening",
                "url": review_url,
            },
            {
                "type": "Action.Submit",
                "title": "✅ Goedkeuren & publiceren",
                "data": {
                    "action": "approve_vacancy_setup",
                    "workflow_id": workflow["id"],
                    "vacancy_id": vacancy_id,
                },
            },
        ],
    }

    try:
        teams = get_teams_service()
        await teams.send_card_to_channel(
            service_url=TEAMS_ALERTS_SERVICE_URL,
            conversation_id=TEAMS_ALERTS_CONVERSATION_ID,
            card=card,
        )
        logger.info(f"Workflow {workflow['id']}: Teams review notification sent")
        return True
    except Exception as e:
        logger.error(f"Workflow {workflow['id']}: failed to send Teams notification: {e}")
        return False


# =============================================================================
# PUBLISHED NOTIFICATION
# =============================================================================

async def handle_send_published_notification(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Auto-triggered after publishing: send Teams notification with full question list.

    Non-blocking — if Teams send fails, we log and still complete the workflow.
    """
    from src.database import get_db_pool
    from src.repositories.pre_screening_repo import PreScreeningRepository
    from src.services.teams_service import get_teams_service

    context = workflow["context"]
    vacancy_id = context.get("vacancy_id", "")
    vacancy_title = context.get("vacancy_title", "Onbekende vacature")
    pre_screening_id = context.get("pre_screening_id")
    source = context.get("source", "manual")

    # Load questions from DB
    knockout_questions = []
    qualification_questions = []

    if pre_screening_id:
        try:
            pool = await get_db_pool()
            ps_repo = PreScreeningRepository(pool)
            question_rows = await ps_repo.get_questions(uuid.UUID(pre_screening_id))

            for q in question_rows:
                if q["question_type"] == "knockout":
                    knockout_questions.append(q["question_text"])
                else:
                    qualification_questions.append(q["question_text"])
        except Exception as e:
            logger.warning(f"Workflow {workflow['id']}: failed to load questions for notification: {e}")

    # Build and send card
    channels = context.get("channels", ["voice", "whatsapp", "cv"])
    card = _build_published_card(
        vacancy_title=vacancy_title,
        vacancy_id=vacancy_id,
        source=source,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        channels=channels,
    )

    try:
        teams = get_teams_service()
        await teams.send_card_to_channel(
            service_url=TEAMS_ALERTS_SERVICE_URL,
            conversation_id=TEAMS_ALERTS_CONVERSATION_ID,
            card=card,
        )
        logger.info(f"Workflow {workflow['id']}: Teams published notification sent for '{vacancy_title}'")
    except Exception as e:
        logger.error(f"Workflow {workflow['id']}: failed to send Teams published notification: {e}")
        ko_count = len(knockout_questions)
        qual_count = len(qualification_questions)
        logger.info(
            f"Teams notification (failed to send):\n"
            f"  Vacature: {vacancy_title}\n"
            f"  Vragen: {ko_count} knockout + {qual_count} kwalificatie"
        )

    return {
        "next_step": "complete",
        "new_status": "completed",
    }


def _channel_labels(channels: list[str]) -> list[str]:
    """Map channel keys to Dutch display labels."""
    labels = {"voice": "Telefoon", "whatsapp": "WhatsApp", "cv": "Smart CV"}
    return [labels.get(ch, ch) for ch in channels]


def _build_published_card(
    vacancy_title: str,
    vacancy_id: str,
    source: str,
    knockout_questions: list[str],
    qualification_questions: list[str],
    channels: list[str] | None = None,
) -> dict:
    """Build an Adaptive Card for the pre-screening published notification."""
    ko_count = len(knockout_questions)
    qual_count = len(qualification_questions)
    total = ko_count + qual_count
    source_label = "ATS Import" if source == "ats_import" else "Handmatig"

    review_url = f"{FRONTEND_URL}/pre-screening/detail/{vacancy_id}?mode=dashboard"

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "Pre-screening gepubliceerd",
                "weight": "Bolder",
                "size": "Large",
                "color": "Good",
            },
            {
                "type": "TextBlock",
                "text": f"De pre-screening voor **{vacancy_title}** is live met {total} vragen.",
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Vacature", "value": vacancy_title},
                    {"title": "Kanalen", "value": ", ".join(_channel_labels(channels or ["voice", "whatsapp", "cv"]))},
                    {"title": "Bron", "value": source_label},
                ],
                "spacing": "Medium",
            },
        ],
        "actions": [],
    }

    # Knockout questions section
    if knockout_questions:
        card["body"].append({
            "type": "TextBlock",
            "text": "Knockout vragen",
            "weight": "Bolder",
            "spacing": "Medium",
        })
        for i, q in enumerate(knockout_questions, 1):
            card["body"].append({
                "type": "TextBlock",
                "text": f"{i}. {q}",
                "wrap": True,
                "spacing": "None" if i > 1 else "Small",
            })

    # Qualification questions section
    if qualification_questions:
        card["body"].append({
            "type": "TextBlock",
            "text": "Kwalificatievragen",
            "weight": "Bolder",
            "spacing": "Medium",
        })
        for i, q in enumerate(qualification_questions, 1):
            card["body"].append({
                "type": "TextBlock",
                "text": f"{i}. {q}",
                "wrap": True,
                "spacing": "None" if i > 1 else "Small",
            })

    # Action: Open pre-screening page
    card["actions"].append({
        "type": "Action.OpenUrl",
        "title": "Beheer pre-screening",
        "url": review_url,
    })

    return card
