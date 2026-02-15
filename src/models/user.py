"""
User profile models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UserProfileBase(BaseModel):
    """Base user profile fields."""
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    phone: Optional[str] = None


class UserProfileCreate(UserProfileBase):
    """Request model for creating a user profile (internal use)."""
    auth_user_id: str


class UserProfileUpdate(BaseModel):
    """Request model for updating a user profile."""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None


class UserProfileResponse(UserProfileBase):
    """Response model for a user profile."""
    id: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserProfileSummary(BaseModel):
    """Summary user profile for embedding in other responses."""
    id: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True
