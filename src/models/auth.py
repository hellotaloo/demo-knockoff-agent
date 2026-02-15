"""
Authentication models.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """Response model for authentication tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token expiry in seconds")
    expires_at: Optional[datetime] = None


class RefreshTokenRequest(BaseModel):
    """Request model for refreshing tokens."""
    refresh_token: str


class AuthCallbackResponse(BaseModel):
    """Response model for OAuth callback."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserProfileResponse"
    workspaces: List["WorkspaceSummary"]

    class Config:
        from_attributes = True


class AuthMeResponse(BaseModel):
    """Response model for /auth/me endpoint."""
    user: "UserProfileResponse"
    workspaces: List["WorkspaceSummary"]

    class Config:
        from_attributes = True


# Import these at the end to avoid circular imports
from src.models.user import UserProfileResponse
from src.models.workspace import WorkspaceSummary

# Update forward references
AuthCallbackResponse.model_rebuild()
AuthMeResponse.model_rebuild()
