"""
Pre-screening WhatsApp Agent - Multi-agent architecture for candidate screening.

This agent uses a coordinator pattern with specialized sub-agents for each phase:
- WelcomeAgent: Greets the candidate
- KnockoutAgent: Asks knockout questions
- ConfirmFailAgent: Handles knockout failures
- AlternateIntakeAgent: Basic intake for non-qualifying candidates
- OpenQuestionsAgent: Qualification questions
- SchedulingAgent: Schedule interview
- GoodbyeAgent: Close conversation
- QuickExitAgent: Fast exit for off-topic responses

Usage with ADK Web:
    cd taloo-backend
    adk web pre_screening_whatsapp_agent --port 8001

The agent uses session state to track the conversation phase and pass data between sub-agents.
"""

from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import FunctionTool
from google.genai import types
from typing import Optional
from datetime import datetime
import logging

from .prompts import (
    COORDINATOR_PROMPT,
    WELCOME_PROMPT,
    KNOCKOUT_PROMPT,
    CONFIRM_FAIL_PROMPT,
    ALTERNATE_INTAKE_PROMPT,
    OPEN_QUESTIONS_PROMPT,
    SCHEDULING_PROMPT,
    GOODBYE_PROMPT,
    QUICK_EXIT_PROMPT,
)
from .tools import (
    evaluate_knockout_answer,
    knockout_failed,
    confirm_knockout_result,
    evaluate_open_answer,
    complete_alternate_intake,
    exit_interview,
    get_available_slots,
    schedule_interview,
    conversation_complete,
)
from src.utils.dutch_dates import get_dutch_date

logger = logging.getLogger(__name__)

# Model to use for all agents
MODEL = "gemini-2.5-flash"


# =============================================================================
# Tool Definitions
# =============================================================================

# Knockout tools - evaluate_knockout_answer handles everything including state updates
evaluate_knockout_tool = FunctionTool(func=evaluate_knockout_answer)
knockout_failed_tool = FunctionTool(func=knockout_failed)

# Confirmation tool
confirm_knockout_result_tool = FunctionTool(func=confirm_knockout_result)

# Open questions tool - handles state updates and progression
evaluate_open_tool = FunctionTool(func=evaluate_open_answer)

# Other tools
complete_alternate_intake_tool = FunctionTool(func=complete_alternate_intake)
exit_interview_tool = FunctionTool(func=exit_interview)

# Scheduling tools
get_available_slots_tool = FunctionTool(func=get_available_slots)
schedule_interview_tool = FunctionTool(func=schedule_interview)

conversation_complete_tool = FunctionTool(func=conversation_complete)


# =============================================================================
# Sub-Agent Definitions
# =============================================================================

welcome_agent = LlmAgent(
    name="WelcomeAgent",
    model=MODEL,
    description="Verwelkomt de kandidaat en start het screeningsproces",
    instruction=WELCOME_PROMPT,
    output_key="welcome_response",
)

knockout_agent = LlmAgent(
    name="KnockoutAgent",
    model=MODEL,
    description="Stelt knockout vragen en evalueert antwoorden",
    instruction=KNOCKOUT_PROMPT,
    tools=[
        evaluate_knockout_tool,  # Handles pass/fail/unrelated and state updates
    ],
    output_key="knockout_response",
)

confirm_fail_agent = LlmAgent(
    name="ConfirmFailAgent",
    model=MODEL,
    description="Bevestigt knockout failure en biedt alternatief",
    instruction=CONFIRM_FAIL_PROMPT,
    tools=[confirm_knockout_result_tool],
    output_key="confirm_fail_response",
)

alternate_intake_agent = LlmAgent(
    name="AlternateIntakeAgent",
    model=MODEL,
    description="Basis intake voor kandidaten die niet kwalificeren",
    instruction=ALTERNATE_INTAKE_PROMPT,
    tools=[complete_alternate_intake_tool],
    output_key="alternate_response",
)

open_questions_agent = LlmAgent(
    name="OpenQuestionsAgent",
    model=MODEL,
    description="Stelt verdiepende kwalificatievragen",
    instruction=OPEN_QUESTIONS_PROMPT,
    tools=[
        evaluate_open_tool,  # Handles evaluation, state updates, and progression
    ],
    output_key="open_response",
)

scheduling_agent = LlmAgent(
    name="SchedulingAgent",
    model=MODEL,
    description="Plant vervolginterview",
    instruction=SCHEDULING_PROMPT,
    tools=[get_available_slots_tool, schedule_interview_tool],
    output_key="scheduling_response",
)

goodbye_agent = LlmAgent(
    name="GoodbyeAgent",
    model=MODEL,
    description="Sluit gesprek af",
    instruction=GOODBYE_PROMPT,
    tools=[conversation_complete_tool],
    output_key="goodbye_response",
)

quick_exit_agent = LlmAgent(
    name="QuickExitAgent",
    model=MODEL,
    description="Snelle afsluiting bij herhaald onrelateerde antwoorden",
    instruction=QUICK_EXIT_PROMPT,
    tools=[conversation_complete_tool],
    output_key="exit_response",
)


# =============================================================================
# Demo/Test Configuration
# =============================================================================

# Default state for testing with ADK web
# In production, this would be set by the application based on vacancy config
DEFAULT_TEST_STATE = {
    # Conversation phase
    "phase": "welcome",
    "unrelated_count": 0,

    # Candidate info
    "candidate_name": "Jan",

    # Vacancy info
    "vacancy_title": "Magazijnmedewerker",
    "company_name": "ITZU",

    # Timing
    "estimated_minutes": 3,

    # Knockout questions
    "knockout_index": 0,
    "knockout_total": 2,
    "knockout_questions": [
        {
            "question": "Heb je een geldig rijbewijs B?",
            "requirement": "Kandidaat moet een geldig rijbewijs B hebben"
        },
        {
            "question": "Ben je bereid om in shiften te werken (ook weekends)?",
            "requirement": "Kandidaat moet bereid zijn om in shiften te werken inclusief weekends"
        }
    ],
    "current_knockout_question": "Heb je een geldig rijbewijs B?",
    "current_knockout_requirement": "Kandidaat moet een geldig rijbewijs B hebben",

    # Open questions
    "open_index": 0,
    "open_total": 2,
    "open_questions": [
        "Welke ervaring heb je met magazijnwerk of logistiek?",
        "Waarom wil je graag bij ons komen werken?"
    ],
    "current_open_question": "Welke ervaring heb je met magazijnwerk of logistiek?",

    # Alternate intake
    "alternate_question_index": 0,

    # Scheduling
    "available_slots": "",  # Will be populated by get_available_slots tool
    "today_date": "",  # Will be set dynamically at runtime

    # Results (filled during conversation)
    "knockout_results": [],
    "open_results": [],
    "failed_requirement": "",
    "failed_answer": "",
    "goodbye_scenario": "",
    "scheduled_time": "",
}


def get_test_state() -> dict:
    """Get a copy of the default test state for ADK web testing."""
    return DEFAULT_TEST_STATE.copy()


# =============================================================================
# State Initialization Callback
# =============================================================================

def initialize_state_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    """
    Initialize session state with default test values if not already set.
    This allows the agent to work out-of-the-box with ADK web for testing.
    """
    state = callback_context.state

    # Check if state is already initialized
    if state.get("phase"):
        logger.debug(f"State already initialized, phase={state.get('phase')}")
        return None  # Continue with normal execution

    logger.info("🚀 Initializing session state with test values...")

    # Set all state values from default test state
    for key, value in DEFAULT_TEST_STATE.items():
        state[key] = value

    # Set today's date dynamically for scheduling context
    today = datetime.now()
    state["today_date"] = f"{get_dutch_date(today)} {today.year}"

    logger.info(f"✅ State initialized for testing (today: {state['today_date']})")
    return None  # Continue with normal execution


# =============================================================================
# Coordinator Agent (Root)
# =============================================================================

# The coordinator routes to sub-agents based on the current phase
root_agent = LlmAgent(
    name="PreScreeningCoordinator",
    model=MODEL,
    description="Coördineert het screeningsproces en routeert naar sub-agents",
    instruction=COORDINATOR_PROMPT,
    before_agent_callback=initialize_state_callback,
    sub_agents=[
        welcome_agent,
        knockout_agent,
        confirm_fail_agent,
        alternate_intake_agent,
        open_questions_agent,
        scheduling_agent,
        goodbye_agent,
        quick_exit_agent,
    ],
)


# =============================================================================
# Factory Function for Production Use
# =============================================================================

def create_pre_screening_agent(
    vacancy_id: str,
    vacancy_title: str,
    company_name: str,
    knockout_questions: list[dict],
    open_questions: list[dict],
    candidate_name: str = "kandidaat",
) -> tuple[LlmAgent, dict]:
    """
    Create a pre-screening agent configured for a specific vacancy.

    Args:
        vacancy_id: The vacancy UUID
        vacancy_title: Title of the vacancy
        company_name: Company name
        knockout_questions: List of knockout questions with 'question' and 'requirement' keys
        open_questions: List of open questions (strings or dicts with 'question' key)
        candidate_name: Name of the candidate

    Returns:
        Tuple of (agent, initial_state) where initial_state should be set on the session
    """
    # Build knockout question list
    knockout_list = []
    for q in knockout_questions:
        if isinstance(q, str):
            knockout_list.append({"question": q, "requirement": q})
        else:
            knockout_list.append({
                "question": q.get("question_text") or q.get("question", ""),
                "requirement": q.get("requirement", q.get("question_text") or q.get("question", ""))
            })

    # Build open question list
    open_list = []
    for q in open_questions:
        if isinstance(q, str):
            open_list.append(q)
        else:
            open_list.append(q.get("question_text") or q.get("question", ""))

    # Calculate estimated time
    knockout_time = len(knockout_list) * 10  # ~10 sec per knockout
    open_time = len(open_list) * 25  # ~25 sec per open question
    overhead = 60  # intro + closing
    estimated_minutes = max(1, round((knockout_time + open_time + overhead) / 60))

    # Build initial state
    initial_state = {
        "phase": "welcome",
        "unrelated_count": 0,
        "candidate_name": candidate_name,
        "vacancy_title": vacancy_title,
        "company_name": company_name,
        "estimated_minutes": estimated_minutes,

        # Knockout
        "knockout_index": 0,
        "knockout_total": len(knockout_list),
        "knockout_questions": knockout_list,
        "current_knockout_question": knockout_list[0]["question"] if knockout_list else "",
        "current_knockout_requirement": knockout_list[0]["requirement"] if knockout_list else "",

        # Open questions
        "open_index": 0,
        "open_total": len(open_list),
        "open_questions": open_list,
        "current_open_question": open_list[0] if open_list else "",

        # Other
        "alternate_question_index": 0,
        "knockout_results": [],
        "open_results": [],
        "failed_requirement": "",
        "failed_answer": "",
        "goodbye_scenario": "",
        "scheduled_time": "",
        "available_slots": "",  # Should be populated when reaching scheduling phase
        "today_date": f"{get_dutch_date(datetime.now())} {datetime.now().year}",
    }

    logger.info(f"✅ Created pre-screening agent for vacancy {vacancy_id[:8]}")
    logger.info(f"   - {len(knockout_list)} knockout questions")
    logger.info(f"   - {len(open_list)} open questions")
    logger.info(f"   - Estimated duration: {estimated_minutes} minutes")

    return root_agent, initial_state
