"""
Workflow PoC Service - Simple state machine to learn the pattern.

Demonstrates:
1. Storing workflow state in PostgreSQL
2. Advancing through steps based on events
3. Timer-based triggers (next_action_at column)
"""
import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


class Step(str, Enum):
    """Workflow steps."""
    WAITING = "waiting"
    COMPLETE = "complete"
    TIMED_OUT = "timed_out"


class WorkflowPocService:
    """
    Simple workflow state machine service.

    Flow:
    1. create() → Creates workflow in WAITING step, sets 1-minute timeout
    2. Either:
       a) advance(event="user_replied") → Moves to COMPLETE
       b) process_timers() → Moves to TIMED_OUT (if timeout passed)
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def ensure_table(self):
        """Create the workflow_poc table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.workflow_poc (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_type VARCHAR(50) NOT NULL,
                current_step VARCHAR(50) NOT NULL,
                status VARCHAR(20) DEFAULT 'active',
                context JSONB DEFAULT '{}',
                next_action_at TIMESTAMPTZ,
                next_action_type VARCHAR(50),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # Create index if not exists
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_workflow_poc_timers
            ON ats.workflow_poc(next_action_at)
            WHERE status = 'active' AND next_action_at IS NOT NULL;
        """)
        logger.info("workflow_poc table ensured")

    async def create(
        self,
        workflow_type: str = "ping_pong",
        context: Optional[dict] = None,
        timeout_seconds: int = 60,
    ) -> dict:
        """
        Create a new workflow instance.

        Sets a timeout timer - if no event received within timeout_seconds,
        the workflow will move to TIMED_OUT when process_timers() is called.
        """
        timeout_at = datetime.utcnow() + timedelta(seconds=timeout_seconds)

        row = await self.pool.fetchrow(
            """
            INSERT INTO ats.workflow_poc
            (workflow_type, current_step, status, context, next_action_at, next_action_type)
            VALUES ($1, $2, 'active', $3::jsonb, $4, 'timeout')
            RETURNING id, workflow_type, current_step, status, context, next_action_at, created_at
            """,
            workflow_type,
            Step.WAITING.value,
            json.dumps(context or {}),
            timeout_at,
        )

        logger.info(f"Created workflow {row['id']} with timeout at {timeout_at}")

        # Parse context - asyncpg returns JSONB as dict, but handle string case too
        context_value = row["context"]
        if isinstance(context_value, str):
            context_value = json.loads(context_value) if context_value else {}
        elif context_value is None:
            context_value = {}

        return {
            "id": str(row["id"]),
            "workflow_type": row["workflow_type"],
            "step": row["current_step"],
            "status": row["status"],
            "context": context_value,
            "timeout_at": row["next_action_at"].isoformat() if row["next_action_at"] else None,
            "created_at": row["created_at"].isoformat(),
        }

    async def get(self, workflow_id: str) -> Optional[dict]:
        """Get a workflow by ID."""
        row = await self.pool.fetchrow(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflow_poc
            WHERE id = $1
            """,
            UUID(workflow_id),
        )

        if not row:
            return None

        # Parse context - asyncpg returns JSONB as dict, but handle string case too
        context_value = row["context"]
        if isinstance(context_value, str):
            context_value = json.loads(context_value) if context_value else {}
        elif context_value is None:
            context_value = {}

        return {
            "id": str(row["id"]),
            "workflow_type": row["workflow_type"],
            "step": row["current_step"],
            "status": row["status"],
            "context": context_value,
            "next_action_at": row["next_action_at"].isoformat() if row["next_action_at"] else None,
            "next_action_type": row["next_action_type"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    async def advance(self, workflow_id: str, event: str) -> dict:
        """
        Process an event and advance the workflow.

        Events:
        - "user_replied": Moves from WAITING to COMPLETE
        """
        workflow = await self.get(workflow_id)

        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        if workflow["status"] != "active":
            raise ValueError(f"Workflow {workflow_id} is not active (status: {workflow['status']})")

        current_step = workflow["step"]
        new_step = current_step
        new_status = "active"

        # State machine logic
        if current_step == Step.WAITING.value:
            if event == "user_replied":
                new_step = Step.COMPLETE.value
                new_status = "completed"
                logger.info(f"Workflow {workflow_id}: WAITING -> COMPLETE (user replied)")

        # Update the workflow
        await self.pool.execute(
            """
            UPDATE ats.workflow_poc
            SET current_step = $2,
                status = $3,
                next_action_at = NULL,
                next_action_type = NULL,
                updated_at = NOW()
            WHERE id = $1
            """,
            UUID(workflow_id),
            new_step,
            new_status,
        )

        return {
            "id": workflow_id,
            "previous_step": current_step,
            "step": new_step,
            "status": new_status,
            "event": event,
        }

    async def process_timers(self) -> dict:
        """
        Process all pending timer actions.

        Called by Cloud Scheduler (or manually for testing).
        Finds all workflows where next_action_at <= now and triggers their actions.
        """
        now = datetime.utcnow()

        # Find workflows with pending timers
        rows = await self.pool.fetch(
            """
            SELECT id, current_step, next_action_type
            FROM ats.workflow_poc
            WHERE status = 'active'
              AND next_action_at IS NOT NULL
              AND next_action_at <= $1
            ORDER BY next_action_at
            LIMIT 100
            """,
            now,
        )

        processed = 0
        results = []

        for row in rows:
            workflow_id = str(row["id"])
            action_type = row["next_action_type"]

            try:
                if action_type == "timeout":
                    # Move to TIMED_OUT
                    await self.pool.execute(
                        """
                        UPDATE ats.workflow_poc
                        SET current_step = $2,
                            status = 'completed',
                            next_action_at = NULL,
                            next_action_type = NULL,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        row["id"],
                        Step.TIMED_OUT.value,
                    )
                    logger.info(f"Workflow {workflow_id}: Timed out")
                    results.append({"id": workflow_id, "action": "timeout", "new_step": Step.TIMED_OUT.value})
                    processed += 1

            except Exception as e:
                logger.error(f"Failed to process timer for {workflow_id}: {e}")
                results.append({"id": workflow_id, "action": action_type, "error": str(e)})

        logger.info(f"Processed {processed} timer actions")

        return {
            "processed": processed,
            "results": results,
        }

    async def list_active(self) -> list[dict]:
        """List all active workflows (for dashboard)."""
        rows = await self.pool.fetch(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflow_poc
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 50
            """,
        )

        results = []
        for row in rows:
            # Parse context - asyncpg returns JSONB as dict, but handle string case too
            context_value = row["context"]
            if isinstance(context_value, str):
                context_value = json.loads(context_value) if context_value else {}
            elif context_value is None:
                context_value = {}

            results.append({
                "id": str(row["id"]),
                "workflow_type": row["workflow_type"],
                "step": row["current_step"],
                "status": row["status"],
                "context": context_value,
                "next_action_at": row["next_action_at"].isoformat() if row["next_action_at"] else None,
                "next_action_type": row["next_action_type"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            })
        return results

    async def list_all(self) -> list[dict]:
        """List all workflows (active and completed)."""
        rows = await self.pool.fetch(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflow_poc
            ORDER BY created_at DESC
            LIMIT 100
            """,
        )

        results = []
        for row in rows:
            # Parse context - asyncpg returns JSONB as dict, but handle string case too
            context_value = row["context"]
            if isinstance(context_value, str):
                context_value = json.loads(context_value) if context_value else {}
            elif context_value is None:
                context_value = {}

            results.append({
                "id": str(row["id"]),
                "workflow_type": row["workflow_type"],
                "step": row["current_step"],
                "status": row["status"],
                "context": context_value,
                "next_action_at": row["next_action_at"].isoformat() if row["next_action_at"] else None,
                "next_action_type": row["next_action_type"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            })
        return results
