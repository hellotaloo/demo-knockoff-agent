"""
Document Collection Agent — step-based conversation loop.

Follows the conversation_flow from the planner: each step has a type
and the agent dispatches to the appropriate handler.

For backward compatibility with in-flight conversations, the legacy
agent is available via legacy_agent module.
"""

from agents.document_collection.collection.agent import (
    DocumentCollectionAgent,
    create_collection_agent,
    is_collection_complete,
    restore_collection_agent,
)
from agents.document_collection.collection.state import CollectionState

__all__ = [
    "CollectionState",
    "DocumentCollectionAgent",
    "create_collection_agent",
    "restore_collection_agent",
    "is_collection_complete",
]
