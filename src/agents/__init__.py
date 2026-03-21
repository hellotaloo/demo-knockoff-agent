"""
Taloo Agent framework — base classes and registry for top-level business agents.

Top-level agents (pre-screening, document collection) are business orchestrators
that share cross-cutting concerns: audit logging, workspace isolation, workflow
integration, candidacy transitions, and agent availability checks.

Sub-components (CV analyzer, interview generator, etc.) remain as standalone
Google ADK agents and are NOT part of this framework.
"""

from src.agents.base import TalooAgent, AgentType
from src.agents.registry import AgentRegistry

__all__ = [
    "TalooAgent",
    "AgentType",
    "AgentRegistry",
]
