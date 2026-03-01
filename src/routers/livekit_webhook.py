"""
LiveKit Webhook Router - Handle pre-screening v2 voice agent results.

Receives structured call results from the LiveKit agent's _on_session_complete callback.
Maps results to application_answers, stores conversation transcript, updates application
status, and triggers the shared post-processor for AI scoring + summary.
"""
import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Header

from src.config import LIVEKIT_WEBHOOK_SECRET
from src.models.livekit import LiveKitCallResultPayload
from src.models import ActivityEventType, ActorType, ActivityChannel
from src.services import ActivityService
from src.services.call_result_processor import process_call_results
from src.database import get_db_pool

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
    2. Stores raw results (knockout pass/fail, open answers) in application_answers
    3. Stores conversation transcript in conversation_messages
    4. Updates application status
    5. Triggers shared post-processor for AI scoring + summary + downstream events
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
    logger.info(f"Payload: knockout_answers={len(payload.knockout_answers)}, open_answers={len(payload.open_answers)}, transcript={len(payload.transcript)}")
    for ka in payload.knockout_answers:
        logger.info(f"  KO answer: qid={ka.question_id}, internal_id={ka.internal_id}, result={ka.result}, answer={ka.raw_answer[:80]}")
    for oa in payload.open_answers:
        logger.info(f"  Open answer: qid={oa.question_id}, internal_id={oa.internal_id}, summary={oa.answer_summary[:80]}")

    # Determine qualification and application status from agent result
    is_abandoned = payload.status in ("voicemail", "incomplete")
    qualified = payload.passed_knockout and payload.status == "completed"
    app_status = "abandoned" if is_abandoned else "processing"

    # Build interview_slot from payload scheduling data
    interview_slot = None
    if payload.chosen_timeslot and payload.scheduled_date:
        from datetime import datetime as dt_cls
        from zoneinfo import ZoneInfo
        try:
            time_str = (payload.scheduled_time or "").lower().replace(" uur", "").replace("uur", "").replace("u", "").replace(":", "")
            hour = int(time_str[:2]) if len(time_str) >= 2 else int(time_str)
            tz = ZoneInfo("Europe/Brussels")
            slot_dt = dt_cls.combine(
                dt_cls.strptime(payload.scheduled_date, "%Y-%m-%d").date(),
                dt_cls.min.time(), tzinfo=tz,
            ).replace(hour=hour)
            interview_slot = slot_dt.isoformat()
        except Exception as e:
            logger.warning(f"Could not parse interview slot: {e}")
            interview_slot = f"{payload.scheduled_date} {payload.scheduled_time}"

    # Store results in transaction
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update application (placeholder summary — post-processor will overwrite)
            if application_id:
                await conn.execute(
                    """
                    UPDATE ats.applications
                    SET qualified = $1, completed_at = NOW(), conversation_id = $2,
                        channel = 'voice', summary = $3, status = $4,
                        interview_slot = $5,
                        interaction_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::int
                    WHERE id = $6
                    """,
                    qualified,
                    call_id,
                    "Verwerken...",
                    app_status,
                    interview_slot,
                    application_id
                )
                logger.info(f"Application {application_id} updated: status={app_status}, qualified={qualified}, interview_slot={interview_slot}")

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

            # Store conversation transcript
            for msg in payload.transcript:
                await conn.execute(
                    """
                    INSERT INTO ats.conversation_messages (conversation_id, role, message)
                    VALUES ($1, $2, $3)
                    """,
                    screening_conv["id"],
                    "user" if msg.role == "user" else "agent",
                    msg.message,
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

            # Store scheduled interview if a timeslot was booked
            if payload.chosen_timeslot and payload.scheduled_date:
                from datetime import date as date_type
                try:
                    selected_date = date_type.fromisoformat(payload.scheduled_date)
                except ValueError:
                    selected_date = None
                    logger.warning(f"Could not parse scheduled_date: {payload.scheduled_date}")

                if selected_date:
                    await conn.execute(
                        """
                        INSERT INTO ats.scheduled_interviews
                        (vacancy_id, application_id, conversation_id, candidate_name,
                         candidate_phone, selected_date, selected_time, selected_slot_text,
                         calendar_event_id, channel, candidate_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'voice', $10)
                        """,
                        vacancy_id,
                        application_id,
                        str(screening_conv["id"]),
                        candidate_name,
                        screening_conv["candidate_phone"],
                        selected_date,
                        payload.scheduled_time or "",
                        payload.chosen_timeslot,
                        payload.calendar_event_id,
                        candidate_id,
                    )
                    logger.info(f"Scheduled interview saved: date={selected_date}, calendar_event={payload.calendar_event_id}")

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

    # Trigger post-processor as background task (scoring + summary + downstream)
    if application_id and not is_abandoned and screening_conv["pre_screening_id"]:
        asyncio.create_task(process_call_results(
            application_id=application_id,
            pre_screening_id=screening_conv["pre_screening_id"],
            conversation_id=screening_conv["id"],
            vacancy_id=vacancy_id,
            candidate_name=candidate_name,
            channel="voice",
        ))
        logger.info(f"Post-processor triggered for application {application_id}")
    elif application_id and not is_abandoned:
        # No pre_screening_id — post-processor won't run, mark completed immediately
        await pool.execute(
            "UPDATE ats.applications SET status = 'completed' WHERE id = $1",
            application_id,
        )

    return {
        "status": "processing",
        "application_id": str(application_id),
        "qualified": qualified,
        "call_id": call_id,
    }
