"""
Pre-screening event handlers.

Reacts to domain events that affect pre-screening agents.
"""
import logging
from uuid import UUID

import asyncpg

from src.events import on

logger = logging.getLogger(__name__)


@on("vacancy_archived")
async def handle_vacancy_archived(pool: asyncpg.Pool, vacancy_id: UUID, **kwargs):
    """Archive pre-screening agent and disable all channels when vacancy is archived."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE ats.vacancy_agents SET status = 'archived' "
            "WHERE vacancy_id = $1 AND agent_type = 'prescreening'",
            vacancy_id,
        )
        if "UPDATE 1" in result:
            logger.info(f"Pre-screening archived for vacancy {vacancy_id}")

        # Disable all channels so they don't appear online in the admin
        await conn.execute(
            "UPDATE agents.pre_screenings "
            "SET voice_enabled = false, whatsapp_enabled = false, cv_enabled = false "
            "WHERE vacancy_id = $1",
            vacancy_id,
        )


@on("vacancy_reopened")
async def handle_vacancy_reopened(pool: asyncpg.Pool, vacancy_id: UUID, **kwargs):
    """Auto re-activate pre-screening when vacancy is re-opened (if previously published)."""
    async with pool.acquire() as conn:
        ps = await conn.fetchrow(
            "SELECT id, published_at FROM agents.pre_screenings WHERE vacancy_id = $1",
            vacancy_id,
        )
        if ps and ps["published_at"]:
            await conn.execute(
                "UPDATE ats.vacancy_agents SET status = 'published' "
                "WHERE vacancy_id = $1 AND agent_type = 'prescreening'",
                vacancy_id,
            )
            logger.info(f"Pre-screening re-activated for reopened vacancy {vacancy_id}")
