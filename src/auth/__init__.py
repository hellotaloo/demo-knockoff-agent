"""
Authentication module for Taloo Backend.

Provides Google OAuth authentication via Supabase Auth,
JWT verification, and workspace-based authorization.
"""

from src.auth.config import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_JWT_SECRET,
    FRONTEND_URL,
)
from src.auth.exceptions import (
    AuthenticationError,
    AuthorizationError,
    InvalidTokenError,
    TokenExpiredError,
    WorkspaceAccessDenied,
)
from src.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    get_auth_context,
    require_role,
)

__all__ = [
    # Config
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWT_SECRET",
    "FRONTEND_URL",
    # Exceptions
    "AuthenticationError",
    "AuthorizationError",
    "InvalidTokenError",
    "TokenExpiredError",
    "WorkspaceAccessDenied",
    # Dependencies
    "get_current_user",
    "get_current_user_optional",
    "get_auth_context",
    "require_role",
]
