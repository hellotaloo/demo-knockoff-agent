"""
Short link repository — stores token → URL mappings for WhatsApp CTA buttons.
"""
import asyncpg
from datetime import datetime
from typing import Optional


class ShortLinkRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(self, token: str, url: str, context: Optional[str] = None, expires_at: Optional[datetime] = None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO system.short_links (token, url, context, expires_at)
                VALUES ($1, $2, $3, $4)
                """,
                token, url, context, expires_at,
            )

    async def get(self, token: str) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT url, expires_at
                FROM system.short_links
                WHERE token = $1
                """,
                token,
            )
