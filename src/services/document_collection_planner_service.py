"""
Document Collection Planner Service.

Orchestrates the smart collection planner: generates a plan, stores it in the
document_collections table, and logs an activity event.

Triggered automatically when a candidacy transitions to OFFER stage.
"""
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
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

    @staticmethod
    def _calculate_sla_seconds(placement_start_date: Optional[date]) -> int:
        """
        Calculate the SLA timeout in seconds for document collection.

        Default SLA is 7 days. If the placement start date falls before that,
        the SLA is set to (start_date - 1 day) so documents are collected
        before the placement begins.
        """
        default_sla_seconds = 7 * 24 * 3600  # 7 days

        if not placement_start_date:
            return default_sla_seconds

        now = datetime.now(timezone.utc)
        placement_deadline = datetime(
            placement_start_date.year,
            placement_start_date.month,
            placement_start_date.day,
            tzinfo=timezone.utc,
        ) - timedelta(days=1)

        seconds_until_deadline = int((placement_deadline - now).total_seconds())

        if seconds_until_deadline < default_sla_seconds:
            # Ensure at least 1 hour SLA even if placement is very soon
            return max(seconds_until_deadline, 3600)

        return default_sla_seconds

    async def generate_and_store_plan(
        self,
        candidacy_id: uuid.UUID,
        candidate_id: uuid.UUID,
        vacancy_id: uuid.UUID,
        workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
        triggered_by: str = "system",
        candidacy_stage: str = "offer",
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

        # Look up placement for this candidacy (regime, start_date, create_contract)
        placement = await self.pool.fetchrow(
            """
            SELECT start_date, regime, contract_id
            FROM ats.placements
            WHERE candidate_id = $1 AND vacancy_id = $2
            ORDER BY created_at DESC LIMIT 1
            """,
            candidate_id, vacancy_id,
        )

        start_date = placement["start_date"] if placement else None
        regime = placement["regime"] if placement else None
        # Goal depends on candidacy stage:
        # - offer stage + placement → collect_and_sign (docs + contract)
        # - earlier stages → collect_basic (just docs, to win time)
        if candidacy_stage == "offer" and placement:
            goal = "collect_and_sign"
        else:
            goal = "collect_basic"

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

        # ── Step 1: Create collection row + workflow IMMEDIATELY ─────────
        # This makes the collection visible in the UI right away,
        # before the LLM generates the plan (which takes 30-60s).
        row = await self.pool.fetchrow(
            """
            INSERT INTO agents.document_collections
                (workspace_id, vacancy_id, candidate_id, candidacy_id,
                 candidate_name, candidate_phone, status, channel, goal)
            VALUES ($1, $2, $3, $4, $5, $6, 'active', 'whatsapp', $7)
            RETURNING id
            """,
            workspace_id,
            vacancy_id,
            candidate_id,
            candidacy_id,
            candidate_name,
            candidate_phone,
            goal,
        )

        collection_id = row["id"]

        logger.info(
            f"Collection row created (plan pending): collection={collection_id}, "
            f"candidacy={candidacy_id}, candidate={candidate_name}"
        )

        # Create workflow immediately so it's visible in the UI
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
                initial_step="generating_plan",
                timeout_seconds=self._calculate_sla_seconds(start_date),
            )
            logger.info(f"Created workflow {workflow_id} for document collection {collection_id}")
        except Exception as e:
            logger.error(f"Failed to create workflow for collection {collection_id}: {e}")

        # ── Step 2: Generate plan via LLM (slow, 30-60s) ────────────────
        try:
            plan = await generate_collection_plan(
                pool=self.pool,
                vacancy_id=vacancy_id,
                candidate_id=candidate_id,
                workspace_id=workspace_id,
                start_date=start_date,
                regime=regime,
            )
        except Exception as e:
            logger.error(f"Failed to generate collection plan for candidacy {candidacy_id}: {e}")
            # Collection row exists but has no plan — recruiter sees it as "pending"
            return collection_id

        # ── Step 3: Update collection with the generated plan ────────────
        # Build initial item_statuses for tasks with known schedules
        initial_item_statuses = {}
        for task in plan.get("agent_managed_tasks", []):
            task_slug = task.get("slug", "") if isinstance(task, dict) else str(task)
            if task_slug == "contract_signing_day" and start_date:
                # Day contracts are scheduled at 8:00 AM Brussels time on the start date
                from datetime import datetime, time, timezone
                from zoneinfo import ZoneInfo
                cet = ZoneInfo("Europe/Brussels")
                scheduled_dt = datetime.combine(start_date, time(8, 0), tzinfo=cet).astimezone(timezone.utc)
                initial_item_statuses[task_slug] = {
                    "status": "pending",
                    "scheduled_at": scheduled_dt.isoformat(),
                }

        agent_state = {"item_statuses": initial_item_statuses} if initial_item_statuses else None

        await self.pool.execute(
            """
            UPDATE agents.document_collections
            SET collection_plan = $1::jsonb,
                documents_required = $2::jsonb,
                agent_state = COALESCE($4::jsonb, agent_state)
            WHERE id = $3
            """,
            json.dumps(plan),
            json.dumps(plan.get("documents_to_collect", [])),
            collection_id,
            json.dumps(agent_state) if agent_state else None,
        )

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

        # Advance workflow from generating_plan → plan_generated
        try:
            orchestrator = await get_orchestrator()
            wf = await orchestrator.find_by_context("collection_id", str(collection_id))
            if wf:
                await orchestrator.service.update_step(wf["id"], "plan_generated")
        except Exception as e:
            logger.error(f"Failed to advance workflow for collection {collection_id}: {e}")

        # Send opening WhatsApp message to candidate
        if candidate_phone:
            try:
                await self._send_opening_message(
                    collection_id=collection_id,
                    plan=plan,
                    vacancy_id=vacancy_id,
                    candidate_phone=candidate_phone,
                    workspace_id=workspace_id,
                )
            except Exception as e:
                logger.error(f"Failed to send opening WhatsApp message for collection {collection_id}: {e}")

        # Advance workflow from plan_generated → collecting
        try:
            orch = await get_orchestrator()
            wf = await orch.find_by_context("collection_id", str(collection_id))
            if wf:
                await orch.service.update_step(wf["id"], "collecting")
                logger.info(f"Workflow advanced to collecting for collection {collection_id}")
            else:
                logger.warning(f"No workflow found for collection {collection_id} — cannot advance to collecting")
        except Exception as e:
            logger.error(f"Failed to advance workflow to collecting: {e}")

        return collection_id

    async def _send_opening_message(
        self,
        collection_id: uuid.UUID,
        plan: dict,
        vacancy_id: uuid.UUID,
        candidate_phone: str,
        workspace_id: uuid.UUID,
    ) -> None:
        """Create collection agent, generate opening message, and send via WhatsApp."""
        from agents.document_collection.collection import create_collection_agent
        from agents.document_collection.collection.type_cache import TypeCache
        from src.services.whatsapp_service import send_whatsapp_message

        # Load type cache
        type_cache = TypeCache(self.pool, workspace_id)
        await type_cache.ensure_loaded()

        # Fetch recruiter info for agent creation
        recruiter = await self.pool.fetchrow(
            """
            SELECT r.name, r.email, r.phone
            FROM ats.vacancies v
            JOIN ats.recruiters r ON r.id = v.recruiter_id
            WHERE v.id = $1
            """,
            vacancy_id,
        )

        agent = create_collection_agent(
            plan=plan,
            type_cache=type_cache,
            collection_id=str(collection_id),
            recruiter_name=recruiter["name"] if recruiter else "",
            recruiter_email=recruiter["email"] if recruiter else "",
            recruiter_phone=recruiter["phone"] if recruiter else "",
        )

        # Generate opening message(s)
        result = await agent.get_initial_message()
        messages = result if isinstance(result, list) else [result]

        # Send each message via WhatsApp
        for msg in messages:
            if msg:
                await send_whatsapp_message(candidate_phone, msg)

        # Store messages in session turns
        for msg in messages:
            if msg:
                await self.pool.execute(
                    """INSERT INTO agents.document_collection_session_turns
                    (conversation_id, role, message) VALUES ($1, 'agent', $2)""",
                    collection_id, msg,
                )

        # Persist agent state so the webhook can continue the conversation
        await self.pool.execute(
            """UPDATE agents.document_collections
            SET agent_state = $1::jsonb, updated_at = NOW()
            WHERE id = $2""",
            agent.state.to_json(),
            collection_id,
        )

        logger.info(f"📤 Opening WhatsApp message sent for collection {collection_id}")
