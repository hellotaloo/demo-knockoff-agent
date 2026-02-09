"""
Document Verification repository - handles document verification audit trail operations.
"""
import asyncpg
import uuid
from typing import Optional, List
from datetime import datetime


class DocumentVerificationRepository:
    """Repository for document verification database operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(
        self,
        application_id: Optional[uuid.UUID],
        vacancy_id: Optional[uuid.UUID],
        document_category: str,
        document_category_confidence: float,
        extracted_name: Optional[str],
        name_extraction_confidence: float,
        expected_candidate_name: Optional[str],
        name_match_result: Optional[str],
        name_match_confidence: Optional[float],
        name_match_details: Optional[str],
        fraud_risk_level: str,
        fraud_indicators: List[dict],
        overall_fraud_confidence: float,
        image_quality: str,
        readability_issues: List[str],
        verification_passed: bool,
        verification_summary: str,
        image_hash: str,
        raw_agent_response: Optional[str] = None,
    ) -> uuid.UUID:
        """
        Create a new document verification record.

        Returns:
            UUID of the created verification record
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO document_verifications (
                    application_id,
                    vacancy_id,
                    document_category,
                    document_category_confidence,
                    extracted_name,
                    name_extraction_confidence,
                    expected_candidate_name,
                    name_match_result,
                    name_match_confidence,
                    name_match_details,
                    fraud_risk_level,
                    fraud_indicators,
                    overall_fraud_confidence,
                    image_quality,
                    readability_issues,
                    verification_passed,
                    verification_summary,
                    image_hash,
                    raw_agent_response
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13, $14, $15::jsonb, $16, $17, $18, $19)
                RETURNING id
                """,
                application_id,
                vacancy_id,
                document_category,
                document_category_confidence,
                extracted_name,
                name_extraction_confidence,
                expected_candidate_name,
                name_match_result,
                name_match_confidence,
                name_match_details,
                fraud_risk_level,
                fraud_indicators,
                overall_fraud_confidence,
                image_quality,
                readability_issues,
                verification_passed,
                verification_summary,
                image_hash,
                raw_agent_response,
            )
            return result["id"]

    async def get_by_id(self, verification_id: uuid.UUID) -> Optional[asyncpg.Record]:
        """Get a document verification by ID."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM document_verifications WHERE id = $1",
                verification_id
            )

    async def list_for_application(
        self,
        application_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0
    ) -> List[asyncpg.Record]:
        """List all document verifications for an application."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT *
                FROM document_verifications
                WHERE application_id = $1
                ORDER BY verified_at DESC
                LIMIT $2 OFFSET $3
                """,
                application_id,
                limit,
                offset
            )

    async def list_by_fraud_risk(
        self,
        fraud_risk_level: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[asyncpg.Record]:
        """List document verifications by fraud risk level."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT *
                FROM document_verifications
                WHERE fraud_risk_level = $1
                ORDER BY verified_at DESC
                LIMIT $2 OFFSET $3
                """,
                fraud_risk_level,
                limit,
                offset
            )
