"""
Document Collection Agent module.

Provides WhatsApp-based document collection with real-time verification.
"""

from .agent import (
    create_document_collection_agent,
    get_document_collection_agent,
    build_document_collection_instruction,
    document_collection_complete_tool,
)

__all__ = [
    "create_document_collection_agent",
    "get_document_collection_agent",
    "build_document_collection_instruction",
    "document_collection_complete_tool",
]
