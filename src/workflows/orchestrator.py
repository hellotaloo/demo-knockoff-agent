"""
Workflow Orchestrator - Central event router for all workflows.

The orchestrator is the single entry point for:
1. Creating new workflows (from outbound API, etc.)
2. Handling events (from VAPI webhook, WhatsApp agent, etc.)
3. Routing events to the correct handler based on workflow_type + step + event

Key principle: Routers are thin - they validate input and forward events here.
"""
import logging
from typing import Callable, Optional

import asyncpg

from src.database import get_db_pool
from src.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)

# Singleton instance
_orchestrator: Optional["WorkflowOrchestrator"] = None


async def get_orchestrator() -> "WorkflowOrchestrator":
    """Get the singleton WorkflowOrchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        pool = await get_db_pool()
        _orchestrator = WorkflowOrchestrator(pool)
        await _orchestrator.initialize()
    return _orchestrator


class WorkflowOrchestrator:
    """
    Central orchestrator for all workflows.

    Routes events to handlers based on (workflow_type, current_step, event) tuple.
    Handlers do the actual work (process transcript, send notifications, etc.)
    and return the next step to transition to.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.service = WorkflowService(pool)
        # Handler registry: (workflow_type, step, event) -> handler function
        self.handlers: dict[tuple[str, str, str], Callable] = {}

    async def initialize(self):
        """Initialize the orchestrator (ensure table exists, register handlers)."""
        await self.service.ensure_table()
        self._register_handlers()
        logger.info("WorkflowOrchestrator initialized")

    def _register_handlers(self):
        """Register all workflow handlers."""
        # Import here to avoid circular imports
        from src.workflows.pre_screening import (
            STEP_CONFIG as PRE_SCREENING_STEP_CONFIG,
            handle_screening_completed,
            handle_send_notifications,
        )

        # Pre-screening workflow handlers
        # Both voice and WhatsApp use the same handlers - channel is in context
        self.handlers[("pre_screening", "in_progress", "screening_completed")] = handle_screening_completed

        # Auto-triggered after screening_completed advances to "processed"
        self.handlers[("pre_screening", "processed", "auto")] = handle_send_notifications

        # Step config per workflow type (for timeouts)
        self.step_configs = {
            "pre_screening": PRE_SCREENING_STEP_CONFIG,
        }

        logger.info(f"Registered {len(self.handlers)} workflow handlers")

    async def create_workflow(
        self,
        workflow_type: str,
        context: dict,
        initial_step: str = "in_progress",
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """
        Create a new workflow instance.

        Args:
            workflow_type: Type of workflow (e.g., "pre_screening")
            context: Workflow context (conversation_id, candidate_name, etc.)
            initial_step: Starting step (default: "in_progress")
            timeout_seconds: Override timeout (default: use step config)

        Returns:
            The created workflow ID
        """
        # Use provided timeout, or fall back to step config, or default to 4 hours
        if timeout_seconds is None:
            timeout_seconds = self._get_step_timeout(workflow_type, initial_step)
        if timeout_seconds is None:
            timeout_seconds = 4 * 3600  # Default 4 hour SLA

        workflow = await self.service.create(
            workflow_type=workflow_type,
            context=context,
            initial_step=initial_step,
            timeout_seconds=timeout_seconds,
        )
        logger.info(
            f"🆕 WORKFLOW CREATED: {workflow_type} | step={initial_step} | SLA={timeout_seconds}s | "
            f"id={workflow['id'][:8]} | context={list(context.keys())}"
        )
        return workflow["id"]

    async def handle_event(
        self,
        workflow_id: str,
        event: str,
        payload: dict,
    ) -> dict:
        """
        Handle an event for a workflow.

        Looks up the handler based on (workflow_type, current_step, event),
        executes it, and advances the workflow to the next step.

        Args:
            workflow_id: The workflow ID
            event: The event name (e.g., "screening_completed")
            payload: Event payload data

        Returns:
            Handler result including next_step and any additional data
        """
        workflow = await self.service.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        if workflow["status"] != "active":
            logger.warning(f"Workflow {workflow_id} is not active (status: {workflow['status']})")
            return {"error": "Workflow not active", "status": workflow["status"]}

        handler_key = (workflow["workflow_type"], workflow["step"], event)
        handler = self.handlers.get(handler_key)

        if not handler:
            logger.warning(f"No handler registered for {handler_key}")
            return {"error": f"No handler for {handler_key}"}

        logger.info(
            f"🔄 WORKFLOW EVENT: {workflow['workflow_type']} | "
            f"step={workflow['step']} | event={event} | id={workflow_id[:8]}"
        )

        # Execute handler
        result = await handler(self, workflow, payload)

        # Advance workflow if handler returned next_step
        if result.get("next_step"):
            new_status = result.get("new_status")
            next_step = result["next_step"]

            # Look up timeout for the new step
            timeout_seconds = self._get_step_timeout(workflow["workflow_type"], next_step)
            timeout_info = f", timeout={timeout_seconds}s" if timeout_seconds else ""
            status_info = f" (status → {new_status})" if new_status else ""

            logger.info(
                f"➡️  WORKFLOW TRANSITION: {workflow['step']} → {next_step}{status_info}{timeout_info} | "
                f"id={workflow_id[:8]}"
            )

            await self.service.update_step(
                workflow_id,
                next_step,
                new_status,
                timeout_seconds=timeout_seconds,
            )

            # Check for auto-triggered handlers on the new step
            await self._check_auto_handlers(workflow_id, workflow["workflow_type"], next_step)

        return result

    async def _check_auto_handlers(self, workflow_id: str, workflow_type: str, step: str):
        """
        Check if there's an auto-triggered handler for the new step.

        Auto handlers are triggered immediately after a step transition,
        unless auto_delay_seconds is configured - then a timer is set.
        """
        auto_key = (workflow_type, step, "auto")
        if auto_key not in self.handlers:
            return

        # Check if there's a delay configured for this step
        delay_seconds = self._get_step_auto_delay(workflow_type, step)

        if delay_seconds and delay_seconds > 0:
            # Set a timer - the ticker will trigger the auto handler
            logger.info(
                f"⏳ AUTO-DELAY: {workflow_type} | step={step} | delay={delay_seconds}s | "
                f"id={workflow_id[:8]}"
            )
            await self.service.set_timer(workflow_id, delay_seconds, "auto")
        else:
            # Trigger immediately
            logger.info(f"🤖 AUTO-TRIGGER: {workflow_type} | step={step} | id={workflow_id[:8]}")
            await self.handle_event(workflow_id, "auto", {})

    def _get_step_timeout(self, workflow_type: str, step: str) -> Optional[int]:
        """
        Get the timeout in seconds for a workflow step.

        Looks up the step config for the workflow type.
        Returns None for terminal states (no timeout needed).
        """
        step_config = self.step_configs.get(workflow_type, {})
        config = step_config.get(step, {})
        return config.get("timeout_seconds")

    def _get_step_auto_delay(self, workflow_type: str, step: str) -> Optional[int]:
        """
        Get the auto-trigger delay in seconds for a workflow step.

        If set, auto handlers will be delayed by this amount instead of
        triggering immediately.
        """
        step_config = self.step_configs.get(workflow_type, {})
        config = step_config.get(step, {})
        return config.get("auto_delay_seconds")

    async def find_by_context(self, key: str, value: str) -> Optional[dict]:
        """
        Find an active workflow by a context field.

        Args:
            key: Context field name (e.g., "conversation_id")
            value: Value to match

        Returns:
            The matching workflow or None
        """
        return await self.service.find_by_context(key, value)

    async def update_context(self, workflow_id: str, updates: dict) -> dict:
        """
        Update workflow context with new data.

        Args:
            workflow_id: The workflow ID
            updates: Dict of fields to merge into context

        Returns:
            Updated workflow
        """
        return await self.service.update_context(workflow_id, updates)

    async def get_workflow(self, workflow_id: str) -> Optional[dict]:
        """Get a workflow by ID."""
        return await self.service.get(workflow_id)
