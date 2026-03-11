"""
Repository for document collections, messages, and uploads.
"""
import asyncpg
import json
import uuid
from typing import Optional


class DocumentCollectionRepository:
    """CRUD operations for agents.document_collections, _messages, _uploads."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # Collections
    # =========================================================================

    async def list_collections(
        self,
        workspace_id: uuid.UUID,
        vacancy_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[asyncpg.Record], int]:
        """List document collections with filtering and pagination."""
        conditions = ["dc.workspace_id = $1"]
        params: list = [workspace_id]
        idx = 2

        if vacancy_id is not None:
            conditions.append(f"dc.vacancy_id = ${idx}")
            params.append(vacancy_id)
            idx += 1

        if status is not None:
            conditions.append(f"dc.status = ${idx}")
            params.append(status)
            idx += 1

        where = " AND ".join(conditions)

        # Count
        total = await self.pool.fetchval(
            f"SELECT COUNT(*) FROM agents.document_collections dc WHERE {where}",
            *params,
        )

        # Fetch
        params.extend([limit, offset])
        rows = await self.pool.fetch(
            f"""
            SELECT dc.id, dc.config_id, dc.workspace_id, dc.vacancy_id, dc.application_id,
                   dc.candidate_id, dc.session_id, dc.candidate_name, dc.candidate_phone,
                   dc.status, dc.channel, dc.retry_count, dc.message_count,
                   dc.documents_required, dc.started_at, dc.updated_at, dc.completed_at,
                   v.title AS vacancy_title,
                   COALESCE(jsonb_array_length(dc.documents_required), 0) AS documents_total,
                   COALESCE((SELECT COUNT(*) FROM agents.document_collection_uploads u
                             WHERE u.collection_id = dc.id AND u.status = 'verified'), 0) AS documents_collected,
                   COALESCE((SELECT COUNT(*) FROM agents.document_collection_session_turns m
                             WHERE m.collection_id = dc.id AND m.role = 'user'), 0) AS user_message_count
            FROM agents.document_collections dc
            LEFT JOIN ats.vacancies v ON dc.vacancy_id = v.id
            WHERE {where}
            ORDER BY dc.started_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        return rows, total

    async def get_by_id(self, collection_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a single document collection."""
        return await self.pool.fetchrow(
            """
            SELECT dc.id, dc.config_id, dc.workspace_id, dc.vacancy_id, dc.application_id,
                   dc.candidate_id, dc.session_id, dc.candidate_name, dc.candidate_phone,
                   dc.status, dc.channel, dc.retry_count, dc.message_count,
                   dc.documents_required, dc.started_at, dc.updated_at, dc.completed_at,
                   v.title AS vacancy_title,
                   COALESCE(jsonb_array_length(dc.documents_required), 0) AS documents_total,
                   COALESCE((SELECT COUNT(*) FROM agents.document_collection_uploads u
                             WHERE u.collection_id = dc.id AND u.status = 'verified'), 0) AS documents_collected,
                   COALESCE((SELECT COUNT(*) FROM agents.document_collection_session_turns m
                             WHERE m.collection_id = dc.id AND m.role = 'user'), 0) AS user_message_count
            FROM agents.document_collections dc
            LEFT JOIN ats.vacancies v ON dc.vacancy_id = v.id
            WHERE dc.id = $1
            """,
            collection_id,
        )

    async def find_active_for_phone(self, candidate_phone: str) -> Optional[asyncpg.Record]:
        """Find an active document collection by phone number."""
        return await self.pool.fetchrow(
            """
            SELECT id, config_id, workspace_id, vacancy_id, application_id,
                   candidate_id, session_id, candidate_name, candidate_phone,
                   status, channel, retry_count, message_count,
                   documents_required, started_at, updated_at, completed_at
            FROM agents.document_collections
            WHERE candidate_phone = $1 AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            candidate_phone,
        )

    async def create(
        self,
        config_id: uuid.UUID,
        workspace_id: uuid.UUID,
        candidate_name: str,
        candidate_phone: Optional[str],
        vacancy_id: Optional[uuid.UUID] = None,
        application_id: Optional[uuid.UUID] = None,
        candidate_id: Optional[uuid.UUID] = None,
        documents_required: Optional[list] = None,
        channel: str = "whatsapp",
    ) -> asyncpg.Record:
        """Create a new document collection."""
        docs_json = json.dumps(documents_required) if documents_required else None
        return await self.pool.fetchrow(
            """
            INSERT INTO agents.document_collections
                (config_id, workspace_id, vacancy_id, application_id, candidate_id,
                 candidate_name, candidate_phone, status, channel, documents_required)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8, $9::jsonb)
            RETURNING id, config_id, workspace_id, vacancy_id, application_id,
                      candidate_id, session_id, candidate_name, candidate_phone,
                      status, channel, retry_count, message_count,
                      documents_required, started_at, updated_at, completed_at
            """,
            config_id, workspace_id, vacancy_id, application_id, candidate_id,
            candidate_name, candidate_phone, channel, docs_json,
        )

    async def update_status(
        self, collection_id: uuid.UUID, status: str
    ) -> None:
        """Update document collection status."""
        completed_clause = ", completed_at = NOW()" if status in ("completed", "abandoned") else ""
        await self.pool.execute(
            f"""
            UPDATE agents.document_collections
            SET status = $1, updated_at = NOW(){completed_clause}
            WHERE id = $2
            """,
            status, collection_id,
        )

    async def abandon_active_for_phone(self, candidate_phone: str) -> int:
        """Abandon all active document collections for a phone number."""
        result = await self.pool.execute(
            """
            UPDATE agents.document_collections
            SET status = 'abandoned', updated_at = NOW(), completed_at = NOW()
            WHERE candidate_phone = $1 AND status = 'active'
            """,
            candidate_phone,
        )
        # result is like "UPDATE N"
        return int(result.split()[-1])

    # =========================================================================
    # Messages
    # =========================================================================

    async def get_messages(self, collection_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all messages for a document collection."""
        return await self.pool.fetch(
            """
            SELECT id, collection_id, role, message, created_at
            FROM agents.document_collection_session_turns
            WHERE collection_id = $1
            ORDER BY created_at
            """,
            collection_id,
        )

    async def add_message(
        self, collection_id: uuid.UUID, role: str, message: str
    ) -> asyncpg.Record:
        """Add a message and increment message_count."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO agents.document_collection_session_turns (collection_id, role, message)
                    VALUES ($1, $2, $3)
                    RETURNING id, collection_id, role, message, created_at
                    """,
                    collection_id, role, message,
                )
                await conn.execute(
                    """
                    UPDATE agents.document_collections
                    SET message_count = message_count + 1, updated_at = NOW()
                    WHERE id = $1
                    """,
                    collection_id,
                )
                return row

    # =========================================================================
    # Uploads
    # =========================================================================

    async def get_uploads(self, collection_id: uuid.UUID) -> list[asyncpg.Record]:
        """Get all uploads for a document collection."""
        return await self.pool.fetch(
            """
            SELECT id, collection_id, application_id, document_type_id,
                   document_side, image_hash, storage_path,
                   verification_result, verification_passed,
                   status, uploaded_at, verified_at
            FROM agents.document_collection_uploads
            WHERE collection_id = $1
            ORDER BY uploaded_at
            """,
            collection_id,
        )

    async def create_upload(
        self,
        collection_id: uuid.UUID,
        document_type_id: Optional[uuid.UUID] = None,
        document_side: str = "single",
        image_hash: Optional[str] = None,
        storage_path: Optional[str] = None,
        application_id: Optional[uuid.UUID] = None,
    ) -> asyncpg.Record:
        """Create a new upload record."""
        return await self.pool.fetchrow(
            """
            INSERT INTO agents.document_collection_uploads
                (collection_id, application_id, document_type_id,
                 document_side, image_hash, storage_path, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending')
            RETURNING id, collection_id, application_id, document_type_id,
                      document_side, image_hash, storage_path,
                      verification_result, verification_passed,
                      status, uploaded_at, verified_at
            """,
            collection_id, application_id, document_type_id,
            document_side, image_hash, storage_path,
        )

    async def update_upload_verification(
        self,
        upload_id: uuid.UUID,
        verification_result: dict,
        verification_passed: bool,
    ) -> None:
        """Update an upload with verification results."""
        await self.pool.execute(
            """
            UPDATE agents.document_collection_uploads
            SET verification_result = $1::jsonb,
                verification_passed = $2,
                status = CASE WHEN $2 THEN 'verified' ELSE 'rejected' END,
                verified_at = NOW()
            WHERE id = $3
            """,
            json.dumps(verification_result), verification_passed, upload_id,
        )
