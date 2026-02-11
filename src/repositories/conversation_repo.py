"""
Conversation repository - handles all conversation-related database operations.
"""
import asyncpg
import uuid
from typing import Optional, Tuple
from datetime import datetime


class ConversationRepository:
    """Repository for screening conversation database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def list_for_vacancy(
        self,
        vacancy_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[asyncpg.Record], int]:
        """
        List screening conversations for a vacancy with optional filtering.

        Returns:
            Tuple of (conversation rows, total count)
        """
        # Build query
        conditions = ["vacancy_id = $1"]
        params = [vacancy_id]
        param_idx = 2

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        # Get total count
        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM ats.screening_conversations WHERE {where_clause}",
            *params
        )

        # Get conversations
        query = f"""
            SELECT id, vacancy_id, candidate_name, candidate_email, status,
                   started_at, completed_at, message_count
            FROM ats.screening_conversations
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])

        rows = await self.pool.fetch(query, *params)

        return rows, total

    async def get_by_id(self, conversation_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single conversation by ID."""
        return await self.pool.fetchrow(
            """
            SELECT id, vacancy_id, pre_screening_id, session_id, candidate_name,
                   candidate_email, candidate_phone, status, started_at, completed_at,
                   message_count, channel, is_test
            FROM ats.screening_conversations
            WHERE id = $1
            """,
            conversation_id
        )

    async def get_messages(self, conversation_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all messages for a conversation."""
        return await self.pool.fetch(
            """
            SELECT role, message, created_at
            FROM ats.conversation_messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC
            """,
            conversation_id
        )

    async def create(
        self,
        vacancy_id: uuid.UUID,
        pre_screening_id: uuid.UUID,
        session_id: str,
        candidate_name: str,
        candidate_phone: Optional[str],
        channel: str,
        is_test: bool = False
    ) -> uuid.UUID:
        """Create a new screening conversation."""
        conv_id = await self.pool.fetchval(
            """
            INSERT INTO ats.screening_conversations
            (vacancy_id, pre_screening_id, session_id, candidate_name, candidate_phone, channel, status, is_test)
            VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
            RETURNING id
            """,
            vacancy_id, pre_screening_id, session_id, candidate_name, candidate_phone, channel, is_test
        )
        return conv_id

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        message: str
    ):
        """Add a message to a conversation."""
        await self.pool.execute(
            """
            INSERT INTO ats.conversation_messages (conversation_id, role, message)
            VALUES ($1, $2, $3)
            """,
            conversation_id, role, message
        )

    async def update_message_count(self, conversation_id: uuid.UUID, count: int):
        """Update the message count for a conversation."""
        await self.pool.execute(
            """
            UPDATE ats.screening_conversations
            SET message_count = $2, updated_at = NOW()
            WHERE id = $1
            """,
            conversation_id, count
        )

    async def update_status(
        self,
        conversation_id: uuid.UUID,
        status: str,
        completed_at: Optional[datetime] = None
    ):
        """Update conversation status."""
        if completed_at:
            await self.pool.execute(
                """
                UPDATE ats.screening_conversations
                SET status = $2, completed_at = $3, updated_at = NOW()
                WHERE id = $1
                """,
                conversation_id, status, completed_at
            )
        else:
            await self.pool.execute(
                """
                UPDATE ats.screening_conversations
                SET status = $2, updated_at = NOW()
                WHERE id = $1
                """,
                conversation_id, status
            )

    async def complete(self, conversation_id: uuid.UUID):
        """Mark conversation as completed."""
        await self.pool.execute(
            """
            UPDATE ats.screening_conversations
            SET status = 'completed', completed_at = NOW(), updated_at = NOW()
            WHERE id = $1
            """,
            conversation_id
        )

    async def find_by_session_id(self, session_id: str) -> Optional[asyncpg.Record]:
        """Find a conversation by ADK session ID."""
        return await self.pool.fetchrow(
            """
            SELECT id, vacancy_id, candidate_phone, status, channel
            FROM ats.screening_conversations
            WHERE session_id = $1
            """,
            session_id
        )

    async def find_active_for_phone(
        self,
        vacancy_id: uuid.UUID,
        phone: str
    ) -> Optional[asyncpg.Record]:
        """Find an active conversation for a phone number."""
        return await self.pool.fetchrow(
            """
            SELECT id FROM ats.screening_conversations
            WHERE vacancy_id = $1 AND candidate_phone = $2 AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            vacancy_id, phone
        )

    async def delete_for_phone(self, vacancy_id: uuid.UUID, phone: str):
        """Delete conversations and messages for a phone number."""
        # Get conversation IDs first
        conv_ids = await self.pool.fetch(
            "SELECT id FROM ats.screening_conversations WHERE vacancy_id = $1 AND candidate_phone = $2",
            vacancy_id, phone
        )

        if conv_ids:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    for row in conv_ids:
                        conv_id = row["id"]
                        # Delete related conversation_messages first
                        await conn.execute(
                            "DELETE FROM ats.conversation_messages WHERE conversation_id = $1",
                            conv_id
                        )

                    # Delete all conversations for this phone
                    await conn.execute(
                        """
                        DELETE FROM ats.screening_conversations
                        WHERE vacancy_id = $1 AND candidate_phone = $2
                        """,
                        vacancy_id, phone
                    )

    async def delete_all(self):
        """Delete all conversations (for demo reset)."""
        await self.pool.execute("DELETE FROM ats.screening_conversations")
