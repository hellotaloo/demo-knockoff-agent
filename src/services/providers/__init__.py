"""
ATS provider interface and registry.

Each provider implements fetch_vacancies() to retrieve raw records
from an external ATS system. The generic VacancyImportService handles
field mapping, transformation, and upserting into the local database.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ATSProvider:
    """Base class for ATS provider integrations."""

    async def fetch_vacancies(
        self, credentials: dict, settings: dict, mapping: dict,
        since: str | None = None,
    ) -> list[dict]:
        """
        Fetch raw vacancy records from the external system.

        Args:
            credentials: Provider-specific auth credentials.
            settings: Connection settings (e.g. sf_object, custom config).
            mapping: Active field mapping (target_field -> {"template": "{{Source.Field}}"}).
            since: ISO datetime string — only fetch records modified after this time.

        Returns:
            List of raw record dicts from the external system.
        """
        raise NotImplementedError

    async def create_record(
        self, credentials: dict, sf_object: str, data: dict
    ) -> str:
        """Create a record in the external system. Returns the record ID."""
        raise NotImplementedError

    async def update_record(
        self, credentials: dict, sf_object: str, record_id: str, data: dict
    ) -> None:
        """Update a record in the external system."""
        raise NotImplementedError

    async def upsert_record(
        self, credentials: dict, sf_object: str, external_id_field: str, external_id: str, data: dict
    ) -> str:
        """Upsert a record using an external ID field. Returns the record ID."""
        raise NotImplementedError


def get_provider(slug: str) -> ATSProvider:
    """Resolve a provider instance by integration slug."""
    if slug == "connexys":
        from src.services.providers.connexys_provider import ConnexysProvider
        return ConnexysProvider()
    raise ValueError(f"No ATS provider registered for: {slug}")
