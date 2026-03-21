"""
DocumentCollectionTalooAgent — top-level agent for document collection.

Wraps the existing document collection services, routers, and workflow handlers
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
class DocumentCollectionTalooAgent(TalooAgent):
    """Document collection business agent.

    Orchestrates document and attribute collection from candidates via WhatsApp.
    Composed of sub-components: smart collection planner, document collection
    agent (conversational), document recognition agent.
    """

    agent_type = AgentType.DOCUMENT_COLLECTION
    workflow_type = "document_collection"

    async def on_start(
        self,
        candidate_id: str,
        vacancy_id: str,
        **context,
    ) -> dict:
        """Start a document collection session for a candidate.

        Args:
            candidate_id: The candidate UUID.
            vacancy_id: The vacancy UUID.
            **context: Must include:
                - candidacy_id: str
                - candidate_name: str
                - candidate_phone: str
                - triggered_by: str (e.g. "stage_trigger:pre_screening_agent")
                Optional:
                - collection_id: str (if already created)

        Returns:
            Dict with workflow_id and any additional state.
        """
        # 1. Check availability (currently missing in doc collection — this fixes it)
        if not await self.check_availability():
            raise PermissionError(
                f"Document collection agent is not enabled for workspace {self.workspace_id}"
            )

        candidacy_id = context["candidacy_id"]
        candidate_name = context.get("candidate_name", "")
        triggered_by = context.get("triggered_by", self.agent_type.value)

        # 2. Log start activity
        await self.log_activity(
            event_type=ActivityEventType.COLLECTION_PLAN_GENERATED,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            channel=ActivityChannel.WHATSAPP,
            metadata={
                "candidacy_id": candidacy_id,
                "triggered_by": triggered_by,
            },
            summary=f"Documentverzameling gestart voor {candidate_name}",
        )

        # 3. Create workflow
        vacancy_title = await self._get_vacancy_title(vacancy_id)
        workflow_context = {
            "candidate_id": candidate_id,
            "candidate_name": candidate_name,
            "candidate_phone": context.get("candidate_phone", ""),
            "vacancy_id": vacancy_id,
            "vacancy_title": vacancy_title,
            "candidacy_id": candidacy_id,
            "triggered_by": triggered_by,
        }
        if context.get("collection_id"):
            workflow_context["collection_id"] = context["collection_id"]

        workflow_id = await self.create_workflow(
            context=workflow_context,
            initial_step="generating_plan",
        )

        logger.info(
            f"Document collection started: candidate={candidate_id[:8]} "
            f"vacancy={vacancy_id[:8]} workflow={workflow_id[:8]}"
        )

        return {
            "workflow_id": workflow_id,
            "candidate_id": candidate_id,
            "vacancy_id": vacancy_id,
            "candidacy_id": candidacy_id,
        }

    async def on_complete(self, result: dict, **context) -> dict:
        """Complete a document collection session.

        Args:
            result: Must include:
                - candidate_id: str
                - vacancy_id: str
                - workflow_id: str
                - collection_id: str
                - documents_collected: int (optional)
                - attributes_collected: int (optional)
            **context: Additional context.

        Returns:
            The result dict, enriched with completion data.
        """
        candidate_id = result["candidate_id"]
        vacancy_id = result["vacancy_id"]
        workflow_id = result["workflow_id"]

        # 1. Log completion activity
        await self.log_activity(
            event_type=ActivityEventType.DOCUMENT_VERIFIED,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            channel=ActivityChannel.WHATSAPP,
            metadata={
                "collection_id": result.get("collection_id"),
                "documents_collected": result.get("documents_collected", 0),
                "attributes_collected": result.get("attributes_collected", 0),
            },
            summary="Documentverzameling afgerond",
        )

        # 2. Advance workflow to complete
        await self.advance_workflow(
            workflow_id=workflow_id,
            event="collection_completed",
            payload=result,
        )

        logger.info(
            f"Document collection completed: candidate={candidate_id[:8]} "
            f"collection={result.get('collection_id', 'unknown')[:8]} "
            f"workflow={workflow_id[:8]}"
        )

        return result

    async def on_error(self, error: Exception, **context) -> None:
        """Handle a document collection error.

        Args:
            error: The exception that occurred.
            **context: Must include candidate_id, vacancy_id.
                Optional: workflow_id, collection_id.
        """
        candidate_id = context.get("candidate_id", "unknown")
        vacancy_id = context.get("vacancy_id")

        await self.log_activity(
            event_type=ActivityEventType.SCREENING_ABANDONED,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            channel=ActivityChannel.WHATSAPP,
            metadata={
                "error": str(error),
                "error_type": type(error).__name__,
                "collection_id": context.get("collection_id"),
            },
            summary=f"Documentverzameling mislukt: {type(error).__name__}",
        )

        logger.error(
            f"Document collection error: candidate={candidate_id[:8] if len(candidate_id) > 8 else candidate_id} "
            f"error={error}"
        )

    async def get_status(self, session_id: str) -> dict:
        """Get the current status of a document collection session.

        Args:
            session_id: The collection ID.

        Returns:
            Dict with status, progress, timestamps.
        """
        from src.workflows.orchestrator import get_orchestrator

        orchestrator = await get_orchestrator()
        workflow = await orchestrator.find_by_context("collection_id", session_id)

        if not workflow:
            return {"status": "not_found", "session_id": session_id}

        return {
            "status": workflow["status"],
            "step": workflow["step"],
            "workflow_id": workflow["id"],
            "created_at": workflow["created_at"],
            "context": workflow["context"],
        }

    async def _get_vacancy_title(self, vacancy_id: str) -> str:
        """Helper to fetch vacancy title for workflow context."""
        import uuid

        row = await self.pool.fetchrow(
            "SELECT title FROM ats.vacancies WHERE id = $1",
            uuid.UUID(vacancy_id),
        )
        return row["title"] if row else "Onbekend"
