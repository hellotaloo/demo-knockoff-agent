"""
Workspaces router - handles workspace management.
"""
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Body
import asyncpg

from src.database import get_db_pool
from src.services import WorkspaceService
from src.auth.dependencies import get_current_user, UserProfile
from src.exceptions import parse_uuid
from src.models import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceSummary,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceInvitationCreate,
    WorkspaceInvitationResponse,
    AcceptInvitationRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


# =============================================================================
# Dependencies
# =============================================================================

async def get_workspace_service(pool: asyncpg.Pool = Depends(get_db_pool)) -> WorkspaceService:
    """Get WorkspaceService instance."""
    return WorkspaceService(pool)


# =============================================================================
# Invitation Accept (must be before /{workspace_id} routes to avoid path conflict)
# =============================================================================

@router.post("/invitations/accept")
async def accept_invitation(
    data: AcceptInvitationRequest = Body(...),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Accept a workspace invitation by token.

    The token must match the authenticated user's email address.
    """
    result = await service.accept_invitation_by_token(
        token=data.token,
        user_id=user.id,
        user_email=user.email,
    )
    return result


# =============================================================================
# Workspace CRUD
# =============================================================================

@router.get("", response_model=List[WorkspaceSummary])
async def list_workspaces(
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    List all workspaces the current user belongs to.
    """
    from src.repositories import WorkspaceMembershipRepository
    pool = await get_db_pool()
    membership_repo = WorkspaceMembershipRepository(pool)

    rows = await membership_repo.get_user_workspaces(user.id)
    return [
        WorkspaceSummary(
            id=str(row["id"]),
            name=row["name"],
            slug=row["slug"],
            logo_url=row["logo_url"],
            role=row["role"],
        )
        for row in rows
    ]


@router.post("", response_model=WorkspaceResponse)
async def create_workspace(
    data: WorkspaceCreate,
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Create a new workspace.

    The creating user becomes the workspace owner.
    """
    result = await service.create_workspace(
        user_id=user.id,
        name=data.name,
        slug=data.slug,
        logo_url=data.logo_url,
    )
    return WorkspaceResponse(**result)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Get workspace details.

    Requires membership in the workspace.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    result = await service.get_workspace(workspace_uuid, user.id, is_super_admin=user.is_super_admin)
    return WorkspaceResponse(**result)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str = Path(..., description="Workspace ID"),
    data: WorkspaceUpdate = Body(...),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Update workspace settings.

    Requires owner role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    result = await service.update_workspace(
        workspace_id=workspace_uuid,
        user_id=user.id,
        name=data.name,
        logo_url=data.logo_url,
        settings=data.settings,
        is_super_admin=user.is_super_admin,
    )
    return WorkspaceResponse(**result)


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Delete a workspace.

    Requires owner role. This action cannot be undone.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    await service.delete_workspace(workspace_uuid, user.id, is_super_admin=user.is_super_admin)
    return {"success": True}


# =============================================================================
# Member Management
# =============================================================================

@router.get("/{workspace_id}/members", response_model=List[WorkspaceMemberResponse])
async def list_members(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    List all members of a workspace.

    Requires membership in the workspace.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    members = await service.get_workspace_members(workspace_uuid, user.id, is_super_admin=user.is_super_admin)
    return [WorkspaceMemberResponse(**m) for m in members]


@router.post("/{workspace_id}/invitations", response_model=WorkspaceInvitationResponse)
async def invite_member(
    workspace_id: str = Path(..., description="Workspace ID"),
    data: WorkspaceInvitationCreate = Body(...),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Invite a user to the workspace.

    Requires owner or admin role.
    If the user already exists, they are added directly.
    Otherwise, an invitation is created.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    result = await service.invite_member(
        workspace_id=workspace_uuid,
        user_id=user.id,
        email=data.email,
        role=data.role.value,
        is_super_admin=user.is_super_admin,
    )

    # Handle direct add vs invitation
    if result.get("status") == "added":
        return WorkspaceInvitationResponse(
            id="direct-add",
            workspace_id=str(workspace_uuid),
            email=result["email"],
            role=result["role"],
            invited_by=str(user.id),
            expires_at=None,
            accepted_at=None,
            created_at=None,
        )

    return WorkspaceInvitationResponse(**result)


@router.get("/{workspace_id}/invitations", response_model=List[WorkspaceInvitationResponse])
async def list_invitations(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    List pending invitations for a workspace.

    Requires owner or admin role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    invitations = await service.get_pending_invitations(
        workspace_uuid, user.id, is_super_admin=user.is_super_admin
    )
    return [WorkspaceInvitationResponse(**inv) for inv in invitations]


@router.delete("/{workspace_id}/invitations/{invitation_id}")
async def cancel_invitation(
    workspace_id: str = Path(..., description="Workspace ID"),
    invitation_id: str = Path(..., description="Invitation ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Cancel a pending invitation.

    Requires owner or admin role.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    invitation_uuid = parse_uuid(invitation_id, field="invitation_id")
    await service.cancel_invitation(
        workspace_uuid, invitation_uuid, user.id, is_super_admin=user.is_super_admin
    )
    return {"success": True}


@router.patch("/{workspace_id}/members/{member_user_id}")
async def update_member_role(
    workspace_id: str = Path(..., description="Workspace ID"),
    member_user_id: str = Path(..., description="Member's user ID"),
    data: WorkspaceMemberUpdate = Body(...),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Update a member's role.

    Requires owner or admin role.
    Owners can change anyone's role (except promote to owner).
    Admins can only change member roles.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    target_uuid = parse_uuid(member_user_id, field="member_user_id")

    result = await service.update_member_role(
        workspace_id=workspace_uuid,
        user_id=user.id,
        target_user_id=target_uuid,
        new_role=data.role.value,
        is_super_admin=user.is_super_admin,
    )
    return result


@router.delete("/{workspace_id}/members/{member_user_id}")
async def remove_member(
    workspace_id: str = Path(..., description="Workspace ID"),
    member_user_id: str = Path(..., description="Member's user ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Remove a member from the workspace.

    Requires owner or admin role.
    Cannot remove workspace owners.
    Admins cannot remove other admins.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    target_uuid = parse_uuid(member_user_id, field="member_user_id")

    await service.remove_member(
        workspace_id=workspace_uuid,
        user_id=user.id,
        target_user_id=target_uuid,
        is_super_admin=user.is_super_admin,
    )
    return {"success": True}


@router.post("/{workspace_id}/leave")
async def leave_workspace(
    workspace_id: str = Path(..., description="Workspace ID"),
    user: UserProfile = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    Leave a workspace.

    Cannot leave if you're the only owner.
    """
    workspace_uuid = parse_uuid(workspace_id, field="workspace_id")
    await service.leave_workspace(workspace_uuid, user.id)
    return {"success": True}
