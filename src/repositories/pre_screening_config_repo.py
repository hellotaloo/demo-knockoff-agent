"""
Pre-screening config repository - handles agents.pre_screening_config (global, single-row).
"""
import asyncpg
from typing import Optional


class PreScreeningConfigRepository:
    """Repository for the global pre-screening agent configuration."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get(self) -> Optional[asyncpg.Record]:
        """Get the global pre-screening config (single row)."""
        return await self.pool.fetchrow(
            """
            SELECT id, max_unrelated_answers, schedule_days_ahead, schedule_start_offset,
                   planning_mode, intro_message, success_message,
                   require_consent, allow_escalation
            FROM agents.pre_screening_config
            LIMIT 1
            """
        )

    async def update(
        self,
        config_id,
        max_unrelated_answers: Optional[int] = None,
        schedule_days_ahead: Optional[int] = None,
        schedule_start_offset: Optional[int] = None,
        planning_mode: Optional[str] = None,
        intro_message: Optional[str] = None,
        success_message: Optional[str] = None,
        require_consent: Optional[bool] = None,
        allow_escalation: Optional[bool] = None,
    ):
        """Update config fields dynamically. Only provided fields will be updated."""
        updates = []
        params = []
        param_idx = 1

        for field_name, value in [
            ("max_unrelated_answers", max_unrelated_answers),
            ("schedule_days_ahead", schedule_days_ahead),
            ("schedule_start_offset", schedule_start_offset),
            ("planning_mode", planning_mode),
            ("intro_message", intro_message),
            ("success_message", success_message),
            ("require_consent", require_consent),
            ("allow_escalation", allow_escalation),
        ]:
            if value is not None:
                updates.append(f"{field_name} = ${param_idx}")
                params.append(value)
                param_idx += 1

        if not updates:
            return

        updates.append("updated_at = NOW()")
        params.append(config_id)

        query = f"""
            UPDATE agents.pre_screening_config
            SET {", ".join(updates)}
            WHERE id = ${param_idx}
        """
        await self.pool.execute(query, *params)
