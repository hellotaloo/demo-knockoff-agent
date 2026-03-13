"""
Document Collection Planner Service.

Orchestrates the smart collection planner: generates a plan, stores it in the
document_collections table, and logs an activity event.

Triggered automatically when a candidacy transitions to OFFER stage.
"""
import json
import logging
import uuid
from typing import Optional

import asyncpg

from src.models.activity import ActivityEventType, ActorType
from src.services.activity_service import ActivityService

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class DocumentCollectionPlannerService:
    """Generates and stores smart collection plans for candidates."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.activity_service = ActivityService(pool)

    async def generate_and_store_plan(
        self,
        candidacy_id: uuid.UUID,
        candidate_id: uuid.UUID,
        vacancy_id: uuid.UUID,
        workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
        triggered_by: str = "system",
    ) -> Optional[uuid.UUID]:
        """
        Generate a collection plan and store it as a document_collection record.

        Args:
            candidacy_id: The candidacy that triggered the plan
            candidate_id: The candidate UUID
            vacancy_id: The vacancy UUID
            workspace_id: Workspace UUID
            triggered_by: Who/what triggered this

        Returns:
            The document_collection ID, or None if generation failed
        """
        from agents.document_collection.smart_collection_planner import generate_collection_plan

        # Fetch candidate info for the record
        candidate = await self.pool.fetchrow(
            "SELECT full_name, phone FROM ats.candidates WHERE id = $1",
            candidate_id,
        )
        if not candidate:
            logger.error(f"Candidate not found: {candidate_id}")
            return None

        candidate_name = candidate["full_name"] or "Onbekend"
        candidate_phone = candidate["phone"]

        # Check if there's already an active collection for this candidacy
        existing = await self.pool.fetchrow(
            """
            SELECT id FROM agents.document_collections
            WHERE candidacy_id = $1 AND status = 'active'
            """,
            candidacy_id,
        )
        if existing:
            logger.info(f"Active collection already exists for candidacy {candidacy_id}: {existing['id']}")
            return existing["id"]

        # Generate the plan via LLM
        try:
            plan = await generate_collection_plan(
                pool=self.pool,
                vacancy_id=vacancy_id,
                candidate_id=candidate_id,
                workspace_id=workspace_id,
            )
        except Exception as e:
            logger.error(f"Failed to generate collection plan for candidacy {candidacy_id}: {e}")
            return None

        # Store the plan as a new document_collection record
        row = await self.pool.fetchrow(
            """
            INSERT INTO agents.document_collections
                (workspace_id, vacancy_id, candidate_id, candidacy_id,
                 candidate_name, candidate_phone, status, channel,
                 collection_plan, documents_required)
            VALUES ($1, $2, $3, $4, $5, $6, 'active', 'whatsapp', $7::jsonb, $8::jsonb)
            RETURNING id
            """,
            workspace_id,
            vacancy_id,
            candidate_id,
            candidacy_id,
            candidate_name,
            candidate_phone,
            json.dumps(plan),
            json.dumps(plan.get("documents_to_collect", [])),
        )

        collection_id = row["id"]
        summary = plan.get("summary", "Verzamelplan gegenereerd")

        logger.info(
            f"Collection plan stored: collection={collection_id}, "
            f"candidacy={candidacy_id}, candidate={candidate_name}"
        )

        # Log activity
        try:
            await self.activity_service.log(
                candidate_id=str(candidate_id),
                event_type=ActivityEventType.COLLECTION_PLAN_GENERATED,
                vacancy_id=str(vacancy_id),
                actor_type=ActorType.AGENT,
                metadata={
                    "collection_id": str(collection_id),
                    "candidacy_id": str(candidacy_id),
                    "documents_count": len(plan.get("documents_to_collect", [])),
                    "attributes_count": len(plan.get("attributes_to_collect", [])),
                    "steps_count": len(plan.get("conversation_steps", [])),
                    "triggered_by": triggered_by,
                },
                summary=summary,
            )
        except Exception as e:
            logger.error(f"Failed to log activity for collection plan: {e}")

        # Create workflow to track the document collection
        try:
            from src.workflows import get_orchestrator

            vacancy_row = await self.pool.fetchrow(
                "SELECT title FROM ats.vacancies WHERE id = $1", vacancy_id
            )
            vacancy_title = vacancy_row["title"] if vacancy_row else "Onbekend"

            orchestrator = await get_orchestrator()
            workflow_id = await orchestrator.create_workflow(
                workflow_type="document_collection",
                context={
                    "collection_id": str(collection_id),
                    "candidacy_id": str(candidacy_id),
                    "candidate_id": str(candidate_id),
                    "candidate_name": candidate_name,
                    "candidate_phone": candidate_phone,
                    "vacancy_id": str(vacancy_id),
                    "vacancy_title": vacancy_title,
                    "triggered_by": triggered_by,
                },
                initial_step="plan_generated",
                timeout_seconds=7 * 24 * 3600,  # 7 day SLA for document collection
            )
            logger.info(f"Created workflow {workflow_id} for document collection {collection_id}")
        except Exception as e:
            logger.error(f"Failed to create workflow for collection {collection_id}: {e}")

        return collection_id
