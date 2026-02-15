"""
Authentication and authorization exceptions.
"""
from typing import Any, Dict, Optional
from fastapi import status

from src.exceptions import TalooException


class AuthenticationError(TalooException):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication required", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED, details)


class InvalidTokenError(AuthenticationError):
    """Raised when the provided token is invalid."""

    def __init__(self, message: str = "Invalid or malformed token", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)


class TokenExpiredError(AuthenticationError):
    """Raised when the token has expired."""

    def __init__(self, message: str = "Token has expired", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)


class AuthorizationError(TalooException):
    """Raised when the user doesn't have permission to perform an action."""

    def __init__(self, message: str = "Permission denied", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status.HTTP_403_FORBIDDEN, details)


class WorkspaceAccessDenied(AuthorizationError):
    """Raised when user doesn't have access to the requested workspace."""

    def __init__(self, workspace_id: str, details: Optional[Dict[str, Any]] = None):
        message = f"Access denied to workspace: {workspace_id}"
        super().__init__(message, details)
        self.workspace_id = workspace_id


class InsufficientRoleError(AuthorizationError):
    """Raised when the user's role is insufficient for the operation."""

    def __init__(self, required_role: str, current_role: str, details: Optional[Dict[str, Any]] = None):
        message = f"Requires '{required_role}' role, but you have '{current_role}'"
        super().__init__(message, details)
        self.required_role = required_role
        self.current_role = current_role
