"""
Candidacy stage transition service.

Owns all logic for moving a candidacy through the recruitment pipeline:
  - Validates that the transition is allowed (state machine)
  - Persists the new stage + resets stage_updated_at
  - Logs a STAGE_CHANGED activity event
  - Fires optional stage-entry side effects (agent triggers)

Two directions are supported:
  1. Agent → Stage:  call transition() after a workflow event fires
  2. Stage → Agent:  register a handler in STAGE_ENTRY_TRIGGERS

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

# ---------------------------------------------------------------------------
# Stage-entry triggers: functions called (as background tasks) after a stage
# transition. Each function receives the candidacy record and optional metadata.
#
# Agents own the early funnel:
#   PRE_SCREENING  → trigger outbound screening (voice / whatsapp)
#   INTERVIEW_PLANNED → trigger scheduling agent (not built yet)
# ---------------------------------------------------------------------------


async def _trigger_outbound_screening(candidacy: asyncpg.Record, metadata: dict) -> None:
    """
    Trigger an outbound screening call/chat when a candidacy enters PRE_SCREENING.

    TODO: extract the shared initiation logic from src/routers/outbound.py into a
    service method and call it here. For now this is a stub that logs intent.
    """
    logger.info(
        f"[STAGE_TRIGGER] PRE_SCREENING entered for candidacy {candidacy['id']} "
        f"(candidate={candidacy['candidate_id']}, vacancy={candidacy['vacancy_id']}) "
        f"— outbound screening trigger not yet wired (implement when ready)"
    )


async def _trigger_scheduling_agent(candidacy: asyncpg.Record, metadata: dict) -> None:
    """
    Trigger the interview scheduling agent when a candidacy enters INTERVIEW_PLANNED.
    Stub — scheduling agent not yet built.
    """
    logger.info(
        f"[STAGE_TRIGGER] INTERVIEW_PLANNED entered for candidacy {candidacy['id']} "
        f"— scheduling agent trigger not yet wired"
    )


# Map: stage → async trigger function(candidacy, metadata)
STAGE_ENTRY_TRIGGERS: dict[CandidacyStage, callable] = {
    CandidacyStage.PRE_SCREENING: _trigger_outbound_screening,
    CandidacyStage.INTERVIEW_PLANNED: _trigger_scheduling_agent,
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

        # 5. Fire stage-entry trigger (if any) as a background coroutine
        trigger = STAGE_ENTRY_TRIGGERS.get(to_stage)
        if trigger:
            asyncio.create_task(trigger(updated, metadata or {}))

        return updated
