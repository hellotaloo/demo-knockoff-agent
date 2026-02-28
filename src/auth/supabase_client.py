"""
Supabase Auth client wrapper.

Handles Google OAuth flow and token management.
"""
import logging
from typing import Any, Dict, Optional
import httpx

from src.auth.config import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    FRONTEND_URL,
)

logger = logging.getLogger(__name__)


class SupabaseAuthClient:
    """
    Client for interacting with Supabase Auth API.

    Handles OAuth flows, token refresh, and user management.
    """

    def __init__(self):
        self.base_url = f"{SUPABASE_URL}/auth/v1"
        self.anon_key = SUPABASE_ANON_KEY
        self.service_role_key = SUPABASE_SERVICE_ROLE_KEY

    def _get_headers(self, use_service_role: bool = False) -> Dict[str, str]:
        """Get headers for Supabase API requests."""
        api_key = self.service_role_key if use_service_role else self.anon_key
        return {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_google_oauth_url(self, redirect_to: Optional[str] = None) -> str:
        """
        Generate the Google OAuth authorization URL.

        Args:
            redirect_to: Optional URL to redirect after successful auth (unused, always goes to /auth/callback)

        Returns:
            The full OAuth authorization URL
        """
        params = {
            "provider": "google",
            "redirect_to": f"{FRONTEND_URL}/auth/callback",
        }
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.base_url}/authorize?{query_string}"

    async def exchange_code_for_session(self, code: str) -> Dict[str, Any]:
        """
        Exchange an OAuth code for a session (access + refresh tokens).

        Args:
            code: The authorization code from OAuth callback

        Returns:
            Session data including access_token, refresh_token, user

        Raises:
            Exception: If the exchange fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/token?grant_type=authorization_code",
                headers=self._get_headers(),
                json={"auth_code": code},
            )

            if response.status_code != 200:
                logger.error(f"OAuth code exchange failed: {response.text}")
                raise Exception(f"OAuth code exchange failed: {response.text}")

            return response.json()

    async def refresh_session(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh an access token using a refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            New session data with fresh access_token

        Raises:
            Exception: If the refresh fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/token?grant_type=refresh_token",
                headers=self._get_headers(),
                json={"refresh_token": refresh_token},
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                raise Exception(f"Token refresh failed: {response.text}")

            return response.json()

    async def get_user(self, access_token: str) -> Dict[str, Any]:
        """
        Get the current user's data using their access token.

        Args:
            access_token: The user's access token

        Returns:
            User data from Supabase Auth

        Raises:
            Exception: If the request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/user",
                headers={
                    **self._get_headers(),
                    "Authorization": f"Bearer {access_token}",
                },
            )

            if response.status_code != 200:
                logger.error(f"Get user failed: {response.text}")
                raise Exception(f"Get user failed: {response.text}")

            return response.json()

    async def sign_out(self, access_token: str) -> bool:
        """
        Sign out a user (invalidate their session).

        Args:
            access_token: The user's access token

        Returns:
            True if successful
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/logout",
                headers={
                    **self._get_headers(),
                    "Authorization": f"Bearer {access_token}",
                },
            )

            return response.status_code == 204


# Singleton instance
supabase_auth = SupabaseAuthClient()
