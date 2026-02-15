"""
User profile repository - handles user profile database operations.
"""
import asyncpg
import uuid
from typing import Optional, List
from datetime import datetime


class UserProfileRepository:
    """Repository for user profile database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a user profile by ID."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.user_profiles WHERE id = $1",
            user_id
        )

    async def get_by_auth_user_id(self, auth_user_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a user profile by Supabase auth user ID."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.user_profiles WHERE auth_user_id = $1",
            auth_user_id
        )

    async def get_by_email(self, email: str) -> Optional[asyncpg.Record]:
        """Get a user profile by email."""
        return await self.pool.fetchrow(
            "SELECT * FROM ats.user_profiles WHERE email = $1",
            email
        )

    async def create(
        self,
        auth_user_id: uuid.UUID,
        email: str,
        full_name: str,
        avatar_url: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> asyncpg.Record:
        """Create a new user profile."""
        return await self.pool.fetchrow(
            """
            INSERT INTO ats.user_profiles (auth_user_id, email, full_name, avatar_url, phone)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            auth_user_id,
            email,
            full_name,
            avatar_url,
            phone,
        )

    async def update(
        self,
        user_id: uuid.UUID,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Optional[asyncpg.Record]:
        """Update a user profile."""
        updates = []
        values = []
        param_num = 1

        if full_name is not None:
            updates.append(f"full_name = ${param_num}")
            values.append(full_name)
            param_num += 1

        if avatar_url is not None:
            updates.append(f"avatar_url = ${param_num}")
            values.append(avatar_url)
            param_num += 1

        if phone is not None:
            updates.append(f"phone = ${param_num}")
            values.append(phone)
            param_num += 1

        if not updates:
            return await self.get_by_id(user_id)

        values.append(user_id)
        query = f"""
            UPDATE ats.user_profiles
            SET {', '.join(updates)}
            WHERE id = ${param_num}
            RETURNING *
        """
        return await self.pool.fetchrow(query, *values)

    async def deactivate(self, user_id: uuid.UUID) -> bool:
        """Deactivate a user profile."""
        result = await self.pool.execute(
            "UPDATE ats.user_profiles SET is_active = false WHERE id = $1",
            user_id
        )
        return result == "UPDATE 1"

    async def activate(self, user_id: uuid.UUID) -> bool:
        """Activate a user profile."""
        result = await self.pool.execute(
            "UPDATE ats.user_profiles SET is_active = true WHERE id = $1",
            user_id
        )
        return result == "UPDATE 1"
