"""
VAPI Service - Voice AI Platform Integration.

Handles outbound calls via VAPI's squad-based voice agents.
Injects dynamic prompts with questions at call time (Full Prompt Override approach).
"""
import os
import logging
from typing import Optional
from datetime import datetime

from src.services.vapi_prompts import (
    build_frontline_prompt,
    build_interviewer_short_prompt,
    build_interviewer_long_prompt,
    build_end_call_prompt,
    build_scheduler_prompt,
)

logger = logging.getLogger(__name__)


def get_dutch_greeting() -> str:
    """
    Get appropriate Dutch greeting based on current time.

    Returns:
        str: "Goedemorgen" (6-12), "Goeiemiddag" (12-18), or "Goeieavond" (18-6)
    """
    hour = datetime.now().hour
    if 6 <= hour < 12:
        return "Goedemorgen"
    elif 12 <= hour < 18:
        return "Goeiemiddag"
    else:
        return "Goeieavond"


class VapiService:
    """
    Service for interacting with VAPI voice AI platform.

    Uses the VAPI server SDK to create outbound calls with a pre-configured squad.
    Injects dynamic prompts with questions at call time.
    """

    def __init__(self):
        """Initialize VAPI client with API key from environment."""
        from vapi import Vapi

        self.api_key = os.environ.get("VAPI_API_KEY")
        if not self.api_key:
            raise RuntimeError("VAPI_API_KEY environment variable is required")

        self.squad_id = os.environ.get("VAPI_SQUAD_ID", "c43899f8-59fa-4886-85d6-02bed3ed325d")
        self.phone_number_id = os.environ.get("VAPI_PHONE_NUMBER_ID")
        self.server_url = os.environ.get("VAPI_SERVER_URL")  # Environment-specific webhook URL

        if not self.phone_number_id:
            raise RuntimeError("VAPI_PHONE_NUMBER_ID environment variable is required")

        # Assistant IDs from VAPI squad for prompt overrides
        # These are needed to inject custom prompts per assistant
        self.assistant_ids = {
            "frontline": os.environ.get("VAPI_FRONTLINE_ID", ""),
            "interviewer_knockout": os.environ.get("VAPI_INTERVIEWER_KNOCKOUT_ID", ""),
            "interviewer_qualify": os.environ.get("VAPI_INTERVIEWER_QUALIFY_ID", ""),
            "end_call": os.environ.get("VAPI_END_CALL_ID", ""),
            "scheduler": os.environ.get("VAPI_SCHEDULER_ID", ""),
        }

        self.client = Vapi(token=self.api_key)
        logger.info(f"VAPI service initialized with squad_id={self.squad_id}, server_url={self.server_url}")

    def create_outbound_call(
        self,
        to_number: str,
        first_name: str,
        candidate_id: str,
        vacancy_id: str,
        vacancy_title: str = "",
        knockout_questions: Optional[list[dict]] = None,
        qualification_questions: Optional[list[dict]] = None,
        pre_screening_id: Optional[str] = None,
    ) -> dict:
        """
        Create an outbound call using the VAPI squad with dynamic prompts.

        Args:
            to_number: Phone number in E.164 format (e.g., "+32412345678")
            first_name: Candidate's first name (for greeting)
            candidate_id: UUID of the candidate record
            vacancy_id: UUID of the vacancy
            vacancy_title: Title of the vacancy for context
            knockout_questions: List of knockout questions with question_text and ideal_answer
            qualification_questions: List of qualification questions
            pre_screening_id: Optional pre-screening UUID for correlation

        Returns:
            dict: Response containing:
                - success: bool
                - message: str
                - call_id: str (VAPI call ID for correlation)
                - status: str

        Raises:
            RuntimeError: If VAPI API call fails
        """
        logger.info(f"Creating VAPI outbound call to {to_number} with squad {self.squad_id}")

        # Default empty lists if not provided
        knockout_questions = knockout_questions or []
        qualification_questions = qualification_questions or []

        try:
            greeting = get_dutch_greeting()

            # Format questions as strings for LiquidJS variables
            # VAPI dashboard prompts use {{knockout_questions}} and {{qualification_questions}}
            # Double newline between questions for better readability in voice prompts
            ko_formatted = "\n\n".join([
                f"{i+1}. {q['question_text']}"
                for i, q in enumerate(knockout_questions)
            ]) if knockout_questions else ""

            qual_formatted = "\n\n".join([
                f"{i+1}. {q['question_text']}"
                for i, q in enumerate(qualification_questions)
            ]) if qualification_questions else ""

            # Extract first questions for first message use
            first_knockout_question = knockout_questions[0]["question_text"] if knockout_questions else ""

            # Build first qualification question with contextual prefix
            if qualification_questions:
                first_q = qualification_questions[0]["question_text"]
                first_q_lower = first_q.lower()
                # Check if question is about experience
                experience_keywords = ["ervaring", "experience", "gewerkt", "worked", "gedaan", "functie", "job", "werk"]
                if any(keyword in first_q_lower for keyword in experience_keywords):
                    first_qualification_question = f"We beginnen met je ervaring. {first_q}"
                else:
                    first_qualification_question = f"Eerste vraag. {first_q}"
            else:
                first_qualification_question = ""

            # Build variable values - these are injected into dashboard prompts via LiquidJS
            variable_values = {
                "greeting": greeting,
                "first_name": first_name,
                "candidate_id": candidate_id,
                "vacancy_id": vacancy_id,
                "vacancy_title": vacancy_title,
                "knockout_questions": ko_formatted,
                "qualification_questions": qual_formatted,
                "first_knockout_question": first_knockout_question,
                "first_qualification_question": first_qualification_question,
            }
            if pre_screening_id:
                variable_values["pre_screening_id"] = pre_screening_id

            logger.info(f"VAPI call variables: greeting={greeting}, first_name={first_name}, "
                       f"knockout_questions={len(knockout_questions)} items, "
                       f"qualification_questions={len(qualification_questions)} items")

            # Build assistant overrides (applies to all assistants in squad)
            assistant_overrides = {
                "variableValues": variable_values,
            }

            # Override server URL if configured (for environment-specific webhooks)
            if self.server_url:
                assistant_overrides["server"] = {
                    "url": self.server_url,
                    "timeoutSeconds": 20,
                }
                logger.info(f"Using environment-specific server URL: {self.server_url}")

            # Build call creation parameters
            # Note: Cannot use squad.membersOverrides with squad_id - use variableValues instead
            call_params = {
                "squad_id": self.squad_id,
                "phone_number_id": self.phone_number_id,
                "customer": {"number": to_number},
                "assistant_overrides": assistant_overrides,
            }

            # Create the outbound call via VAPI SDK
            response = self.client.calls.create(**call_params)

            result = {
                "success": True,
                "message": "Call initiated successfully",
                "call_id": response.id,
                "status": response.status if hasattr(response, "status") else "queued",
            }

            logger.info(f"VAPI call created: {result}")
            return result

        except Exception as e:
            logger.error(f"VAPI call creation failed: {e}")
            return {
                "success": False,
                "message": str(e),
                "call_id": None,
                "status": "failed",
            }

    def create_web_call_config(
        self,
        first_name: str,
        vacancy_id: str,
        vacancy_title: str,
        knockout_questions: Optional[list[dict]] = None,
        qualification_questions: Optional[list[dict]] = None,
        pre_screening_id: Optional[str] = None,
    ) -> dict:
        """
        Create configuration for VAPI web call (browser-based simulation).

        This is used for testing voice calls in the browser without a real phone call.
        Returns the squad_id and assistant_overrides for the frontend to use with
        vapi.start(null, assistantOverrides, squadId).

        Args:
            first_name: Candidate's first name (for greeting)
            vacancy_id: UUID of the vacancy
            vacancy_title: Title of the vacancy for context
            knockout_questions: List of knockout questions with question_text and ideal_answer
            qualification_questions: List of qualification questions
            pre_screening_id: Optional pre-screening UUID

        Returns:
            dict with squad_id and assistant_overrides (contains variableValues)
        """
        knockout_questions = knockout_questions or []
        qualification_questions = qualification_questions or []

        greeting = get_dutch_greeting()

        # Format questions as strings for LiquidJS variables (same as create_outbound_call)
        ko_formatted = "\n\n".join([
            f"{i+1}. {q['question_text']}"
            for i, q in enumerate(knockout_questions)
        ]) if knockout_questions else ""

        qual_formatted = "\n\n".join([
            f"{i+1}. {q['question_text']}"
            for i, q in enumerate(qualification_questions)
        ]) if qualification_questions else ""

        # Extract first questions for first message use
        first_knockout_question = knockout_questions[0]["question_text"] if knockout_questions else ""

        # Build first qualification question with contextual prefix
        if qualification_questions:
            first_q = qualification_questions[0]["question_text"]
            first_q_lower = first_q.lower()
            experience_keywords = ["ervaring", "experience", "gewerkt", "worked", "gedaan", "functie", "job", "werk"]
            if any(keyword in first_q_lower for keyword in experience_keywords):
                first_qualification_question = f"We beginnen met je ervaring. {first_q}"
            else:
                first_qualification_question = f"Eerste vraag. {first_q}"
        else:
            first_qualification_question = ""

        # Build variable values for LiquidJS templates in VAPI dashboard prompts
        variable_values = {
            "greeting": greeting,
            "first_name": first_name,
            "candidate_id": "web-simulation",  # Dummy ID for web calls
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy_title,
            "knockout_questions": ko_formatted,
            "qualification_questions": qual_formatted,
            "first_knockout_question": first_knockout_question,
            "first_qualification_question": first_qualification_question,
        }
        if pre_screening_id:
            variable_values["pre_screening_id"] = pre_screening_id

        assistant_overrides = {
            "variableValues": variable_values,
        }

        # Override server URL if configured (for environment-specific webhooks)
        if self.server_url:
            assistant_overrides["server"] = {
                "url": self.server_url,
                "timeoutSeconds": 20,
            }

        logger.info(f"Web call config created: greeting={greeting}, first_name={first_name}, "
                   f"knockout_questions={len(knockout_questions)} items, "
                   f"qualification_questions={len(qualification_questions)} items")

        return {
            "squad_id": self.squad_id,
            "assistant_overrides": assistant_overrides,
        }


# Singleton instance for convenience
_vapi_service: Optional[VapiService] = None


def get_vapi_service() -> VapiService:
    """Get or create the VAPI service singleton."""
    global _vapi_service
    if _vapi_service is None:
        _vapi_service = VapiService()
    return _vapi_service
