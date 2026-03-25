"""
Candidacy stage transition service.

Owns all logic for moving a candidacy through the recruitment pipeline:
  - Validates that the transition is allowed (state machine)
  - Persists the new stage + resets stage_updated_at
  - Logs a STAGE_CHANGED activity event
  - Fires stage-entry agent triggers (e.g. document collection on OFFER)

Usage:
    service = CandidacyStageTransitionService(pool)
    updated = await service.transition(
        candidacy_id=uuid.UUID("..."),
        to_stage=CandidacyStage.QUALIFIED,
        triggered_by="pre_screening_agent",
        metadata={"application_id": "..."},
    )
"""
import asyncio
import logging
import uuid
from typing import Optional

import asyncpg

from src.exceptions import InvalidTransitionError, NotFoundError
from src.models.activity import ActivityEventType, ActorType
from src.models.candidacy import CandidacyStage
from src.repositories.candidacy_repo import CandidacyRepository
from src.services.activity_service import ActivityService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine: maps each stage to the set of stages it may transition into.
# Terminal stages (PLACED, REJECTED, WITHDRAWN) have no allowed forward moves.
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[CandidacyStage, list[CandidacyStage]] = {
    CandidacyStage.NEW: [
        CandidacyStage.PRE_SCREENING,
        CandidacyStage.REJECTED,
        CandidacyStage.WITHDRAWN,
    ],
    CandidacyStage.PRE_SCREENING: [
        CandidacyStage.QUALIFIED,
        CandidacyStage.INTERVIEW_PLANNED,
        CandidacyStage.REJECTED,
        CandidacyStage.WITHDRAWN,
    ],
    CandidacyStage.QUALIFIED: [
        CandidacyStage.INTERVIEW_PLANNED,
        CandidacyStage.REJECTED,
        CandidacyStage.WITHDRAWN,
    ],
    CandidacyStage.INTERVIEW_PLANNED: [
        CandidacyStage.INTERVIEW_DONE,
        CandidacyStage.REJECTED,
        CandidacyStage.WITHDRAWN,
    ],
    CandidacyStage.INTERVIEW_DONE: [
        CandidacyStage.OFFER,
        CandidacyStage.REJECTED,
        CandidacyStage.WITHDRAWN,
    ],
    CandidacyStage.OFFER: [
        CandidacyStage.PLACED,
        CandidacyStage.REJECTED,
        CandidacyStage.WITHDRAWN,
    ],
    # Terminal stages — no transitions allowed
    CandidacyStage.PLACED: [],
    CandidacyStage.REJECTED: [],
    CandidacyStage.WITHDRAWN: [],
}

class CandidacyStageTransitionService:
    """
    Validates and executes candidacy stage transitions.

    Always use this service (never call repo.update_stage directly) so that:
    - Transitions are validated against the state machine
    - Activities are always logged
    - Stage-entry agent triggers fire automatically
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = CandidacyRepository(pool)
        self.activity_service = ActivityService(pool)

    async def transition(
        self,
        candidacy_id: uuid.UUID,
        to_stage: CandidacyStage,
        triggered_by: str,
        metadata: Optional[dict] = None,
    ) -> asyncpg.Record:
        """
        Transition a candidacy to a new stage.

        Args:
            candidacy_id: The candidacy to transition.
            to_stage: The target stage.
            triggered_by: Who/what triggered this (e.g. "pre_screening_agent", "recruiter").
            metadata: Optional extra data stored in the activity log.

        Returns:
            The updated candidacy record (id, stage, candidate_id, vacancy_id, ...).

        Raises:
            NotFoundError: If the candidacy doesn't exist.
            InvalidTransitionError: If the transition is not allowed by the state machine.
        """
        # 1. Load current state
        row = await self.repo.get_by_id(candidacy_id)
        if row is None:
            raise NotFoundError("Candidacy", str(candidacy_id))

        current_stage = CandidacyStage(row["stage"])

        # 2. Validate
        allowed = VALID_TRANSITIONS.get(current_stage, [])
        if to_stage not in allowed:
            raise InvalidTransitionError(current_stage.value, to_stage.value)

        # 3. Persist
        updated = await self.repo.update_stage(candidacy_id, to_stage.value)

        logger.info(
            f"Stage transition: candidacy={candidacy_id} "
            f"{current_stage.value} → {to_stage.value} (by={triggered_by})"
        )

        # 4. Log activity
        actor_type = ActorType.AGENT if "agent" in triggered_by else ActorType.RECRUITER
        try:
            await self.activity_service.log(
                candidate_id=str(row["candidate_id"]),
                event_type=ActivityEventType.STAGE_CHANGED,
                actor_type=actor_type,
                vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
                metadata={
                    "from_stage": current_stage.value,
                    "to_stage": to_stage.value,
                    "triggered_by": triggered_by,
                    **(metadata or {}),
                },
                summary=f"Stage gewijzigd: {current_stage.value} → {to_stage.value}",
            )
        except Exception as e:
            # Don't fail the transition if activity logging fails
            logger.error(f"Failed to log STAGE_CHANGED activity for candidacy {candidacy_id}: {e}")

        # 5. Fire stage-entry triggers (background — don't block the transition)
        asyncio.create_task(
            self._fire_stage_triggers(
                candidacy_id=candidacy_id,
                to_stage=to_stage,
                candidate_id=row["candidate_id"],
                vacancy_id=row["vacancy_id"],
                triggered_by=triggered_by,
            )
        )

        return updated

    async def _fire_stage_triggers(
        self,
        candidacy_id: uuid.UUID,
        to_stage: CandidacyStage,
        candidate_id: uuid.UUID,
        vacancy_id: Optional[uuid.UUID],
        triggered_by: str,
    ) -> None:
        """
        Fire any agent triggers associated with entering a stage.

        Runs as a background task so it doesn't block the stage transition response.
        """
        try:
            if to_stage == CandidacyStage.OFFER and vacancy_id:
                await self._trigger_document_collection(
                    candidacy_id=candidacy_id,
                    candidate_id=candidate_id,
                    vacancy_id=vacancy_id,
                    triggered_by=triggered_by,
                )
        except Exception as e:
            logger.error(f"Stage trigger failed for candidacy {candidacy_id} → {to_stage.value}: {e}")

    async def _trigger_document_collection(
        self,
        candidacy_id: uuid.UUID,
        candidate_id: uuid.UUID,
        vacancy_id: uuid.UUID,
        triggered_by: str,
    ) -> None:
        """Generate a smart collection plan when a candidacy enters OFFER stage."""
        # Check if the document collection agent is active for this vacancy
        va = await self.pool.fetchrow(
            "SELECT status FROM ats.vacancy_agents WHERE vacancy_id = $1 AND agent_type = 'document_collection'",
            vacancy_id,
        )
        if not va or va["status"] not in ("generated", "published"):
            logger.info(f"Document collection agent not active for vacancy {vacancy_id}, skipping")
            return

        from src.services.document_collection_planner_service import DocumentCollectionPlannerService

        logger.info(f"Triggering document collection planner for candidacy {candidacy_id}")

        # Resolve workspace_id from vacancy
        vacancy_row = await self.pool.fetchrow(
            "SELECT workspace_id FROM ats.vacancies WHERE id = $1", vacancy_id
        )
        if not vacancy_row:
            logger.error(f"Vacancy not found for document collection trigger: {vacancy_id}")
            return

        planner = DocumentCollectionPlannerService(self.pool)
        collection_id = await planner.generate_and_store_plan(
            candidacy_id=candidacy_id,
            candidate_id=candidate_id,
            vacancy_id=vacancy_id,
            workspace_id=vacancy_row["workspace_id"],
            triggered_by=f"stage_trigger:{triggered_by}",
            candidacy_stage="offer",
        )

        if collection_id:
            logger.info(f"Document collection plan created: {collection_id} for candidacy {candidacy_id}")
        else:
            logger.warning(f"Document collection plan generation failed for candidacy {candidacy_id}")
