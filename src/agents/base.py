"""
TalooAgent — Abstract base class for all top-level Taloo agents.

Every top-level agent (pre-screening, document collection, and future agents)
must inherit from this class. It enforces:

1. Audit logging — standardized activity logging with workspace context
2. Workspace isolation — agent availability checks per workspace
3. Workflow integration — create and advance workflow instances
4. Candidacy transitions — stage changes with automatic activity logging
5. Lifecycle hooks — on_start, on_complete, on_error, get_status

The base class does NOT own the message loop. Each agent handles its own
channel-specific logic (WhatsApp, voice, web, etc.).
"""

import logging
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

import asyncpg

from src.models.activity import ActivityChannel, ActivityEventType, ActorType
from src.repositories.workspace_agent_availability_repo import WorkspaceAgentAvailabilityRepository
from src.services.activity_service import ActivityService
from src.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Registry of all top-level agent types."""

    PRESCREENING = "prescreening"
    DOCUMENT_COLLECTION = "document_collection"


class TalooAgent(ABC):
    """Base class for all top-level Taloo agents.

    Provides built-in methods for audit logging, workspace checks, workflow
    management, and candidacy transitions. Subclasses must implement the
    lifecycle hooks: on_start, on_complete, on_error, and get_status.

    Usage:
        class MyAgent(TalooAgent):
            agent_type = AgentType.MY_AGENT
            workflow_type = "my_workflow"

            async def on_start(self, candidate_id, vacancy_id, **context):
                ...
    """

    # --- Must be set by subclass ---
    agent_type: AgentType
    workflow_type: str

    def __init__(self, pool: asyncpg.Pool, workspace_id: uuid.UUID):
        self.pool = pool
        self.workspace_id = workspace_id
        self._activity_service = ActivityService(pool)
        self._workflow_service = WorkflowService(pool)
        self._availability_repo = WorkspaceAgentAvailabilityRepository(pool)

    # -------------------------------------------------------------------------
    # Built-in: every agent gets these
    # -------------------------------------------------------------------------

    async def check_availability(self) -> bool:
        """Check if this agent type is enabled for the workspace."""
        return await self._availability_repo.is_agent_available(
            self.workspace_id, self.agent_type.value
        )

    async def log_activity(
        self,
        event_type: ActivityEventType,
        candidate_id: str,
        application_id: Optional[str] = None,
        vacancy_id: Optional[str] = None,
        channel: Optional[ActivityChannel] = None,
        actor_type: ActorType = ActorType.AGENT,
        actor_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        summary: Optional[str] = None,
    ) -> str:
        """Log an activity event with automatic workspace and agent context.

        Wraps ActivityService.log() and injects agent_type and workspace_id
        into the metadata so every audit entry is traceable.

        Returns:
            The created activity ID.
        """
        enriched_metadata = {
            "agent_type": self.agent_type.value,
            "workspace_id": str(self.workspace_id),
            **(metadata or {}),
        }
        return await self._activity_service.log(
            candidate_id=candidate_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id or self.agent_type.value,
            application_id=application_id,
            vacancy_id=vacancy_id,
            channel=channel,
            metadata=enriched_metadata,
            summary=summary,
        )

    async def create_workflow(
        self,
        context: dict,
        initial_step: str = "in_progress",
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """Create a workflow instance for this agent run.

        Delegates to WorkflowOrchestrator.create_workflow() so that step
        configs and auto-triggers are respected.

        Args:
            context: Workflow context (candidate_id, vacancy_id, etc.)
            initial_step: Starting step (default: "in_progress")
            timeout_seconds: Override timeout (None = use step config)

        Returns:
            The created workflow ID.
        """
        from src.workflows.orchestrator import get_orchestrator

        orchestrator = await get_orchestrator()
        return await orchestrator.create_workflow(
            workflow_type=self.workflow_type,
            context=context,
            initial_step=initial_step,
            timeout_seconds=timeout_seconds,
            workspace_id=self.workspace_id,
        )

    async def advance_workflow(self, workflow_id: str, event: str, payload: Optional[dict] = None) -> dict:
        """Fire a workflow event to advance to the next step.

        Args:
            workflow_id: The workflow ID to advance.
            event: The event name (e.g. "screening_completed").
            payload: Event payload data.

        Returns:
            Handler result including next_step and any additional data.
        """
        from src.workflows.orchestrator import get_orchestrator

        orchestrator = await get_orchestrator()
        return await orchestrator.handle_event(workflow_id, event, payload or {})

    async def transition_candidacy(
        self,
        candidacy_id: uuid.UUID,
        to_stage: str,
        triggered_by: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> asyncpg.Record:
        """Transition a candidacy stage with automatic activity logging.

        Delegates to CandidacyStageTransitionService which handles:
        - State machine validation
        - Stage persistence
        - STAGE_CHANGED activity logging
        - Stage-entry triggers (e.g. document collection on OFFER)

        Args:
            candidacy_id: The candidacy UUID to transition.
            to_stage: Target stage (CandidacyStage value).
            triggered_by: Who triggered this (default: agent_type value).
            metadata: Extra data for the activity log.

        Returns:
            The updated candidacy record.
        """
        from src.models.candidacy import CandidacyStage
        from src.services.candidacy_transition_service import CandidacyStageTransitionService

        service = CandidacyStageTransitionService(self.pool)
        return await service.transition(
            candidacy_id=candidacy_id,
            to_stage=CandidacyStage(to_stage),
            triggered_by=triggered_by or self.agent_type.value,
            metadata=metadata,
        )

    # -------------------------------------------------------------------------
    # Lifecycle hooks: subclass MUST implement
    # -------------------------------------------------------------------------

    @abstractmethod
    async def on_start(self, candidate_id: str, vacancy_id: str, **context) -> dict:
        """Called when the agent begins work for a candidate.

        Implementations should:
        - Check agent availability (via self.check_availability())
        - Create a workflow (via self.create_workflow())
        - Log a start activity (via self.log_activity())
        - Return initial state dict (must include "workflow_id")
        """
        ...

    @abstractmethod
    async def on_complete(self, result: dict, **context) -> dict:
        """Called when the agent finishes its work.

        Implementations should:
        - Log a completion activity
        - Advance the workflow (via self.advance_workflow())
        - Transition candidacy if applicable
        - Return the final result dict
        """
        ...

    @abstractmethod
    async def on_error(self, error: Exception, **context) -> None:
        """Called on unrecoverable errors.

        Implementations should:
        - Log an error activity
        - Update workflow state (e.g. mark as failed)
        """
        ...

    @abstractmethod
    async def get_status(self, session_id: str) -> dict:
        """Return current agent status for frontend consumption.

        Must include at minimum: status, progress indicators, timestamps.
        """
        ...
