"""
Workflow PoC Router - Test endpoints for the workflow state machine.

Demonstrates:
1. Starting a workflow with a timeout
2. Sending events to advance the workflow
3. Processing timers (what Cloud Scheduler would call)
4. Listing workflows for dashboard
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.database import get_db_pool
from src.services.workflow_poc_service import WorkflowPocService

router = APIRouter(prefix="/poc/workflow", tags=["Workflow PoC"])


# Request/Response models
class StartWorkflowRequest(BaseModel):
    """Request to start a new workflow."""
    workflow_type: str = "ping_pong"
    context: Optional[dict] = None
    timeout_seconds: int = 60  # Default 1 minute timeout


class SendEventRequest(BaseModel):
    """Request to send an event to a workflow."""
    event: str  # e.g., "user_replied"


# Dependency to get service
async def get_workflow_service() -> WorkflowPocService:
    pool = await get_db_pool()
    service = WorkflowPocService(pool)
    await service.ensure_table()  # Ensure table exists
    return service


@router.post("/start")
async def start_workflow(
    request: StartWorkflowRequest,
    service: WorkflowPocService = Depends(get_workflow_service),
):
    """
    Start a new workflow with a timeout timer.

    The workflow starts in WAITING step. If no event is received
    within timeout_seconds, it will move to TIMED_OUT when /tick is called.

    Example:
        curl -X POST localhost:8080/poc/workflow/start \\
          -H "Content-Type: application/json" \\
          -d '{"context": {"message": "Hello!"}}'
    """
    result = await service.create(
        workflow_type=request.workflow_type,
        context=request.context,
        timeout_seconds=request.timeout_seconds,
    )
    return result


@router.post("/{workflow_id}/event")
async def send_event(
    workflow_id: str,
    request: SendEventRequest,
    service: WorkflowPocService = Depends(get_workflow_service),
):
    """
    Send an event to advance the workflow.

    Events:
    - "user_replied": Moves from WAITING to COMPLETE

    Example:
        curl -X POST localhost:8080/poc/workflow/{id}/event \\
          -H "Content-Type: application/json" \\
          -d '{"event": "user_replied"}'
    """
    try:
        result = await service.advance(workflow_id, request.event)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    service: WorkflowPocService = Depends(get_workflow_service),
):
    """
    Get the current state of a workflow.

    Example:
        curl localhost:8080/poc/workflow/{id}
    """
    result = await service.get(workflow_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return result


@router.get("")
async def list_workflows(
    active_only: bool = False,
    service: WorkflowPocService = Depends(get_workflow_service),
):
    """
    List all workflows (for dashboard).

    Example:
        curl localhost:8080/poc/workflow
        curl "localhost:8080/poc/workflow?active_only=true"
    """
    if active_only:
        workflows = await service.list_active()
    else:
        workflows = await service.list_all()

    return {
        "count": len(workflows),
        "workflows": workflows,
    }


@router.post("/tick")
async def process_timers(
    service: WorkflowPocService = Depends(get_workflow_service),
):
    """
    Process all pending timer actions.

    This endpoint would be called by Cloud Scheduler every minute.
    For local testing, call it manually.

    Example:
        curl -X POST localhost:8080/poc/workflow/tick
    """
    result = await service.process_timers()
    return result
