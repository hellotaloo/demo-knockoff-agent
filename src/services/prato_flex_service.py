"""
Prato Flex Service for workforce management integration.

This module provides functionality to interact with the Prato Flex API:
1. Look up codes (certificate types, detail types, etc.)
2. Create certificates for persons (medical certificates, work modifications, etc.)

Uses token-based authentication with 'WB {token}' authorization header.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from src.config import PRATO_FLEX_API_URL, PRATO_FLEX_API_TOKEN

logger = logging.getLogger(__name__)

# Default timeout for API requests (seconds)
DEFAULT_TIMEOUT = 30


class PratoFlexService:
    """
    Service for interacting with the Prato Flex API.

    Uses lazy initialization for the HTTP client.
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with auth headers."""
        if self._client is None:
            if not PRATO_FLEX_API_URL:
                raise RuntimeError("PRATO_FLEX_API_URL environment variable is required.")
            if not PRATO_FLEX_API_TOKEN:
                raise RuntimeError("PRATO_FLEX_API_TOKEN environment variable is required.")

            self._client = httpx.AsyncClient(
                base_url=PRATO_FLEX_API_URL.rstrip("/"),
                headers={
                    "Authorization": f"WB {PRATO_FLEX_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=DEFAULT_TIMEOUT,
            )
            logger.info("Created Prato Flex API client")

        return self._client

    async def get_codes(self, kind: int, language: str = "nl") -> list[dict]:
        """
        Get code descriptions from Prato Flex.

        Common kinds:
            43 = Certificate types (e.g., Rijbewijs, Werkvergunning, Paspoort)
            44 = Certificate detail types (sub-types scoped to a parent type)
            64 = Document types

        Args:
            kind: The code kind to retrieve.
            language: Language code (default "nl").

        Returns:
            List of code dicts with id, description, descriptionshort, etc.

        Raises:
            PratoFlexError: If the API returns an error.
        """
        client = self._get_client()

        try:
            response = await client.get(
                "/integration/codes",
                params={"kind": kind, "language": language},
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data)} codes for kind={kind}")
                return data

            error_body = response.text
            logger.error(f"Prato Flex codes API error {response.status_code}: {error_body}")
            raise PratoFlexError(f"Prato Flex API error {response.status_code}: {error_body}")

        except httpx.HTTPError as e:
            logger.error(f"Prato Flex codes request failed: {e}")
            raise PratoFlexError(f"Failed to connect to Prato Flex: {e}") from e

    async def get_certificate_types(self, language: str = "nl") -> list[dict]:
        """Get all certificate types (kind 43)."""
        return await self.get_codes(kind=43, language=language)

    async def get_certificate_detail_types(self, language: str = "nl") -> list[dict]:
        """Get all certificate detail types (kind 44)."""
        return await self.get_codes(kind=44, language=language)

    async def create_certificate(
        self,
        person_id: int,
        *,
        certificate_type: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        detail_type: Optional[str] = None,
        document_number: Optional[str] = None,
        delivered_by: Optional[str] = None,
        delivered_date: Optional[datetime] = None,
        remarks: Optional[str] = None,
        amount_work_allowance: Optional[int] = None,
        days_modified_work: Optional[int] = None,
        hours_modified_work: Optional[int] = None,
        url: Optional[str] = None,
    ) -> dict:
        """
        Create a new certificate for a person in Prato Flex.

        Args:
            person_id: The Prato Flex person ID.
            certificate_type: Certificate type code (kind 43), e.g. "10" for Rijbewijs.
            start_date: Start date of the certificate validity period (required).
            end_date: End date of the certificate validity period.
            detail_type: Detail type code (kind 44), sub-type within the certificate type.
            document_number: Document number or for student certificates the worked days count.
            delivered_by: The issuer of the certificate.
            delivered_date: The date on which the certificate was issued.
            remarks: Free text remarks about the certificate.
            amount_work_allowance: Work allowance amount (required for type 800 with ACT12+/ACT-25).
            days_modified_work: Days of modified work.
            hours_modified_work: Hours of modified work.
            url: URL to redirect from the certificate detail UI.

        Returns:
            The created certificate data from Prato Flex.

        Raises:
            PratoFlexError: If the API returns an error.
        """
        client = self._get_client()

        body = {
            "type": certificate_type,
            "startdate": start_date.isoformat(),
        }

        if amount_work_allowance is not None:
            body["amountworkallowance"] = amount_work_allowance
        if days_modified_work is not None:
            body["daysmodifiedwork"] = days_modified_work
        if hours_modified_work is not None:
            body["hoursmodifiedwork"] = hours_modified_work

        if end_date is not None:
            body["enddate"] = end_date.isoformat()
        if detail_type is not None:
            body["detailtype"] = detail_type
        if document_number is not None:
            body["documentnumber"] = document_number
        if delivered_by is not None:
            body["deliveredby"] = delivered_by
        if delivered_date is not None:
            body["delivereddate"] = delivered_date.isoformat()
        if remarks is not None:
            body["remarks"] = remarks
        if url is not None:
            body["url"] = url

        try:
            response = await client.post(
                f"/integration/person/{person_id}/certificate",
                json=body,
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"Created certificate for person {person_id}: type={certificate_type}")
                return data

            if response.status_code == 404:
                raise PratoFlexError(f"Person {person_id} not found in Prato Flex")

            error_body = response.text
            logger.error(f"Prato Flex API error {response.status_code}: {error_body}")
            raise PratoFlexError(
                f"Prato Flex API error {response.status_code}: {error_body}"
            )

        except httpx.HTTPError as e:
            logger.error(f"Prato Flex request failed for person {person_id}: {e}")
            raise PratoFlexError(f"Failed to connect to Prato Flex: {e}") from e

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class PratoFlexError(Exception):
    """Custom exception for Prato Flex API errors."""
    pass


# Singleton instance
prato_flex_service = PratoFlexService()
