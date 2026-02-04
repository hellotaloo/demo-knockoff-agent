"""
Custom exception classes and error handling.

This module provides custom exceptions and utilities for consistent
error handling across the application.
"""
import uuid
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class TalooException(Exception):
    """Base exception for all Taloo-specific errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(TalooException):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str, resource_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"{resource} not found: {resource_id}"
        super().__init__(message, status.HTTP_404_NOT_FOUND, details)
        self.resource = resource
        self.resource_id = resource_id


class ValidationError(TalooException):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status.HTTP_400_BAD_REQUEST, details)
        self.field = field


class InvalidUUIDError(ValidationError):
    """Raised when a UUID format is invalid."""

    def __init__(self, uuid_str: str, field: str = "id"):
        message = f"Invalid UUID format: {uuid_str}"
        super().__init__(message, field=field)
        self.uuid_str = uuid_str


# =============================================================================
# Exception Handlers
# =============================================================================

async def taloo_exception_handler(request: Request, exc: TalooException) -> JSONResponse:
    """Handle TalooException instances."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "details": exc.details
        }
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions."""
    # Log the error for debugging
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "details": {"message": str(exc)}
        }
    )


# =============================================================================
# Helper Functions
# =============================================================================

def parse_uuid(uuid_str: str, field: str = "id") -> uuid.UUID:
    """
    Parse a UUID string and raise InvalidUUIDError if invalid.

    This replaces the repeated try/except UUID pattern throughout the codebase.

    Args:
        uuid_str: The UUID string to parse
        field: The field name for error messages (default: "id")

    Returns:
        A validated UUID object

    Raises:
        InvalidUUIDError: If the UUID format is invalid

    Example:
        >>> vacancy_uuid = parse_uuid(vacancy_id, field="vacancy_id")
    """
    try:
        return uuid.UUID(uuid_str)
    except (ValueError, AttributeError, TypeError):
        raise InvalidUUIDError(uuid_str, field=field)


def register_exception_handlers(app):
    """
    Register all custom exception handlers with the FastAPI app.

    Call this during app initialization:
        from src.exceptions import register_exception_handlers
        register_exception_handlers(app)
    """
    app.add_exception_handler(TalooException, taloo_exception_handler)
    # Optionally add a catch-all handler for debugging
    # app.add_exception_handler(Exception, generic_exception_handler)
