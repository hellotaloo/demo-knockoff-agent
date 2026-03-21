"""
PreScreeningTalooAgent — top-level agent for candidate pre-screening.

Wraps the existing pre-screening services, routers, and workflow handlers
with a standardized lifecycle interface. Does NOT replace existing logic —
provides a contract layer for audit, workflow, and workspace concerns.
"""

import logging
from typing import Any, Optional

from src.agents.base import AgentType, TalooAgent
from src.agents.registry import AgentRegistry
from src.models.activity import ActivityChannel, ActivityEventType, ActorType

logger = logging.getLogger(__name__)


@AgentRegistry.register
class PreScreeningTalooAgent(TalooAgent):
    """Pre-screening business agent.

    Orchestrates candidate screening across WhatsApp, voice, and web channels.
    Composed of sub-components: interview question generator, WhatsApp agent,
    voice agent, CV analyzer, transcript processor, interview analyzer.
    """

    agent_type = AgentType.PRESCREENING
    workflow_type = "pre_screening"

    async def on_start(
        self,
        candidate_id: str,
        vacancy_id: str,
        **context,
    ) -> dict:
        """Start a pre-screening session for a candidate.

        Args:
            candidate_id: The candidate UUID.
            vacancy_id: The vacancy UUID.
            **context: Must include:
                - channel: ActivityChannel (VOICE, WHATSAPP, WEB)
                - candidate_name: str
                - candidate_phone: str (optional)
                - application_id: str (optional)
                - conversation_id: str (optional)
                - is_test: bool (optional, default False)

        Returns:
            Dict with workflow_id and any additional state.
        """
        # 1. Check availability
        if not await self.check_availability():
            raise PermissionError(
                f"Pre-screening agent is not enabled for workspace {self.workspace_id}"
            )

        channel: ActivityChannel = context.get("channel", ActivityChannel.WEB)
        candidate_name: str = context.get("candidate_name", "")
        application_id: Optional[str] = context.get("application_id")

        # 2. Log start activity
        activity_metadata = {
            "channel": channel.value if isinstance(channel, ActivityChannel) else channel,
            "is_test": context.get("is_test", False),
        }
        if context.get("candidate_phone"):
            phone = context["candidate_phone"]
            activity_metadata["phone_number"] = f"+{phone[:3]} *** ** {phone[-2:]}"

        await self.log_activity(
            event_type=ActivityEventType.SCREENING_STARTED,
            candidate_id=candidate_id,
            application_id=application_id,
            vacancy_id=vacancy_id,
            channel=channel if isinstance(channel, ActivityChannel) else None,
            metadata=activity_metadata,
            summary=f"Pre-screening gestart via {channel.value if isinstance(channel, ActivityChannel) else channel}",
        )

        # 3. Create workflow
        workflow_context = {
            "candidate_id": candidate_id,
            "candidate_name": candidate_name,
            "candidate_phone": context.get("candidate_phone", ""),
            "vacancy_id": vacancy_id,
            "channel": channel.value if isinstance(channel, ActivityChannel) else channel,
        }
        if context.get("conversation_id"):
            workflow_context["conversation_id"] = context["conversation_id"]
        if application_id:
            workflow_context["application_id"] = application_id

        workflow_id = await self.create_workflow(context=workflow_context)

        logger.info(
            f"Pre-screening started: candidate={candidate_id[:8]} "
            f"vacancy={vacancy_id[:8]} workflow={workflow_id[:8]}"
        )

        return {
            "workflow_id": workflow_id,
            "candidate_id": candidate_id,
            "vacancy_id": vacancy_id,
        }

    async def on_complete(self, result: dict, **context) -> dict:
        """Complete a pre-screening session.

        Args:
            result: Must include:
                - candidate_id: str
                - vacancy_id: str
                - workflow_id: str
                - qualified: bool
                - application_id: str (optional)
                - summary: str (optional)
                - interview_slot: str (optional, ISO datetime)
            **context: Additional context (channel, etc.)

        Returns:
            The result dict, enriched with completion data.
        """
        candidate_id = result["candidate_id"]
        vacancy_id = result["vacancy_id"]
        workflow_id = result["workflow_id"]
        qualified = result.get("qualified", False)
        channel = context.get("channel")

        # 1. Log completion activity
        completion_event = ActivityEventType.QUALIFIED if qualified else ActivityEventType.DISQUALIFIED
        await self.log_activity(
            event_type=completion_event,
            candidate_id=candidate_id,
            application_id=result.get("application_id"),
            vacancy_id=vacancy_id,
            channel=channel if isinstance(channel, ActivityChannel) else None,
            metadata={
                "qualified": qualified,
                "interview_slot": result.get("interview_slot"),
            },
            summary=result.get("summary"),
        )

        # 2. Advance workflow
        await self.advance_workflow(
            workflow_id=workflow_id,
            event="screening_completed",
            payload=result,
        )

        logger.info(
            f"Pre-screening completed: candidate={candidate_id[:8]} "
            f"qualified={qualified} workflow={workflow_id[:8]}"
        )

        return result

    async def on_error(self, error: Exception, **context) -> None:
        """Handle a pre-screening error.

        Args:
            error: The exception that occurred.
            **context: Must include candidate_id, vacancy_id.
                Optional: workflow_id, application_id.
        """
        candidate_id = context.get("candidate_id", "unknown")
        vacancy_id = context.get("vacancy_id")

        await self.log_activity(
            event_type=ActivityEventType.SCREENING_ABANDONED,
            candidate_id=candidate_id,
            application_id=context.get("application_id"),
            vacancy_id=vacancy_id,
            metadata={
                "error": str(error),
                "error_type": type(error).__name__,
            },
            summary=f"Pre-screening mislukt: {type(error).__name__}",
        )

        logger.error(
            f"Pre-screening error: candidate={candidate_id[:8] if len(candidate_id) > 8 else candidate_id} "
            f"error={error}"
        )

    async def get_status(self, session_id: str) -> dict:
        """Get the current status of a pre-screening session.

        Args:
            session_id: The conversation/session ID.

        Returns:
            Dict with status, progress, timestamps.
        """
        from src.workflows.orchestrator import get_orchestrator

        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("conversation_id", session_id)

        if not workflow:
            return {"status": "not_found", "session_id": session_id}

        return {
            "status": workflow["status"],
            "step": workflow["step"],
            "workflow_id": workflow["id"],
            "created_at": workflow["created_at"],
            "context": workflow["context"],
        }
