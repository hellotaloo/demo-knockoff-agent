"""
Workspace models.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


class WorkspaceRole(str, Enum):
    """Workspace membership roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceBase(BaseModel):
    """Base workspace fields."""
    name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(None, min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    logo_url: Optional[str] = None


class WorkspaceCreate(WorkspaceBase):
    """Request model for creating a workspace."""
    pass


class WorkspaceUpdate(BaseModel):
    """Request model for updating a workspace."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    logo_url: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class WorkspaceResponse(WorkspaceBase):
    """Response model for a workspace."""
    id: str
    settings: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkspaceSummary(BaseModel):
    """Summary workspace for embedding in other responses (e.g., user's workspaces)."""
    id: str
    name: str
    slug: str
    logo_url: Optional[str] = None
    role: WorkspaceRole

    class Config:
        from_attributes = True


class WorkspaceWithMembers(WorkspaceResponse):
    """Workspace response including member list."""
    members: List["WorkspaceMemberResponse"] = []


# =============================================================================
# Membership Models
# =============================================================================

class WorkspaceMemberBase(BaseModel):
    """Base membership fields."""
    role: WorkspaceRole = WorkspaceRole.MEMBER


class WorkspaceMemberResponse(WorkspaceMemberBase):
    """Response model for a workspace member."""
    id: str
    user_id: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    joined_at: datetime

    class Config:
        from_attributes = True


class WorkspaceMemberUpdate(BaseModel):
    """Request model for updating a member's role."""
    role: WorkspaceRole


# =============================================================================
# Invitation Models
# =============================================================================

class WorkspaceInvitationCreate(BaseModel):
    """Request model for inviting a user to a workspace."""
    email: str = Field(..., description="Email address to invite")
    role: WorkspaceRole = Field(default=WorkspaceRole.MEMBER, description="Role to assign")


class WorkspaceInvitationResponse(BaseModel):
    """Response model for a workspace invitation."""
    id: str
    workspace_id: str
    email: str
    role: WorkspaceRole
    invited_by: str
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Update forward references
WorkspaceWithMembers.model_rebuild()
