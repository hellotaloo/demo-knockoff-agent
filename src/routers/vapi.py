"""
VAPI Webhook Router - Handle VAPI voice call events.

VAPI is a voice AI platform that uses "squads" of assistants with handoffs.
This router handles webhooks sent by VAPI after calls complete.
"""
import os
import json
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header

from src.config import VAPI_WEBHOOK_SECRET
from src.models.vapi import VapiWebhookPayload, VapiEndOfCallReportPayload
from src.models import ActivityEventType, ActorType, ActivityChannel
from src.services import ActivityService
from src.services.screening_notes_integration_service import trigger_screening_notes_integration
from src.database import get_db_pool
from transcript_processor import process_transcript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["VAPI Webhooks"])


async def verify_vapi_signature(
    x_vapi_secret: Optional[str] = None,
) -> bool:
    """
    Verify VAPI webhook request using X-Vapi-Secret header.

    VAPI sends the configured secret in the X-Vapi-Secret header.
    """
    if not VAPI_WEBHOOK_SECRET:
        logger.warning("VAPI_WEBHOOK_SECRET not set, skipping signature validation")
        return True

    if not x_vapi_secret:
        logger.warning("No X-Vapi-Secret header provided")
        return False

    if x_vapi_secret != VAPI_WEBHOOK_SECRET:
        logger.warning("X-Vapi-Secret mismatch")
        return False

    return True


@router.post("/events")
async def vapi_webhook(
    request: Request,
    x_vapi_secret: Optional[str] = Header(None, alias="X-Vapi-Secret"),
):
    """
    Handle VAPI webhook events.

    Main events:
    - status-update: Call state changes (queued, ringing, in-progress, ended)
    - end-of-call-report: Final transcript and call data
    - transcript: Partial/final transcripts during call

    The webhook URL configured in VAPI dashboard: https://taloo-dev.ngrok.app/vapi/events
    """
    # Validate signature
    if not await verify_vapi_signature(x_vapi_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    body = await request.body()
    try:
        payload_dict = json.loads(body)

        # VAPI wraps the actual payload inside a "message" object
        # Unwrap it if present
        if "message" in payload_dict and isinstance(payload_dict["message"], dict):
            logger.info("VAPI webhook: unwrapping 'message' envelope")
            payload_dict = payload_dict["message"]

        payload = VapiWebhookPayload(**payload_dict)
    except Exception as e:
        logger.error(f"Failed to parse VAPI webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    event_type = payload.type
    logger.info(f"VAPI webhook received: type={event_type}")

    # Log full payload for debugging (truncated)
    body_str = body.decode("utf-8", errors="replace")
    if len(body_str) > 2000:
        body_str = body_str[:2000] + "... [truncated]"
    logger.debug(f"[vapi/events] payload: {body_str}")

    # Handle message events (no type field, has message field instead)
    if event_type is None and payload.message is not None:
        # Real-time transcript messages during call - log but don't process
        logger.debug(f"VAPI message event: role={payload.message.role}")
        return {"status": "received", "action": "logged", "event": "message"}

    # Route based on event type
    if event_type == "status-update":
        return await _handle_status_update(payload)
    elif event_type == "end-of-call-report":
        return await _handle_end_of_call(payload_dict)
    elif event_type == "tool-calls":
        return await _handle_tool_calls(payload_dict)
    elif event_type == "transcript":
        # Partial transcripts - log but don't process
        logger.debug("VAPI transcript event received")
        return {"status": "received", "action": "logged"}
    else:
        logger.debug(f"Unhandled VAPI event type: {event_type}")
        return {"status": "received", "action": "ignored"}


async def _handle_status_update(payload: VapiWebhookPayload) -> dict:
    """Handle call status updates."""
    status = payload.status
    call_id = payload.call.id if payload.call else "unknown"

    logger.info(f"VAPI call {call_id} status: {status}")

    # Could update screening_conversations status here if needed
    # For now, just log

    return {"status": "received", "action": "logged", "call_status": status}


async def _handle_tool_calls(payload_dict: dict) -> dict:
    """
    Handle VAPI tool-calls events.

    VAPI sends tool calls when an assistant needs to execute a function.
    We route to our internal endpoints and return results in VAPI's expected format.

    Payload structure:
    {
        "type": "tool-calls",
        "call": {"id": "call-uuid", ...},
        "toolCallList": [{"id": "tc-id", "name": "function_name", "arguments": {...}}]
    }

    Response format:
    {
        "results": [{"toolCallId": "tc-id", "result": "JSON string"}]
    }
    """
    call_obj = payload_dict.get("call", {})
    call_id = call_obj.get("id", "unknown")
    tool_calls = payload_dict.get("toolCallList", [])

    logger.info(f"VAPI tool-calls: call_id={call_id}, tools={[tc.get('name') for tc in tool_calls]}")

    results = []

    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id")

        # VAPI can send tool calls in two formats:
        # 1. Direct: {"id": "...", "name": "...", "arguments": {...}}
        # 2. Function wrapper: {"id": "...", "type": "function", "function": {"name": "...", "arguments": "{...}"}}
        if "function" in tool_call and isinstance(tool_call["function"], dict):
            # Function wrapper format - arguments is a JSON string
            func = tool_call["function"]
            tool_name = func.get("name")
            args_raw = func.get("arguments", "{}")
            arguments = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        else:
            # Direct format
            tool_name = tool_call.get("name")
            arguments = tool_call.get("arguments", {})

        logger.info(f"Processing tool: {tool_name} with args: {arguments}")

        try:
            if tool_name in ("get_time_slots", "getTimeSlots", "get_schedule_slots", "getScheduleSlots"):
                result = await _tool_get_time_slots(call_id, arguments)
            elif tool_name in ("save_slot", "saveSlot", "save_schedule_slot", "saveScheduleSlot"):
                result = await _tool_save_slot(call_id, arguments)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}
                logger.warning(f"Unknown VAPI tool: {tool_name}")

            results.append({
                "toolCallId": tool_call_id,
                "result": json.dumps(result)
            })
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            results.append({
                "toolCallId": tool_call_id,
                "result": json.dumps({"error": str(e)})
            })

    return {"results": results}


async def _tool_get_time_slots(call_id: str, arguments: dict) -> dict:
    """
    Handle get_time_slots tool call.

    Returns available interview slots for the recruiter's calendar.
    """
    from pre_screening_voice_agent.calendar_helpers import get_time_slots_for_voice

    specific_date = arguments.get("specific_date")
    start_from_days = arguments.get("days_ahead", 3)

    result = await get_time_slots_for_voice(
        specific_date=specific_date,
        start_from_days=start_from_days,
    )

    logger.info(f"[VAPI tool] get_time_slots: {len(result.get('slots', []))} slots")

    return {
        "slots": result.get("slots", []),
        "formatted_text": result.get("formatted", ""),
        "has_availability": result.get("has_availability", False),
    }


async def _tool_save_slot(call_id: str, arguments: dict) -> dict:
    """
    Handle save_slot tool call.

    Saves the selected interview slot and creates a calendar event.
    Uses VAPI call_id to look up candidate info from screening_conversations.
    """
    from src.services.scheduling_service import SchedulingService

    pool = await get_db_pool()
    service = SchedulingService(pool)

    selected_date = arguments.get("selected_date")
    selected_time = arguments.get("selected_time")
    selected_slot_text = arguments.get("selected_slot_text")

    if not selected_date or not selected_time:
        return {"error": "Missing required fields: selected_date and selected_time"}

    # Look up candidate info from screening_conversation (created when call started)
    screening_conv = await pool.fetchrow(
        """
        SELECT sc.candidate_name, sc.candidate_phone, c.email as candidate_email
        FROM ats.screening_conversations sc
        LEFT JOIN ats.applications a ON a.conversation_id = sc.session_id AND a.vacancy_id = sc.vacancy_id
        LEFT JOIN ats.candidates c ON c.id = a.candidate_id
        WHERE sc.session_id = $1 AND sc.channel = 'voice'
        """,
        call_id
    )

    candidate_name = screening_conv["candidate_name"] if screening_conv else "Kandidaat"
    candidate_email = screening_conv["candidate_email"] if screening_conv else None

    logger.info(f"[VAPI tool] save_slot: call_id={call_id}, date={selected_date}, time={selected_time}, candidate={candidate_name}")

    try:
        # Use VAPI call_id as conversation_id (maps to screening_conversations.session_id)
        result = await service.save_scheduled_slot(
            conversation_id=call_id,
            selected_date=selected_date,
            selected_time=selected_time,
            selected_slot_text=selected_slot_text,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
        )

        # Create Google Calendar event if configured
        recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
        if recruiter_email and result.get("success"):
            from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository
            calendar_result = await service.schedule_slot_async(
                recruiter_email=recruiter_email,
                candidate_name=candidate_name,
                date=selected_date,
                time=selected_time,
                conversation_id=call_id,
                candidate_email=candidate_email,
            )
            if calendar_result.confirmed and calendar_result.calendar_event_id:
                repo = ScheduledInterviewRepository(pool)
                await repo.update_calendar_event_id(
                    interview_id=uuid.UUID(result["scheduled_interview_id"]),
                    calendar_event_id=calendar_result.calendar_event_id
                )
                logger.info(f"[VAPI tool] Calendar event created: {calendar_result.calendar_event_id}")

        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "scheduled_interview_id": result.get("scheduled_interview_id"),
            "vacancy_title": result.get("vacancy_title"),
        }

    except ValueError as e:
        logger.error(f"[VAPI tool] save_slot error: {e}")
        return {"error": str(e), "success": False}


async def _handle_end_of_call(payload_dict: dict) -> dict:
    """
    Handle end-of-call-report event.

    This is the main processing point - similar to ElevenLabs post_call_transcription.
    1. Look up screening conversation by VAPI call_id (stored in session_id)
    2. Extract transcript from artifact
    3. Process transcript with transcript_processor agent
    4. Store results in applications and application_answers
    """
    # Debug: Log the raw payload structure for squad transcripts
    if "artifact" in payload_dict:
        artifact_keys = list(payload_dict["artifact"].keys()) if payload_dict["artifact"] else []
        logger.info(f"VAPI artifact keys: {artifact_keys}")
        if "messages" in payload_dict.get("artifact", {}):
            msgs = payload_dict["artifact"]["messages"]
            logger.info(f"VAPI messages count: {len(msgs) if msgs else 0}")
            if msgs and len(msgs) > 0:
                # Log first message structure
                first_msg_keys = list(msgs[0].keys())
                logger.info(f"First message keys: {first_msg_keys}")

    try:
        payload = VapiEndOfCallReportPayload(**payload_dict)
    except Exception as e:
        logger.error(f"Failed to parse end-of-call-report: {e}")
        logger.error(f"Payload dict: {json.dumps(payload_dict, default=str)[:2000]}")
        return {"status": "error", "message": str(e)}

    call = payload.call
    call_id = call.id
    ended_reason = payload.endedReason or call.endedReason

    logger.info(f"VAPI call ended: call_id={call_id}, reason={ended_reason}")

    pool = await get_db_pool()

    # Look up screening conversation by VAPI call_id (stored in session_id)
    screening_conv = await pool.fetchrow(
        """
        SELECT sc.id, sc.pre_screening_id, sc.vacancy_id, sc.candidate_phone,
               sc.candidate_name, sc.is_test, v.title as vacancy_title
        FROM ats.screening_conversations sc
        JOIN ats.vacancies v ON v.id = sc.vacancy_id
        WHERE sc.session_id = $1 AND sc.channel = 'voice'
        """,
        call_id
    )

    if not screening_conv:
        logger.warning(f"No screening conversation found for VAPI call_id: {call_id}")
        # Still return success - call completed but we can't process it
        return {"status": "received", "action": "no_conversation_found", "call_id": call_id}

    pre_screening_id = screening_conv["pre_screening_id"]
    vacancy_id = screening_conv["vacancy_id"]
    vacancy_title = screening_conv["vacancy_title"]
    candidate_phone = screening_conv["candidate_phone"]
    candidate_name = screening_conv["candidate_name"] or "Voice Candidate"
    is_test = screening_conv["is_test"] or False

    logger.info(f"Processing VAPI transcript for vacancy '{vacancy_title}' (pre-screening {pre_screening_id})")

    # Extract transcript
    artifact = payload.artifact
    if not artifact or not artifact.messages:
        logger.warning(f"No transcript in VAPI call {call_id}")
        # Log the artifact structure for debugging
        logger.warning(f"Artifact structure: {artifact}")
        return {"status": "received", "action": "no_transcript", "call_id": call_id}

    # Log first few messages for debugging squad transcript structure
    logger.info(f"VAPI artifact has {len(artifact.messages)} messages")
    if artifact.messages:
        sample = artifact.messages[0]
        logger.info(f"Sample message structure: role={sample.role}, "
                   f"message={sample.message is not None}, content={sample.content is not None}, "
                   f"assistantId={sample.assistantId}, assistantName={sample.assistantName}")

    # Convert VAPI transcript format to our format
    # Squad calls include messages from all assistants - combine them chronologically
    transcript = []
    for msg in artifact.messages:
        # Use text property which handles both 'message' and 'content' fields
        message_text = msg.text
        if not message_text:
            continue  # Skip empty messages

        # Normalize role: VAPI uses "bot" or "assistant" for AI, "user" for human
        role = msg.role
        if role in ("bot", "assistant"):
            role = "assistant"

        transcript.append({
            "role": role,
            "message": message_text,
            "time_in_call_secs": msg.secondsFromStart or 0,
            # Include assistant info for debugging
            "assistant_name": msg.assistantName or msg.name,
        })

    logger.info(f"Processing VAPI transcript: {len(transcript)} messages from squad")

    # Get pre-screening questions
    questions = await pool.fetch(
        """
        SELECT id, question_type, position, question_text, ideal_answer
        FROM ats.pre_screening_questions
        WHERE pre_screening_id = $1
        ORDER BY question_type, position
        """,
        pre_screening_id
    )

    # Build question lists with proper IDs
    knockout_questions = []
    qualification_questions = []
    ko_idx = 1
    qual_idx = 1

    for q in questions:
        q_dict = {
            "db_id": str(q["id"]),
            "question_text": q["question_text"],
            "ideal_answer": q["ideal_answer"],
        }
        if q["question_type"] == "knockout":
            q_dict["id"] = f"ko_{ko_idx}"
            knockout_questions.append(q_dict)
            ko_idx += 1
        else:
            q_dict["id"] = f"qual_{qual_idx}"
            qualification_questions.append(q_dict)
            qual_idx += 1

    # Calculate call duration from timestamps
    # VAPI can send timestamps as ISO strings or Unix milliseconds
    call_duration = 0
    if call.startedAt and call.endedAt:
        try:
            # Handle both string (ISO) and numeric (Unix ms) timestamps
            if isinstance(call.startedAt, (int, float)):
                started = datetime.fromtimestamp(call.startedAt / 1000)  # Unix ms
            else:
                started = datetime.fromisoformat(call.startedAt.replace("Z", "+00:00"))

            if isinstance(call.endedAt, (int, float)):
                ended = datetime.fromtimestamp(call.endedAt / 1000)  # Unix ms
            else:
                ended = datetime.fromisoformat(call.endedAt.replace("Z", "+00:00"))

            call_duration = int((ended - started).total_seconds())
        except Exception as e:
            logger.warning(f"Failed to calculate call duration: {e}")
            pass

    call_date = datetime.now().strftime("%Y-%m-%d")

    # Find existing application and set status to 'processing'
    existing_app = None
    if candidate_phone:
        existing_app = await pool.fetchrow(
            """
            SELECT id, candidate_id FROM ats.applications
            WHERE vacancy_id = $1 AND candidate_phone = $2 AND channel = 'voice' AND status != 'completed'
            """,
            vacancy_id, candidate_phone
        )

    if existing_app:
        await pool.execute(
            "UPDATE ats.applications SET status = 'processing' WHERE id = $1",
            existing_app["id"]
        )
        logger.info(f"Application {existing_app['id']} status -> processing")

    # Process transcript with AI
    result = await process_transcript(
        transcript=transcript,
        knockout_questions=knockout_questions,
        qualification_questions=qualification_questions,
        call_date=call_date,
    )

    # Store results in transaction
    async with pool.acquire() as conn:
        async with conn.transaction():
            if existing_app:
                application_id = existing_app["id"]
                await conn.execute(
                    """
                    UPDATE ats.applications
                    SET qualified = $1, interaction_seconds = $2,
                        completed_at = NOW(), conversation_id = $3, channel = 'voice',
                        summary = $4, interview_slot = $5, status = 'completed'
                    WHERE id = $6
                    """,
                    result.overall_passed,
                    call_duration,
                    call_id,
                    result.summary,
                    result.interview_slot,
                    application_id
                )
                logger.info(f"Updated application {application_id} with status=completed")
            else:
                app_row = await conn.fetchrow(
                    """
                    INSERT INTO ats.applications
                    (vacancy_id, candidate_name, candidate_phone, channel, qualified,
                     interaction_seconds, completed_at, conversation_id, summary, interview_slot, is_test, status)
                    VALUES ($1, $2, $3, 'voice', $4, $5, NOW(), $6, $7, $8, $9, 'completed')
                    RETURNING id
                    """,
                    vacancy_id, candidate_name, candidate_phone,
                    result.overall_passed, call_duration, call_id,
                    result.summary, result.interview_slot, is_test
                )
                application_id = app_row["id"]
                logger.info(f"Created new application {application_id} with status=completed")

            # Store answers
            for kr in result.knockout_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'voice')
                    """,
                    application_id, kr.id, kr.question_text, kr.answer,
                    kr.passed, kr.score, kr.rating
                )

            for qr in result.qualification_results:
                await conn.execute(
                    """
                    INSERT INTO ats.application_answers
                    (application_id, question_id, question_text, answer, passed, score, rating, source, motivation)
                    VALUES ($1, $2, $3, $4, NULL, $5, $6, 'voice', $7)
                    """,
                    application_id, qr.id, qr.question_text, qr.answer,
                    qr.score, qr.rating, qr.motivation
                )

            # Update conversation status
            await conn.execute(
                """
                UPDATE ats.screening_conversations
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE session_id = $1 AND channel = 'voice'
                """,
                call_id
            )

            # Store transcript messages
            conv_id = screening_conv["id"]
            for msg in transcript:
                await conn.execute(
                    """
                    INSERT INTO ats.conversation_messages (conversation_id, role, message)
                    VALUES ($1, $2, $3)
                    """,
                    conv_id, "user" if msg["role"] == "user" else "agent", msg["message"]
                )

    logger.info(f"VAPI call {call_id} processed: application {application_id}")

    # Log activity
    candidate_id = existing_app["candidate_id"] if existing_app else None
    if candidate_id:
        activity_service = ActivityService(pool)
        scores = [qr.score for qr in result.qualification_results if qr.score is not None]
        avg_score = round(sum(scores) / len(scores)) if scores else None

        event_type = ActivityEventType.QUALIFIED if result.overall_passed else ActivityEventType.DISQUALIFIED
        await activity_service.log(
            candidate_id=str(candidate_id),
            event_type=event_type,
            application_id=str(application_id),
            vacancy_id=str(vacancy_id),
            channel=ActivityChannel.VOICE,
            actor_type=ActorType.AGENT,
            metadata={"score": avg_score, "duration_seconds": call_duration},
            summary=f"Pre-screening {'geslaagd' if result.overall_passed else 'niet geslaagd'}"
        )

    # Trigger screening notes integration (Google Doc creation + calendar attachment)
    # Runs as background task for qualified candidates with scheduled interviews
    if result.overall_passed:
        asyncio.create_task(trigger_screening_notes_integration(
            pool=pool,
            application_id=application_id,
            recruiter_email=os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL"),
        ))
        logger.info(f"📄 Triggered screening notes integration for application {application_id}")

    return {
        "status": "processed",
        "application_id": str(application_id),
        "overall_passed": result.overall_passed,
        "call_id": call_id,
    }
