"""
Workspace membership repository - handles membership database operations.
"""
import asyncpg
import uuid
import secrets
from typing import Optional, List
from datetime import datetime, timedelta, timezone


class WorkspaceMembershipRepository:
    """Repository for workspace membership database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # Memberships
    # =========================================================================

    async def get_membership(
        self,
        user_profile_id: uuid.UUID,
        workspace_id: uuid.UUID
    ) -> Optional[asyncpg.Record]:
        """Get a specific membership."""
        return await self.pool.fetchrow(
            """
            SELECT wm.*, w.name as workspace_name, w.slug as workspace_slug
            FROM ats.workspace_memberships wm
            JOIN ats.workspaces w ON w.id = wm.workspace_id
            WHERE wm.user_profile_id = $1 AND wm.workspace_id = $2
            """,
            user_profile_id,
            workspace_id
        )

    async def get_user_workspaces(self, user_profile_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all workspaces a user belongs to."""
        return await self.pool.fetch(
            """
            SELECT
                w.id,
                w.name,
                w.slug,
                w.logo_url,
                w.settings,
                w.created_at,
                w.updated_at,
                wm.role,
                wm.created_at as joined_at
            FROM ats.workspace_memberships wm
            JOIN ats.workspaces w ON w.id = wm.workspace_id
            WHERE wm.user_profile_id = $1
            ORDER BY w.name
            """,
            user_profile_id
        )

    async def get_workspace_members(self, workspace_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all members of a workspace."""
        return await self.pool.fetch(
            """
            SELECT
                wm.id,
                wm.role,
                wm.created_at as joined_at,
                up.id as user_id,
                up.email,
                up.full_name,
                up.avatar_url
            FROM ats.workspace_memberships wm
            JOIN ats.user_profiles up ON up.id = wm.user_profile_id
            WHERE wm.workspace_id = $1
            ORDER BY
                CASE wm.role
                    WHEN 'owner' THEN 1
                    WHEN 'admin' THEN 2
                    ELSE 3
                END,
                up.full_name
            """,
            workspace_id
        )

    async def add_member(
        self,
        user_profile_id: uuid.UUID,
        workspace_id: uuid.UUID,
        role: str = "member",
        invited_by: Optional[uuid.UUID] = None,
    ) -> asyncpg.Record:
        """Add a member to a workspace."""
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.workspace_memberships (user_profile_id, workspace_id, role, invited_by)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_profile_id, workspace_id) DO UPDATE
            SET role = EXCLUDED.role
            RETURNING *
            """,
            user_profile_id,
            workspace_id,
            role,
            invited_by,
        )

    async def update_member_role(
        self,
        user_profile_id: uuid.UUID,
        workspace_id: uuid.UUID,
        role: str,
    ) -> Optional[asyncpg.Record]:
        """Update a member's role."""
        return await self.pool.fetchrow(
            """
            UPDATE ats.workspace_memberships
            SET role = $3
            WHERE user_profile_id = $1 AND workspace_id = $2
            RETURNING *
            """,
            user_profile_id,
            workspace_id,
            role,
        )

    async def remove_member(
        self,
        user_profile_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool:
        """Remove a member from a workspace."""
        result = await self.pool.execute(
            """
            DELETE FROM ats.workspace_memberships
            WHERE user_profile_id = $1 AND workspace_id = $2
            """,
            user_profile_id,
            workspace_id,
        )
        return result == "DELETE 1"

    async def count_workspace_members(self, workspace_id: uuid.UUID) -> int:
        """Count members in a workspace."""
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) as count FROM ats.workspace_memberships WHERE workspace_id = $1",
            workspace_id
        )
        return row["count"]

    async def count_workspace_owners(self, workspace_id: uuid.UUID) -> int:
        """Count owners in a workspace."""
        row = await self.pool.fetchrow(
            """
            SELECT COUNT(*) as count FROM ats.workspace_memberships
            WHERE workspace_id = $1 AND role = 'owner'
            """,
            workspace_id
        )
        return row["count"]

    # =========================================================================
    # Invitations
    # =========================================================================

    async def get_invitation_by_id(self, invitation_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get an invitation by ID."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.workspace_invitations WHERE id = $1",
            invitation_id
        )

    async def get_invitation_by_token(self, token: str) -> Optional[asyncpg.Record]:
        """Get an invitation by token."""
        return await self.pool.fetchrow(
            """
            SELECT wi.*, w.name as workspace_name, w.slug as workspace_slug
            FROM ats.workspace_invitations wi
            JOIN ats.workspaces w ON w.id = wi.workspace_id
            WHERE wi.token = $1
            """,
            token
        )

    async def get_pending_invitation(
        self,
        workspace_id: uuid.UUID,
        email: str,
    ) -> Optional[asyncpg.Record]:
        """Get a pending (not accepted, not expired) invitation."""
        return await self.pool.fetchrow(
            """
            SELECT * FROM ats.workspace_invitations
            WHERE workspace_id = $1
              AND email = $2
              AND accepted_at IS NULL
              AND expires_at > NOW()
            """,
            workspace_id,
            email,
        )

    async def get_workspace_invitations(self, workspace_id: uuid.UUID) -> List[asyncpg.Record]:
        """Get all pending invitations for a workspace."""
        return await self.pool.fetch(
            """
            SELECT wi.*, up.full_name as invited_by_name
            FROM ats.workspace_invitations wi
            JOIN ats.user_profiles up ON up.id = wi.invited_by
            WHERE wi.workspace_id = $1
              AND wi.accepted_at IS NULL
              AND wi.expires_at > NOW()
            ORDER BY wi.created_at DESC
            """,
            workspace_id
        )

    async def create_invitation(
        self,
        workspace_id: uuid.UUID,
        email: str,
        role: str,
        invited_by: uuid.UUID,
        expires_in_days: int = 7,
    ) -> asyncpg.Record:
        """Create a workspace invitation."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        return await self.pool.fetchrow(
            """
            INSERT INTO ats.workspace_invitations (workspace_id, email, role, token, invited_by, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (workspace_id, email)
            DO UPDATE SET
                role = EXCLUDED.role,
                token = EXCLUDED.token,
                invited_by = EXCLUDED.invited_by,
                expires_at = EXCLUDED.expires_at,
                accepted_at = NULL
            RETURNING *
            """,
            workspace_id,
            email.lower(),
            role,
            token,
            invited_by,
            expires_at,
        )

    async def accept_invitation(self, invitation_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Mark an invitation as accepted."""
        return await self.pool.fetchrow(
            """
            UPDATE ats.workspace_invitations
            SET accepted_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            invitation_id
        )

    async def delete_invitation(self, invitation_id: uuid.UUID) -> bool:
        """Delete an invitation."""
        result = await self.pool.execute(
            "DELETE FROM ats.workspace_invitations WHERE id = $1",
            invitation_id
        )
        return result == "DELETE 1"

    async def get_invitations_for_email(self, email: str) -> List[asyncpg.Record]:
        """Get all pending invitations for an email address."""
        return await self.pool.fetch(
            """
            SELECT wi.*, w.name as workspace_name, w.slug as workspace_slug
            FROM ats.workspace_invitations wi
            JOIN ats.workspaces w ON w.id = wi.workspace_id
            WHERE wi.email = $1
              AND wi.accepted_at IS NULL
              AND wi.expires_at > NOW()
            ORDER BY wi.created_at DESC
            """,
            email.lower()
        )
