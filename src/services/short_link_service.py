"""
Short link service — creates and resolves short tokens for WhatsApp CTA URLs.

Usage:
    service = ShortLinkService(pool)
    token = await service.create("https://yousign.app/signatures/...", context="contract_signing")
    # → "a3f9bc12"
    # Send via WhatsApp: https://demo.taloo.be/r/a3f9bc12

    url = await service.resolve("a3f9bc12")
    # → "https://yousign.app/signatures/..."
"""
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from src.repositories.short_link_repo import ShortLinkRepository


_ALPHABET = string.ascii_lowercase + string.digits
_TOKEN_LENGTH = 8


def _generate_token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_TOKEN_LENGTH))


class ShortLinkService:
    def __init__(self, pool: asyncpg.Pool):
        self.repo = ShortLinkRepository(pool)

    async def create(
        self,
        url: str,
        context: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> str:
        """Store a URL and return a short token."""
        token = _generate_token()
        await self.repo.create(token, url, context, expires_at)
        return token

    async def resolve(self, token: str) -> Optional[str]:
        """
        Look up a token and return the target URL.
        Returns None if not found or expired.
        """
        row = await self.repo.get(token)
        if not row:
            return None
        if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
            return None
        return row["url"]
