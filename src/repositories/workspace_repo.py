"""
Workspace repository - handles workspace database operations.
"""
import asyncpg
import uuid
from typing import Optional, List, Tuple
from datetime import datetime


class WorkspaceRepository:
    """Repository for workspace database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_by_id(self, workspace_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a workspace by ID."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.workspaces WHERE id = $1",
            workspace_id
        )

    async def get_by_slug(self, slug: str) -> Optional[asyncpg.Record]:
        """Get a workspace by slug."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.workspaces WHERE slug = $1",
            slug
        )

    async def list_all(self) -> List[asyncpg.Record]:
        """Get all workspaces."""
        return await self.pool.fetch(
            "SELECT * FROM ats.workspaces ORDER BY name"
        )

    async def create(
        self,
        name: str,
        slug: str,
        logo_url: Optional[str] = None,
        settings: Optional[dict] = None,
    ) -> asyncpg.Record:
        """Create a new workspace."""
        import json
        settings_json = json.dumps(settings or {})
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.workspaces (name, slug, logo_url, settings)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING *
            """,
            name,
            slug,
            logo_url,
            settings_json,
        )

    async def update(
        self,
        workspace_id: uuid.UUID,
        name: Optional[str] = None,
        logo_url: Optional[str] = None,
        settings: Optional[dict] = None,
    ) -> Optional[asyncpg.Record]:
        """Update a workspace."""
        import json
        updates = []
        values = []
        param_num = 1

        if name is not None:
            updates.append(f"name = ${param_num}")
            values.append(name)
            param_num += 1

        if logo_url is not None:
            updates.append(f"logo_url = ${param_num}")
            values.append(logo_url)
            param_num += 1

        if settings is not None:
            updates.append(f"settings = ${param_num}::jsonb")
            values.append(json.dumps(settings))
            param_num += 1

        if not updates:
            return await self.get_by_id(workspace_id)

        values.append(workspace_id)
        query = f"""
            UPDATE ats.workspaces
            SET {', '.join(updates)}
            WHERE id = ${param_num}
            RETURNING *
        """
        return await self.pool.fetchrow(query, *values)

    async def delete(self, workspace_id: uuid.UUID) -> bool:
        """Delete a workspace."""
        result = await self.pool.execute(
            "DELETE FROM ats.workspaces WHERE id = $1",
            workspace_id
        )
        return result == "DELETE 1"

    async def generate_unique_slug(self, base_slug: str) -> str:
        """Generate a unique slug based on a base slug."""
        import re
        # Normalize the base slug
        slug = re.sub(r'[^a-z0-9-]', '', base_slug.lower().replace(' ', '-'))
        slug = re.sub(r'-+', '-', slug).strip('-')

        if not slug:
            slug = "workspace"

        # Check if it exists
        existing = await self.get_by_slug(slug)
        if not existing:
            return slug

        # Add numeric suffix
        counter = 1
        while True:
            new_slug = f"{slug}-{counter}"
            existing = await self.get_by_slug(new_slug)
            if not existing:
                return new_slug
            counter += 1
            if counter > 100:
                # Fallback to UUID suffix
                return f"{slug}-{uuid.uuid4().hex[:8]}"
