"""
Activities Router - Table view of all active agent tasks.

Shows a unified table of what agents are working on, with stuck detection.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from src.database import get_db_pool
from src.services.workflow_service import WorkflowService
from src.workflows.pre_screening import STEP_CONFIG as PRE_SCREENING_STEP_CONFIG

# Step configs per workflow type (mirrors orchestrator)
WORKFLOW_STEP_CONFIGS = {
    "pre_screening": PRE_SCREENING_STEP_CONFIG,
}

router = APIRouter(prefix="/api/activities", tags=["Activities"])


# Response models
class WorkflowStep(BaseModel):
    """A single step in the workflow visualization."""
    id: str
    label: str
    status: Literal["completed", "current", "pending", "failed"]


class TaskRow(BaseModel):
    """A single row in the tasks table."""
    id: str
    candidate_name: Optional[str]
    vacancy_title: Optional[str]
    workflow_type: str
    workflow_type_label: str
    current_step: str
    current_step_label: str
    step_detail: Optional[str]  # Granular detail about what's happening within the step
    status: str
    is_stuck: bool
    updated_at: str
    time_ago: str
    workflow_steps: list[WorkflowStep]  # Visual workflow progress
    # SLA timing (for active/stuck items)
    timeout_at: Optional[str]  # When this step will auto-timeout (ISO datetime)
    time_remaining: Optional[str]  # Human readable: "5h 23m left", "2m left", "overdue"
    time_remaining_seconds: Optional[int]  # Seconds until timeout (negative = overdue)
    # Duration (for completed items)
    duration: Optional[str]  # Human readable total duration: "45 min", "2h 15m"
    duration_seconds: Optional[int]  # Total duration in seconds


class TasksResponse(BaseModel):
    """Response for the tasks endpoint."""
    tasks: list[TaskRow]
    total: int
    stuck_count: int
    active_count: int


class MarkCompleteRequest(BaseModel):
    """Request to mark a task as manually completed."""
    completed_by: str  # Recruiter name or ID
    notes: Optional[str] = None  # Optional notes about why it was marked complete


class MarkCompleteResponse(BaseModel):
    """Response after marking a task as complete."""
    success: bool
    task_id: str
    new_status: str
    new_step: str
    completed_by: str
    completed_at: str
    message: str


# Helpers
def _time_ago(dt_str: str) -> str:
    """Convert ISO datetime string to 'X ago' format."""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} min ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    else:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days > 1 else ''} ago"


def _is_sla_breached(timeout_at_str: Optional[str]) -> bool:
    """Check if SLA is breached (timeout_at is in the past)."""
    if not timeout_at_str:
        return False
    timeout_at = datetime.fromisoformat(timeout_at_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return now > timeout_at


def _get_stuck_threshold(workflow_type: str, step: str) -> int:
    """Get the stuck threshold in seconds for a workflow step."""
    step_config = WORKFLOW_STEP_CONFIGS.get(workflow_type, {})
    config = step_config.get(step, {})
    threshold = config.get("stuck_threshold_seconds")
    return threshold if threshold is not None else 3600  # Default 1 hour


def _time_remaining(timeout_at_str: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """
    Calculate time remaining until timeout.

    Returns:
        (human_readable, seconds) tuple.
        - human_readable: "5h 23m left", "2m left", "overdue", or None
        - seconds: positive = time left, negative = overdue, None = no timeout
    """
    if not timeout_at_str:
        return None, None

    timeout_at = datetime.fromisoformat(timeout_at_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    diff = timeout_at - now
    seconds = int(diff.total_seconds())

    if seconds < 0:
        # Overdue
        overdue_seconds = abs(seconds)
        if overdue_seconds < 60:
            return "overdue", seconds
        elif overdue_seconds < 3600:
            mins = overdue_seconds // 60
            return f"{mins}m overdue", seconds
        else:
            hours = overdue_seconds // 3600
            mins = (overdue_seconds % 3600) // 60
            if mins > 0:
                return f"{hours}h {mins}m overdue", seconds
            return f"{hours}h overdue", seconds
    elif seconds < 60:
        return f"{seconds}s left", seconds
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins}m left", seconds
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        if mins > 0:
            return f"{hours}h {mins}m left", seconds
        return f"{hours}h left", seconds


def _format_duration(created_at_str: str, updated_at_str: str) -> tuple[Optional[str], Optional[int]]:
    """
    Calculate and format the total duration of a completed workflow.

    Returns:
        (human_readable, seconds) tuple.
    """
    try:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        seconds = int((updated_at - created_at).total_seconds())

        if seconds < 60:
            return f"{seconds}s", seconds
        elif seconds < 3600:
            mins = seconds // 60
            return f"{mins} min", seconds
        elif seconds < 86400:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            if mins > 0:
                return f"{hours}h {mins}m", seconds
            return f"{hours}h", seconds
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            if hours > 0:
                return f"{days}d {hours}h", seconds
            return f"{days}d", seconds
    except Exception:
        return None, None


def _get_workflow_type_label(workflow_type: str) -> str:
    """Human-readable workflow type."""
    labels = {
        "pre_screening": "Pre-screening",
        "document_collection": "Document Collection",
        "scheduling": "Interview Planning",
        "cv_analysis": "CV Analysis",
        "voice_screening": "Voice Screening",
        # PoC types
        "ping_pong": "Test",
        "test": "Test",
        "test_flow": "Test",
        "quick_test": "Test",
        "timeout_test": "Test",
    }
    return labels.get(workflow_type, workflow_type.replace("_", " ").title())


def _get_step_label(step: str) -> str:
    """Simple human-readable step label (main status)."""
    labels = {
        "in_progress": "In Progress",
        "processing": "Processing",
        "processed": "Processed",
        "complete": "Complete",
        "failed": "Failed",
        "timed_out": "Timed Out",
        "waiting": "Waiting",
        "request_sent": "Request Sent",
        "verifying": "Verifying",
        "waiting_backside": "Waiting",
        "expired": "Expired",
        "marked_as_complete": "Manually Completed",
    }
    return labels.get(step, step.replace("_", " ").title())


def _get_step_detail(workflow_type: str, step: str, context: dict) -> Optional[str]:
    """Granular detail about what's happening within the step."""
    # Handle manually completed workflows (any type)
    if step == "marked_as_complete":
        completed_by = context.get("completed_by", "Recruiter")
        return f"Afgesloten door {completed_by}"

    # Pre-screening steps
    if workflow_type == "pre_screening":
        channel = context.get("channel", "whatsapp")
        channel_label = "WhatsApp" if channel == "whatsapp" else "Voice"

        details = {
            "in_progress": f"{channel_label} gesprek",
            "processing": "Gesprek verwerken",
            "processed": "Notificaties verzonden",
            "complete": None,  # No detail needed for complete
            "failed": "Kandidaat niet gekwalificeerd",
            "timed_out": "Geen reactie ontvangen",
        }
        return details.get(step)

    # Document collection steps
    elif workflow_type == "document_collection":
        doc_type = context.get("document_type", "document")
        details = {
            "request_sent": f"Wacht op {doc_type}",
            "waiting": f"Wacht op {doc_type}",
            "verifying": f"{doc_type} verifiëren",
            "waiting_backside": "Wacht op achterkant",
            "complete": None,
            "expired": "Verzoek verlopen",
            "timed_out": "Geen reactie ontvangen",
        }
        return details.get(step)

    # Default - no detail
    return None


def _get_workflow_steps(workflow_type: str, current_step: str, status: str, context: Optional[dict] = None) -> list[WorkflowStep]:
    """Generate workflow steps for visualization."""
    # Define step sequences for each workflow type
    step_sequences = {
        "pre_screening": [
            ("in_progress", "Gesprek"),
            ("processing", "Verwerken"),
            ("processed", "Notificaties"),
            ("complete", "Afgerond"),
        ],
        "document_collection": [
            ("request_sent", "Verzoek"),
            ("waiting", "Wachten"),
            ("verifying", "Verifiëren"),
            ("complete", "Afgerond"),
        ],
    }

    # Get steps for this workflow type, or use generic steps
    steps = step_sequences.get(workflow_type, [
        ("in_progress", "Bezig"),
        ("processing", "Verwerken"),
        ("complete", "Afgerond"),
    ])

    # For manually completed workflows, use previous_step to show actual progress
    is_manually_completed = current_step == "marked_as_complete"
    effective_step = current_step
    if is_manually_completed and context:
        effective_step = context.get("previous_step", current_step)

    # Determine which step we're at
    current_index = -1
    for i, (step_id, _) in enumerate(steps):
        if step_id == effective_step:
            current_index = i
            break

    # If current step not found in sequence, try to infer position
    if current_index == -1:
        if effective_step in ("complete", "processed", "marked_as_complete"):
            current_index = len(steps) - 1
        elif effective_step in ("failed", "timed_out", "expired"):
            # Mark at the current position (wherever it failed)
            current_index = len(steps) - 2  # Assume failed near the end
        else:
            current_index = 0

    # Build workflow steps with status
    result = []
    is_failed = status in ("failed", "timed_out", "expired") or effective_step in ("failed", "timed_out", "expired")

    for i, (step_id, label) in enumerate(steps):
        if i < current_index:
            step_status = "completed"
        elif i == current_index:
            if is_failed:
                step_status = "failed"
            elif is_manually_completed:
                # Show where it was stuck when manually completed
                step_status = "completed"  # Mark as completed (it was resolved)
            elif effective_step == "complete" or status == "completed":
                step_status = "completed"
            else:
                step_status = "current"
        else:
            step_status = "pending"

        result.append(WorkflowStep(
            id=step_id,
            label=label,
            status=step_status,
        ))

    return result


@router.get("/tasks", response_model=TasksResponse)
async def get_tasks(
    status: Literal["active", "completed", "all"] = "active",
    stuck_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get all tasks as a table.

    Query params:
    - status: "active" (default), "completed", or "all"
    - stuck_only: Only show stuck tasks (no update for > 1 hour)
    - limit, offset: Pagination
    """
    pool = await get_db_pool()
    service = WorkflowService(pool)
    await service.ensure_table()

    # Get workflows based on status filter
    if status == "active":
        workflows = await service.list_active()
    else:
        workflows = await service.list_all()
        if status == "completed":
            workflows = [w for w in workflows if w["status"] == "completed"]

    # Build task rows
    tasks = []
    stuck_count = 0
    active_count = 0

    for wf in workflows:
        context = wf.get("context", {})
        updated_at = wf.get("updated_at", wf["created_at"])
        timeout_at = wf.get("next_action_at")

        # Item is stuck when SLA is breached (next_action_at is in the past)
        is_stuck = wf["status"] == "active" and _is_sla_breached(timeout_at)

        if is_stuck:
            stuck_count += 1
        elif wf["status"] == "active":
            active_count += 1

        # Apply stuck filter
        # - stuck_only=true: show ONLY stuck items
        # - stuck_only=false + status=active: exclude stuck items (they have their own tab)
        if stuck_only and not is_stuck:
            continue
        if not stuck_only and status == "active" and is_stuck:
            continue

        # Calculate time remaining (for active/stuck items)
        time_remaining_str, time_remaining_secs = _time_remaining(timeout_at)

        # Calculate duration (for completed items)
        duration_str, duration_secs = None, None
        if wf["status"] == "completed":
            created_at = wf.get("created_at")
            if created_at and updated_at:
                duration_str, duration_secs = _format_duration(created_at, updated_at)

        task = TaskRow(
            id=wf["id"],
            candidate_name=context.get("candidate_name"),
            vacancy_title=context.get("vacancy_title"),
            workflow_type=wf["workflow_type"],
            workflow_type_label=_get_workflow_type_label(wf["workflow_type"]),
            current_step=wf["step"],
            current_step_label=_get_step_label(wf["step"]),
            step_detail=_get_step_detail(wf["workflow_type"], wf["step"], context),
            status="stuck" if is_stuck else wf["status"],
            is_stuck=is_stuck,
            updated_at=updated_at,
            time_ago=_time_ago(updated_at),
            workflow_steps=_get_workflow_steps(wf["workflow_type"], wf["step"], wf["status"], context),
            timeout_at=timeout_at,
            time_remaining=time_remaining_str,
            time_remaining_seconds=time_remaining_secs,
            duration=duration_str,
            duration_seconds=duration_secs,
        )
        tasks.append(task)

    # Apply pagination
    total = len(tasks)
    tasks = tasks[offset:offset + limit]

    return TasksResponse(
        tasks=tasks,
        total=total,
        stuck_count=stuck_count,
        active_count=active_count,
    )


@router.post("/tick")
async def process_timers():
    """
    Process all pending timer actions (timeout expired workflows).

    This endpoint should be called by Cloud Scheduler every minute.
    For local testing, call it manually.

    Returns:
        Dict with processed count and results for each timed-out workflow.

    Example:
        curl -X POST localhost:8080/api/activities/tick
    """
    pool = await get_db_pool()
    service = WorkflowService(pool)
    result = await service.process_timers()
    return result


@router.post("/tasks/{task_id}/complete", response_model=MarkCompleteResponse)
async def mark_task_complete(task_id: str, request: MarkCompleteRequest):
    """
    Mark a stuck or active task as manually completed by a recruiter.

    This is used when a recruiter wants to resolve a stuck workflow without
    waiting for the candidate to respond.

    The workflow will be marked with:
    - status: "completed"
    - step: "marked_as_complete"
    - Context updated with: completed_by, completed_at, completion_notes
    """
    pool = await get_db_pool()
    service = WorkflowService(pool)

    # Get the workflow
    workflow = await service.get(task_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Task not found")

    if workflow["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Task is already {workflow['status']}, cannot mark as complete"
        )

    # Record completion details in context
    completed_at = datetime.now(timezone.utc).isoformat()
    completion_context = {
        "manually_completed": True,
        "completed_by": request.completed_by,
        "completed_at": completed_at,
        "previous_step": workflow["step"],  # Store where workflow was before manual completion
    }
    if request.notes:
        completion_context["completion_notes"] = request.notes

    await service.update_context(task_id, completion_context)

    # Update step and status
    await service.update_step(
        task_id,
        new_step="marked_as_complete",
        new_status="completed",
    )

    return MarkCompleteResponse(
        success=True,
        task_id=task_id,
        new_status="completed",
        new_step="marked_as_complete",
        completed_by=request.completed_by,
        completed_at=completed_at,
        message=f"Task marked as complete by {request.completed_by}",
    )


@router.post("/seed-demo")
async def seed_demo_data():
    """
    Seed realistic demo data for frontend development.

    Creates:
    - 5 pre-screening tasks (various steps)
    - 3 document collection tasks
    - 2 that will be stuck (short timeout)
    - Completes 2 tasks
    """
    pool = await get_db_pool()
    service = WorkflowService(pool)
    await service.ensure_table()

    demo_data = [
        # Active pre-screenings
        {
            "workflow_type": "pre_screening",
            "context": {
                "candidate_name": "Jan Peeters",
                "vacancy_title": "Magazijnier",
                "knockout_index": 2,
                "knockout_total": 3,
            },
            "timeout_seconds": 7200,
        },
        {
            "workflow_type": "pre_screening",
            "context": {
                "candidate_name": "Marie Claes",
                "vacancy_title": "Orderpicker",
                "knockout_index": 1,
                "knockout_total": 3,
            },
            "timeout_seconds": 7200,
        },
        {
            "workflow_type": "pre_screening",
            "context": {
                "candidate_name": "Pieter Jansen",
                "vacancy_title": "Heftruckchauffeur",
                "knockout_index": 3,
                "knockout_total": 3,
            },
            "timeout_seconds": 7200,
        },
        {
            "workflow_type": "pre_screening",
            "context": {
                "candidate_name": "Lisa De Vos",
                "vacancy_title": "Teamleader Warehouse",
                "knockout_index": 2,
                "knockout_total": 3,
            },
            "timeout_seconds": 7200,
        },
        # Document collection
        {
            "workflow_type": "document_collection",
            "context": {
                "candidate_name": "Tom Willems",
                "vacancy_title": "Orderpicker",
                "document_type": "ID kaart",
            },
            "timeout_seconds": 86400,
        },
        {
            "workflow_type": "document_collection",
            "context": {
                "candidate_name": "Anna Vermeersch",
                "vacancy_title": "Magazijnier",
                "document_type": "Rijbewijs",
            },
            "timeout_seconds": 86400,
        },
        {
            "workflow_type": "document_collection",
            "context": {
                "candidate_name": "Kevin Maes",
                "vacancy_title": "Heftruckchauffeur",
                "document_type": "Heftruckattest",
            },
            "timeout_seconds": 86400,
        },
        # These will be stuck (1 second timeout = already expired)
        {
            "workflow_type": "pre_screening",
            "context": {
                "candidate_name": "Sarah Janssen",
                "vacancy_title": "Orderpicker",
                "knockout_index": 1,
                "knockout_total": 3,
            },
            "timeout_seconds": 1,
        },
        {
            "workflow_type": "document_collection",
            "context": {
                "candidate_name": "Bart Goossens",
                "vacancy_title": "Magazijnier",
                "document_type": "ID kaart",
            },
            "timeout_seconds": 1,
        },
    ]

    created = []
    for data in demo_data:
        result = await service.create(
            workflow_type=data["workflow_type"],
            context=data["context"],
            initial_step="waiting",  # Demo data starts in waiting step
            timeout_seconds=data["timeout_seconds"],
        )
        created.append(result)

    # Complete two tasks (to show completed items)
    if len(created) >= 3:
        await service.update_step(created[2]["id"], "complete", "completed")  # Pieter - completed

    return {
        "created": len(created),
        "message": f"Created {len(created)} demo tasks. Call GET /api/activities/tasks to see them.",
    }
