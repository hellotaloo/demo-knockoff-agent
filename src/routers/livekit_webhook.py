"""
LiveKit Webhook Router - Handle pre-screening v2 voice agent results.

Receives structured call results from the LiveKit agent's _on_session_complete callback.
Maps results to application_answers, updates application status, and advances workflows.
"""
import asyncio
import os
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Header

from src.config import LIVEKIT_WEBHOOK_SECRET
from src.models.livekit import LiveKitCallResultPayload
from src.models import ActivityEventType, ActorType, ActivityChannel
from src.services import ActivityService
from src.services.screening_notes_integration_service import trigger_screening_notes_integration
from src.database import get_db_pool
from src.workflows import get_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/livekit", tags=["LiveKit Webhooks"])

# Map agent knockout result → application_answers.passed
RESULT_TO_PASSED = {
    "pass": True,
    "fail": False,
    "unclear": None,
    "irrelevant": None,
    "recruiter_requested": None,
}


@router.post("/call-result")
async def livekit_call_result(
    payload: LiveKitCallResultPayload,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Receive call results from the pre-screening v2 LiveKit agent.

    The agent POSTs CandidateData.to_dict() here when a session completes.
    This endpoint:
    1. Looks up the screening conversation by call_id
    2. Maps results to application_answers
    3. Updates application status
    4. Fires workflow events
    5. Triggers notifications for qualified candidates
    """
    # Validate webhook secret
    if LIVEKIT_WEBHOOK_SECRET:
        if not x_webhook_secret or x_webhook_secret != LIVEKIT_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    call_id = payload.call_id
    logger.info(f"LiveKit call result received: call_id={call_id}, status={payload.status}")

    pool = await get_db_pool()

    # Look up screening conversation by call_id (stored as session_id)
    screening_conv = await pool.fetchrow(
        """
        SELECT sc.id, sc.pre_screening_id, sc.vacancy_id, sc.candidate_phone,
               sc.candidate_name, sc.is_test, sc.application_id, sc.candidate_id,
               v.title as vacancy_title
        FROM ats.screening_conversations sc
        JOIN ats.vacancies v ON v.id = sc.vacancy_id
        WHERE sc.session_id = $1 AND sc.channel = 'voice'
        """,
        call_id
    )

    if not screening_conv:
        logger.warning(f"No screening conversation found for LiveKit call_id: {call_id}")
        return {"status": "received", "action": "no_conversation_found", "call_id": call_id}

    application_id = screening_conv["application_id"]
    vacancy_id = screening_conv["vacancy_id"]
    candidate_name = screening_conv["candidate_name"] or "Voice Candidate"
    candidate_id = screening_conv["candidate_id"]

    logger.info(f"Processing LiveKit result for vacancy '{screening_conv['vacancy_title']}', application {application_id}")

    # Determine qualification and application status from agent result
    is_abandoned = payload.status in ("voicemail", "incomplete")
    qualified = payload.passed_knockout and payload.status == "completed"
    app_status = "abandoned" if is_abandoned else "completed"

    # Build summary from results
    summary = _build_summary(payload)

    # Store results in transaction
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update application
            if application_id:
                await conn.execute(
                    """
                    UPDATE ats.applications
                    SET qualified = $1, completed_at = NOW(), conversation_id = $2,
                        channel = 'voice', summary = $3, status = $4
                    WHERE id = $5
                    """,
                    qualified,
                    call_id,
                    summary,
                    app_status,
                    application_id
                )
                logger.info(f"Application {application_id} updated: status={app_status}, qualified={qualified}")

                # Store knockout answers
                for answer in payload.knockout_answers:
                    question_id = answer.internal_id or answer.question_id
                    await conn.execute(
                        """
                        INSERT INTO ats.application_answers
                        (application_id, question_id, question_text, answer, passed, source)
                        VALUES ($1, $2, $3, $4, $5, 'voice')
                        """,
                        application_id,
                        question_id,
                        answer.question_text,
                        answer.raw_answer,
                        RESULT_TO_PASSED.get(answer.result),
                    )

                # Store open question answers
                for answer in payload.open_answers:
                    question_id = answer.internal_id or answer.question_id
                    await conn.execute(
                        """
                        INSERT INTO ats.application_answers
                        (application_id, question_id, question_text, answer, source, motivation)
                        VALUES ($1, $2, $3, $4, 'voice', $5)
                        """,
                        application_id,
                        question_id,
                        answer.question_text,
                        answer.answer_summary,
                        answer.candidate_note or "",
                    )

            # Update conversation status
            conv_status = "abandoned" if is_abandoned else "completed"
            await conn.execute(
                """
                UPDATE ats.screening_conversations
                SET status = $1, completed_at = NOW(), updated_at = NOW()
                WHERE session_id = $2 AND channel = 'voice'
                """,
                conv_status,
                call_id,
            )

    # Log activity
    if candidate_id and not is_abandoned:
        activity_service = ActivityService(pool)
        event_type = ActivityEventType.QUALIFIED if qualified else ActivityEventType.DISQUALIFIED
        await activity_service.log(
            candidate_id=str(candidate_id),
            event_type=event_type,
            application_id=str(application_id),
            vacancy_id=str(vacancy_id),
            channel=ActivityChannel.VOICE,
            actor_type=ActorType.AGENT,
            metadata={"agent_status": payload.status},
            summary=f"Pre-screening {'geslaagd' if qualified else 'niet geslaagd'}"
        )

    # Trigger screening notes integration for qualified candidates
    if qualified:
        asyncio.create_task(trigger_screening_notes_integration(
            pool=pool,
            application_id=application_id,
            recruiter_email=os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL"),
        ))
        logger.info(f"Triggered screening notes integration for application {application_id}")

    # Notify workflow orchestrator
    try:
        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", call_id)

        if workflow:
            await orchestrator.handle_event(
                workflow_id=workflow["id"],
                event="screening_completed",
                payload={
                    "qualified": qualified,
                    "interview_slot": payload.chosen_timeslot,
                    "application_id": str(application_id),
                    "summary": summary,
                },
            )
            logger.info(f"Workflow {workflow['id']}: screening_completed event handled")
        else:
            logger.debug(f"No workflow found for call_id {call_id}")
    except Exception as e:
        logger.error(f"Failed to notify workflow orchestrator: {e}")

    return {
        "status": "processed",
        "application_id": str(application_id),
        "qualified": qualified,
        "call_id": call_id,
    }


def _build_summary(payload: LiveKitCallResultPayload) -> str:
    """Build a human-readable summary from agent results."""
    parts = []

    if payload.status == "voicemail":
        return "Voicemail gedetecteerd"
    if payload.status == "incomplete":
        return "Gesprek onvolledig afgerond"
    if payload.status == "escalated":
        return "Kandidaat wil spreken met recruiter"

    # Knockout results
    ko_pass = sum(1 for a in payload.knockout_answers if a.result == "pass")
    ko_fail = sum(1 for a in payload.knockout_answers if a.result == "fail")
    ko_total = len(payload.knockout_answers)
    if ko_total > 0:
        parts.append(f"Knockout: {ko_pass}/{ko_total} geslaagd")

    # Open questions
    oq_count = len(payload.open_answers)
    if oq_count > 0:
        parts.append(f"{oq_count} open {'vraag' if oq_count == 1 else 'vragen'} beantwoord")

    # Scheduling
    if payload.chosen_timeslot:
        parts.append(f"Afspraak: {payload.chosen_timeslot}")
    elif payload.scheduling_preference:
        parts.append(f"Voorkeur: {payload.scheduling_preference}")

    # Status-specific notes
    if payload.status == "knockout_failed":
        if payload.interested_in_alternatives:
            parts.append("Interesse in andere vacatures")
        else:
            parts.append("Knockout niet geslaagd")
    elif payload.status == "not_interested":
        parts.append("Kandidaat niet geinteresseerd")

    return ". ".join(parts) if parts else f"Status: {payload.status}"
