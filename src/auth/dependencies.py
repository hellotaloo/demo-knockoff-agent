"""
FastAPI authentication dependencies.

Provides dependency injection for authenticated endpoints.
"""
import logging
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import Depends, Header

from src.database import get_db_pool
from src.auth.jwt import verify_supabase_token, extract_user_id, extract_email, extract_user_metadata
from src.auth.exceptions import (
    AuthenticationError,
    InvalidTokenError,
    WorkspaceAccessDenied,
    InsufficientRoleError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Models for Auth Context
# =============================================================================

class UserProfile:
    """User profile from database."""

    def __init__(
        self,
        id: UUID,
        auth_user_id: UUID,
        email: str,
        full_name: str,
        avatar_url: Optional[str] = None,
        phone: Optional[str] = None,
        is_active: bool = True,
    ):
        self.id = id
        self.auth_user_id = auth_user_id
        self.email = email
        self.full_name = full_name
        self.avatar_url = avatar_url
        self.phone = phone
        self.is_active = is_active


class WorkspaceMembership:
    """Workspace membership info."""

    def __init__(
        self,
        workspace_id: UUID,
        workspace_name: str,
        workspace_slug: str,
        role: str,
    ):
        self.workspace_id = workspace_id
        self.workspace_name = workspace_name
        self.workspace_slug = workspace_slug
        self.role = role


class AuthContext:
    """
    Full authentication context for a request.

    Contains the authenticated user, selected workspace, and role.
    """

    def __init__(
        self,
        user: UserProfile,
        workspace: Optional[WorkspaceMembership] = None,
    ):
        self.user = user
        self.workspace = workspace

    @property
    def user_id(self) -> UUID:
        return self.user.id

    @property
    def workspace_id(self) -> Optional[UUID]:
        return self.workspace.workspace_id if self.workspace else None

    @property
    def role(self) -> Optional[str]:
        return self.workspace.role if self.workspace else None


# =============================================================================
# Token Extraction
# =============================================================================

def extract_token(authorization: Optional[str]) -> str:
    """
    Extract the JWT token from Authorization header.

    Args:
        authorization: The Authorization header value

    Returns:
        The token string (without "Bearer " prefix)

    Raises:
        AuthenticationError: If header is missing or malformed
    """
    if not authorization:
        raise AuthenticationError("Authorization header required")

    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError("Invalid authorization header format. Use: Bearer <token>")

    return parts[1]


# =============================================================================
# Database Queries
# =============================================================================

async def get_user_profile_by_auth_id(pool: asyncpg.Pool, auth_user_id: str) -> Optional[UserProfile]:
    """Get user profile by Supabase auth user ID."""
    query = """
        SELECT id, auth_user_id, email, full_name, avatar_url, phone, is_active
        FROM ats.user_profiles
        WHERE auth_user_id = $1
    """
    row = await pool.fetchrow(query, UUID(auth_user_id))
    if not row:
        return None

    return UserProfile(
        id=row["id"],
        auth_user_id=row["auth_user_id"],
        email=row["email"],
        full_name=row["full_name"],
        avatar_url=row["avatar_url"],
        phone=row["phone"],
        is_active=row["is_active"],
    )


async def get_workspace_membership(
    pool: asyncpg.Pool,
    user_profile_id: UUID,
    workspace_id: UUID
) -> Optional[WorkspaceMembership]:
    """Get workspace membership for a user."""
    query = """
        SELECT
            w.id as workspace_id,
            w.name as workspace_name,
            w.slug as workspace_slug,
            wm.role
        FROM ats.workspace_memberships wm
        JOIN ats.workspaces w ON w.id = wm.workspace_id
        WHERE wm.user_profile_id = $1 AND wm.workspace_id = $2
    """
    row = await pool.fetchrow(query, user_profile_id, workspace_id)
    if not row:
        return None

    return WorkspaceMembership(
        workspace_id=row["workspace_id"],
        workspace_name=row["workspace_name"],
        workspace_slug=row["workspace_slug"],
        role=row["role"],
    )


async def get_user_workspaces(pool: asyncpg.Pool, user_profile_id: UUID) -> list[WorkspaceMembership]:
    """Get all workspaces a user belongs to."""
    query = """
        SELECT
            w.id as workspace_id,
            w.name as workspace_name,
            w.slug as workspace_slug,
            wm.role
        FROM ats.workspace_memberships wm
        JOIN ats.workspaces w ON w.id = wm.workspace_id
        WHERE wm.user_profile_id = $1
        ORDER BY w.name
    """
    rows = await pool.fetch(query, user_profile_id)
    return [
        WorkspaceMembership(
            workspace_id=row["workspace_id"],
            workspace_name=row["workspace_name"],
            workspace_slug=row["workspace_slug"],
            role=row["role"],
        )
        for row in rows
    ]


async def create_user_profile(
    pool: asyncpg.Pool,
    auth_user_id: str,
    email: str,
    full_name: str,
    avatar_url: Optional[str] = None,
) -> UserProfile:
    """Create a new user profile."""
    query = """
        INSERT INTO ats.user_profiles (auth_user_id, email, full_name, avatar_url)
        VALUES ($1, $2, $3, $4)
        RETURNING id, auth_user_id, email, full_name, avatar_url, phone, is_active
    """
    row = await pool.fetchrow(query, UUID(auth_user_id), email, full_name, avatar_url)
    return UserProfile(
        id=row["id"],
        auth_user_id=row["auth_user_id"],
        email=row["email"],
        full_name=row["full_name"],
        avatar_url=row["avatar_url"],
        phone=row["phone"],
        is_active=row["is_active"],
    )


async def create_workspace_with_owner(
    pool: asyncpg.Pool,
    user_profile_id: UUID,
    name: str,
    slug: str,
) -> WorkspaceMembership:
    """Create a new workspace and add the user as owner."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Create workspace
            workspace_row = await conn.fetchrow(
                """
                INSERT INTO ats.workspaces (name, slug)
                VALUES ($1, $2)
                RETURNING id, name, slug
                """,
                name,
                slug,
            )

            # Add user as owner
            await conn.execute(
                """
                INSERT INTO ats.workspace_memberships (user_profile_id, workspace_id, role)
                VALUES ($1, $2, 'owner')
                """,
                user_profile_id,
                workspace_row["id"],
            )

            return WorkspaceMembership(
                workspace_id=workspace_row["id"],
                workspace_name=workspace_row["name"],
                workspace_slug=workspace_row["slug"],
                role="owner",
            )


# =============================================================================
# Dependency Functions
# =============================================================================

async def get_current_user(
    authorization: Optional[str] = Header(None),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> UserProfile:
    """
    Get the current authenticated user.

    This dependency verifies the JWT token and retrieves the user profile.
    If the user doesn't exist yet (first login), it creates their profile.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(user: UserProfile = Depends(get_current_user)):
            return {"user": user.email}
    """
    token = extract_token(authorization)
    payload = verify_supabase_token(token)

    auth_user_id = extract_user_id(payload)
    email = extract_email(payload)
    metadata = extract_user_metadata(payload)

    # Try to get existing user profile
    user = await get_user_profile_by_auth_id(pool, auth_user_id)

    if not user:
        # First login - create user profile
        full_name = metadata.get("full_name") or metadata.get("name") or email.split("@")[0]
        avatar_url = metadata.get("avatar_url") or metadata.get("picture")

        user = await create_user_profile(
            pool=pool,
            auth_user_id=auth_user_id,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
        )
        logger.info(f"Created new user profile for {email}")

    if not user.is_active:
        raise AuthenticationError("User account is deactivated")

    return user


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> Optional[UserProfile]:
    """
    Get the current user if authenticated, otherwise return None.

    Useful for endpoints that support both authenticated and anonymous access.
    """
    if not authorization:
        return None

    try:
        return await get_current_user(authorization, pool)
    except AuthenticationError:
        return None


async def get_auth_context(
    authorization: Optional[str] = Header(None),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> AuthContext:
    """
    Get the full authentication context including workspace.

    This dependency:
    1. Authenticates the user via JWT
    2. Validates workspace access if X-Workspace-ID is provided
    3. Returns both user and workspace info

    Usage:
        @router.get("/vacancies")
        async def list_vacancies(ctx: AuthContext = Depends(get_auth_context)):
            # ctx.user, ctx.workspace_id, ctx.role are available
            return await repo.list_by_workspace(ctx.workspace_id)
    """
    user = await get_current_user(authorization, pool)

    workspace = None
    if x_workspace_id:
        try:
            workspace_uuid = UUID(x_workspace_id)
        except ValueError:
            raise InvalidTokenError(f"Invalid workspace ID format: {x_workspace_id}")

        workspace = await get_workspace_membership(pool, user.id, workspace_uuid)
        if not workspace:
            raise WorkspaceAccessDenied(x_workspace_id)

    return AuthContext(user=user, workspace=workspace)


def require_role(*allowed_roles: str):
    """
    Dependency factory that requires specific roles.

    Usage:
        @router.delete("/workspaces/{id}")
        async def delete_workspace(
            ctx: AuthContext = Depends(require_role("owner"))
        ):
            # Only workspace owners can reach here
            ...
    """
    async def dependency(
        ctx: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if not ctx.workspace:
            raise AuthenticationError("Workspace context required")

        if ctx.role not in allowed_roles:
            raise InsufficientRoleError(
                required_role=", ".join(allowed_roles),
                current_role=ctx.role,
            )

        return ctx

    return dependency
