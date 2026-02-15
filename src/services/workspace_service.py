"""
Workspace service - handles workspace management operations.
"""
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID

import asyncpg

from src.auth.exceptions import AuthorizationError, WorkspaceAccessDenied, InsufficientRoleError
from src.repositories import WorkspaceRepository, WorkspaceMembershipRepository, UserProfileRepository

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Service for workspace operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.workspace_repo = WorkspaceRepository(pool)
        self.membership_repo = WorkspaceMembershipRepository(pool)
        self.user_repo = UserProfileRepository(pool)

    async def create_workspace(
        self,
        user_id: UUID,
        name: str,
        slug: Optional[str] = None,
        logo_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new workspace with the user as owner.

        Args:
            user_id: The user creating the workspace
            name: Workspace name
            slug: Optional URL slug (auto-generated if not provided)
            logo_url: Optional logo URL

        Returns:
            Workspace data dict
        """
        # Generate slug if not provided
        if not slug:
            slug = await self.workspace_repo.generate_unique_slug(name)
        else:
            # Verify slug is unique
            existing = await self.workspace_repo.get_by_slug(slug)
            if existing:
                slug = await self.workspace_repo.generate_unique_slug(slug)

        # Create workspace
        workspace_row = await self.workspace_repo.create(
            name=name,
            slug=slug,
            logo_url=logo_url,
        )

        # Add user as owner
        await self.membership_repo.add_member(
            user_profile_id=user_id,
            workspace_id=workspace_row["id"],
            role="owner",
        )

        return self._workspace_to_dict(workspace_row, role="owner")

    async def get_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get workspace details.

        Args:
            workspace_id: The workspace ID
            user_id: The requesting user's ID

        Returns:
            Workspace data dict

        Raises:
            WorkspaceAccessDenied: If user doesn't have access
        """
        # Verify membership
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace:
            raise WorkspaceAccessDenied(str(workspace_id))

        return self._workspace_to_dict(workspace, role=membership["role"])

    async def update_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
        name: Optional[str] = None,
        logo_url: Optional[str] = None,
        settings: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Update workspace settings.

        Args:
            workspace_id: The workspace ID
            user_id: The requesting user's ID
            name: Optional new name
            logo_url: Optional new logo URL
            settings: Optional new settings

        Returns:
            Updated workspace data

        Raises:
            InsufficientRoleError: If user is not owner
        """
        # Verify ownership
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        if membership["role"] != "owner":
            raise InsufficientRoleError("owner", membership["role"])

        # Update workspace
        workspace = await self.workspace_repo.update(
            workspace_id=workspace_id,
            name=name,
            logo_url=logo_url,
            settings=settings,
        )

        return self._workspace_to_dict(workspace, role="owner")

    async def delete_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Delete a workspace.

        Args:
            workspace_id: The workspace ID
            user_id: The requesting user's ID

        Returns:
            True if deleted

        Raises:
            InsufficientRoleError: If user is not owner
        """
        # Verify ownership
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        if membership["role"] != "owner":
            raise InsufficientRoleError("owner", membership["role"])

        return await self.workspace_repo.delete(workspace_id)

    async def get_workspace_members(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        Get all members of a workspace.

        Args:
            workspace_id: The workspace ID
            user_id: The requesting user's ID

        Returns:
            List of member dicts
        """
        # Verify membership
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        members = await self.membership_repo.get_workspace_members(workspace_id)
        return [
            {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "email": row["email"],
                "full_name": row["full_name"],
                "avatar_url": row["avatar_url"],
                "role": row["role"],
                "joined_at": row["joined_at"],
            }
            for row in members
        ]

    async def invite_member(
        self,
        workspace_id: UUID,
        user_id: UUID,
        email: str,
        role: str = "member",
    ) -> Dict[str, Any]:
        """
        Invite a user to the workspace.

        Args:
            workspace_id: The workspace ID
            user_id: The inviting user's ID
            email: Email to invite
            role: Role to assign (admin or member)

        Returns:
            Invitation data

        Raises:
            InsufficientRoleError: If user can't invite
        """
        # Verify can invite (owner or admin)
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        if membership["role"] not in ("owner", "admin"):
            raise InsufficientRoleError("owner or admin", membership["role"])

        # Can't invite as owner
        if role == "owner":
            raise AuthorizationError("Cannot invite as owner")

        # Check if user already exists and is a member
        existing_user = await self.user_repo.get_by_email(email)
        if existing_user:
            existing_membership = await self.membership_repo.get_membership(
                existing_user["id"],
                workspace_id
            )
            if existing_membership:
                raise AuthorizationError(f"User {email} is already a member")

            # User exists - add them directly
            await self.membership_repo.add_member(
                user_profile_id=existing_user["id"],
                workspace_id=workspace_id,
                role=role,
                invited_by=user_id,
            )
            return {
                "status": "added",
                "email": email,
                "role": role,
                "message": f"User {email} added to workspace",
            }

        # Create invitation
        invitation = await self.membership_repo.create_invitation(
            workspace_id=workspace_id,
            email=email,
            role=role,
            invited_by=user_id,
        )

        return {
            "id": str(invitation["id"]),
            "workspace_id": str(invitation["workspace_id"]),
            "email": invitation["email"],
            "role": invitation["role"],
            "expires_at": invitation["expires_at"],
            "created_at": invitation["created_at"],
        }

    async def update_member_role(
        self,
        workspace_id: UUID,
        user_id: UUID,
        target_user_id: UUID,
        new_role: str,
    ) -> Dict[str, Any]:
        """
        Update a member's role.

        Args:
            workspace_id: The workspace ID
            user_id: The requesting user's ID
            target_user_id: The user to update
            new_role: The new role

        Returns:
            Updated membership data

        Raises:
            InsufficientRoleError: If user can't update roles
        """
        # Verify can update (owner or admin)
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        if membership["role"] not in ("owner", "admin"):
            raise InsufficientRoleError("owner or admin", membership["role"])

        # Get target membership
        target_membership = await self.membership_repo.get_membership(target_user_id, workspace_id)
        if not target_membership:
            raise AuthorizationError("User is not a member of this workspace")

        # Can't change owner's role (unless you're the owner)
        if target_membership["role"] == "owner" and membership["role"] != "owner":
            raise AuthorizationError("Cannot change owner's role")

        # Can't promote to owner
        if new_role == "owner":
            raise AuthorizationError("Cannot promote to owner")

        # Admin can't change other admin's role
        if membership["role"] == "admin" and target_membership["role"] == "admin":
            raise AuthorizationError("Admins cannot change other admin's role")

        await self.membership_repo.update_member_role(target_user_id, workspace_id, new_role)

        return {
            "user_id": str(target_user_id),
            "workspace_id": str(workspace_id),
            "role": new_role,
        }

    async def remove_member(
        self,
        workspace_id: UUID,
        user_id: UUID,
        target_user_id: UUID,
    ) -> bool:
        """
        Remove a member from the workspace.

        Args:
            workspace_id: The workspace ID
            user_id: The requesting user's ID
            target_user_id: The user to remove

        Returns:
            True if removed

        Raises:
            InsufficientRoleError: If user can't remove members
        """
        # Verify can remove (owner or admin)
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))

        if membership["role"] not in ("owner", "admin"):
            raise InsufficientRoleError("owner or admin", membership["role"])

        # Get target membership
        target_membership = await self.membership_repo.get_membership(target_user_id, workspace_id)
        if not target_membership:
            return True  # Already not a member

        # Can't remove owner
        if target_membership["role"] == "owner":
            raise AuthorizationError("Cannot remove workspace owner")

        # Admin can't remove other admins
        if membership["role"] == "admin" and target_membership["role"] == "admin":
            raise AuthorizationError("Admins cannot remove other admins")

        return await self.membership_repo.remove_member(target_user_id, workspace_id)

    async def leave_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Leave a workspace.

        Args:
            workspace_id: The workspace ID
            user_id: The user leaving

        Returns:
            True if left

        Raises:
            AuthorizationError: If user is the only owner
        """
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            return True  # Not a member

        # If owner, check there's another owner
        if membership["role"] == "owner":
            owner_count = await self.membership_repo.count_workspace_owners(workspace_id)
            if owner_count <= 1:
                raise AuthorizationError(
                    "Cannot leave workspace as the only owner. Transfer ownership first."
                )

        return await self.membership_repo.remove_member(user_id, workspace_id)

    def _workspace_to_dict(self, row: asyncpg.Record, role: str) -> Dict[str, Any]:
        """Convert workspace row to dict."""
        return {
            "id": str(row["id"]),
            "name": row["name"],
            "slug": row["slug"],
            "logo_url": row["logo_url"],
            "settings": row["settings"] or {},
            "role": role,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
