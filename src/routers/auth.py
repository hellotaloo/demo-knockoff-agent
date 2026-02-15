"""
Authentication router - handles Google OAuth login and token management.
"""
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Header, HTTPException
from fastapi.responses import RedirectResponse
import asyncpg

from src.database import get_db_pool
from src.services import AuthService
from src.auth.dependencies import get_current_user, UserProfile
from src.auth.exceptions import AuthenticationError
from src.auth.jwt import create_dev_token
from src.repositories import UserProfileRepository, WorkspaceMembershipRepository, WorkspaceRepository
from src.models import (
    TokenResponse,
    RefreshTokenRequest,
    AuthCallbackResponse,
    AuthMeResponse,
    UserProfileResponse,
    WorkspaceSummary,
)

# Default workspace for dev login
DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Dev user constants
DEV_USER_EMAIL = "laurijn@taloo.be"
DEV_USER_NAME = "Laurijn Deschepper"
DEV_USER_AVATAR = "/users/laurijn.png"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# =============================================================================
# Dependencies
# =============================================================================

async def get_auth_service(pool: asyncpg.Pool = Depends(get_db_pool)) -> AuthService:
    """Get AuthService instance."""
    return AuthService(pool)


# =============================================================================
# OAuth Endpoints
# =============================================================================

@router.get("/login/google")
async def login_google(
    redirect_to: Optional[str] = Query(None, description="URL to redirect after login"),
    service: AuthService = Depends(get_auth_service),
):
    """
    Initiate Google OAuth login.

    Redirects the user to Google's OAuth consent page.
    After authentication, the user is redirected to /auth/callback.
    """
    auth_url = service.get_google_login_url(redirect_to)
    return RedirectResponse(url=auth_url)


@router.get("/callback", response_model=AuthCallbackResponse)
async def auth_callback(
    code: str = Query(..., description="Authorization code from OAuth"),
    service: AuthService = Depends(get_auth_service),
):
    """
    Handle OAuth callback.

    Exchanges the authorization code for access and refresh tokens.
    Creates the user profile if this is their first login.

    Returns the tokens, user profile, and list of workspaces.
    """
    result = await service.handle_oauth_callback(code)

    return AuthCallbackResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
        user=UserProfileResponse(**result["user"]),
        workspaces=[WorkspaceSummary(**w) for w in result["workspaces"]],
    )


# =============================================================================
# Token Management
# =============================================================================

@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    request: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
):
    """
    Refresh access token.

    Use this endpoint when the access token is about to expire.
    Requires the refresh token from the original login.
    """
    result = await service.refresh_tokens(request.refresh_token)

    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/logout")
async def logout(
    authorization: Optional[str] = Header(None),
    service: AuthService = Depends(get_auth_service),
):
    """
    Log out the current user.

    Invalidates the current session.
    """
    if not authorization:
        return {"success": True}

    # Extract token from header
    parts = authorization.split(" ")
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]
        await service.logout(token)

    return {"success": True}


# =============================================================================
# User Info
# =============================================================================

@router.get("/me", response_model=AuthMeResponse)
async def get_me(
    authorization: Optional[str] = Header(None),
    service: AuthService = Depends(get_auth_service),
):
    """
    Get current user info.

    Returns the authenticated user's profile and list of workspaces.
    """
    if not authorization:
        raise AuthenticationError("Authorization header required")

    # Extract token from header
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError("Invalid authorization header format")

    token = parts[1]
    result = await service.get_current_user_data(token)

    return AuthMeResponse(
        user=UserProfileResponse(**result["user"]),
        workspaces=[WorkspaceSummary(**w) for w in result["workspaces"]],
    )


# =============================================================================
# Development Only
# =============================================================================

@router.post("/dev-login", response_model=AuthCallbackResponse)
async def dev_login(
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """
    Development-only login endpoint.

    Creates a test user and returns a valid JWT token.
    Only works when ENVIRONMENT=local.
    """
    environment = os.getenv("ENVIRONMENT", "production")
    if environment not in ("local", "development"):
        raise HTTPException(
            status_code=403,
            detail="Dev login only available in local/development environment"
        )

    user_repo = UserProfileRepository(pool)
    membership_repo = WorkspaceMembershipRepository(pool)
    workspace_repo = WorkspaceRepository(pool)

    # Check if dev user exists
    dev_user = await user_repo.get_by_email(DEV_USER_EMAIL)

    if not dev_user:
        # Create a stable auth_user_id for the dev user
        dev_auth_user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

        # Create dev user
        dev_user = await user_repo.create(
            auth_user_id=dev_auth_user_id,
            email=DEV_USER_EMAIL,
            full_name=DEV_USER_NAME,
            avatar_url=DEV_USER_AVATAR,
        )

    # GOD MODE: Add dev user to ALL workspaces as owner
    all_workspaces = await workspace_repo.list_all()
    for ws in all_workspaces:
        await membership_repo.add_member(
            workspace_id=ws["id"],
            user_profile_id=dev_user["id"],
            role="owner",
            invited_by=None,
        )

    # Get user's workspaces
    workspaces = await membership_repo.get_user_workspaces(dev_user["id"])

    # Create a JWT token
    token = create_dev_token(
        user_id=str(dev_user["auth_user_id"]),
        email=dev_user["email"],
        full_name=dev_user["full_name"],
        expires_in=86400,  # 24 hours
    )

    return AuthCallbackResponse(
        access_token=token,
        refresh_token="dev-refresh-token-not-functional",
        token_type="bearer",
        expires_in=86400,
        user=UserProfileResponse(
            id=str(dev_user["id"]),
            email=dev_user["email"],
            full_name=dev_user["full_name"],
            avatar_url=dev_user["avatar_url"],
            phone=dev_user["phone"],
            is_active=dev_user["is_active"],
            created_at=dev_user["created_at"],
            updated_at=dev_user["updated_at"],
        ),
        workspaces=[
            WorkspaceSummary(
                id=str(w["id"]),
                name=w["name"],
                slug=w["slug"],
                logo_url=w["logo_url"],
                role=w["role"],
            )
            for w in workspaces
        ],
    )
