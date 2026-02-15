"""
Activities Router - Table view of all active agent tasks.

Shows a unified table of what agents are working on, with stuck detection.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.database import get_db_pool
from src.services.workflow_poc_service import WorkflowPocService

router = APIRouter(prefix="/api/activities", tags=["Activities"])


# Response models
class TaskRow(BaseModel):
    """A single row in the tasks table."""
    id: str
    candidate_name: Optional[str]
    vacancy_title: Optional[str]
    workflow_type: str
    workflow_type_label: str
    current_step: str
    current_step_label: str
    status: str
    is_stuck: bool
    updated_at: str
    time_ago: str


class TasksResponse(BaseModel):
    """Response for the tasks endpoint."""
    tasks: list[TaskRow]
    total: int
    stuck_count: int


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


def _is_stuck(dt_str: str, threshold_minutes: int = 60) -> bool:
    """Check if a task is stuck (no update for > threshold)."""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() > threshold_minutes * 60


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


def _get_step_label(workflow_type: str, step: str, context: dict) -> str:
    """Human-readable step label with context."""
    # Pre-screening steps
    if workflow_type == "pre_screening":
        knockout_idx = context.get("knockout_index", 1)
        knockout_total = context.get("knockout_total", 3)
        open_idx = context.get("open_index", 1)
        open_total = context.get("open_total", 2)

        labels = {
            "hello": "Wacht op reactie",
            "knockout": f"Knockout vraag {knockout_idx}/{knockout_total}",
            "open": f"Open vraag {open_idx}/{open_total}",
            "schedule": "Interview inplannen",
            "complete": "Afgerond",
            "failed": "Niet geslaagd",
            "timed_out": "Timeout",
            "waiting": f"Knockout vraag {knockout_idx}/{knockout_total}",
        }
        return labels.get(step, step.replace("_", " ").title())

    # Document collection steps
    elif workflow_type == "document_collection":
        doc_type = context.get("document_type", "document")
        labels = {
            "request_sent": f"Wacht op {doc_type}",
            "waiting": f"Wacht op {doc_type}",
            "verifying": "Verifiëren",
            "waiting_backside": "Wacht op achterkant",
            "complete": "Ontvangen",
            "expired": "Verlopen",
            "timed_out": "Timeout",
        }
        return labels.get(step, step.replace("_", " ").title())

    # Default
    step_labels = {
        "waiting": "Wacht op reactie",
        "complete": "Afgerond",
        "timed_out": "Timeout",
    }
    return step_labels.get(step, step.replace("_", " ").title())


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
    service = WorkflowPocService(pool)
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

    for wf in workflows:
        context = wf.get("context", {})
        updated_at = wf.get("updated_at", wf["created_at"])
        is_stuck = wf["status"] == "active" and _is_stuck(updated_at)

        if is_stuck:
            stuck_count += 1

        # Apply stuck_only filter
        if stuck_only and not is_stuck:
            continue

        task = TaskRow(
            id=wf["id"],
            candidate_name=context.get("candidate_name"),
            vacancy_title=context.get("vacancy_title"),
            workflow_type=wf["workflow_type"],
            workflow_type_label=_get_workflow_type_label(wf["workflow_type"]),
            current_step=wf["step"],
            current_step_label=_get_step_label(wf["workflow_type"], wf["step"], context),
            status="stuck" if is_stuck else wf["status"],
            is_stuck=is_stuck,
            updated_at=updated_at,
            time_ago=_time_ago(updated_at),
        )
        tasks.append(task)

    # Apply pagination
    total = len(tasks)
    tasks = tasks[offset:offset + limit]

    return TasksResponse(
        tasks=tasks,
        total=total,
        stuck_count=stuck_count,
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
    service = WorkflowPocService(pool)
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
            timeout_seconds=data["timeout_seconds"],
        )
        created.append(result)

    # Complete two tasks (to show completed items)
    if len(created) >= 3:
        await service.advance(created[2]["id"], "user_replied")  # Pieter - completed

    return {
        "created": len(created),
        "message": f"Created {len(created)} demo tasks. Call GET /api/activities/tasks to see them.",
    }
