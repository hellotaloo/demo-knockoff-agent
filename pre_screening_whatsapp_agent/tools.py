"""
State management tools for the pre-screening WhatsApp agent.

These tools allow sub-agents to update conversation state and control flow.
Tools use ToolContext to read and modify session state.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from google.adk.tools import ToolContext
from src.services.scheduling_service import scheduling_service

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


# =============================================================================
# State Keys Documentation
# =============================================================================
# phase: welcome | knockout | confirm_fail | alternate_intake | open_questions | scheduling | goodbye | exited
# knockout_index: int - current knockout question (0-based)
# knockout_total: int - total knockout questions
# knockout_results: list[dict] - results of each knockout question
# open_index: int - current open question (0-based)
# open_total: int - total open questions
# open_results: list[dict] - results of each open question
# unrelated_count: int - number of unrelated/off-topic answers
# candidate_name: str - candidate's name
# candidate_qualified: bool - whether candidate passed all checks
# goodbye_scenario: success | alternate | knockout_fail | exit
# failed_requirement: str - the requirement that wasn't met
# failed_answer: str - the answer that failed
# alternate_question_index: int - current alternate intake question (0-based)


def evaluate_knockout_answer(
    tool_context: ToolContext,
    passed: bool,
    answer_summary: str,
    is_unrelated: bool = False,
) -> dict:
    """
    Evaluate a knockout question answer and update state accordingly.

    Args:
        tool_context: ADK tool context for state access
        passed: Whether the answer meets the knockout requirement
        answer_summary: Brief summary of what the candidate answered
        is_unrelated: Whether the answer was completely off-topic

    Returns:
        dict with action and next question (if any)
    """
    state = tool_context.state

    # Handle unrelated answer
    if is_unrelated:
        unrelated_count = state.get("unrelated_count", 0) + 1
        state["unrelated_count"] = unrelated_count
        logger.info(f"🚫 Unrelated answer: count={unrelated_count}")

        if unrelated_count >= 2:
            state["phase"] = "exited"
            state["goodbye_scenario"] = "exit"
            return {
                "action": "exit",
                "reason": "Te veel onrelateerde antwoorden",
                "message": "Interview wordt beëindigd"
            }
        return {
            "action": "repeat_question",
            "current_question": state.get("current_knockout_question"),
            "message": "Vraag opnieuw stellen"
        }

    # Handle failed answer
    if not passed:
        state["phase"] = "confirm_fail"
        state["failed_requirement"] = state.get("current_knockout_requirement", "")
        state["failed_answer"] = answer_summary
        logger.info(f"❌ Knockout failed: {answer_summary}")
        return {
            "action": "knockout_failed",
            "failed_requirement": state.get("current_knockout_requirement"),
            "message": "Vraag bevestiging van de kandidaat"
        }

    # Handle passed answer - record result and move to next
    knockout_results = state.get("knockout_results", [])
    knockout_results.append({
        "question": state.get("current_knockout_question"),
        "answer": answer_summary,
        "passed": True
    })
    state["knockout_results"] = knockout_results

    # Move to next question
    current_index = state.get("knockout_index", 0)
    knockout_total = state.get("knockout_total", 0)
    knockout_questions = state.get("knockout_questions", [])

    next_index = current_index + 1
    state["knockout_index"] = next_index

    logger.info(f"✅ Knockout passed: {current_index + 1}/{knockout_total}")

    # Check if more knockout questions
    if next_index < knockout_total and next_index < len(knockout_questions):
        next_q = knockout_questions[next_index]
        state["current_knockout_question"] = next_q.get("question", "")
        state["current_knockout_requirement"] = next_q.get("requirement", "")
        return {
            "action": "next_question",
            "question_number": next_index + 1,
            "total_questions": knockout_total,
            "next_question": next_q.get("question", ""),
            "message": f"Stel nu vraag {next_index + 1}: {next_q.get('question', '')}"
        }

    # All knockout questions done - move to open questions
    state["phase"] = "open_questions"
    state["open_index"] = 0
    open_questions = state.get("open_questions", [])
    if open_questions:
        state["current_open_question"] = open_questions[0] if isinstance(open_questions[0], str) else open_questions[0].get("question", "")

    logger.info("✅ All knockout questions passed, moving to open questions")
    return {
        "action": "knockout_complete",
        "message": "Alle knockout vragen doorlopen. Ga door naar kwalificatievragen.",
        "next_phase": "open_questions",
        "first_open_question": state.get("current_open_question", "")
    }


def knockout_failed(
    tool_context: ToolContext,
    failed_requirement: str,
    candidate_answer: str
) -> dict:
    """
    Mark knockout as failed and move to confirmation phase.

    Args:
        tool_context: ADK tool context for state access
        failed_requirement: The requirement that wasn't met
        candidate_answer: What the candidate answered

    Returns:
        dict with failure details
    """
    state = tool_context.state
    state["phase"] = "confirm_fail"
    state["failed_requirement"] = failed_requirement
    state["failed_answer"] = candidate_answer

    logger.info(f"❌ Knockout failed: {failed_requirement}")
    return {
        "action": "confirm_failure",
        "failed_requirement": failed_requirement,
        "candidate_answer": candidate_answer,
        "message": "Vraag de kandidaat of dit klopt en of ze interesse hebben in andere vacatures"
    }


def confirm_knockout_result(
    tool_context: ToolContext,
    candidate_confirms_failure: bool,
    interested_in_alternatives: bool
) -> dict:
    """
    Handle the result of knockout failure confirmation.

    Args:
        tool_context: ADK tool context for state access
        candidate_confirms_failure: True if candidate confirms they don't meet requirement
        interested_in_alternatives: True if candidate wants to hear about other vacancies

    Returns:
        dict with next action
    """
    state = tool_context.state

    if not candidate_confirms_failure:
        # Candidate wants to retry - go back to knockout
        state["phase"] = "knockout"
        logger.info("🔄 Candidate wants to retry knockout question")
        return {
            "action": "retry_knockout",
            "current_question": state.get("current_knockout_question"),
            "message": "Stel de vraag opnieuw"
        }

    if interested_in_alternatives:
        # Start alternate intake
        state["phase"] = "alternate_intake"
        state["alternate_question_index"] = 0
        logger.info("📋 Starting alternate intake")
        return {
            "action": "start_alternate_intake",
            "message": "Start de alternatieve intake (3 vragen)"
        }

    # Not interested in alternatives - say goodbye
    state["phase"] = "goodbye"
    state["goodbye_scenario"] = "knockout_fail"
    logger.info("👋 Candidate not interested in alternatives")
    return {
        "action": "goodbye",
        "scenario": "knockout_fail",
        "message": "Sluit het gesprek vriendelijk af"
    }


def evaluate_open_answer(
    tool_context: ToolContext,
    quality_score: int,
    answer_summary: str,
    is_unrelated: bool = False
) -> dict:
    """
    Evaluate an open question answer and move to next or scheduling.

    Args:
        tool_context: ADK tool context for state access
        quality_score: Score from 1-5 for the answer quality
        answer_summary: Brief summary of the answer
        is_unrelated: Whether the answer was off-topic

    Returns:
        dict with evaluation details and next action
    """
    state = tool_context.state

    # Handle unrelated answer
    if is_unrelated:
        unrelated_count = state.get("unrelated_count", 0) + 1
        state["unrelated_count"] = unrelated_count
        logger.info(f"🚫 Unrelated answer in open questions: count={unrelated_count}")

        if unrelated_count >= 2:
            state["phase"] = "exited"
            state["goodbye_scenario"] = "exit"
            return {
                "action": "exit",
                "reason": "Te veel onrelateerde antwoorden",
                "message": "Interview wordt beëindigd"
            }
        return {
            "action": "repeat_question",
            "current_question": state.get("current_open_question"),
            "message": "Vraag opnieuw stellen"
        }

    # Record the answer
    open_results = state.get("open_results", [])
    open_results.append({
        "question": state.get("current_open_question"),
        "answer": answer_summary,
        "score": quality_score
    })
    state["open_results"] = open_results

    # Move to next question
    current_index = state.get("open_index", 0)
    open_total = state.get("open_total", 0)
    open_questions = state.get("open_questions", [])

    next_index = current_index + 1
    state["open_index"] = next_index

    logger.info(f"📝 Open question {current_index + 1}/{open_total} answered, score={quality_score}")

    # Check if more open questions
    if next_index < open_total and next_index < len(open_questions):
        next_q = open_questions[next_index]
        next_question = next_q if isinstance(next_q, str) else next_q.get("question", "")
        state["current_open_question"] = next_question
        return {
            "action": "next_question",
            "question_number": next_index + 1,
            "total_questions": open_total,
            "next_question": next_question,
            "message": f"Stel nu vraag {next_index + 1}: {next_question}"
        }

    # All open questions done - move to scheduling
    state["phase"] = "scheduling"
    state["candidate_qualified"] = True
    logger.info("✅ All open questions done, moving to scheduling")
    return {
        "action": "open_complete",
        "message": "Alle vragen beantwoord! Ga door naar het inplannen van een interview.",
        "next_phase": "scheduling"
    }


def complete_alternate_intake(tool_context: ToolContext) -> dict:
    """
    Complete the alternate intake questionnaire and move to goodbye.

    Args:
        tool_context: ADK tool context for state access

    Returns:
        dict confirming completion
    """
    state = tool_context.state
    state["phase"] = "goodbye"
    state["goodbye_scenario"] = "alternate"

    logger.info("📋 Alternate intake completed")
    return {
        "action": "alternate_complete",
        "message": "Bedank de kandidaat en zeg dat een recruiter contact opneemt bij een match"
    }


def exit_interview(tool_context: ToolContext, reason: str) -> dict:
    """
    Immediately exit the interview.

    Args:
        tool_context: ADK tool context for state access
        reason: Brief reason for exit

    Returns:
        dict confirming exit
    """
    state = tool_context.state
    state["phase"] = "exited"
    state["goodbye_scenario"] = "exit"
    state["exit_reason"] = reason

    logger.info(f"🚪 Interview exit: {reason}")
    return {
        "action": "exit",
        "reason": reason,
        "message": "Sluit af met één korte zin"
    }


def get_available_slots(tool_context: ToolContext) -> dict:
    """
    Get available interview time slots from the scheduling service.

    Args:
        tool_context: ADK tool context for state access

    Returns:
        dict with available slots formatted for display
    """
    state = tool_context.state

    print("🔧 [get_available_slots] Tool called!")

    # Get slots from the real scheduling service
    slot_data = scheduling_service.get_available_slots(
        days_ahead=3,
        start_offset_days=3,
    )

    # Store slots in state for later validation
    state["available_slots_data"] = [s.model_dump() for s in slot_data.slots]

    print(f"📅 [get_available_slots] Retrieved {len(slot_data.slots)} days of available slots")
    for slot in slot_data.slots:
        print(f"   - {slot.dutch_date} ({slot.date})")
    logger.info(f"📅 Retrieved {len(slot_data.slots)} days of available slots")

    # Build explicit slots list with dates for LLM
    slots_for_llm = []
    for slot in slot_data.slots:
        slots_for_llm.append({
            "date": slot.date,  # YYYY-MM-DD format
            "dutch_date": slot.dutch_date,  # e.g., "Maandag 16 februari"
            "morning_times": slot.morning,  # ["10u", "11u"]
            "afternoon_times": slot.afternoon,  # ["14u", "16u"]
        })

    return {
        "action": "slots_retrieved",
        "slots": slots_for_llm,
        "formatted_text": slot_data.formatted_text,
        "message": "Presenteer EXACT deze tijdsloten aan de kandidaat. Gebruik de dutch_date waarden letterlijk."
    }


def schedule_interview(
    tool_context: ToolContext,
    date: str,
    time: str,
) -> dict:
    """
    Schedule an interview at the chosen date and time.
    Creates a Google Calendar event if configured.

    Args:
        tool_context: ADK tool context for state access
        date: The date chosen by the candidate (e.g., "2026-02-18")
        time: The time chosen by the candidate (e.g., "10u" or "14u")

    Returns:
        dict with scheduling confirmation and calendar event details
    """
    state = tool_context.state
    conversation_id = state.get("conversation_id", "test-conversation")
    candidate_name = state.get("candidate_name", "Kandidaat")

    print(f"🔧 [schedule_interview] Tool called! date={date}, time={time}")

    # Get recruiter email from environment for calendar integration
    recruiter_email = os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")
    print(f"   Recruiter email: {recruiter_email or 'NOT SET'}")

    if recruiter_email:
        # Use async method to create calendar event
        try:
            print(f"   Creating calendar event for {candidate_name}...")
            # Check if we're already in an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an event loop - create a new thread to run the async code
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        scheduling_service.schedule_slot_async(
                            recruiter_email=recruiter_email,
                            candidate_name=candidate_name,
                            date=date,
                            time=time,
                            conversation_id=conversation_id,
                            duration_minutes=30,
                        )
                    )
                    result = future.result(timeout=30)
            except RuntimeError:
                # No running event loop - use asyncio.run directly
                result = asyncio.run(
                    scheduling_service.schedule_slot_async(
                        recruiter_email=recruiter_email,
                        candidate_name=candidate_name,
                        date=date,
                        time=time,
                        conversation_id=conversation_id,
                        duration_minutes=30,
                    )
                )
            calendar_created = result.calendar_event_id is not None
            print(f"📅 [schedule_interview] Calendar event created: {result.calendar_event_id}")
            logger.info(f"📅 Interview scheduled with calendar event: {result.calendar_event_id}")
        except Exception as e:
            print(f"❌ [schedule_interview] Failed to create calendar event: {e}")
            logger.error(f"Failed to create calendar event: {e}")
            # Fall back to simple scheduling
            result = scheduling_service.schedule_slot(
                slot=f"{date} om {time}",
                conversation_id=conversation_id,
            )
            calendar_created = False
    else:
        # No calendar integration - use simple scheduling
        result = scheduling_service.schedule_slot(
            slot=f"{date} om {time}",
            conversation_id=conversation_id,
        )
        calendar_created = False
        logger.info("📅 Interview scheduled (no calendar integration)")

    # Update state
    state["scheduled_time"] = result.slot
    state["phase"] = "completed"
    state["conversation_outcome"] = f"Interview ingepland: {result.slot}"
    state["conversation_completed"] = True
    state["candidate_qualified"] = True

    return {
        "action": "interview_scheduled",
        "confirmed": result.confirmed,
        "scheduled_time": result.slot,
        "calendar_event_created": calendar_created,
        "calendar_event_id": getattr(result, "calendar_event_id", None),
        "message": result.message
    }


def conversation_complete(tool_context: ToolContext, outcome: str) -> dict:
    """
    Signal that the conversation is complete.

    Args:
        tool_context: ADK tool context for state access
        outcome: Brief description of the outcome

    Returns:
        dict: Confirmation with status
    """
    state = tool_context.state
    state["conversation_outcome"] = outcome
    state["conversation_completed"] = True

    logger.info(f"🏁 CONVERSATION COMPLETE: {outcome}")
    return {
        "status": "success",
        "message": f"Gesprek afgerond: {outcome}",
        "completed": True
    }
