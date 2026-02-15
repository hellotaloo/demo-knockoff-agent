"""
Authentication service - handles Google OAuth and user management.
"""
import logging
from typing import Optional, Dict, Any, Tuple
from uuid import UUID

import asyncpg

from src.auth.supabase_client import supabase_auth
from src.auth.jwt import verify_supabase_token, extract_user_id, extract_email, extract_user_metadata
from src.auth.exceptions import AuthenticationError, InvalidTokenError
from src.repositories import UserProfileRepository, WorkspaceRepository, WorkspaceMembershipRepository

logger = logging.getLogger(__name__)


class AuthService:
    """Service for authentication operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.user_repo = UserProfileRepository(pool)
        self.workspace_repo = WorkspaceRepository(pool)
        self.membership_repo = WorkspaceMembershipRepository(pool)

    def get_google_login_url(self, redirect_to: Optional[str] = None) -> str:
        """
        Get the Google OAuth login URL.

        Args:
            redirect_to: Optional URL to redirect after successful auth

        Returns:
            The OAuth authorization URL
        """
        return supabase_auth.get_google_oauth_url(redirect_to)

    async def handle_oauth_callback(self, code: str) -> Dict[str, Any]:
        """
        Handle the OAuth callback and exchange code for tokens.

        Args:
            code: The authorization code from OAuth callback

        Returns:
            Dict containing tokens, user profile, and workspaces

        Raises:
            AuthenticationError: If the callback handling fails
        """
        try:
            # Exchange code for session
            session = await supabase_auth.exchange_code_for_session(code)

            access_token = session.get("access_token")
            refresh_token = session.get("refresh_token")
            expires_in = session.get("expires_in", 3600)

            if not access_token:
                raise AuthenticationError("Failed to get access token")

            # Get or create user profile
            user, workspaces = await self._get_or_create_user_from_token(access_token)

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": expires_in,
                "user": user,
                "workspaces": workspaces,
            }

        except Exception as e:
            logger.error(f"OAuth callback failed: {e}")
            raise AuthenticationError(f"OAuth callback failed: {str(e)}")

    async def refresh_tokens(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            Dict containing new tokens

        Raises:
            AuthenticationError: If refresh fails
        """
        try:
            session = await supabase_auth.refresh_session(refresh_token)

            return {
                "access_token": session.get("access_token"),
                "refresh_token": session.get("refresh_token"),
                "token_type": "bearer",
                "expires_in": session.get("expires_in", 3600),
            }

        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise AuthenticationError(f"Token refresh failed: {str(e)}")

    async def logout(self, access_token: str) -> bool:
        """
        Log out the user (invalidate their session).

        Args:
            access_token: The user's access token

        Returns:
            True if successful
        """
        try:
            return await supabase_auth.sign_out(access_token)
        except Exception as e:
            logger.error(f"Logout failed: {e}")
            return False

    async def get_current_user_data(self, access_token: str) -> Dict[str, Any]:
        """
        Get the current user's profile and workspaces.

        Args:
            access_token: The user's access token

        Returns:
            Dict containing user profile and workspaces
        """
        user, workspaces = await self._get_or_create_user_from_token(access_token)
        return {
            "user": user,
            "workspaces": workspaces,
        }

    async def _get_or_create_user_from_token(
        self,
        access_token: str
    ) -> Tuple[Dict[str, Any], list]:
        """
        Get or create user profile from access token.

        Returns:
            Tuple of (user_dict, workspaces_list)
        """
        # Verify token and extract claims
        payload = verify_supabase_token(access_token)
        auth_user_id = extract_user_id(payload)
        email = extract_email(payload)
        metadata = extract_user_metadata(payload)

        # Try to get existing user profile
        user_row = await self.user_repo.get_by_auth_user_id(UUID(auth_user_id))

        if not user_row:
            # First login - create user profile
            full_name = metadata.get("full_name") or metadata.get("name") or email.split("@")[0]
            avatar_url = metadata.get("avatar_url") or metadata.get("picture")

            user_row = await self.user_repo.create(
                auth_user_id=UUID(auth_user_id),
                email=email,
                full_name=full_name,
                avatar_url=avatar_url,
            )
            logger.info(f"Created new user profile for {email}")

            # Check for pending invitations
            invitations = await self.membership_repo.get_invitations_for_email(email)
            if invitations:
                # Accept all pending invitations
                for inv in invitations:
                    await self.membership_repo.add_member(
                        user_profile_id=user_row["id"],
                        workspace_id=inv["workspace_id"],
                        role=inv["role"],
                        invited_by=inv["invited_by"],
                    )
                    await self.membership_repo.accept_invitation(inv["id"])
                    logger.info(f"Auto-accepted invitation for {email} to workspace {inv['workspace_name']}")
            else:
                # No invitations - create personal workspace
                workspace_name = f"{full_name}'s Workspace"
                workspace_slug = await self.workspace_repo.generate_unique_slug(full_name.lower().replace(" ", "-"))

                workspace_row = await self.workspace_repo.create(
                    name=workspace_name,
                    slug=workspace_slug,
                )

                await self.membership_repo.add_member(
                    user_profile_id=user_row["id"],
                    workspace_id=workspace_row["id"],
                    role="owner",
                )
                logger.info(f"Created personal workspace '{workspace_name}' for {email}")

        # Get user's workspaces
        workspace_rows = await self.membership_repo.get_user_workspaces(user_row["id"])

        # Build response dicts
        user_dict = {
            "id": str(user_row["id"]),
            "email": user_row["email"],
            "full_name": user_row["full_name"],
            "avatar_url": user_row["avatar_url"],
            "phone": user_row["phone"],
            "is_active": user_row["is_active"],
            "created_at": user_row["created_at"],
            "updated_at": user_row["updated_at"],
        }

        workspaces_list = [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "slug": row["slug"],
                "logo_url": row["logo_url"],
                "role": row["role"],
            }
            for row in workspace_rows
        ]

        return user_dict, workspaces_list
