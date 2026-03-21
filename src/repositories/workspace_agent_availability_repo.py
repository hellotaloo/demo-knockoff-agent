"""
Workspace agent availability repository - GOD admin control over which agents are available per workspace.
"""
import uuid
from typing import Optional

import asyncpg


class WorkspaceAgentAvailabilityRepository:
    """Repository for agents.workspace_agent_availability."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def is_agent_available(self, workspace_id: uuid.UUID, agent_type: str) -> bool:
        """Check if an agent type is available for a workspace. Missing row = not available."""
        row = await self.pool.fetchrow(
            """
            SELECT is_available
            FROM agents.workspace_agent_availability
            WHERE workspace_id = $1 AND agent_type = $2
            """,
            workspace_id,
            agent_type,
        )
        if not row:
            return False
        return row["is_available"]

    async def get_available_agents(self, workspace_id: uuid.UUID) -> list[str]:
        """Get all available agent types for a workspace."""
        rows = await self.pool.fetch(
            """
            SELECT agent_type
            FROM agents.workspace_agent_availability
            WHERE workspace_id = $1 AND is_available = true
            ORDER BY agent_type
            """,
            workspace_id,
        )
        return [row["agent_type"] for row in rows]
