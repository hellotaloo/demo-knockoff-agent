"""
Scheduling Router - Endpoints for interview time slot management.

This router provides endpoints used by:
- ElevenLabs voice agents (via webhook)
- knockout_agent (can also import service directly)
- Frontend applications

Supports Google Calendar integration when GOOGLE_SERVICE_ACCOUNT_FILE is configured.
Uses GOOGLE_CALENDAR_IMPERSONATE_EMAIL as the default recruiter calendar.
"""
import logging
import os
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.database import get_db_pool
from src.services.scheduling_service import (
    scheduling_service,
    SchedulingService,
    TimeSlot,
    SlotData,
)
from src.models import ActivityEventType, ActorType, ActivityChannel
from src.services import ActivityService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduling", tags=["Scheduling"])


# =============================================================================
# Request/Response Models
# =============================================================================

class GetTimeSlotsRequest(BaseModel):
    """Request for getting available time slots."""
    conversation_id: Optional[str] = None
    recruiter_id: Optional[str] = None


class GetTimeSlotsResponse(BaseModel):
    """Response containing available time slots."""
    slots: list[TimeSlot]
    formatted_text: str


class SaveSlotRequest(BaseModel):
    """Request body for saving selected time slot (ElevenLabs webhook)."""
    conversation_id: str
    selected_date: str  # YYYY-MM-DD
    selected_time: str  # e.g., "10u", "14u"
    selected_slot_text: Optional[str] = None
    candidate_name: Optional[str] = None
    candidate_phone: Optional[str] = None
    candidate_email: Optional[str] = None  # If provided, candidate gets calendar invite
    notes: Optional[str] = None
    debug: Optional[bool] = False  # Skip DB lookup, just create calendar event


class SaveSlotResponse(BaseModel):
    """Response after saving a scheduled interview slot."""
    success: bool
    scheduled_interview_id: Optional[str] = None  # Optional for debug mode
    message: str
    vacancy_id: Optional[str] = None  # Optional for debug mode
    vacancy_title: Optional[str] = None
    selected_date: str
    selected_time: str
    selected_slot_text: Optional[str] = None


class UpdateNotesRequest(BaseModel):
    """Request body for updating interview notes by conversation_id."""
    notes: str
    append: bool = False  # If True, append to existing notes. If False, replace.


class UpdateNotesResponse(BaseModel):
    """Response after updating interview notes."""
    success: bool
    message: str
    conversation_id: str
    scheduled_interview_id: Optional[str] = None


class RescheduleRequest(BaseModel):
    """Request body for rescheduling an interview."""
    new_date: str  # YYYY-MM-DD
    new_time: str  # e.g., "10u", "14u"
    new_slot_text: Optional[str] = None  # Full Dutch text, e.g., "maandag 17 februari om 14u"
    reason: Optional[str] = None  # Reason for rescheduling


class RescheduleResponse(BaseModel):
    """Response after rescheduling an interview."""
    success: bool
    message: str
    conversation_id: str
    previous_interview_id: str
    previous_status: str  # Will be "rescheduled"
    new_interview_id: str
    new_date: str
    new_time: str
    new_slot_text: Optional[str] = None


class CancelRequest(BaseModel):
    """Request body for cancelling an interview."""
    reason: Optional[str] = None  # Reason for cancellation


class CancelResponse(BaseModel):
    """Response after cancelling an interview."""
    success: bool
    message: str
    conversation_id: str
    interview_id: str
    previous_status: str
    calendar_event_cancelled: bool = False


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/get-time-slots", response_model=GetTimeSlotsResponse)
async def get_time_slots(request: GetTimeSlotsRequest = GetTimeSlotsRequest()):
    """
    Get available time slots for scheduling interviews.

    This endpoint is called by:
    - ElevenLabs voice agent via webhook tool
    - Frontend applications for scheduling UI

    Returns 3 business days starting from +3 days from today,
    with morning (voormiddag) and afternoon (namiddag) slots.

    If Google Calendar is configured (GOOGLE_SERVICE_ACCOUNT_FILE),
    returns real availability from the recruiter's calendar.
    Uses GOOGLE_CALENDAR_IMPERSONATE_EMAIL as the default recruiter calendar.

    Request body is optional - all fields have defaults.
    """
    logger.info(
        f"[scheduling/get-time-slots] request: "
        f"conversation_id={request.conversation_id}, "
        f"recruiter_id={request.recruiter_id}"
    )

    # Use default recruiter email from environment
    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    # Use async version for Google Calendar integration
    slot_data = await scheduling_service.get_available_slots_async(
        recruiter_email=recruiter_email
    )

    response = GetTimeSlotsResponse(
        slots=slot_data.slots,
        formatted_text=slot_data.formatted_text
    )

    # Log response for debugging
    lines = [
        "[scheduling/get-time-slots] response:",
        f"  recruiter_email={recruiter_email or 'not configured'}",
        f"  slots_count={len(response.slots)}"
    ]
    for i, slot in enumerate(response.slots, 1):
        lines.append(f"  slot {i}: {slot.dutch_date} ({slot.date})")
        lines.append(f"    voormiddag: {', '.join(slot.morning)}")
        lines.append(f"    namiddag: {', '.join(slot.afternoon)}")
    logger.info("\n".join(lines))

    return response


@router.post("/save-slot", response_model=SaveSlotResponse)
async def save_time_slot(request: SaveSlotRequest):
    """
    Save a selected interview time slot and create a Google Calendar event.

    This endpoint is called by ElevenLabs voice agent via webhook tool
    when a candidate selects an interview time slot.

    The endpoint:
    1. Looks up vacancy_id from conversation_id (via screening_conversations)
    2. Creates a scheduled_interviews record in the database
    3. Creates a Google Calendar event (if configured)
    4. Returns confirmation for the agent to relay to candidate

    ElevenLabs Webhook Tool Configuration:
    - URL: https://your-domain.com/api/scheduling/save-slot
    - Method: POST
    - Body parameters:
      - conversation_id: dynamic_variable (system.conversation_id)
      - selected_date: llm_prompt ("Extract the selected date in YYYY-MM-DD format")
      - selected_time: llm_prompt ("Extract the selected time, e.g., '10u' or '14u'")
      - selected_slot_text: llm_prompt ("Extract the full slot text in Dutch")
    """
    # Enhanced logging for debugging ElevenLabs webhook calls
    print("\n" + "=" * 60)
    print("📅 SAVE INTERVIEW SLOT - Webhook Called")
    print("=" * 60)
    print(f"  conversation_id: {request.conversation_id}")
    print(f"  selected_date:   {request.selected_date}")
    print(f"  selected_time:   {request.selected_time}")
    print(f"  slot_text:       {request.selected_slot_text}")
    print(f"  candidate_name:  {request.candidate_name}")
    print(f"  candidate_email: {request.candidate_email}")
    print(f"  debug_mode:      {request.debug}")
    print("-" * 60)

    logger.info(
        f"[scheduling/save-slot] request: "
        f"conversation_id={request.conversation_id}, "
        f"date={request.selected_date}, time={request.selected_time}, "
        f"debug={request.debug}"
    )

    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

    # Debug mode: skip DB lookup, just create calendar event
    if request.debug:
        logger.info("[scheduling/save-slot] DEBUG MODE - skipping DB lookup")
        candidate_name = request.candidate_name or "Test Kandidaat"

        if recruiter_email:
            print(f"📆 Creating calendar event for: {candidate_name}")
            print(f"   Recruiter calendar: {recruiter_email}")
            if request.candidate_email:
                print(f"   Candidate email (will receive invite): {request.candidate_email}")
            calendar_result = await scheduling_service.schedule_slot_async(
                recruiter_email=recruiter_email,
                candidate_name=candidate_name,
                date=request.selected_date,
                time=request.selected_time,
                conversation_id=request.conversation_id,
                candidate_email=request.candidate_email,
            )
            message = calendar_result.message
            success = calendar_result.confirmed
            print(f"   Calendar result: {'✅ Created' if success else '❌ Failed'}")
        else:
            message = "Calendar not configured (GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set)"
            success = False
            print("⚠️  Calendar not configured (GOOGLE_CALENDAR_IMPERSONATE_EMAIL not set)")

        response = SaveSlotResponse(
            success=success,
            scheduled_interview_id=None,
            message=message,
            vacancy_id=None,
            vacancy_title=None,
            selected_date=request.selected_date,
            selected_time=request.selected_time,
            selected_slot_text=request.selected_slot_text,
        )
        print(f"\n✅ DEBUG Response: success={success}")
        print(f"   Message: {message}")
        print("=" * 60 + "\n")
        logger.info(f"[scheduling/save-slot] DEBUG response: {response.model_dump()}")
        return response

    # Normal mode: save to DB and create calendar event
    try:
        pool = await get_db_pool()
        service = SchedulingService(pool)

        # Save to database
        result = await service.save_scheduled_slot(
            conversation_id=request.conversation_id,
            selected_date=request.selected_date,
            selected_time=request.selected_time,
            selected_slot_text=request.selected_slot_text,
            candidate_name=request.candidate_name,
            candidate_phone=request.candidate_phone,
            candidate_email=request.candidate_email,
            notes=request.notes,
        )

        # Create Google Calendar event if configured
        if recruiter_email and result.get("success"):
            from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository
            candidate_name = request.candidate_name or result.get("candidate_name", "Kandidaat")
            candidate_email = request.candidate_email or result.get("candidate_email")
            print(f"📆 Creating calendar event for: {candidate_name}")
            print(f"   Recruiter calendar: {recruiter_email}")
            print(f"   Date: {request.selected_date}")
            print(f"   Time: {request.selected_time}")
            if candidate_email:
                print(f"   Candidate email (will receive invite): {candidate_email}")
            calendar_result = await service.schedule_slot_async(
                recruiter_email=recruiter_email,
                candidate_name=candidate_name,
                date=request.selected_date,
                time=request.selected_time,
                conversation_id=request.conversation_id,
                candidate_email=candidate_email,
            )
            if calendar_result.confirmed:
                print(f"   Calendar event ID: {calendar_result.calendar_event_id}")
                print(f"   Calendar result: ✅ Created")
                logger.info(f"[scheduling/save-slot] Calendar event created for {candidate_name}")
                # Store the calendar event ID in the database
                if calendar_result.calendar_event_id and result.get("scheduled_interview_id"):
                    repo = ScheduledInterviewRepository(pool)
                    await repo.update_calendar_event_id(
                        interview_id=uuid.UUID(result["scheduled_interview_id"]),
                        calendar_event_id=calendar_result.calendar_event_id
                    )
                    print(f"   Stored calendar_event_id in database")
            else:
                print(f"   Calendar result: ❌ Failed - {calendar_result.message}")
                logger.warning(f"[scheduling/save-slot] Calendar event failed: {calendar_result.message}")

        response = SaveSlotResponse(
            success=result["success"],
            scheduled_interview_id=result["scheduled_interview_id"],
            message=result["message"],
            vacancy_id=result["vacancy_id"],
            vacancy_title=result.get("vacancy_title"),
            selected_date=result["selected_date"],
            selected_time=result["selected_time"],
            selected_slot_text=result.get("selected_slot_text"),
        )

        print(f"\n✅ Response: success={result['success']}")
        print(f"   Interview ID: {result['scheduled_interview_id']}")
        print(f"   Vacancy: {result.get('vacancy_title')} ({result['vacancy_id']})")
        print(f"   Message: {result['message']}")
        print("=" * 60 + "\n")
        logger.info(f"[scheduling/save-slot] response: {response.model_dump()}")

        # Log activity: interview scheduled
        if result.get("success") and result.get("application_id"):
            app_row = await pool.fetchrow(
                "SELECT candidate_id FROM ats.applications WHERE id = $1",
                uuid.UUID(result["application_id"])
            )
            if app_row and app_row["candidate_id"]:
                activity_service = ActivityService(pool)
                slot_text = request.selected_slot_text or f"{request.selected_date} om {request.selected_time}"
                await activity_service.log(
                    candidate_id=str(app_row["candidate_id"]),
                    event_type=ActivityEventType.INTERVIEW_SCHEDULED,
                    application_id=result["application_id"],
                    vacancy_id=result["vacancy_id"],
                    channel=ActivityChannel.VOICE,
                    actor_type=ActorType.CANDIDATE,
                    metadata={"date": request.selected_date, "time": request.selected_time},
                    summary=f"Interview ingepland op {slot_text}"
                )

        return response

    except ValueError as e:
        logger.error(f"[scheduling/save-slot] error: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[scheduling/save-slot] unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save scheduled slot")


@router.patch(
    "/interviews/by-conversation/{conversation_id}/notes",
    response_model=UpdateNotesResponse
)
async def update_interview_notes(
    conversation_id: str,
    request: UpdateNotesRequest
):
    """
    Update notes for a scheduled interview by ElevenLabs conversation_id.

    This endpoint is called after the voice conversation is analyzed by AI
    to add a summary to the scheduled interview record.

    Args:
        conversation_id: ElevenLabs conversation_id (path parameter)
        request: Contains notes and append flag

    Returns:
        Updated interview info or 404 if not found
    """
    from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository

    logger.info(
        f"[scheduling/update-notes] conversation_id={conversation_id}, "
        f"append={request.append}, notes_length={len(request.notes)}"
    )

    try:
        pool = await get_db_pool()
        repo = ScheduledInterviewRepository(pool)

        result = await repo.update_notes_by_conversation_id(
            conversation_id=conversation_id,
            notes=request.notes,
            append=request.append
        )

        if not result:
            logger.warning(
                f"[scheduling/update-notes] Interview not found for "
                f"conversation_id={conversation_id}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No scheduled interview found for conversation_id: {conversation_id}"
            )

        response = UpdateNotesResponse(
            success=True,
            message="Notes updated successfully",
            conversation_id=conversation_id,
            scheduled_interview_id=str(result["id"])
        )

        logger.info(
            f"[scheduling/update-notes] success: interview_id={result['id']}"
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[scheduling/update-notes] unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update interview notes"
        )


@router.post(
    "/interviews/by-conversation/{conversation_id}/reschedule",
    response_model=RescheduleResponse
)
async def reschedule_interview(
    conversation_id: str,
    request: RescheduleRequest
):
    """
    Reschedule an existing interview to a new time slot.

    This endpoint:
    1. Finds the existing scheduled_interview by conversation_id
    2. Marks it as 'rescheduled' (preserves history)
    3. Creates a new scheduled_interview with the new time
    4. Optionally creates a new Google Calendar event

    Called by:
    - ElevenLabs voice agent when candidate requests reschedule
    - Frontend scheduling UI

    Args:
        conversation_id: ElevenLabs conversation_id (path parameter)
        request: Contains new_date, new_time, and optional reason

    Returns:
        RescheduleResponse with both old and new interview IDs
    """
    from datetime import datetime
    from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository

    print("\n" + "=" * 60)
    print("🔄 RESCHEDULE INTERVIEW - Request Received")
    print("=" * 60)
    print(f"  conversation_id: {conversation_id}")
    print(f"  new_date:        {request.new_date}")
    print(f"  new_time:        {request.new_time}")
    print(f"  new_slot_text:   {request.new_slot_text}")
    print(f"  reason:          {request.reason}")
    print("-" * 60)

    logger.info(
        f"[scheduling/reschedule] request: "
        f"conversation_id={conversation_id}, "
        f"new_date={request.new_date}, new_time={request.new_time}"
    )

    try:
        pool = await get_db_pool()
        repo = ScheduledInterviewRepository(pool)

        # 1. Find existing active interview
        existing = await repo.get_active_by_conversation_id(conversation_id)
        if not existing:
            logger.warning(
                f"[scheduling/reschedule] No active interview found for "
                f"conversation_id={conversation_id}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No active scheduled interview found for conversation_id: {conversation_id}"
            )

        print(f"  Found existing interview: {existing['id']}")
        print(f"  Current status: {existing['status']}")
        print(f"  Current slot: {existing['selected_date']} at {existing['selected_time']}")

        # 2. Mark existing as 'rescheduled'
        reschedule_note = f"Rescheduled: {request.reason or 'No reason provided'}"
        await repo.update_status(
            interview_id=existing["id"],
            status="rescheduled",
            notes=reschedule_note
        )
        print(f"  Marked existing interview as 'rescheduled'")

        # 3. Create new scheduled interview with same conversation_id
        new_date = datetime.strptime(request.new_date, "%Y-%m-%d").date()
        history_note = f"Rescheduled from {existing['selected_date']} {existing['selected_time']}"

        new_interview_id = await repo.create(
            vacancy_id=existing["vacancy_id"],
            conversation_id=conversation_id,  # Keep same conversation_id
            selected_date=new_date,
            selected_time=request.new_time,
            selected_slot_text=request.new_slot_text,
            application_id=existing["application_id"],
            candidate_name=existing["candidate_name"],
            candidate_phone=existing["candidate_phone"],
            channel=existing["channel"],
            notes=history_note
        )
        print(f"  Created new interview: {new_interview_id}")

        # 4. Handle Google Calendar (cancel old event, create new one)
        recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
        if recruiter_email:
            from src.services.google_calendar_service import calendar_service
            service = SchedulingService(pool)

            # Cancel old calendar event if it exists
            old_calendar_event_id = existing.get("calendar_event_id")
            if old_calendar_event_id:
                try:
                    print(f"📆 Cancelling old calendar event: {old_calendar_event_id}")
                    await calendar_service.delete_event(
                        calendar_email=recruiter_email,
                        event_id=old_calendar_event_id
                    )
                    print(f"   Old event cancelled: ✅")
                except Exception as e:
                    logger.warning(f"[scheduling/reschedule] Failed to cancel old event: {e}")
                    print(f"   Old event cancel: ⚠️ Failed - {e}")

            # Create new calendar event
            try:
                candidate_name = existing["candidate_name"] or "Kandidaat"
                print(f"📆 Creating new calendar event for: {candidate_name}")
                print(f"   Recruiter calendar: {recruiter_email}")
                print(f"   Date: {request.new_date}")
                print(f"   Time: {request.new_time}")

                calendar_result = await service.schedule_slot_async(
                    recruiter_email=recruiter_email,
                    candidate_name=candidate_name,
                    date=request.new_date,
                    time=request.new_time,
                    conversation_id=conversation_id
                )
                if calendar_result.confirmed and calendar_result.calendar_event_id:
                    print(f"   Calendar event ID: {calendar_result.calendar_event_id}")
                    print(f"   Calendar result: ✅ Created")
                    # Store the new calendar event ID
                    await repo.update_calendar_event_id(
                        interview_id=new_interview_id,
                        calendar_event_id=calendar_result.calendar_event_id
                    )
                    print(f"   Stored calendar_event_id in database")
                else:
                    print(f"   Calendar result: ✅ Created (no event ID)")
            except Exception as e:
                logger.warning(f"[scheduling/reschedule] Calendar event failed: {e}")
                print(f"   Calendar result: ⚠️ Failed - {e}")

        # Build response message
        slot_text = request.new_slot_text or f"{request.new_date} om {request.new_time}"
        message = f"Interview herverzet naar {slot_text}"

        response = RescheduleResponse(
            success=True,
            message=message,
            conversation_id=conversation_id,
            previous_interview_id=str(existing["id"]),
            previous_status="rescheduled",
            new_interview_id=str(new_interview_id),
            new_date=request.new_date,
            new_time=request.new_time,
            new_slot_text=request.new_slot_text
        )

        print(f"\n✅ Reschedule successful")
        print(f"   Previous: {existing['id']} -> rescheduled")
        print(f"   New: {new_interview_id}")
        print("=" * 60 + "\n")

        logger.info(f"[scheduling/reschedule] success: {response.model_dump()}")

        # Log activity: interview rescheduled
        if existing.get("application_id"):
            app_row = await pool.fetchrow(
                "SELECT candidate_id FROM ats.applications WHERE id = $1",
                existing["application_id"]
            )
            if app_row and app_row["candidate_id"]:
                activity_service = ActivityService(pool)
                await activity_service.log(
                    candidate_id=str(app_row["candidate_id"]),
                    event_type=ActivityEventType.INTERVIEW_RESCHEDULED,
                    application_id=str(existing["application_id"]),
                    vacancy_id=str(existing["vacancy_id"]),
                    actor_type=ActorType.RECRUITER,
                    metadata={
                        "old_date": str(existing["selected_date"]),
                        "old_time": existing["selected_time"],
                        "new_date": request.new_date,
                        "new_time": request.new_time,
                        "reason": request.reason
                    },
                    summary=f"Interview herverzet naar {slot_text}"
                )

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[scheduling/reschedule] unexpected error: {e}")
        logger.error(traceback.format_exc())
        print(f"❌ Reschedule error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reschedule interview: {str(e)}"
        )


@router.post(
    "/interviews/by-conversation/{conversation_id}/cancel",
    response_model=CancelResponse
)
async def cancel_interview(
    conversation_id: str,
    request: CancelRequest = CancelRequest()
):
    """
    Cancel a scheduled interview.

    This endpoint:
    1. Finds the active scheduled_interview by conversation_id
    2. Marks it as 'cancelled'
    3. Cancels the Google Calendar event if it exists

    Called by:
    - ElevenLabs voice agent when candidate cancels
    - Frontend scheduling UI

    Args:
        conversation_id: ElevenLabs conversation_id (path parameter)
        request: Optional reason for cancellation

    Returns:
        CancelResponse with interview details
    """
    from src.repositories.scheduled_interview_repo import ScheduledInterviewRepository

    print("\n" + "=" * 60)
    print("❌ CANCEL INTERVIEW - Request Received")
    print("=" * 60)
    print(f"  conversation_id: {conversation_id}")
    print(f"  reason:          {request.reason}")
    print("-" * 60)

    logger.info(
        f"[scheduling/cancel] request: "
        f"conversation_id={conversation_id}, reason={request.reason}"
    )

    try:
        pool = await get_db_pool()
        repo = ScheduledInterviewRepository(pool)

        # 1. Find existing active interview
        existing = await repo.get_active_by_conversation_id(conversation_id)
        if not existing:
            logger.warning(
                f"[scheduling/cancel] No active interview found for "
                f"conversation_id={conversation_id}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No active scheduled interview found for conversation_id: {conversation_id}"
            )

        print(f"  Found existing interview: {existing['id']}")
        print(f"  Current status: {existing['status']}")
        print(f"  Current slot: {existing['selected_date']} at {existing['selected_time']}")

        previous_status = existing["status"]

        # 2. Mark as cancelled
        cancel_note = f"Cancelled: {request.reason or 'No reason provided'}"
        await repo.update_status(
            interview_id=existing["id"],
            status="cancelled",
            notes=cancel_note
        )
        print(f"  Marked interview as 'cancelled'")

        # 3. Cancel Google Calendar event if it exists
        calendar_cancelled = False
        recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
        calendar_event_id = existing.get("calendar_event_id")

        if recruiter_email and calendar_event_id:
            from src.services.google_calendar_service import calendar_service
            try:
                print(f"📆 Cancelling calendar event: {calendar_event_id}")
                await calendar_service.delete_event(
                    calendar_email=recruiter_email,
                    event_id=calendar_event_id
                )
                calendar_cancelled = True
                print(f"   Calendar event cancelled: ✅")
            except Exception as e:
                logger.warning(f"[scheduling/cancel] Failed to cancel calendar event: {e}")
                print(f"   Calendar event cancel: ⚠️ Failed - {e}")

        response = CancelResponse(
            success=True,
            message="Interview geannuleerd",
            conversation_id=conversation_id,
            interview_id=str(existing["id"]),
            previous_status=previous_status,
            calendar_event_cancelled=calendar_cancelled
        )

        print(f"\n✅ Cancellation successful")
        print(f"   Interview: {existing['id']} -> cancelled")
        print(f"   Calendar cancelled: {calendar_cancelled}")
        print("=" * 60 + "\n")

        logger.info(f"[scheduling/cancel] success: {response.model_dump()}")

        # Log activity: interview cancelled
        if existing.get("application_id"):
            app_row = await pool.fetchrow(
                "SELECT candidate_id FROM ats.applications WHERE id = $1",
                existing["application_id"]
            )
            if app_row and app_row["candidate_id"]:
                activity_service = ActivityService(pool)
                await activity_service.log(
                    candidate_id=str(app_row["candidate_id"]),
                    event_type=ActivityEventType.INTERVIEW_CANCELLED,
                    application_id=str(existing["application_id"]),
                    vacancy_id=str(existing["vacancy_id"]),
                    actor_type=ActorType.RECRUITER,
                    metadata={"reason": request.reason},
                    summary=f"Interview geannuleerd" + (f": {request.reason}" if request.reason else "")
                )

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"[scheduling/cancel] unexpected error: {e}")
        logger.error(traceback.format_exc())
        print(f"❌ Cancel error: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel interview: {str(e)}"
        )
