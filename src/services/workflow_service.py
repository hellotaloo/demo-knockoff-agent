"""
Workflow Service - State machine for managing workflow instances.

Provides:
1. Storing workflow state in PostgreSQL (ats.workflows table)
2. Advancing through steps based on events
3. Timer-based triggers (next_action_at column)
4. Context lookup for finding workflows by conversation_id, etc.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


class WorkflowService:
    """
    Workflow state machine service.

    Used by the WorkflowOrchestrator to persist and manage workflow state.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def ensure_table(self):
        """Create the workflows table if it doesn't exist."""
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS ats.workflows (
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
        # Create index for timer processing
        await self.pool.execute("""
            CREATE INDEX IF NOT EXISTS idx_workflows_timers
            ON ats.workflows(next_action_at)
            WHERE status = 'active' AND next_action_at IS NOT NULL;
        """)
        logger.info("workflows table ensured")

    async def create(
        self,
        workflow_type: str,
        context: Optional[dict] = None,
        initial_step: str = "in_progress",
        timeout_seconds: Optional[int] = None,
    ) -> dict:
        """
        Create a new workflow instance.

        Args:
            workflow_type: Type of workflow (e.g., "pre_screening")
            context: Workflow context data (conversation_id, candidate_name, etc.)
            initial_step: Starting step (default: "in_progress")
            timeout_seconds: Timeout before workflow is marked timed_out (None = no auto-timeout)

        Returns:
            Created workflow dict with id, type, step, status, context
        """
        # If timeout_seconds is provided, calculate timeout_at; otherwise no auto-timeout
        timeout_at = None
        next_action_type = None
        if timeout_seconds is not None:
            timeout_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
            next_action_type = "timeout"

        row = await self.pool.fetchrow(
            """
            INSERT INTO ats.workflows
            (workflow_type, current_step, status, context, next_action_at, next_action_type)
            VALUES ($1, $2, 'active', $3::jsonb, $4, $5)
            RETURNING id, workflow_type, current_step, status, context, next_action_at, created_at
            """,
            workflow_type,
            initial_step,
            json.dumps(context or {}),
            timeout_at,
            next_action_type,
        )

        logger.info(f"Created workflow {row['id']} type={workflow_type} step={initial_step}")

        return self._row_to_dict(row)

    async def get(self, workflow_id: str) -> Optional[dict]:
        """Get a workflow by ID."""
        row = await self.pool.fetchrow(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflows
            WHERE id = $1
            """,
            UUID(workflow_id),
        )

        if not row:
            return None

        return self._row_to_dict(row)

    async def find_by_context(self, key: str, value: str) -> Optional[dict]:
        """
        Find an active workflow by a context field value.

        Useful for looking up workflows by conversation_id, application_id, etc.

        Args:
            key: The context field name (e.g., "conversation_id")
            value: The value to match

        Returns:
            The matching workflow or None
        """
        row = await self.pool.fetchrow(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflows
            WHERE status = 'active'
              AND context->>$1 = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            key,
            value,
        )

        if not row:
            return None

        return self._row_to_dict(row)

    async def update_step(
        self,
        workflow_id: str,
        new_step: str,
        new_status: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> dict:
        """
        Update workflow step and optionally status.

        Args:
            workflow_id: The workflow ID
            new_step: The new step name
            new_status: Optional new status (default: keep current)
            timeout_seconds: Optional timeout for the new step (resets timer)

        Returns:
            Updated workflow dict
        """
        # Calculate new timeout if provided
        timeout_at = None
        if timeout_seconds is not None:
            timeout_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)

        if new_status:
            # Terminal status - clear timers
            await self.pool.execute(
                """
                UPDATE ats.workflows
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
        elif timeout_at:
            # Update step with new timeout
            await self.pool.execute(
                """
                UPDATE ats.workflows
                SET current_step = $2,
                    next_action_at = $3,
                    next_action_type = 'timeout',
                    updated_at = NOW()
                WHERE id = $1
                """,
                UUID(workflow_id),
                new_step,
                timeout_at,
            )
        else:
            # Just update step, keep existing timer
            await self.pool.execute(
                """
                UPDATE ats.workflows
                SET current_step = $2,
                    updated_at = NOW()
                WHERE id = $1
                """,
                UUID(workflow_id),
                new_step,
            )

        logger.info(f"Workflow {workflow_id}: step -> {new_step}" + (f", status -> {new_status}" if new_status else ""))

        return await self.get(workflow_id)

    async def update_context(self, workflow_id: str, updates: dict) -> dict:
        """
        Merge updates into workflow context.

        Args:
            workflow_id: The workflow ID
            updates: Dict of fields to merge into context

        Returns:
            Updated workflow dict
        """
        await self.pool.execute(
            """
            UPDATE ats.workflows
            SET context = context || $2::jsonb,
                updated_at = NOW()
            WHERE id = $1
            """,
            UUID(workflow_id),
            json.dumps(updates),
        )

        logger.info(f"Workflow {workflow_id}: context updated with {list(updates.keys())}")

        return await self.get(workflow_id)

    async def set_timer(self, workflow_id: str, delay_seconds: int, action_type: str = "timeout") -> dict:
        """
        Set a timer for a workflow.

        Args:
            workflow_id: The workflow ID
            delay_seconds: Seconds until the timer fires
            action_type: Type of action ("timeout" or "auto")

        Returns:
            Updated workflow dict
        """
        timer_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

        await self.pool.execute(
            """
            UPDATE ats.workflows
            SET next_action_at = $2,
                next_action_type = $3,
                updated_at = NOW()
            WHERE id = $1
            """,
            UUID(workflow_id),
            timer_at,
            action_type,
        )

        logger.info(f"Workflow {workflow_id}: timer set for {delay_seconds}s, action={action_type}")

        return await self.get(workflow_id)

    async def process_timers(self) -> dict:
        """
        Process all pending timer actions.

        Called by Cloud Scheduler (or manually for testing).
        Finds all workflows where next_action_at <= now.

        - "timeout" actions: Mark workflow as timed_out
        - "auto" actions: Returned in auto_triggers for caller to handle

        Returns:
            Dict with processed count, results, and auto_triggers list
        """
        now = datetime.now(timezone.utc)

        rows = await self.pool.fetch(
            """
            SELECT id, workflow_type, current_step, next_action_type
            FROM ats.workflows
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
        auto_triggers = []  # Workflows that need auto event triggered

        for row in rows:
            workflow_id = str(row["id"])
            action_type = row["next_action_type"]

            try:
                if action_type == "timeout":
                    # SLA breached - do NOT auto-complete. Item stays active and stuck.
                    # The UI will show it as stuck based on next_action_at being in the past.
                    logger.info(f"Workflow {workflow_id}: SLA breached (staying stuck until manual resolution)")
                    results.append({"id": workflow_id, "action": "sla_breached", "status": "stuck"})
                    # Don't increment processed - we're not changing anything
                    continue

                elif action_type == "auto":
                    # Clear the timer, return for caller to trigger
                    await self.pool.execute(
                        """
                        UPDATE ats.workflows
                        SET next_action_at = NULL,
                            next_action_type = NULL,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        row["id"],
                    )
                    logger.info(f"Workflow {workflow_id}: Auto trigger ready")
                    auto_triggers.append({
                        "id": workflow_id,
                        "workflow_type": row["workflow_type"],
                        "step": row["current_step"],
                    })
                    results.append({"id": workflow_id, "action": "auto", "step": row["current_step"]})
                    processed += 1

            except Exception as e:
                logger.error(f"Failed to process timer for {workflow_id}: {e}")
                results.append({"id": workflow_id, "action": action_type, "error": str(e)})

        if processed > 0:
            logger.info(f"Processed {processed} timer actions ({len(auto_triggers)} auto triggers)")

        return {
            "processed": processed,
            "results": results,
            "auto_triggers": auto_triggers,
        }

    async def get_counts(self) -> dict:
        """
        Get workflow counts for navigation sidebar.

        Returns:
            Dict with active_count (non-stuck) and stuck_count
        """
        # Stuck = SLA breached (next_action_at is in the past)
        # Active = SLA not breached yet (next_action_at is in the future or NULL)
        row = await self.pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE status = 'active'
                    AND (next_action_at IS NULL OR next_action_at > NOW())
                ) AS active_count,
                COUNT(*) FILTER (
                    WHERE status = 'active'
                    AND next_action_at IS NOT NULL
                    AND next_action_at <= NOW()
                ) AS stuck_count
            FROM ats.workflows
            WHERE status = 'active'
            """
        )

        return {
            "active": row["active_count"] if row else 0,
            "stuck": row["stuck_count"] if row else 0,
        }

    async def list_active(self) -> list[dict]:
        """List all active workflows (for dashboard)."""
        rows = await self.pool.fetch(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflows
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 50
            """,
        )

        return [self._row_to_dict(row) for row in rows]

    async def list_all(self) -> list[dict]:
        """List all workflows (active and completed)."""
        rows = await self.pool.fetch(
            """
            SELECT id, workflow_type, current_step, status, context,
                   next_action_at, next_action_type, created_at, updated_at
            FROM ats.workflows
            ORDER BY created_at DESC
            LIMIT 100
            """,
        )

        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row) -> dict:
        """Convert a database row to a workflow dict."""
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
            "next_action_at": row["next_action_at"].isoformat() if row.get("next_action_at") else None,
            "next_action_type": row.get("next_action_type"),
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }
