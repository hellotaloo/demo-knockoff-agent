"""
Pre-screening repository - handles all pre-screening-related database operations.
"""
import asyncpg
import uuid
from typing import Optional, Tuple
from datetime import datetime


class PreScreeningRepository:
    """Repository for pre-screening database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_for_vacancy(self, vacancy_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get pre-screening configuration for a vacancy with agent IDs."""
        return await self.pool.fetchrow(
            """
            SELECT id, vacancy_id, intro, knockout_failed_action, final_action, status,
                   created_at, updated_at, published_at, is_online, elevenlabs_agent_id, whatsapp_agent_id,
                   voice_enabled, whatsapp_enabled, cv_enabled
            FROM ats.pre_screenings
            WHERE vacancy_id = $1
            """,
            vacancy_id
        )

    async def get_questions(self, pre_screening_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all questions for a pre-screening."""
        return await self.pool.fetch(
            """
            SELECT id, question_type, position, question_text, ideal_answer, vacancy_snippet, is_approved
            FROM ats.pre_screening_questions
            WHERE pre_screening_id = $1
            ORDER BY question_type, position
            """,
            pre_screening_id
        )

    async def upsert(
        self,
        vacancy_id: uuid.UUID,
        intro: str,
        knockout_failed_action: str,
        final_action: str,
        knockout_questions: list[dict],
        qualification_questions: list[dict],
        approved_ids: list[str]
    ) -> uuid.UUID:
        """
        Save or update pre-screening configuration with questions.

        Returns the pre_screening_id.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Check if pre-screening already exists for this vacancy
                existing_id = await conn.fetchval(
                    "SELECT id FROM ats.pre_screenings WHERE vacancy_id = $1",
                    vacancy_id
                )

                if existing_id:
                    # Update existing pre-screening
                    await conn.execute(
                        """
                        UPDATE ats.pre_screenings
                        SET intro = $1, knockout_failed_action = $2, final_action = $3,
                            status = 'active', updated_at = NOW()
                        WHERE id = $4
                        """,
                        intro, knockout_failed_action, final_action, existing_id
                    )
                    pre_screening_id = existing_id

                    # Delete existing questions (will be replaced)
                    await conn.execute(
                        "DELETE FROM ats.pre_screening_questions WHERE pre_screening_id = $1",
                        pre_screening_id
                    )
                else:
                    # Create new pre-screening
                    row = await conn.fetchrow(
                        """
                        INSERT INTO ats.pre_screenings (vacancy_id, intro, knockout_failed_action, final_action, status)
                        VALUES ($1, $2, $3, $4, 'active')
                        RETURNING id
                        """,
                        vacancy_id, intro, knockout_failed_action, final_action
                    )
                    pre_screening_id = row["id"]

                # Insert knockout questions
                for position, q in enumerate(knockout_questions):
                    is_approved = q["id"] in approved_ids
                    await conn.execute(
                        """
                        INSERT INTO ats.pre_screening_questions
                        (pre_screening_id, question_type, position, question_text, vacancy_snippet, is_approved)
                        VALUES ($1, 'knockout', $2, $3, $4, $5)
                        """,
                        pre_screening_id, position, q["question"], q.get("vacancy_snippet"), is_approved
                    )

                # Insert qualification questions (with ideal_answer)
                for position, q in enumerate(qualification_questions):
                    is_approved = q["id"] in approved_ids
                    await conn.execute(
                        """
                        INSERT INTO ats.pre_screening_questions
                        (pre_screening_id, question_type, position, question_text, ideal_answer, vacancy_snippet, is_approved)
                        VALUES ($1, 'qualification', $2, $3, $4, $5, $6)
                        """,
                        pre_screening_id, position, q["question"], q.get("ideal_answer", ""), q.get("vacancy_snippet"), is_approved
                    )

        return pre_screening_id

    async def delete(self, vacancy_id: uuid.UUID) -> bool:
        """
        Delete pre-screening configuration for a vacancy.

        Returns True if deleted, False if not found.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Check if pre-screening exists
                pre_screening_id = await conn.fetchval(
                    "SELECT id FROM ats.pre_screenings WHERE vacancy_id = $1",
                    vacancy_id
                )

                if not pre_screening_id:
                    return False

                # Delete pre-screening (questions cascade automatically)
                await conn.execute(
                    "DELETE FROM ats.pre_screenings WHERE id = $1",
                    pre_screening_id
                )

        return True

    async def update_publish_state(
        self,
        pre_screening_id: uuid.UUID,
        published_at: datetime,
        elevenlabs_agent_id: Optional[str],
        whatsapp_agent_id: Optional[str],
        is_online: bool,
        voice_enabled: bool,
        whatsapp_enabled: bool,
        cv_enabled: bool
    ):
        """Update pre-screening publish state with agent IDs and channel flags."""
        await self.pool.execute(
            """
            UPDATE ats.pre_screenings
            SET published_at = $1,
                elevenlabs_agent_id = $2,
                whatsapp_agent_id = $3,
                is_online = $4,
                voice_enabled = $5,
                whatsapp_enabled = $6,
                cv_enabled = $7,
                updated_at = NOW()
            WHERE id = $8
            """,
            published_at, elevenlabs_agent_id, whatsapp_agent_id, is_online,
            voice_enabled, whatsapp_enabled, cv_enabled, pre_screening_id
        )

    async def update_agent_id(
        self,
        pre_screening_id: uuid.UUID,
        agent_type: str,
        agent_id: str
    ):
        """Update a specific agent ID (elevenlabs or whatsapp)."""
        if agent_type == "elevenlabs":
            await self.pool.execute(
                "UPDATE ats.pre_screenings SET elevenlabs_agent_id = $1, updated_at = NOW() WHERE id = $2",
                agent_id, pre_screening_id
            )
        elif agent_type == "whatsapp":
            await self.pool.execute(
                "UPDATE ats.pre_screenings SET whatsapp_agent_id = $1, updated_at = NOW() WHERE id = $2",
                agent_id, pre_screening_id
            )

    async def update_status_flags(
        self,
        pre_screening_id: uuid.UUID,
        is_online: Optional[bool] = None,
        voice_enabled: Optional[bool] = None,
        whatsapp_enabled: Optional[bool] = None,
        cv_enabled: Optional[bool] = None
    ):
        """
        Update status flags dynamically.

        Only provided fields will be updated.
        """
        updates = []
        params = []
        param_idx = 1

        if is_online is not None:
            updates.append(f"is_online = ${param_idx}")
            params.append(is_online)
            param_idx += 1

        if voice_enabled is not None:
            updates.append(f"voice_enabled = ${param_idx}")
            params.append(voice_enabled)
            param_idx += 1

        if whatsapp_enabled is not None:
            updates.append(f"whatsapp_enabled = ${param_idx}")
            params.append(whatsapp_enabled)
            param_idx += 1

        if cv_enabled is not None:
            updates.append(f"cv_enabled = ${param_idx}")
            params.append(cv_enabled)
            param_idx += 1

        if not updates:
            return  # Nothing to update

        # Add updated_at and the WHERE clause parameter
        updates.append("updated_at = NOW()")
        params.append(pre_screening_id)

        # Execute update
        query = f"""
            UPDATE ats.pre_screenings
            SET {", ".join(updates)}
            WHERE id = ${param_idx}
        """
        await self.pool.execute(query, *params)

    async def get_with_status(self, pre_screening_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get pre-screening with current status flags and agent IDs."""
        return await self.pool.fetchrow(
            """
            SELECT is_online, voice_enabled, whatsapp_enabled, cv_enabled,
                   elevenlabs_agent_id, whatsapp_agent_id
            FROM ats.pre_screenings
            WHERE id = $1
            """,
            pre_screening_id
        )

    async def update_online_status(self, pre_screening_id: uuid.UUID, is_online: bool):
        """Toggle online/offline status."""
        await self.pool.execute(
            "UPDATE ats.pre_screenings SET is_online = $1, updated_at = NOW() WHERE id = $2",
            is_online, pre_screening_id
        )
