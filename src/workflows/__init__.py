"""
Workflows package - Central workflow orchestration for all agent workflows.

This package provides:
- WorkflowOrchestrator: Central event router for all workflows
- get_orchestrator(): Singleton accessor for the orchestrator
- Workflow handlers for each workflow type (pre_screening, document_collection, etc.)
"""

from src.workflows.orchestrator import WorkflowOrchestrator, get_orchestrator

__all__ = [
    "WorkflowOrchestrator",
    "get_orchestrator",
]
