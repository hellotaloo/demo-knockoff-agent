"""
Vacancy Setup Workflow Handlers

Automates the pipeline from question generation to publication:
  generating → analyzing → (awaiting_review | publishing) → notifying → complete

Events:
- questions_saved: Fired when recruiter saves pre-screening questions
- auto (analyzing): Runs interview analysis agent
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

# =============================================================================
# STEP CONFIGURATION
# =============================================================================

STEP_CONFIG = {
    "generating": {
        "timeout_seconds": 5 * 60,          # 5 min - question generation
        "stuck_threshold_seconds": 3 * 60,
    },
    "analyzing": {
        "timeout_seconds": 2 * 60,          # 2 min - analysis agent
        "stuck_threshold_seconds": 60,
        "auto_delay_seconds": 0,             # Immediate
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
    Transitions to: analyzing
    """
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

    return {"next_step": "analyzing"}


async def handle_run_analysis(
    orchestrator: "WorkflowOrchestrator",
    workflow: dict,
    payload: dict,
) -> dict:
    """
    Auto-triggered: run interview analysis agent.

    Loads questions and vacancy from DB, runs analysis, decides next step:
    - verdict == "poor" → awaiting_review (Teams notification)
    - context has require_review → awaiting_review (Teams notification)
    - otherwise → publishing
    """
    from interview_analysis_agent import analyze_interview
    from src.database import get_db_pool
    from src.repositories.pre_screening_repo import PreScreeningRepository
    from src.repositories.vacancy_repo import VacancyRepository

    context = workflow["context"]
    vacancy_id = context.get("vacancy_id")
    pre_screening_id = context.get("pre_screening_id")

    if not vacancy_id or not pre_screening_id:
        logger.error(f"Workflow {workflow['id']}: missing vacancy_id or pre_screening_id in context")
        return {"next_step": "complete", "new_status": "completed", "error": "missing_context"}

    pool = await get_db_pool()
    ps_repo = PreScreeningRepository(pool)
    vacancy_repo = VacancyRepository(pool)

    # Load vacancy info
    vacancy_row = await vacancy_repo.get_basic_info(uuid.UUID(vacancy_id))
    vacancy_title = vacancy_row["title"] if vacancy_row else "Onbekende vacature"
    vacancy_description = (vacancy_row["description"] or "") if vacancy_row else ""

    # Load questions with ko_N/qual_N ID mapping
    ps_uuid = uuid.UUID(pre_screening_id)
    question_rows = await ps_repo.get_questions(ps_uuid)

    if not question_rows:
        logger.warning(f"Workflow {workflow['id']}: no questions found, skipping analysis")
        return {"next_step": "publishing"}

    questions = []
    ko_counter = 1
    qual_counter = 1
    for q in question_rows:
        if q["question_type"] == "knockout":
            q_id = f"ko_{ko_counter}"
            ko_counter += 1
            q_type = "knockout"
        else:
            q_id = f"qual_{qual_counter}"
            qual_counter += 1
            q_type = "qualifying"
        questions.append({"id": q_id, "text": q["question_text"], "type": q_type})

    # Run analysis agent
    logger.info(f"Workflow {workflow['id']}: running analysis on {len(questions)} questions")

    try:
        result = await analyze_interview(
            questions=questions,
            vacancy_title=vacancy_title,
            vacancy_description=vacancy_description,
        )
    except Exception as e:
        logger.error(f"Workflow {workflow['id']}: analysis agent failed: {e}")
        # Don't block the pipeline on analysis failure - proceed to publishing
        await orchestrator.update_context(workflow["id"], {
            "analysis_error": str(e),
        })
        return {"next_step": "publishing"}

    # Save analysis result to DB
    try:
        await ps_repo.save_analysis_result(ps_uuid, result)
        logger.info(f"Workflow {workflow['id']}: analysis result saved")
    except Exception as e:
        logger.warning(f"Workflow {workflow['id']}: failed to save analysis result: {e}")

    # Extract verdict info
    summary = result.get("summary", {})
    verdict = summary.get("verdict", "good")
    one_liner = summary.get("oneLiner", "")
    completion_rate = summary.get("completionRate", 0)

    await orchestrator.update_context(workflow["id"], {
        "verdict": verdict,
        "oneLiner": one_liner,
        "completionRate": completion_rate,
    })

    # Decision: does this need recruiter review?
    require_review = context.get("require_review", False)

    if verdict == "poor":
        logger.info(f"Workflow {workflow['id']}: verdict=poor → awaiting_review")
        await _send_review_teams_notification(workflow, context, result, is_poor=True)
        return {"next_step": "awaiting_review"}

    if require_review:
        logger.info(f"Workflow {workflow['id']}: require_review=True → awaiting_review")
        await _send_review_teams_notification(workflow, context, result, is_poor=False)
        return {"next_step": "awaiting_review"}

    logger.info(f"Workflow {workflow['id']}: verdict={verdict} → publishing")
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

    # Publish with all 3 channels enabled
    published_at = datetime.utcnow()
    whatsapp_agent_id = vacancy_id  # WhatsApp agent uses vacancy_id as identifier

    logger.info(f"Workflow {workflow['id']}: publishing pre-screening (voice, whatsapp, cv)")

    await ps_repo.update_publish_state(
        pre_screening_id,
        published_at,
        elevenlabs_agent_id=None,  # Voice uses master agent from env
        whatsapp_agent_id=whatsapp_agent_id,
        is_online=True,
        voice_enabled=True,
        whatsapp_enabled=True,
        cv_enabled=True,
    )

    await orchestrator.update_context(workflow["id"], {
        "published_at": published_at.isoformat(),
        "channels": ["voice", "whatsapp", "cv"],
    })

    logger.info(f"Workflow {workflow['id']}: published successfully → notifying")

    return {"next_step": "notifying"}


# =============================================================================
# TEAMS NOTIFICATION
# =============================================================================

async def _send_review_teams_notification(
    workflow: dict,
    context: dict,
    analysis_result: dict,
    is_poor: bool,
) -> bool:
    """
    Send Adaptive Card to Teams asking recruiter to review the pre-screening.

    Card includes:
    - Vacancy title, verdict, oneLiner
    - completionRate stat
    - Approve action button
    - Link to pre-screening page
    """
    from src.services.teams_service import get_teams_service

    vacancy_title = context.get("vacancy_title", "Onbekende vacature")
    vacancy_id = context.get("vacancy_id", "")
    summary = analysis_result.get("summary", {})
    verdict = summary.get("verdict", "unknown")
    verdict_headline = summary.get("verdictHeadline", "")
    one_liner = summary.get("oneLiner", "")
    completion_rate = summary.get("completionRate", 0)

    # Build card
    card = _build_review_card(
        workflow_id=workflow["id"],
        vacancy_title=vacancy_title,
        vacancy_id=vacancy_id,
        verdict=verdict,
        verdict_headline=verdict_headline,
        one_liner=one_liner,
        completion_rate=completion_rate,
        is_poor=is_poor,
    )

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
        logger.info(
            f"📢 Teams notification (failed to send):\n"
            f"  💼 {vacancy_title}\n"
            f"  📊 Verdict: {verdict}\n"
            f"  📝 {one_liner}"
        )
        return False


def _build_review_card(
    workflow_id: str,
    vacancy_title: str,
    vacancy_id: str,
    verdict: str,
    verdict_headline: str,
    one_liner: str,
    completion_rate: int,
    is_poor: bool,
) -> dict:
    """Build an Adaptive Card for the recruiter review notification."""
    # Title styling based on severity
    if is_poor:
        title_text = "⚠️ Pre-screening vereist review"
        title_color = "Attention"
        subtitle = "De analyse heeft problemen gevonden met de interviewvragen."
    else:
        title_text = "📋 Pre-screening klaar voor review"
        title_color = "Default"
        subtitle = "De interviewvragen zijn geanalyseerd en klaar voor beoordeling."

    # Frontend URL for the pre-screening page
    review_url = f"{FRONTEND_URL}/pre-screening/detail/{vacancy_id}?mode=dashboard"

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": title_text,
                "weight": "Bolder",
                "size": "Large",
                "color": title_color,
            },
            {
                "type": "TextBlock",
                "text": subtitle,
                "wrap": True,
                "spacing": "Small",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "💼 Vacature", "value": vacancy_title},
                    {"title": "📊 Verdict", "value": verdict_headline or verdict},
                    {"title": "📈 Verwachte voltooiing", "value": f"{completion_rate}%"},
                ],
                "spacing": "Medium",
            },
        ],
        "actions": [],
    }

    # Add one-liner summary
    if one_liner:
        card["body"].append({
            "type": "TextBlock",
            "text": f"📝 {one_liner}",
            "wrap": True,
            "spacing": "Medium",
        })

    # Action: Open pre-screening page in browser
    card["actions"].append({
        "type": "Action.OpenUrl",
        "title": "📄 Bekijk pre-screening",
        "url": review_url,
    })

    # Action: Approve and publish (sends invoke back to webhook)
    card["actions"].append({
        "type": "Action.Submit",
        "title": "✅ Goedkeuren & publiceren",
        "data": {
            "action": "approve_vacancy_setup",
            "workflow_id": workflow_id,
            "vacancy_id": vacancy_id,
        },
    })

    return card


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
    card = _build_published_card(
        vacancy_title=vacancy_title,
        vacancy_id=vacancy_id,
        source=source,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
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


def _build_published_card(
    vacancy_title: str,
    vacancy_id: str,
    source: str,
    knockout_questions: list[str],
    qualification_questions: list[str],
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
                    {"title": "Kanalen", "value": "WhatsApp, Phone, Smart CV"},
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
