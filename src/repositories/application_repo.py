"""
Application repository - handles all application-related database operations.
"""
import asyncpg
import uuid
from typing import Optional, Tuple
from datetime import datetime


class ApplicationRepository:
    """Repository for application database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_for_vacancy(
        self,
        vacancy_id: uuid.UUID,
        qualified: Optional[bool] = None,
        completed: Optional[bool] = None,
        synced: Optional[bool] = None,
        is_test: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List applications for a vacancy with optional filtering.

        Returns:
            Tuple of (application rows, total count)
        """
        # Build query with filters
        conditions = [
            "vacancy_id = $1"
        ]
        params = [vacancy_id]
        param_idx = 2

        if qualified is not None:
            conditions.append(f"qualified = ${param_idx}")
            params.append(qualified)
            param_idx += 1

        if completed is not None:
            # Translate completed boolean to status filter for backwards compatibility
            if completed:
                conditions.append("status = 'completed'")
            else:
                conditions.append("status != 'completed'")

        if synced is not None:
            conditions.append(f"synced = ${param_idx}")
            params.append(synced)
            param_idx += 1

        if is_test is not None:
            conditions.append(f"is_test = ${param_idx}")
            params.append(is_test)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}"

        # Get total count
        count_query = f"SELECT COUNT(*) FROM applications {where_clause}"
        total = await self.pool.fetchval(count_query, *params)

        # Get applications
        query = f"""
            SELECT id, vacancy_id, candidate_name, channel, status, qualified,
                   started_at, completed_at, interaction_seconds, synced, synced_at, summary, interview_slot, is_test
            FROM applications
            {where_clause}
            ORDER BY started_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)

        return rows, total

    async def get_by_id(self, application_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single application by ID."""
        return await self.pool.fetchrow(
            """
            SELECT id, vacancy_id, candidate_name, channel, status, qualified,
                   started_at, completed_at, interaction_seconds, synced, synced_at, summary, interview_slot, is_test
            FROM applications
            WHERE id = $1
            """,
            application_id
        )

    async def get_answers(self, application_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all answers for an application."""
        return await self.pool.fetch(
            """
            SELECT question_id, question_text, answer, passed, score, rating, motivation
            FROM application_answers
            WHERE application_id = $1
            ORDER BY id
            """,
            application_id
        )

    async def get_questions_for_vacancy(self, vacancy_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all pre-screening questions for a vacancy."""
        return await self.pool.fetch(
            """
            SELECT psq.id, psq.question_type, psq.position, psq.question_text, psq.ideal_answer
            FROM pre_screening_questions psq
            JOIN pre_screenings ps ON ps.id = psq.pre_screening_id
            WHERE ps.vacancy_id = $1
            ORDER BY
                CASE psq.question_type WHEN 'knockout' THEN 0 ELSE 1 END,
                psq.position
            """,
            vacancy_id
        )

    async def create(
        self,
        vacancy_id: uuid.UUID,
        candidate_name: str,
        candidate_phone: Optional[str],
        channel: str,
        is_test: bool = False
    ) -> uuid.UUID:
        """Create a new application."""
        app_id = await self.pool.fetchval(
            """
            INSERT INTO applications (
                vacancy_id, candidate_name, candidate_phone, channel,
                status, qualified, started_at, interaction_seconds,
                synced, is_test
            )
            VALUES ($1, $2, $3, $4, 'active', false, NOW(), 0, false, $5)
            RETURNING id
            """,
            vacancy_id, candidate_name, candidate_phone, channel, is_test
        )
        return app_id

    async def update_completed(
        self,
        application_id: uuid.UUID,
        qualified: bool,
        interaction_seconds: int,
        summary: Optional[str] = None,
        interview_slot: Optional[str] = None
    ):
        """Mark an application as completed."""
        await self.pool.execute(
            """
            UPDATE applications
            SET status = 'completed',
                qualified = $2,
                completed_at = NOW(),
                interaction_seconds = $3,
                summary = $4,
                interview_slot = $5
            WHERE id = $1
            """,
            application_id, qualified, interaction_seconds, summary, interview_slot
        )

    async def set_status(self, application_id: uuid.UUID, status: str):
        """Update application status."""
        await self.pool.execute(
            "UPDATE applications SET status = $2 WHERE id = $1",
            application_id, status
        )

    async def insert_knockout_answer(
        self,
        application_id: uuid.UUID,
        question_id: str,
        question_text: str,
        answer: str,
        passed: bool
    ):
        """Insert a knockout question answer."""
        await self.pool.execute(
            """
            INSERT INTO application_answers (application_id, question_id, question_text, answer, passed)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (application_id, question_id) DO UPDATE
            SET answer = EXCLUDED.answer, passed = EXCLUDED.passed
            """,
            application_id, question_id, question_text, answer, passed
        )

    async def insert_qualification_answer(
        self,
        application_id: uuid.UUID,
        question_id: str,
        question_text: str,
        answer: str,
        score: int,
        rating: str,
        motivation: Optional[str] = None
    ):
        """Insert a qualification question answer with scoring."""
        await self.pool.execute(
            """
            INSERT INTO application_answers (
                application_id, question_id, question_text, answer,
                score, rating, motivation
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (application_id, question_id) DO UPDATE
            SET answer = EXCLUDED.answer,
                score = EXCLUDED.score,
                rating = EXCLUDED.rating,
                motivation = EXCLUDED.motivation
            """,
            application_id, question_id, question_text, answer, score, rating, motivation
        )

    async def delete_answers(self, application_id: uuid.UUID):
        """Delete all answers for an application."""
        await self.pool.execute(
            "DELETE FROM application_answers WHERE application_id = $1",
            application_id
        )

    async def find_by_phone(
        self,
        vacancy_id: uuid.UUID,
        phone: str,
        exclude_completed: bool = True
    ) -> Optional[asyncpg.Record]:
        """Find an application by phone number."""
        if exclude_completed:
            return await self.pool.fetchrow(
                """
                SELECT id, vacancy_id, candidate_name, channel, status, qualified
                FROM applications
                WHERE vacancy_id = $1 AND candidate_phone = $2 AND status != 'completed'
                """,
                vacancy_id, phone
            )
        else:
            return await self.pool.fetchrow(
                """
                SELECT id, vacancy_id, candidate_name, channel, status, qualified
                FROM applications
                WHERE vacancy_id = $1 AND candidate_phone = $2
                ORDER BY started_at DESC
                LIMIT 1
                """,
                vacancy_id, phone
            )

    async def delete_for_phone(self, vacancy_id: uuid.UUID, phone: str):
        """Delete applications and conversations for a phone number."""
        # Get application ID first
        app_id = await self.pool.fetchval(
            "SELECT id FROM applications WHERE vacancy_id = $1 AND candidate_phone = $2",
            vacancy_id, phone
        )

        if app_id:
            # Delete answers
            await self.pool.execute(
                "DELETE FROM application_answers WHERE application_id = $1",
                app_id
            )
            # Delete application
            await self.pool.execute(
                "DELETE FROM applications WHERE id = $1",
                app_id
            )

    async def find_test_applications(self) -> list[asyncpg.Record]:
        """Find all test applications that need reprocessing."""
        return await self.pool.fetch(
            """
            SELECT a.id, a.vacancy_id, a.candidate_name
            FROM applications a
            WHERE a.is_test = true
            ORDER BY a.started_at DESC
            """
        )
