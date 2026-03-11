"""
Short link redirect router.

GET /r/{token} → 302 redirect to the stored URL.

Used for WhatsApp CTA buttons where the full URL is too long
to pass as a template variable (e.g. Yousign signing links).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
import asyncpg

from src.dependencies import get_pool
from src.services.short_link_service import ShortLinkService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["redirect"])


@router.get("/r/{token}", include_in_schema=False)
async def redirect(token: str, pool: asyncpg.Pool = Depends(get_pool)):
    url = await ShortLinkService(pool).resolve(token)
    if not url:
        raise HTTPException(status_code=404, detail="Link not found or expired")
    logger.info("Short link resolved: %s → %s", token, url[:60])
    return RedirectResponse(url=url, status_code=302)
