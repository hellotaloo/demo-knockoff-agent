"""
Document Recognition Agent module.

Provides document verification capabilities with fraud detection.
"""

from .agent import (
    verify_document,
    verify_document_base64,
    DocumentVerificationResult,
    FraudIndicator,
)

__all__ = [
    "verify_document",
    "verify_document_base64",
    "DocumentVerificationResult",
    "FraudIndicator",
]
